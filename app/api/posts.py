import io
import re
import unicodedata
import uuid

import cloudinary
import cloudinary.api
import cloudinary.uploader
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.comment import Comment
from app.models.post import Post, SavedPost
from app.models.post_media import PostMedia
from app.models.reaction import Reaction
from app.models.subject import Subject, SubjectEnrollment
from app.models.user import User, UserRole
from app.schemas.post import CommentCreateRequest, CommentOut, MediaOut, PostCreateRequest, PostOut, ReactionCreateRequest
from app.security.deps import get_current_user, get_current_user_optional
from app.services.notifications import create_notification

router = APIRouter(prefix="/posts", tags=["posts"])

MAX_POST_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
)


def _slugify(text: str, post_id: int) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return f"{text}-{post_id}" if text else str(post_id)


def _extract_hashtags(content: str) -> list[str]:
    return list({m.lower() for m in re.findall(r"#([a-zA-Z0-9_]+)", content)})


def _extract_mentions(content: str) -> list[str]:
    return list({m.lower() for m in re.findall(r"@([a-zA-Z0-9_]+)", content)})


def _post_to_out(
    post: Post,
    author: User,
    comments_count: int = 0,
    reactions_count: int = 0,
    user_reacted: bool = False,
    user_saved: bool = False,
    comments: list[CommentOut] | None = None,
    media: list[MediaOut] | None = None,
    subject_name: str | None = None,
) -> PostOut:
    return PostOut(
        id=post.id,
        author_id=post.author_id,
        author_name=author.full_name,
        author_username=author.username,
        author_avatar_base64=author.avatar_base64,
        author_role=author.role.value if isinstance(author.role, UserRole) else author.role,
        title=post.title,
        content=post.content,
        slug=post.slug,
        visibility=post.visibility,
        target_batch_years=post.target_batch_years,
        tags=post.tags,
        subject_id=post.subject_id,
        subject_name=subject_name,
        media=media or [],
        comments_count=comments_count,
        reactions_count=reactions_count,
        user_reacted=user_reacted,
        user_saved=user_saved,
        comments=comments or [],
        created_at=str(post.created_at) if post.created_at else "",
    )


def _load_media_for_posts(db: Session, post_ids: list[int]) -> dict[int, list[MediaOut]]:
    """Load media for a batch of posts."""
    if not post_ids:
        return {}
    rows = db.scalars(
        select(PostMedia).where(PostMedia.post_id.in_(post_ids)).order_by(PostMedia.position)
    ).all()
    media_map: dict[int, list[MediaOut]] = {}
    for m in rows:
        media_map.setdefault(m.post_id, []).append(
            MediaOut(id=m.id, file_url=m.file_url, file_name=m.file_name, file_size=m.file_size, file_type=m.file_type, position=m.position)
        )
    return media_map


def _can_see_post(post: Post, user: User | None, user_subject_ids: set[int] | None = None) -> bool:
    """Check if user can see this post based on visibility."""
    if post.visibility == "public":
        return True
    if not user:
        return False
    if user.role == UserRole.admin:
        return True
    if post.visibility == "faculties_only":
        return user.role == UserRole.faculty
    if post.visibility == "students_only":
        return user.role in (UserRole.student, UserRole.faculty) or bool(user.batch_year)
    if post.visibility == "batch_only":
        if user.role == UserRole.faculty:
            return True
        if user.batch_year:
            return user.batch_year in post.target_batch_years
    if post.visibility == "subject_only":
        if not post.subject_id:
            return False
        if user_subject_ids is not None:
            return post.subject_id in user_subject_ids
        return False
    return False


@router.get("/feed", response_model=list[PostOut])
def get_feed(
    filter: str | None = Query(None),
    batch_year: int | None = Query(None),
    subject_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    all_posts = db.scalars(
        select(Post).order_by(desc(Post.created_at)).limit(200)
    ).all()

    author_ids = {p.author_id for p in all_posts}
    authors = {}
    if author_ids:
        author_list = db.scalars(select(User).where(User.id.in_(author_ids))).all()
        authors = {a.id: a for a in author_list}

    # Build set of subject IDs the current user is enrolled in (for visibility checks)
    user_subject_ids: set[int] = set()
    if current_user:
        if current_user.role == UserRole.admin:
            # Admin can see all subject posts
            all_subjects = db.scalars(select(SubjectEnrollment)).all()
            user_subject_ids = {e.subject_id for e in all_subjects}
        else:
            enrollments = db.scalars(
                select(SubjectEnrollment).where(SubjectEnrollment.user_id == current_user.id)
            ).all()
            user_subject_ids = {e.subject_id for e in enrollments}

    # Build subject name map for posts
    subject_ids_in_posts = {p.subject_id for p in all_posts if p.subject_id}
    subject_name_map: dict[int, str] = {}
    if subject_ids_in_posts:
        subjects = db.scalars(select(Subject).where(Subject.id.in_(subject_ids_in_posts))).all()
        subject_name_map = {s.id: s.name for s in subjects}

    post_ids = [p.id for p in all_posts]
    comments_count_map: dict[int, int] = {}
    reactions_count_map: dict[int, int] = {}
    user_reacted_set: set[int] = set()
    user_saved_set: set[int] = set()
    media_map: dict[int, list[MediaOut]] = {}
    if post_ids:
        comments_rows = db.execute(
            select(Comment.post_id, func.count(Comment.id)).where(Comment.post_id.in_(post_ids)).group_by(Comment.post_id)
        ).all()
        comments_count_map = {post_id: count for post_id, count in comments_rows}

        reaction_rows = db.execute(
            select(Reaction.post_id, func.count(Reaction.id)).where(Reaction.post_id.in_(post_ids)).group_by(Reaction.post_id)
        ).all()
        reactions_count_map = {post_id: count for post_id, count in reaction_rows}

        media_map = _load_media_for_posts(db, post_ids)

        if current_user:
            user_reaction_rows = db.execute(
                select(Reaction.post_id).where(Reaction.post_id.in_(post_ids), Reaction.user_id == current_user.id)
            ).all()
            user_reacted_set = {row[0] for row in user_reaction_rows}
            user_saved_rows = db.execute(
                select(SavedPost.post_id).where(SavedPost.post_id.in_(post_ids), SavedPost.user_id == current_user.id)
            ).all()
            user_saved_set = {row[0] for row in user_saved_rows}

    result: list[PostOut] = []
    for post in all_posts:
        author = authors.get(post.author_id)
        if not author:
            continue
        if not _can_see_post(post, current_user, user_subject_ids):
            continue

        # Apply frontend filter
        if filter:
            if filter == "public" and post.visibility != "public":
                continue
            if filter == "faculty" and post.visibility != "faculties_only":
                continue
            if filter == "batch" and post.visibility != "batch_only":
                continue
            if filter == "students" and post.visibility != "students_only":
                continue
            if filter == "subject" and post.visibility != "subject_only":
                continue

        # Subject ID filter (when user clicks a specific subject tab)
        if subject_id is not None:
            if post.subject_id != subject_id:
                continue

        # Batch year filter
        if batch_year and post.visibility == "batch_only":
            if batch_year not in post.target_batch_years:
                continue

        result.append(
            _post_to_out(
                post,
                author,
                comments_count=comments_count_map.get(post.id, 0),
                reactions_count=reactions_count_map.get(post.id, 0),
                user_reacted=post.id in user_reacted_set,
                user_saved=post.id in user_saved_set,
                media=media_map.get(post.id, []),
                subject_name=subject_name_map.get(post.subject_id) if post.subject_id else None,
            )
        )

    return result


@router.get("/search", response_model=list[PostOut])
def search_posts(q: str = Query("", min_length=1), db: Session = Depends(get_db)):
    term = f"%{q}%"
    posts = db.scalars(
        select(Post).where(
            or_(
                Post.title.ilike(term),
                Post.content.ilike(term),
                Post.tags_csv.ilike(term),
            )
        ).order_by(desc(Post.created_at)).limit(50)
    ).all()

    author_ids = {p.author_id for p in posts}
    authors = {}
    if author_ids:
        author_list = db.scalars(select(User).where(User.id.in_(author_ids))).all()
        authors = {a.id: a for a in author_list}

    post_ids = [p.id for p in posts]
    comments_count_map: dict[int, int] = {}
    reactions_count_map: dict[int, int] = {}
    if post_ids:
        comments_rows = db.execute(
            select(Comment.post_id, func.count(Comment.id)).where(Comment.post_id.in_(post_ids)).group_by(Comment.post_id)
        ).all()
        comments_count_map = {post_id: count for post_id, count in comments_rows}

        reaction_rows = db.execute(
            select(Reaction.post_id, func.count(Reaction.id)).where(Reaction.post_id.in_(post_ids)).group_by(Reaction.post_id)
        ).all()
        reactions_count_map = {post_id: count for post_id, count in reaction_rows}

    media_map = _load_media_for_posts(db, post_ids)

    # Search results only show public posts (no auth required for search).
    return [
        _post_to_out(
            p,
            authors[p.author_id],
            comments_count=comments_count_map.get(p.id, 0),
            reactions_count=reactions_count_map.get(p.id, 0),
            media=media_map.get(p.id, []),
        )
        for p in posts
        if p.author_id in authors and p.visibility == "public"
    ]


@router.get("/tags/suggest", response_model=list[str])
def suggest_tags(
    q: str = Query("", min_length=1),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    query = q.lower().strip()
    posts = db.scalars(select(Post).order_by(desc(Post.created_at)).limit(300)).all()
    tags: list[str] = []
    seen: set[str] = set()
    for post in posts:
        if not _can_see_post(post, current_user):
            continue
        for tag in post.tags:
            if tag.startswith(query) and tag not in seen:
                seen.add(tag)
                tags.append(tag)
            if len(tags) >= 10:
                return tags
    return tags


@router.get("/by-tag/{tag}", response_model=list[PostOut])
def get_posts_by_tag(
    tag: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    tag_lower = tag.lower()
    all_posts = db.scalars(
        select(Post).where(Post.tags_csv.ilike(f"%{tag_lower}%")).order_by(desc(Post.created_at)).limit(50)
    ).all()

    # Filter to only posts that actually contain this tag
    matched = [p for p in all_posts if tag_lower in p.tags]

    author_ids = {p.author_id for p in matched}
    authors = {}
    if author_ids:
        author_list = db.scalars(select(User).where(User.id.in_(author_ids))).all()
        authors = {a.id: a for a in author_list}

    post_ids = [p.id for p in matched]
    comments_count_map: dict[int, int] = {}
    reactions_count_map: dict[int, int] = {}
    if post_ids:
        comments_rows = db.execute(
            select(Comment.post_id, func.count(Comment.id)).where(Comment.post_id.in_(post_ids)).group_by(Comment.post_id)
        ).all()
        comments_count_map = {post_id: count for post_id, count in comments_rows}

        reaction_rows = db.execute(
            select(Reaction.post_id, func.count(Reaction.id)).where(Reaction.post_id.in_(post_ids)).group_by(Reaction.post_id)
        ).all()
        reactions_count_map = {post_id: count for post_id, count in reaction_rows}

    media_map = _load_media_for_posts(db, post_ids)

    return [
        _post_to_out(
            p,
            authors[p.author_id],
            comments_count=comments_count_map.get(p.id, 0),
            reactions_count=reactions_count_map.get(p.id, 0),
            media=media_map.get(p.id, []),
        )
        for p in matched
        if p.author_id in authors and _can_see_post(p, current_user)
    ]


@router.get("/{slug}", response_model=PostOut)
def get_post(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    post = db.scalar(select(Post).where(Post.slug == slug))
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # Build user_subject_ids so subject_only posts are accessible to enrolled users
    user_subject_ids: set[int] = set()
    if current_user:
        if current_user.role == UserRole.admin:
            all_enrollments = db.scalars(select(SubjectEnrollment)).all()
            user_subject_ids = {e.subject_id for e in all_enrollments}
        else:
            enrollments = db.scalars(
                select(SubjectEnrollment).where(SubjectEnrollment.user_id == current_user.id)
            ).all()
            user_subject_ids = {e.subject_id for e in enrollments}

    if not _can_see_post(post, current_user, user_subject_ids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to view this post")

    author = db.scalar(select(User).where(User.id == post.author_id))
    if not author:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    comments = db.scalars(
        select(Comment).where(Comment.post_id == post.id).order_by(Comment.created_at.asc())
    ).all()
    author_ids = {c.author_id for c in comments}
    comment_authors = {}
    if author_ids:
        users = db.scalars(select(User).where(User.id.in_(author_ids))).all()
        comment_authors = {u.id: u for u in users}

    comment_out = [
        CommentOut(
            id=c.id,
            author_id=c.author_id,
            author_username=comment_authors.get(c.author_id).username if comment_authors.get(c.author_id) else None,
            author_avatar_base64=comment_authors.get(c.author_id).avatar_base64 if comment_authors.get(c.author_id) else None,
            author_name=comment_authors.get(c.author_id).full_name if comment_authors.get(c.author_id) else "Unknown",
            content=c.content,
            reply_to_comment_id=getattr(c, "parent_comment_id", None),
            created_at=str(c.created_at) if c.created_at else "",
        )
        for c in comments
    ]

    reactions_count = db.scalar(select(func.count(Reaction.id)).where(Reaction.post_id == post.id)) or 0
    user_reacted = False
    user_saved = False
    if current_user:
        user_reacted = db.scalar(
            select(Reaction.id).where(Reaction.post_id == post.id, Reaction.user_id == current_user.id)
        ) is not None
        user_saved = db.scalar(
            select(SavedPost.id).where(SavedPost.post_id == post.id, SavedPost.user_id == current_user.id)
        ) is not None
    media_list = _load_media_for_posts(db, [post.id]).get(post.id, [])
    return _post_to_out(
        post,
        author,
        comments_count=len(comment_out),
        reactions_count=reactions_count,
        user_reacted=user_reacted,
        user_saved=user_saved,
        comments=comment_out,
        media=media_list,
    )


@router.post("", response_model=PostOut)
def create_post(payload: PostCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only faculty and admin can create posts")

    if payload.visibility == "batch_only" and not payload.target_batch_years:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="batch_only posts require target batch years")

    if payload.visibility == "subject_only":
        if not payload.subject_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="subject_only posts require a subject_id")
        # Verify the author is enrolled in the subject (as faculty or admin)
        if current_user.role != UserRole.admin:
            enrollment = db.scalar(
                select(SubjectEnrollment).where(
                    SubjectEnrollment.subject_id == payload.subject_id,
                    SubjectEnrollment.user_id == current_user.id,
                    SubjectEnrollment.role == "faculty",
                )
            )
            if not enrollment:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not assigned as faculty for this subject")

    tags = _extract_hashtags(payload.content)

    post = Post(
        author_id=current_user.id,
        title=payload.title,
        content=payload.content,
        slug="temp",
        visibility=payload.visibility,
        subject_id=payload.subject_id if payload.visibility == "subject_only" else None,
    )
    post.target_batch_years = payload.target_batch_years
    post.tags = tags
    db.add(post)
    db.flush()
    post.slug = _slugify(payload.title, post.id)
    db.commit()
    db.refresh(post)

    # Resolve subject name
    subject_name: str | None = None
    if post.subject_id:
        subject = db.scalar(select(Subject).where(Subject.id == post.subject_id))
        subject_name = subject.name if subject else None

    # Notify mentioned users in post content.
    mentioned_usernames = _extract_mentions(payload.content)
    if mentioned_usernames:
        mentioned_users = db.scalars(select(User).where(User.username.in_(mentioned_usernames))).all()
        for mentioned in mentioned_users:
            if mentioned.id == current_user.id:
                continue
            create_notification(
                db,
                user_id=mentioned.id,
                type="mention",
                title=f"{current_user.full_name} mentioned you in a post",
                body=payload.content[:160],
                target_url=f"/{current_user.username or 'post'}/{post.slug}",
            )

    return _post_to_out(post, current_user, subject_name=subject_name)


@router.post("/{post_id}/upload", response_model=MediaOut)
def upload_post_media(
    post_id: int,
    file: UploadFile = File(...),
    position: int = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.scalar(select(Post).where(Post.id == post_id))
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = file.file.read()
    if len(content) > MAX_POST_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 50 MB)")

    content_type = file.content_type or "application/octet-stream"
    is_image = content_type.startswith("image/")
    is_video = content_type.startswith("video/")
    is_audio = content_type.startswith("audio/")

    if is_image:
        resource_type = "image"
    elif is_video:
        resource_type = "video"
    else:
        resource_type = "raw"
    if is_audio:
        resource_type = "raw"

    folder = f"kec_posts/{post_id}"

    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(content),
            folder=folder,
            resource_type=resource_type,
            public_id=f"{uuid.uuid4().hex}",
        )
        file_url = result.get("secure_url", "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    media = PostMedia(
        post_id=post_id,
        file_url=file_url,
        file_name=file.filename,
        file_size=len(content),
        file_type=content_type,
        position=position,
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return MediaOut(
        id=media.id,
        file_url=media.file_url,
        file_name=media.file_name,
        file_size=media.file_size,
        file_type=media.file_type,
        position=media.position,
    )


def _build_subject_ids(user: User, db: Session) -> set[int]:
    """Return the set of subject IDs the user is enrolled in (admin gets all)."""
    if user.role == UserRole.admin:
        return {e.subject_id for e in db.scalars(select(SubjectEnrollment)).all()}
    return {e.subject_id for e in db.scalars(
        select(SubjectEnrollment).where(SubjectEnrollment.user_id == user.id)
    ).all()}


@router.post("/{post_id}/comments", response_model=CommentOut)
def create_comment(
    post_id: int,
    payload: CommentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.scalar(select(Post).where(Post.id == post_id))
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if not _can_see_post(post, current_user, _build_subject_ids(current_user, db)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to comment on this post")

    comment = Comment(post_id=post_id, author_id=current_user.id, content=payload.content.strip())
    if payload.reply_to_comment_id:
        parent = db.scalar(
            select(Comment).where(Comment.id == payload.reply_to_comment_id, Comment.post_id == post_id)
        )
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reply target not found")
        comment.parent_comment_id = payload.reply_to_comment_id
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Notify reply target.
    if payload.reply_to_comment_id and parent and parent.author_id != current_user.id:
        create_notification(
            db,
            user_id=parent.author_id,
            type="comment_reply",
            title=f"{current_user.full_name} replied to your comment",
            body=comment.content[:160],
            target_url=f"/{current_user.username or 'post'}/{post.slug}",
        )

    # Notify mentioned users.
    mentioned_usernames = _extract_mentions(comment.content)
    if mentioned_usernames:
        mentioned_users = db.scalars(select(User).where(User.username.in_(mentioned_usernames))).all()
        for mentioned in mentioned_users:
            if mentioned.id == current_user.id:
                continue
            create_notification(
                db,
                user_id=mentioned.id,
                type="mention",
                title=f"{current_user.full_name} mentioned you",
                body=comment.content[:160],
                target_url=f"/{current_user.username or 'post'}/{post.slug}",
            )

    return CommentOut(
        id=comment.id,
        author_id=current_user.id,
        author_username=current_user.username,
        author_avatar_base64=current_user.avatar_base64,
        author_name=current_user.full_name,
        content=comment.content,
        reply_to_comment_id=getattr(comment, "parent_comment_id", None),
        created_at=str(comment.created_at) if comment.created_at else "",
    )


@router.post("/{post_id}/reactions")
def react_to_post(
    post_id: int,
    payload: ReactionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = db.scalar(select(Post).where(Post.id == post_id))
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if not _can_see_post(post, current_user, _build_subject_ids(current_user, db)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed to react to this post")

    existing = db.scalar(
        select(Reaction).where(
            Reaction.post_id == post_id,
            Reaction.user_id == current_user.id,
            Reaction.type == payload.type,
        )
    )

    total = db.scalar(select(func.count(Reaction.id)).where(Reaction.post_id == post_id)) or 0

    if existing:
        db.delete(existing)
        db.commit()
        return {"message": "Reaction removed", "active": False, "count": max(0, total - 1)}

    reaction = Reaction(post_id=post_id, user_id=current_user.id, type=payload.type)
    db.add(reaction)
    db.commit()
    return {"message": "Reaction added", "active": True, "count": total + 1}


@router.get("/by-user/{user_id}", response_model=list[PostOut])
def get_posts_by_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    target_user = db.scalar(select(User).where(User.id == user_id))
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user_posts = db.scalars(
        select(Post).where(Post.author_id == user_id).order_by(desc(Post.created_at)).limit(50)
    ).all()

    subj_ids = _build_subject_ids(current_user, db) if current_user else set()
    visible = [p for p in user_posts if _can_see_post(p, current_user, subj_ids)]

    post_ids = [p.id for p in visible]
    comments_count_map: dict[int, int] = {}
    reactions_count_map: dict[int, int] = {}
    user_reacted_set: set[int] = set()
    user_saved_set: set[int] = set()
    if post_ids:
        comments_rows = db.execute(
            select(Comment.post_id, func.count(Comment.id)).where(Comment.post_id.in_(post_ids)).group_by(Comment.post_id)
        ).all()
        comments_count_map = {pid: cnt for pid, cnt in comments_rows}
        reaction_rows = db.execute(
            select(Reaction.post_id, func.count(Reaction.id)).where(Reaction.post_id.in_(post_ids)).group_by(Reaction.post_id)
        ).all()
        reactions_count_map = {pid: cnt for pid, cnt in reaction_rows}
        if current_user:
            ur_rows = db.execute(
                select(Reaction.post_id).where(Reaction.post_id.in_(post_ids), Reaction.user_id == current_user.id)
            ).all()
            user_reacted_set = {row[0] for row in ur_rows}
            us_rows = db.execute(
                select(SavedPost.post_id).where(SavedPost.post_id.in_(post_ids), SavedPost.user_id == current_user.id)
            ).all()
            user_saved_set = {row[0] for row in us_rows}

    media_map = _load_media_for_posts(db, post_ids)

    return [
        _post_to_out(p, target_user, comments_count=comments_count_map.get(p.id, 0), reactions_count=reactions_count_map.get(p.id, 0), user_reacted=p.id in user_reacted_set, user_saved=p.id in user_saved_set, media=media_map.get(p.id, []))
        for p in visible
    ]


@router.delete("/{post_id}")
def delete_post(post_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    post = db.scalar(select(Post).where(Post.id == post_id))
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if current_user.role not in (UserRole.admin, UserRole.faculty) and post.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this post")
    # Clean up Cloudinary media
    try:
        prefix = f"kec_posts/{post.id}"
        for resource_type in ("image", "video", "raw"):
            try:
                cloudinary.api.delete_resources_by_prefix(prefix, resource_type=resource_type)
            except Exception:
                pass
        try:
            cloudinary.api.delete_folder(prefix)
        except Exception:
            pass
    except Exception:
        pass
    db.delete(post)
    db.commit()
    return {"message": "Post deleted"}


# ── Saved / Bookmark Posts ──

@router.post("/{post_id}/save")
def save_post(post_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    post = db.scalar(select(Post).where(Post.id == post_id))
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    existing = db.scalar(
        select(SavedPost).where(SavedPost.user_id == current_user.id, SavedPost.post_id == post_id)
    )
    if existing:
        return {"message": "Already saved", "saved": True}
    saved = SavedPost(user_id=current_user.id, post_id=post_id)
    db.add(saved)
    db.commit()
    return {"message": "Post saved", "saved": True}


@router.delete("/{post_id}/save")
def unsave_post(post_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = db.scalar(
        select(SavedPost).where(SavedPost.user_id == current_user.id, SavedPost.post_id == post_id)
    )
    if not existing:
        return {"message": "Not saved", "saved": False}
    db.delete(existing)
    db.commit()
    return {"message": "Post unsaved", "saved": False}


@router.get("/saved/list", response_model=list[PostOut])
def get_saved_posts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    saved_rows = db.scalars(
        select(SavedPost).where(SavedPost.user_id == current_user.id).order_by(desc(SavedPost.created_at))
    ).all()
    post_ids = [s.post_id for s in saved_rows]
    if not post_ids:
        return []

    posts_list = db.scalars(select(Post).where(Post.id.in_(post_ids))).all()
    posts_map = {p.id: p for p in posts_list}

    author_ids = {p.author_id for p in posts_list}
    authors = db.scalars(select(User).where(User.id.in_(author_ids))).all()
    author_map = {a.id: a for a in authors}

    comments_rows = db.execute(
        select(Comment.post_id, func.count(Comment.id)).where(Comment.post_id.in_(post_ids)).group_by(Comment.post_id)
    ).all()
    comments_count_map = {pid: cnt for pid, cnt in comments_rows}

    reaction_rows = db.execute(
        select(Reaction.post_id, func.count(Reaction.id)).where(Reaction.post_id.in_(post_ids)).group_by(Reaction.post_id)
    ).all()
    reactions_count_map = {pid: cnt for pid, cnt in reaction_rows}

    ur_rows = db.execute(
        select(Reaction.post_id).where(Reaction.post_id.in_(post_ids), Reaction.user_id == current_user.id)
    ).all()
    user_reacted_set = {row[0] for row in ur_rows}

    media_map = _load_media_for_posts(db, post_ids)

    result = []
    for pid in post_ids:
        p = posts_map.get(pid)
        if not p:
            continue
        author = author_map.get(p.author_id)
        if not author:
            continue
        result.append(
            _post_to_out(p, author, comments_count=comments_count_map.get(p.id, 0), reactions_count=reactions_count_map.get(p.id, 0), user_reacted=p.id in user_reacted_set, user_saved=True, media=media_map.get(p.id, []))
        )
    return result

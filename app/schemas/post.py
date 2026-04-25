from pydantic import BaseModel, Field


class PostCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=5000)
    visibility: str = Field(pattern="^(public|students_only|batch_only|faculties_only|subject_only)$")
    target_batch_years: list[int] = Field(default_factory=list)
    subject_id: int | None = None


class MediaOut(BaseModel):
    id: int
    file_url: str
    file_name: str
    file_size: int
    file_type: str
    position: int = 0


class CommentCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    reply_to_comment_id: int | None = None


class ReactionCreateRequest(BaseModel):
    type: str = Field(default="like", pattern="^(like)$")


class CommentOut(BaseModel):
    id: int
    author_id: int
    author_username: str | None = None
    author_avatar_base64: str | None = None
    author_name: str
    content: str
    reply_to_comment_id: int | None = None
    created_at: str


class PostOut(BaseModel):
    id: int
    author_id: int
    author_name: str
    author_username: str | None = None
    author_avatar_base64: str | None = None
    author_role: str
    title: str
    content: str
    slug: str
    visibility: str
    target_batch_years: list[int]
    tags: list[str]
    subject_id: int | None = None
    subject_name: str | None = None
    media: list[MediaOut] = Field(default_factory=list)
    comments_count: int = 0
    reactions_count: int = 0
    user_reacted: bool = False
    user_saved: bool = False
    comments: list[CommentOut] = Field(default_factory=list)
    created_at: str

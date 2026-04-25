from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.subject import Subject, SubjectEnrollment
from app.models.user import User, UserRole
from app.security.deps import get_current_user

router = APIRouter(prefix="/subjects", tags=["subjects"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class SubjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=1, max_length=30, pattern=r"^[A-Z0-9_\-]+$")
    description: str | None = Field(default=None, max_length=500)


class SubjectOut(BaseModel):
    id: int
    name: str
    code: str
    description: str | None = None
    created_by: int
    created_at: str
    member_count: int = 0
    faculty_count: int = 0

    model_config = {"from_attributes": True}


class EnrollmentOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    username: str | None = None
    email: str
    role: str  # role within subject: "faculty" | "student"
    subject_id: int


class AssignRequest(BaseModel):
    user_id: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def _require_faculty_or_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(status_code=403, detail="Faculty or admin access required")
    return current_user


def _enroll_count(db: Session, subject_id: int) -> tuple[int, int]:
    """Returns (total_members, faculty_count)"""
    all_e = db.scalars(select(SubjectEnrollment).where(SubjectEnrollment.subject_id == subject_id)).all()
    faculty = sum(1 for e in all_e if e.role == "faculty")
    return len(all_e), faculty


def _subject_to_out(subject: Subject, db: Session) -> SubjectOut:
    total, faculty = _enroll_count(db, subject.id)
    return SubjectOut(
        id=subject.id,
        name=subject.name,
        code=subject.code,
        description=subject.description,
        created_by=subject.created_by,
        created_at=str(subject.created_at) if subject.created_at else "",
        member_count=total,
        faculty_count=faculty,
    )


# ── Admin: CRUD subjects ──────────────────────────────────────────────────────

@router.post("", response_model=SubjectOut, status_code=201)
def create_subject(
    payload: SubjectCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    """Admin creates a new subject/course."""
    code = payload.code.upper()
    existing = db.scalar(select(Subject).where(Subject.code == code))
    if existing:
        raise HTTPException(status_code=400, detail=f"Subject code '{code}' already exists")

    subject = Subject(
        name=payload.name,
        code=code,
        description=payload.description,
        created_by=admin.id,
    )
    db.add(subject)
    db.commit()
    db.refresh(subject)
    return _subject_to_out(subject, db)


@router.get("", response_model=list[SubjectOut])
def list_subjects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Admin → all subjects.
    Faculty/Student → only subjects they're enrolled in.
    """
    if current_user.role == UserRole.admin:
        subjects = db.scalars(select(Subject).order_by(Subject.name)).all()
    else:
        enrollments = db.scalars(
            select(SubjectEnrollment).where(SubjectEnrollment.user_id == current_user.id)
        ).all()
        subject_ids = [e.subject_id for e in enrollments]
        if not subject_ids:
            return []
        subjects = db.scalars(select(Subject).where(Subject.id.in_(subject_ids)).order_by(Subject.name)).all()

    return [_subject_to_out(s, db) for s in subjects]


@router.get("/all", response_model=list[SubjectOut])
def list_all_subjects(db: Session = Depends(get_db), _admin: User = Depends(_require_admin)):
    """Admin only — list every subject with enrollment counts."""
    subjects = db.scalars(select(Subject).order_by(Subject.name)).all()
    return [_subject_to_out(s, db) for s in subjects]


@router.delete("/{subject_id}", status_code=204)
def delete_subject(
    subject_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(_require_admin),
):
    """Admin deletes a subject (cascades all enrollments)."""
    subject = db.scalar(select(Subject).where(Subject.id == subject_id))
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")
    db.delete(subject)
    db.commit()


# ── Admin: assign / remove faculty ───────────────────────────────────────────

@router.post("/{subject_id}/assign-faculty", response_model=EnrollmentOut, status_code=201)
def assign_faculty(
    subject_id: int,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(_require_admin),
):
    """Admin assigns a faculty member to a subject."""
    subject = db.scalar(select(Subject).where(Subject.id == subject_id))
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    user = db.scalar(select(User).where(User.id == payload.user_id))
    if not user or user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(status_code=400, detail="User not found or is not a faculty member")

    existing = db.scalar(
        select(SubjectEnrollment).where(
            SubjectEnrollment.subject_id == subject_id,
            SubjectEnrollment.user_id == payload.user_id,
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="Faculty already assigned to this subject")

    enrollment = SubjectEnrollment(
        subject_id=subject_id,
        user_id=payload.user_id,
        role="faculty",
        assigned_by=admin.id,
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)

    return EnrollmentOut(
        id=enrollment.id,
        user_id=user.id,
        full_name=user.full_name,
        username=user.username,
        email=user.email,
        role=enrollment.role,
        subject_id=subject_id,
    )


@router.delete("/{subject_id}/members/{user_id}", status_code=204)
def remove_member(
    subject_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin: remove any member.
    Faculty: can only remove students from subjects they teach.
    """
    subject = db.scalar(select(Subject).where(Subject.id == subject_id))
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Check permission
    if current_user.role == UserRole.admin:
        pass  # full access
    elif current_user.role == UserRole.faculty:
        # Must be enrolled as faculty in this subject
        faculty_enrollment = db.scalar(
            select(SubjectEnrollment).where(
                SubjectEnrollment.subject_id == subject_id,
                SubjectEnrollment.user_id == current_user.id,
                SubjectEnrollment.role == "faculty",
            )
        )
        if not faculty_enrollment:
            raise HTTPException(status_code=403, detail="You are not a faculty of this subject")
        # Can only remove students, not other faculty
        target_enrollment = db.scalar(
            select(SubjectEnrollment).where(
                SubjectEnrollment.subject_id == subject_id,
                SubjectEnrollment.user_id == user_id,
            )
        )
        if target_enrollment and target_enrollment.role == "faculty":
            raise HTTPException(status_code=403, detail="Faculty cannot remove other faculty — contact admin")
    else:
        raise HTTPException(status_code=403, detail="Access denied")

    enrollment = db.scalar(
        select(SubjectEnrollment).where(
            SubjectEnrollment.subject_id == subject_id,
            SubjectEnrollment.user_id == user_id,
        )
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    db.delete(enrollment)
    db.commit()


# ── Faculty: assign students ──────────────────────────────────────────────────

@router.post("/{subject_id}/assign-student", response_model=EnrollmentOut, status_code=201)
def assign_student(
    subject_id: int,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_faculty_or_admin),
):
    """Faculty assigns a student to one of their subjects. Admin can do it too."""
    subject = db.scalar(select(Subject).where(Subject.id == subject_id))
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Faculty must be enrolled in the subject themselves
    if current_user.role == UserRole.faculty:
        faculty_e = db.scalar(
            select(SubjectEnrollment).where(
                SubjectEnrollment.subject_id == subject_id,
                SubjectEnrollment.user_id == current_user.id,
                SubjectEnrollment.role == "faculty",
            )
        )
        if not faculty_e:
            raise HTTPException(status_code=403, detail="You are not assigned as faculty for this subject")

    user = db.scalar(select(User).where(User.id == payload.user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role not in (UserRole.student, UserRole.guest):
        raise HTTPException(status_code=400, detail="Only students can be enrolled as students")

    existing = db.scalar(
        select(SubjectEnrollment).where(
            SubjectEnrollment.subject_id == subject_id,
            SubjectEnrollment.user_id == payload.user_id,
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="Student already enrolled in this subject")

    enrollment = SubjectEnrollment(
        subject_id=subject_id,
        user_id=payload.user_id,
        role="student",
        assigned_by=current_user.id,
    )
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)

    return EnrollmentOut(
        id=enrollment.id,
        user_id=user.id,
        full_name=user.full_name,
        username=user.username,
        email=user.email,
        role=enrollment.role,
        subject_id=subject_id,
    )


# ── List members of a subject ────────────────────────────────────────────────

@router.get("/{subject_id}/members", response_model=list[EnrollmentOut])
def list_members(
    subject_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all enrolled members of a subject. Faculty/Admin only."""
    if current_user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(status_code=403, detail="Faculty or admin access required")

    subject = db.scalar(select(Subject).where(Subject.id == subject_id))
    if not subject:
        raise HTTPException(status_code=404, detail="Subject not found")

    enrollments = db.scalars(
        select(SubjectEnrollment).where(SubjectEnrollment.subject_id == subject_id)
    ).all()

    user_ids = [e.user_id for e in enrollments]
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}

    result = []
    for e in enrollments:
        u = users.get(e.user_id)
        if u:
            result.append(EnrollmentOut(
                id=e.id,
                user_id=u.id,
                full_name=u.full_name,
                username=u.username,
                email=u.email,
                role=e.role,
                subject_id=subject_id,
            ))
    return result


# ── My subjects (for feed tab building) ──────────────────────────────────────

@router.get("/my", response_model=list[SubjectOut])
def my_subjects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Return subjects the current user is enrolled in."""
    enrollments = db.scalars(
        select(SubjectEnrollment).where(SubjectEnrollment.user_id == current_user.id)
    ).all()
    subject_ids = [e.subject_id for e in enrollments]
    if not subject_ids:
        return []
    subjects = db.scalars(select(Subject).where(Subject.id.in_(subject_ids)).order_by(Subject.name)).all()
    return [_subject_to_out(s, db) for s in subjects]


# ── Subjects for a specific user (for profile page) ───────────────────────────

class UserSubjectOut(BaseModel):
    id: int
    name: str
    code: str
    description: str | None = None
    enrollment_role: str  # "faculty" or "student"


@router.get("/user/{user_id}", response_model=list[UserSubjectOut])
def get_user_subjects(
    user_id: int,
    db: Session = Depends(get_db),
):
    """Get subjects a specific user is enrolled in. Public endpoint — visible to everyone."""
    enrollments = db.scalars(
        select(SubjectEnrollment).where(SubjectEnrollment.user_id == user_id)
    ).all()
    if not enrollments:
        return []

    enrollment_map = {e.subject_id: e.role for e in enrollments}
    subject_ids = list(enrollment_map.keys())
    subjects = db.scalars(select(Subject).where(Subject.id.in_(subject_ids)).order_by(Subject.name)).all()

    return [
        UserSubjectOut(
            id=s.id,
            name=s.name,
            code=s.code,
            description=s.description,
            enrollment_role=enrollment_map[s.id],
        )
        for s in subjects
    ]

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.groups import router as groups_router
from app.api.messages import router as messages_router
from app.api.notifications import router as notifications_router
from app.api.posts import router as posts_router
from app.api.subjects import router as subjects_router

api_router = APIRouter()
api_router.include_router(admin_router)
api_router.include_router(ai_router)
api_router.include_router(auth_router)
api_router.include_router(groups_router)
api_router.include_router(messages_router)
api_router.include_router(notifications_router)
api_router.include_router(posts_router)
api_router.include_router(subjects_router)


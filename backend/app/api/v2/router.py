from fastapi import APIRouter

from app.api.v2.ai import router as ai_router
from app.api.v2.auth import router as auth_router
from app.api.v2.catalog import router as catalog_router
from app.api.v2.dashboard import router as dashboard_router
from app.api.v2.devices import router as devices_router
from app.api.v2.feedback import router as feedback_router
from app.api.v2.notifications import router as notifications_router
from app.api.v2.recommendations import router as recommendations_router
from app.api.v2.repairs import router as repairs_router
from app.api.v2.reservations import router as reservations_router
from app.api.v2.scheduling import router as scheduling_router
from app.api.v2.system import router as system_router
from app.api.v2.users import router as users_router

router = APIRouter()
router.include_router(system_router, tags=["system"])
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(catalog_router, tags=["catalog"])
router.include_router(dashboard_router, tags=["dashboard"])
router.include_router(ai_router, tags=["ai"])
router.include_router(devices_router, tags=["devices"])
router.include_router(notifications_router, tags=["notifications"])
router.include_router(reservations_router, tags=["reservations"])
router.include_router(feedback_router, tags=["feedback"])
router.include_router(scheduling_router, tags=["scheduling"])
router.include_router(repairs_router, tags=["repairs"])
router.include_router(recommendations_router, tags=["recommendations"])
router.include_router(users_router, tags=["users"])

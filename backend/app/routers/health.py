from fastapi import APIRouter
from app.services import health as health_svc

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/overview")
def overview():
    return health_svc.get_health_overview()

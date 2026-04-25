from fastapi import APIRouter, Query
from app.services import dashboard as dash

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(hours: int = Query(24, ge=1, le=720)):
    return dash.get_dashboard(hours)

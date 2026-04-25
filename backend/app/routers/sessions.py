from fastapi import APIRouter, Query
from app.services import agentcore_data as data

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("/{memory_id}/actors")
def get_actors(memory_id: str):
    return data.list_actors(memory_id)


@router.get("/{memory_id}/list")
def get_sessions(memory_id: str, actor_id: str = Query(...)):
    return data.list_sessions(memory_id, actor_id)


@router.get("/{memory_id}/{session_id}/events")
def get_events(
    memory_id: str,
    session_id: str,
    actor_id: str = Query(...),
    include_payloads: bool = Query(True),
):
    return data.list_events(memory_id, session_id, actor_id, include_payloads)

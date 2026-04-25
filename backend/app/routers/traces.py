from fastapi import APIRouter, Query
from app.services import traces as trace_svc
from app.services.traces import LogGroupNotFoundError

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("/search")
def search(
    hours: int = Query(24, ge=1, le=720),
    agent_id: str | None = None,
    session_id: str | None = None,
    error_only: bool = False,
):
    try:
        results = trace_svc.search_traces(hours, agent_id, session_id, error_only)
        return {"traces": results, "otel_enabled": True}
    except LogGroupNotFoundError:
        return {"traces": [], "otel_enabled": False, "message": "OTEL log group not found. Traces are not enabled."}


@router.get("/{trace_id}")
def get_trace(trace_id: str, hours: int = Query(72, ge=1, le=720)):
    try:
        return trace_svc.get_trace(trace_id, hours)
    except LogGroupNotFoundError:
        return {"traceId": trace_id, "spans": [], "otel_enabled": False}

from fastapi import APIRouter, Query
from app.services import cloudwatch as cw

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/runtime")
def runtime_metrics(hours: int = Query(24, ge=1, le=720), resource_arn: str | None = None):
    return cw.get_runtime_metrics(hours, resource_arn)


@router.get("/gateway")
def gateway_metrics(hours: int = Query(24, ge=1, le=720), resource_arn: str | None = None):
    return cw.get_gateway_metrics(hours, resource_arn)


@router.get("/memory")
def memory_metrics(hours: int = Query(24, ge=1, le=720), resource_arn: str | None = None):
    return cw.get_memory_metrics(hours, resource_arn)


@router.get("/leaderboard")
def agent_leaderboard(hours: int = Query(24, ge=1, le=720)):
    return cw.get_agent_leaderboard(hours)


@router.get("/tokens")
def token_usage(hours: int = Query(24, ge=1, le=720)):
    return cw.get_token_usage(hours)

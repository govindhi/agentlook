from fastapi import APIRouter, HTTPException
from app.services import agentcore_control as ctrl

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


@router.get("/evaluators")
def get_evaluators():
    return ctrl.list_evaluators()


@router.get("/configs")
def get_configs():
    return ctrl.list_online_evaluation_configs()


@router.get("/configs/{config_id}")
def get_config(config_id: str):
    try:
        return ctrl.get_online_evaluation_config(config_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

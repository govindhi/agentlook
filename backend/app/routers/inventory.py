from fastapi import APIRouter, HTTPException
from app.services import agentcore_control as ctrl

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/runtimes")
def get_runtimes():
    return ctrl.list_agent_runtimes()


@router.get("/runtimes/{runtime_id}")
def get_runtime(runtime_id: str):
    try:
        return ctrl.get_agent_runtime(runtime_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/runtimes/{runtime_id}/endpoints")
def get_runtime_endpoints(runtime_id: str):
    return ctrl.list_agent_runtime_endpoints(runtime_id)


@router.get("/gateways")
def get_gateways():
    return ctrl.list_gateways()


@router.get("/gateways/{gateway_id}/targets")
def get_gateway_targets(gateway_id: str):
    return ctrl.list_gateway_targets(gateway_id)


@router.get("/memories")
def get_memories():
    return ctrl.list_memories()

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.routers import inventory, metrics, sessions, evaluations, traces, health, dashboard

logger = logging.getLogger(__name__)

app = FastAPI(title="AgentLook", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


app.include_router(inventory.router)
app.include_router(metrics.router)
app.include_router(sessions.router)
app.include_router(evaluations.router)
app.include_router(traces.router)
app.include_router(health.router)
app.include_router(dashboard.router)

if settings.debug_endpoints:
    from app.routers import debug
    app.include_router(debug.router)
    logger.info("Debug endpoints enabled at /api/debug/*")

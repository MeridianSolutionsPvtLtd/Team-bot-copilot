from fastapi import FastAPI

from app.copilot_api import router as copilot_router
from app.db import init_db
from app.scheduler import start_scheduler
from app.subscriptions import ensure_subscription
from app.webhook import router as webhook_router

app = FastAPI(title="Teams Meeting Intelligence Agent")
app.include_router(webhook_router, prefix="/graph", tags=["graph"])
app.include_router(copilot_router, prefix="/api", tags=["copilot"])


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.on_event("startup")
def startup() -> None:
    init_db()
    ensure_subscription()
    start_scheduler()

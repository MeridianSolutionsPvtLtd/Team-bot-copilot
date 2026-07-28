import logging
import threading
import time

from fastapi import FastAPI

from app.copilot_api import router as copilot_router
from app.db import init_db
from app.scheduler import start_scheduler
from app.subscriptions import ensure_subscription
from app.webhook import router as webhook_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Teams Meeting Intelligence Agent")
app.include_router(webhook_router, prefix="/graph", tags=["graph"])
app.include_router(copilot_router, prefix="/api", tags=["copilot"])


@app.get("/health")
def health():
    return {"status": "healthy"}


def _setup_subscription_delayed() -> None:
    # Graph validates the webhook during subscription creation and expects
    # a fast 200 response. Run this only after the app is fully listening.
    time.sleep(8)
    result = ensure_subscription()
    if result is None:
        logger.warning(
            "App started without an active Graph subscription. "
            "Check webhook URL, permissions, and Graph API logs."
        )
    else:
        logger.info("Graph subscription is active: %s", result.get("id"))


@app.on_event("startup")
def startup() -> None:
    init_db()
    start_scheduler()
    threading.Thread(target=_setup_subscription_delayed, daemon=True).start()

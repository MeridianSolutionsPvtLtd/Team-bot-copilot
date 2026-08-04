import logging
import threading
import time

from fastapi import FastAPI

from app.copilot_api import router as copilot_router
from app.db import init_db
from app.logging_setup import configure_logging
from app.scheduler import start_scheduler
from app.subscriptions import ensure_subscription
from app.webhook import router as webhook_router

configure_logging()
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
    logger.info("Subscription setup thread started; waiting 8s for app to listen.")
    time.sleep(8)
    try:
        result = ensure_subscription()
        if result is None:
            logger.warning(
                "App started without an active Graph subscription. "
                "Check webhook URL, tenant transcript Graph access, permissions, and Graph API logs."
            )
        else:
            logger.info(
                "Graph subscription is active: id=%s expiry=%s resource=%s",
                result.get("id"),
                result.get("expirationDateTime"),
                result.get("resource"),
            )
    except Exception:
        logger.exception("Unexpected failure during delayed subscription setup.")


@app.on_event("startup")
def startup() -> None:
    logger.info("Application startup beginning.")
    try:
        init_db()
        logger.info("Storage init completed.")
    except Exception:
        logger.exception("Storage init failed during startup.")
        raise

    try:
        start_scheduler()
        logger.info("Subscription renewal scheduler started.")
    except Exception:
        logger.exception("Scheduler failed to start.")
        raise

    threading.Thread(target=_setup_subscription_delayed, daemon=True, name="graph-sub-setup").start()
    logger.info("Startup complete; Graph subscription setup queued.")

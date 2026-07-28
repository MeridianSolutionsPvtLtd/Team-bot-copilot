import logging

from app.config import settings
from app.graph import TARGET_RESOURCE, create_subscription, list_subscriptions, renew_subscription

logger = logging.getLogger(__name__)


def ensure_subscription() -> dict | None:
    try:
        subscriptions = list_subscriptions()
        for sub in subscriptions:
            if (
                sub.get("resource") == TARGET_RESOURCE
                and sub.get("notificationUrl") == settings.webhook_public_url
            ):
                logger.info("Found existing subscription %s", sub.get("id"))
                return renew_subscription(sub["id"])

        logger.info("No matching subscription found. Creating a new one.")
        return create_subscription()
    except Exception as exc:
        logger.error("Graph subscription setup failed: %s", exc)
        return None

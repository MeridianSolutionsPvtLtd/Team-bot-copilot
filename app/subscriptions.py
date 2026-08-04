import logging

from app.config import settings
from app.graph import TARGET_RESOURCE, create_subscription, list_subscriptions, renew_subscription

logger = logging.getLogger(__name__)


def ensure_subscription() -> dict | None:
    try:
        logger.info(
            "Ensuring Graph subscription for resource=%s notificationUrl=%s",
            TARGET_RESOURCE,
            settings.webhook_public_url,
        )
        subscriptions = list_subscriptions()
        logger.info("Graph currently has %d subscription(s).", len(subscriptions))
        for sub in subscriptions:
            logger.info(
                "Existing subscription id=%s resource=%s url=%s expiry=%s",
                sub.get("id"),
                sub.get("resource"),
                sub.get("notificationUrl"),
                sub.get("expirationDateTime"),
            )
            if (
                sub.get("resource") == TARGET_RESOURCE
                and sub.get("notificationUrl") == settings.webhook_public_url
            ):
                logger.info("Found matching subscription %s — renewing.", sub.get("id"))
                renewed = renew_subscription(sub["id"])
                logger.info(
                    "Renewed subscription %s until %s",
                    renewed.get("id"),
                    renewed.get("expirationDateTime"),
                )
                return renewed

        logger.info("No matching subscription found. Creating a new one.")
        created = create_subscription()
        logger.info(
            "Created subscription %s until %s",
            created.get("id"),
            created.get("expirationDateTime"),
        )
        return created
    except Exception as exc:
        logger.error("Graph subscription setup failed: %s", exc, exc_info=True)
        return None

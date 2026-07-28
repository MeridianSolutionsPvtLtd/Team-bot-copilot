from app.graph import create_subscription, list_subscriptions, renew_subscription

TARGET_RESOURCE = "communications/onlineMeetings/getAllTranscripts"


def ensure_subscription() -> dict:
    subscriptions = list_subscriptions()
    for sub in subscriptions:
        if sub.get("resource") == TARGET_RESOURCE:
            return renew_subscription(sub["id"])
    return create_subscription()

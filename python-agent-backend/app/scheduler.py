from apscheduler.schedulers.background import BackgroundScheduler

from app.subscriptions import ensure_subscription

scheduler = BackgroundScheduler(timezone="UTC")


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(ensure_subscription, "interval", hours=12, id="renew_subscription", replace_existing=True)
    scheduler.start()

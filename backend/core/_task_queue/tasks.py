from celery import shared_task


@shared_task
def ping_task(message: str = "pong") -> dict:
    return {"message": message}

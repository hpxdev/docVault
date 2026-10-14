"""Celery tasks: thin wrappers around `app.services.pipeline.execute_stage`."""

from app.core.config import get_settings
from app.services.pipeline import execute_stage
from app.workers import stages  # noqa: F401  (registers stage functions)
from app.workers.celery_app import TIME_LIMITS, celery_app


def _make_task(stage: str):
    soft, hard = TIME_LIMITS[stage]

    @celery_app.task(
        name=f"vault.{stage}", bind=True, soft_time_limit=soft, time_limit=hard, max_retries=None
    )
    def run(self, document_id: str) -> str:
        outcome = execute_stage(
            stage,
            document_id,
            attempt=self.request.retries + 1,
            task_id=self.request.id,
        )
        if outcome.result == "retry":
            raise self.retry(countdown=outcome.countdown, max_retries=get_settings().ai_max_retries)
        return outcome.result

    return run


extract_task = _make_task("extract")
index_task = _make_task("index")
insights_task = _make_task("insights")

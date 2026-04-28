import logging

from celery import shared_task
from django.db import transaction

from .models import Job, JobStatus
from .pipeline import run_job_pipeline

logger = logging.getLogger(__name__)


@shared_task
def run_pipeline_job(job_id: str) -> None:
    with transaction.atomic():
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            return
        if job.status == JobStatus.CANCELLED:
            return
        if job.status != JobStatus.PENDING:
            return
        job.status = JobStatus.PROCESSING
        job.save(update_fields=["status", "updated_at"])
        logger.info("Job %s processing", job_id)

    run_job_pipeline(job_id)

import logging
import time

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Job, JobStatus

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

    time.sleep(0.12)

    with transaction.atomic():
        try:
            job = Job.objects.select_for_update().get(pk=job_id)
        except Job.DoesNotExist:
            return
        if job.status == JobStatus.CANCELLED:
            return
        if job.status != JobStatus.PROCESSING:
            return
        job.status = JobStatus.COMPLETED
        job.partial_results = {
            "stub": True,
            "stages": job.pipeline_config.get("stages", []),
        }
        job.updated_at = timezone.now()
        job.save(update_fields=["status", "partial_results", "updated_at"])
        logger.info("Job %s completed (stub)", job_id)

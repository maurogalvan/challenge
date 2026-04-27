from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Job, JobStatus

logger = logging.getLogger(__name__)

STAGE_ORDER = ("extract", "analyze", "enrich")


class JobTransitionError(ValueError):
    pass


def normalize_pipeline_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("pipeline_config must be a JSON object")
    raw_stages = config.get("stages")
    if raw_stages is None:
        raise ValueError("pipeline_config.stages is required")
    if not isinstance(raw_stages, list):
        raise ValueError("pipeline_config.stages must be a list")
    allowed = set(STAGE_ORDER)
    for s in raw_stages:
        if not isinstance(s, str) or s not in allowed:
            raise ValueError(
                f"Invalid stage {s!r}. Use only: {', '.join(STAGE_ORDER)}"
            )
    pos = {name: i for i, name in enumerate(STAGE_ORDER)}
    seen: set[str] = set()
    ordered: list[str] = []
    for s in sorted(raw_stages, key=lambda x: pos[x]):
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    out: dict[str, Any] = {**config, "stages": ordered}
    return out


@transaction.atomic
def create_job(
    *,
    document_name: str,
    document_type: str,
    content: str,
    pipeline_config: dict[str, Any],
) -> Job:
    cfg = normalize_pipeline_config(pipeline_config)
    job = Job.objects.create(
        document_name=document_name,
        document_type=document_type,
        content=content,
        pipeline_config=cfg,
        status=JobStatus.PENDING,
    )
    return job


def get_job_by_id(job_id) -> Job | None:
    try:
        return Job.objects.get(pk=job_id)
    except Job.DoesNotExist:
        return None


def list_jobs(*, status: str | None = None):
    qs = Job.objects.all()
    if status is not None:
        if status not in {c.value for c in JobStatus}:
            return None, "Invalid status filter"
        qs = qs.filter(status=status)
    return qs, None


@transaction.atomic
def request_cancel_job(job: Job) -> bool:
    job = Job.objects.select_for_update().get(pk=job.pk)
    if job.status in (
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ):
        return False
    if job.status not in (JobStatus.PENDING, JobStatus.PROCESSING):
        return False
    job.status = JobStatus.CANCELLED
    job.save(update_fields=["status", "updated_at"])
    logger.info("Job %s cancelled at %s", job.pk, timezone.now())
    return True


def ensure_transition(from_status: str, to_status: str) -> None:
    allowed: dict[str, set[str]] = {
        JobStatus.PENDING: {JobStatus.PROCESSING, JobStatus.CANCELLED, JobStatus.FAILED},
        JobStatus.PROCESSING: {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        },
        JobStatus.COMPLETED: set(),
        JobStatus.FAILED: set(),
        JobStatus.CANCELLED: set(),
    }
    if to_status not in allowed.get(from_status, set()):
        raise JobTransitionError(
            f"Cannot move from {from_status!r} to {to_status!r}"
        )

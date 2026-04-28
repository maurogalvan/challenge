from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from .models import Job, JobStatus

logger = logging.getLogger(__name__)

STAGE_ORDER = ("extract", "analyze", "enrich")
PROVIDER_SPEEDS = frozenset({"fast", "slow"})


class JobTransitionError(ValueError):
    pass


def _normalize_overrides(config: dict[str, Any]) -> dict[str, str] | None:
    raw = config.get("provider_overrides")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("pipeline_config.provider_overrides must be an object")
    for key in raw:
        if key not in STAGE_ORDER:
            raise ValueError(
                f"Unknown key in provider_overrides: {key!r} "
                f"(allowed: {', '.join(STAGE_ORDER)})"
            )
    out: dict[str, str] = {}
    for stage in STAGE_ORDER:
        if stage not in raw:
            continue
        v = raw[stage]
        if not isinstance(v, str) or v.lower() not in PROVIDER_SPEEDS:
            raise ValueError(
                f"provider_overrides.{stage} must be 'fast' or 'slow'"
            )
        out[stage] = v.lower()
    return out or None


def normalize_pipeline_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("pipeline_config must be a JSON object")
    raw_stages = config.get("stages")
    if raw_stages is None:
        raise ValueError("pipeline_config.stages is required")
    if not isinstance(raw_stages, list):
        raise ValueError("pipeline_config.stages must be a list")
    if len(raw_stages) == 0:
        raise ValueError("pipeline_config.stages must contain at least one stage")
    allowed = set(STAGE_ORDER)
    for s in raw_stages:
        if not isinstance(s, str) or s not in allowed:
            raise ValueError(
                f"Invalid stage {s!r}. Use only: {', '.join(STAGE_ORDER)}"
            )
    wanted = {s for s in raw_stages if isinstance(s, str)}
    ordered = [s for s in STAGE_ORDER if s in wanted]
    if not ordered:
        raise ValueError("pipeline_config.stages must contain at least one valid stage")
    k = len(ordered)
    prefix = list(STAGE_ORDER)[:k]
    if ordered != prefix:
        raise ValueError(
            "pipeline_config.stages must be a contiguous prefix of the pipeline: "
            "['extract'], ['extract', 'analyze'], or "
            "['extract', 'analyze', 'enrich'] (order is normalized). "
            f"Got a non-prefix set equivalent to {ordered!r}."
        )
    ovr = _normalize_overrides(config)
    if ovr:
        for key in ovr:
            if key not in ordered:
                raise ValueError(
                    f"provider_overrides.{key} is not applicable to stages {ordered!r}"
                )
    base = {
        k: v
        for k, v in config.items()
        if k not in ("stages", "provider_overrides")
    }
    out: dict[str, Any] = {**base, "stages": ordered}
    if ovr is not None:
        out["provider_overrides"] = ovr
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

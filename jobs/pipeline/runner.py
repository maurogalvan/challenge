from __future__ import annotations

import logging
import time
from typing import Any

from django.db import transaction

from .. import event_stream, services
from ..models import Job, JobStatus
from ..providers import get_analyzer, get_enricher, get_extractor

logger = logging.getLogger(__name__)


def _override(cfg: dict[str, Any], stage: str) -> str:
    raw = cfg.get("provider_overrides")
    if not isinstance(raw, dict):
        return "fast"
    v = raw.get(stage, "fast")
    return v if isinstance(v, str) else "fast"


def _mark_failed(
    job_id,
    error_message: str,
    partial_results: dict[str, Any],
) -> bool:
    from django.utils import timezone

    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job_id)
        if job.status == JobStatus.CANCELLED:
            return False
        if job.status != JobStatus.PROCESSING:
            return False
        services.ensure_transition(job.status, JobStatus.FAILED)
        job.status = JobStatus.FAILED
        job.error_message = error_message
        job.partial_results = partial_results
        job.updated_at = timezone.now()
        job.save(
            update_fields=["status", "error_message", "partial_results", "updated_at"]
        )
        logger.warning("job_failed job_id=%s error=%s", job_id, error_message)
        return True


def _mark_completed(job_id: str, partial_results: dict[str, Any]) -> bool:
    from django.utils import timezone

    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job_id)
        if job.status == JobStatus.CANCELLED:
            return False
        if job.status != JobStatus.PROCESSING:
            return False
        services.ensure_transition(job.status, JobStatus.COMPLETED)
        job.status = JobStatus.COMPLETED
        job.partial_results = partial_results
        job.error_message = ""
        job.updated_at = timezone.now()
        job.save(
            update_fields=["status", "partial_results", "error_message", "updated_at"]
        )
        logger.info("job_completed job_id=%s", job_id)
        return True


def _save_progress(job_id: str, by_stage: dict[str, Any]) -> None:
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job_id)
        if job.status == JobStatus.CANCELLED:
            return
        if job.status != JobStatus.PROCESSING:
            return
        job.partial_results = {"by_stage": by_stage}
        job.save(update_fields=["partial_results", "updated_at"])


def _cancelled(job_id) -> bool:
    j = Job.objects.get(pk=job_id)
    return j.status == JobStatus.CANCELLED


def run_job_pipeline(job_id: str) -> None:
    try:
        job = Job.objects.get(pk=job_id)
    except Job.DoesNotExist:
        return

    if job.status != JobStatus.PROCESSING:
        return

    cfg: dict = job.pipeline_config
    stages: list[str] = list(cfg.get("stages") or [])
    by_stage: dict[str, Any] = {}
    if isinstance(job.partial_results, dict) and "by_stage" in (job.partial_results or {}):
        by_stage = dict((job.partial_results or {}).get("by_stage") or {})

    working_text: str = job.content
    analysis: dict[str, Any] | None = None

    logger.info("pipeline_start job_id=%s stages=%s", job_id, stages)

    for stage in stages:
        if _cancelled(job_id):
            return

        var = _override(cfg, stage)
        logger.info(
            "pipeline_stage_start job_id=%s stage=%s provider_variant=%s",
            job_id,
            stage,
            var,
        )
        event_stream.publish_job_event(
            job_id,
            "job.stage_started",
            {"stage": stage, "provider_variant": var},
        )

        stage_start = time.perf_counter()
        try:
            if stage == "extract":
                ex = get_extractor(_override(cfg, "extract"))
                working_text = ex.extract(working_text)
                by_stage["extract"] = {"text": working_text}
            elif stage == "analyze":
                an = get_analyzer(_override(cfg, "analyze"))
                analysis = an.analyze(working_text)
                by_stage["analyze"] = analysis
            elif stage == "enrich":
                assert analysis is not None
                en = get_enricher(_override(cfg, "enrich"))
                by_stage["enrich"] = en.enrich(analysis)
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - stage_start) * 1000)
            logger.exception(
                "pipeline_stage_failed job_id=%s stage=%s provider_variant=%s elapsed_ms=%s",
                job_id,
                stage,
                var,
                elapsed_ms,
            )
            err_msg = f"{stage}: {e}"[:2000]
            if _mark_failed(
                job_id,
                err_msg,
                {"by_stage": by_stage, "last_stage": stage},
            ):
                event_stream.publish_job_event(
                    job_id,
                    "job.failed",
                    {
                        "last_stage": stage,
                        "error_message": err_msg,
                    },
                )
            return

        _save_progress(job_id, by_stage)
        elapsed_ms = int((time.perf_counter() - stage_start) * 1000)
        logger.info(
            "pipeline_stage_completed job_id=%s stage=%s provider_variant=%s elapsed_ms=%s",
            job_id,
            stage,
            var,
            elapsed_ms,
        )
        if not _cancelled(job_id):
            event_stream.publish_job_event(
                job_id,
                "job.stage_completed",
                {"stage": stage, "result": by_stage.get(stage)},
            )

    if _mark_completed(job_id, {"by_stage": by_stage}):
        event_stream.publish_job_event(
            job_id,
            "job.completed",
            {"stages": list(by_stage.keys())},
        )

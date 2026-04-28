from unittest.mock import patch

import pytest

from jobs.models import Job, JobStatus
from jobs.pipeline.runner import run_job_pipeline
from jobs.services import create_job, request_cancel_job


@pytest.mark.django_db
def test_create_job_emits_job_created(django_capture_on_commit_callbacks):
    with patch("jobs.event_stream.publish_job_event") as publish:
        with django_capture_on_commit_callbacks(execute=True):
            job = create_job(
                document_name="doc.txt",
                document_type="text/plain",
                content="hola",
                pipeline_config={"stages": ["extract"]},
            )

    publish.assert_called_once()
    args = publish.call_args.args
    assert args[0] == str(job.id)
    assert args[1] == "job.created"


@pytest.mark.django_db
def test_cancel_job_emits_job_cancelled(django_capture_on_commit_callbacks):
    job = Job.objects.create(
        document_name="doc.txt",
        document_type="text/plain",
        content="hola",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.PENDING,
    )
    with patch("jobs.event_stream.publish_job_event") as publish:
        with django_capture_on_commit_callbacks(execute=True):
            ok = request_cancel_job(job)

    assert ok is True
    publish.assert_called_once_with(str(job.id), "job.cancelled", {})


@pytest.mark.django_db
def test_pipeline_extract_emits_stage_and_completed_events():
    job = Job.objects.create(
        document_name="doc.txt",
        document_type="text/plain",
        content="hola",
        pipeline_config={"stages": ["extract"], "provider_overrides": {"extract": "fast"}},
        status=JobStatus.PROCESSING,
    )
    with patch("jobs.pipeline.runner.event_stream.publish_job_event") as publish:
        run_job_pipeline(str(job.id))

    event_types = [call.args[1] for call in publish.call_args_list]
    assert event_types == [
        "job.stage_started",
        "job.stage_completed",
        "job.completed",
    ]


@pytest.mark.django_db
def test_pipeline_failure_emits_job_failed_event():
    job = Job.objects.create(
        document_name="doc.txt",
        document_type="text/plain",
        content="hola",
        pipeline_config={"stages": ["extract", "analyze", "enrich"]},
        status=JobStatus.PROCESSING,
    )

    from jobs.providers.analyzers import FastMockAnalyzer

    def _boom(self, text: str):
        raise RuntimeError("force fail")

    with patch("jobs.pipeline.runner.event_stream.publish_job_event") as publish:
        with patch.object(FastMockAnalyzer, "analyze", _boom):
            run_job_pipeline(str(job.id))

    event_types = [call.args[1] for call in publish.call_args_list]
    assert "job.failed" in event_types

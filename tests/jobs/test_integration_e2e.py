from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from jobs.models import Job, JobStatus
from jobs.providers.analyzers import FastMockAnalyzer


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_e2e_create_job_runs_pipeline_and_emits_events(
    api: APIClient, django_capture_on_commit_callbacks
):
    emitted: List[Tuple[str, str, Dict[str, Any]]] = []

    def _capture(
        job_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        emitted.append((job_id, event_type, payload or {}))
        return True

    with patch("jobs.event_stream.publish_job_event", side_effect=_capture):
        with django_capture_on_commit_callbacks(execute=True):
            r = api.post(
                "/api/v1/jobs/",
                {
                    "document_name": "e2e.txt",
                    "document_type": "text/plain",
                    "content": "hola mundo e2e",
                    "pipeline_config": {
                        "stages": ["extract", "analyze"],
                        "provider_overrides": {"extract": "fast", "analyze": "fast"},
                    },
                },
                format="json",
            )

    assert r.status_code == 201, r.content
    job_id = r.data["job_id"]
    job = Job.objects.get(pk=job_id)
    assert job.status == JobStatus.COMPLETED
    assert "by_stage" in (job.partial_results or {})
    assert "extract" in job.partial_results["by_stage"]
    assert "analyze" in job.partial_results["by_stage"]

    event_types = [e[1] for e in emitted]
    assert event_types.count("job.created") == 1
    assert event_types.count("job.stage_started") == 2
    assert event_types.count("job.stage_completed") == 2
    assert event_types.count("job.completed") == 1
    # Con transacciones de test, el callback on_commit de job.created
    # puede ejecutarse después de los eventos de pipeline.
    assert event_types.index("job.completed") > event_types.index("job.stage_started")
    assert all(e[0] == str(job_id) for e in emitted)


@pytest.mark.django_db
def test_e2e_failure_emits_failed_event_and_keeps_partials(
    api: APIClient, django_capture_on_commit_callbacks
):
    emitted: List[Tuple[str, str, Dict[str, Any]]] = []

    def _capture(
        job_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        emitted.append((job_id, event_type, payload or {}))
        return True

    def _boom(self, text: str):
        raise RuntimeError("forced integration fail")

    with patch.object(FastMockAnalyzer, "analyze", _boom):
        with patch("jobs.event_stream.publish_job_event", side_effect=_capture):
            with django_capture_on_commit_callbacks(execute=True):
                r = api.post(
                    "/api/v1/jobs/",
                    {
                        "document_name": "e2e-fail.txt",
                        "document_type": "text/plain",
                        "content": "hola mundo e2e fail",
                        "pipeline_config": {
                            "stages": ["extract", "analyze", "enrich"],
                            "provider_overrides": {
                                "extract": "fast",
                                "analyze": "fast",
                            },
                        },
                    },
                    format="json",
                )

    assert r.status_code == 201, r.content
    job_id = r.data["job_id"]
    job = Job.objects.get(pk=job_id)
    assert job.status == JobStatus.FAILED
    assert "analyze" in job.error_message
    assert "by_stage" in (job.partial_results or {})
    assert "extract" in job.partial_results["by_stage"]

    event_types = [e[1] for e in emitted]
    assert "job.failed" in event_types
    assert "job.completed" not in event_types

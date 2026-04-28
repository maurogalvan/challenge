from unittest.mock import patch

import pytest

from jobs.models import JobStatus
from jobs.pipeline.runner import run_job_pipeline
from jobs.services import create_job


@pytest.mark.django_db
def test_run_pipeline_completes_with_stages():
    j = create_job(
        document_name="a",
        document_type="t",
        content="hello world",
        pipeline_config={
            "stages": ["extract", "analyze"],
            "provider_overrides": {"extract": "fast", "analyze": "slow"},
        },
    )
    j.status = JobStatus.PROCESSING
    j.save()
    run_job_pipeline(str(j.id))
    j.refresh_from_db()
    assert j.status == JobStatus.COMPLETED
    assert j.error_message == ""
    assert "by_stage" in (j.partial_results or {})
    assert "extract" in j.partial_results["by_stage"]
    assert "analyze" in j.partial_results["by_stage"]
    assert j.partial_results["by_stage"]["extract"]["text"]


@pytest.mark.django_db
def test_run_pipeline_fails_and_keeps_partials():
    j = create_job(
        document_name="a",
        document_type="t",
        content="x",
        pipeline_config={"stages": ["extract", "analyze", "enrich"]},
    )
    j.status = JobStatus.PROCESSING
    j.save()

    from jobs.providers.analyzers import FastMockAnalyzer

    def _boom(self, text: str):
        raise RuntimeError("force fail")

    with patch.object(FastMockAnalyzer, "analyze", _boom):
        run_job_pipeline(str(j.id))

    j.refresh_from_db()
    assert j.status == JobStatus.FAILED
    assert "analyze" in j.error_message
    pr = j.partial_results or {}
    assert "by_stage" in pr
    assert "extract" in pr["by_stage"]
    assert pr.get("last_stage") == "analyze"

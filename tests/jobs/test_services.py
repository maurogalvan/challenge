import pytest

from jobs.models import JobStatus
from jobs.services import (
    create_job,
    get_job_by_id,
    list_jobs,
    normalize_pipeline_config,
    request_cancel_job,
)


def test_normalize_pipeline_config_orders_stages():
    assert normalize_pipeline_config(
        {"stages": ["enrich", "extract", "extract"]}
    )["stages"] == ["extract", "enrich"]


def test_normalize_rejects_invalid_stage():
    with pytest.raises(ValueError, match="Invalid stage"):
        normalize_pipeline_config({"stages": ["extract", "laser"]})


@pytest.mark.django_db
def test_create_job():
    j = create_job(
        document_name="a.pdf",
        document_type="application/pdf",
        content="x",
        pipeline_config={"stages": ["extract"]},
    )
    assert j.status == JobStatus.PENDING
    assert get_job_by_id(j.id) is not None


@pytest.mark.django_db
def test_list_jobs_filter():
    create_job(
        document_name="a",
        document_type="",
        content="c",
        pipeline_config={"stages": ["extract"]},
    )
    qs, err = list_jobs(status=JobStatus.PENDING)
    assert err is None
    assert qs.count() >= 1
    q2, err2 = list_jobs(status="nope")
    assert q2 is None
    assert err2


@pytest.mark.django_db
def test_cancel_only_when_active():
    j = create_job(
        document_name="a",
        document_type="",
        content="c",
        pipeline_config={"stages": ["extract"]},
    )
    j.status = JobStatus.COMPLETED
    j.save()
    assert request_cancel_job(j) is False
    j2 = create_job(
        document_name="b",
        document_type="",
        content="c",
        pipeline_config={"stages": ["extract"]},
    )
    assert request_cancel_job(j2) is True
    j2.refresh_from_db()
    assert j2.status == JobStatus.CANCELLED

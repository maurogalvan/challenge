import pytest
from rest_framework.test import APIClient

from jobs.models import Job, JobStatus


@pytest.fixture
def api():
    return APIClient()


@pytest.mark.django_db
def test_create_list_retrieve_and_cancel_flow(api: APIClient):
    r = api.post(
        "/api/v1/jobs/",
        {
            "document_name": "x.txt",
            "document_type": "text/plain",
            "content": "hola",
            "pipeline_config": {"stages": ["extract", "analyze"]},
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    job_id = r.data["job_id"]
    g = api.get(f"/api/v1/jobs/{job_id}/")
    assert g.status_code == 200
    assert g.data["status"] in (JobStatus.PENDING, JobStatus.PROCESSING, JobStatus.COMPLETED)
    listed = api.get("/api/v1/jobs/?status=pending")
    assert listed.status_code == 200
    assert "results" in listed.data
    c = api.post(f"/api/v1/jobs/{job_id}/cancel/", {}, format="json")
    if c.status_code == 200:
        assert c.data["status"] == JobStatus.CANCELLED
    else:
        assert c.status_code == 409


@pytest.mark.django_db
def test_cancel_conflict_when_completed(api: APIClient):
    j = Job.objects.create(
        document_name="f",
        document_type="t",
        content="c",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.COMPLETED,
    )
    r = api.post(f"/api/v1/jobs/{j.id}/cancel/", {}, format="json")
    assert r.status_code == 409


@pytest.mark.django_db
def test_list_invalid_status(api: APIClient):
    r = api.get("/api/v1/jobs/?status=notastate")
    assert r.status_code == 400

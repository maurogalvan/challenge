from unittest.mock import patch

import grpc
import pytest

import job_gateway_pb2 as pb2
from jobs.grpc_service import DocumentProcessingGatewayServicer
from jobs.models import Job, JobStatus


class _Ctx:
    def __init__(self):
        self.code = None
        self.details = ""

    def set_code(self, code):
        self.code = code

    def set_details(self, details):
        self.details = details


@pytest.mark.django_db
def test_grpc_create_job_success_calls_shared_service_and_enqueues_task():
    svc = DocumentProcessingGatewayServicer()
    req = pb2.CreateJobRequest(
        document_name="grpc.txt",
        document_type="text/plain",
        content="hola grpc",
        pipeline_config=pb2.PipelineConfig(
            stages=["extract", "analyze"],
            provider_overrides={"extract": "fast", "analyze": "fast"},
        ),
    )
    ctx = _Ctx()
    with patch("jobs.grpc_service.run_pipeline_job.delay") as delay:
        res = svc.CreateJob(req, ctx)
    assert ctx.code is None
    assert res.job_id
    assert res.status in {JobStatus.PENDING, JobStatus.PROCESSING, JobStatus.COMPLETED}
    delay.assert_called_once_with(res.job_id)


@pytest.mark.django_db
def test_grpc_create_job_validation_error():
    svc = DocumentProcessingGatewayServicer()
    req = pb2.CreateJobRequest(
        document_name="grpc.txt",
        document_type="text/plain",
        content="hola grpc",
        pipeline_config=pb2.PipelineConfig(stages=["enrich"]),
    )
    ctx = _Ctx()
    res = svc.CreateJob(req, ctx)
    assert res.job_id == ""
    assert ctx.code == grpc.StatusCode.INVALID_ARGUMENT
    assert "contiguous prefix" in ctx.details or "prefix" in ctx.details


@pytest.mark.django_db
def test_grpc_get_job_success_and_not_found():
    svc = DocumentProcessingGatewayServicer()
    j = Job.objects.create(
        document_name="x",
        document_type="t",
        content="c",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.COMPLETED,
    )

    ok_ctx = _Ctx()
    ok_res = svc.GetJob(pb2.GetJobRequest(job_id=str(j.id)), ok_ctx)
    assert ok_ctx.code is None
    assert ok_res.job_id == str(j.id)
    assert ok_res.status == JobStatus.COMPLETED

    miss_ctx = _Ctx()
    miss_res = svc.GetJob(pb2.GetJobRequest(job_id="00000000-0000-0000-0000-000000000000"), miss_ctx)
    assert miss_res.job_id == ""
    assert miss_ctx.code == grpc.StatusCode.NOT_FOUND


@pytest.mark.django_db
def test_grpc_list_jobs_with_filter_and_invalid_filter():
    svc = DocumentProcessingGatewayServicer()
    Job.objects.create(
        document_name="a",
        document_type="text/plain",
        content="1",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.PENDING,
    )
    Job.objects.create(
        document_name="b",
        document_type="text/plain",
        content="2",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.COMPLETED,
    )

    ok_ctx = _Ctx()
    ok_res = svc.ListJobs(pb2.ListJobsRequest(status=JobStatus.PENDING), ok_ctx)
    assert ok_ctx.code is None
    assert len(ok_res.jobs) >= 1
    assert all(j.status == JobStatus.PENDING for j in ok_res.jobs)

    bad_ctx = _Ctx()
    bad_res = svc.ListJobs(pb2.ListJobsRequest(status="wrong"), bad_ctx)
    assert len(bad_res.jobs) == 0
    assert bad_ctx.code == grpc.StatusCode.INVALID_ARGUMENT


@pytest.mark.django_db
def test_grpc_cancel_job_success_conflict_and_not_found():
    svc = DocumentProcessingGatewayServicer()
    pending = Job.objects.create(
        document_name="p",
        document_type="text/plain",
        content="x",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.PENDING,
    )
    done = Job.objects.create(
        document_name="d",
        document_type="text/plain",
        content="y",
        pipeline_config={"stages": ["extract"]},
        status=JobStatus.COMPLETED,
    )

    ok_ctx = _Ctx()
    ok_res = svc.CancelJob(pb2.CancelJobRequest(job_id=str(pending.id)), ok_ctx)
    assert ok_ctx.code is None
    assert ok_res.ok is True
    assert ok_res.job.status == JobStatus.CANCELLED

    conflict_ctx = _Ctx()
    conflict_res = svc.CancelJob(pb2.CancelJobRequest(job_id=str(done.id)), conflict_ctx)
    assert conflict_ctx.code is None
    assert conflict_res.ok is False
    assert conflict_res.job.status == JobStatus.COMPLETED
    assert "cannot cancel" in conflict_res.detail

    miss_ctx = _Ctx()
    miss_res = svc.CancelJob(
        pb2.CancelJobRequest(job_id="00000000-0000-0000-0000-000000000000"),
        miss_ctx,
    )
    assert miss_res.ok is False
    assert miss_ctx.code == grpc.StatusCode.NOT_FOUND

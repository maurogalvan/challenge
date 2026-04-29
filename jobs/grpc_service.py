from __future__ import annotations

import json
from concurrent import futures
from typing import Any

import grpc
from django.conf import settings

import job_gateway_pb2 as pb2
import job_gateway_pb2_grpc as pb2_grpc
from jobs.models import Job
from jobs.services import create_job, get_job_by_id, list_jobs, request_cancel_job
from jobs.tasks import run_pipeline_job


def _job_to_response(job: Job) -> pb2.JobResponse:
    return pb2.JobResponse(
        job_id=str(job.id),
        status=job.status,
        document_name=job.document_name,
        document_type=job.document_type,
        content=job.content,
        pipeline_config_json=json.dumps(job.pipeline_config or {}, ensure_ascii=False),
        partial_results_json=json.dumps(job.partial_results or {}, ensure_ascii=False),
        error_message=job.error_message or "",
        created_at=job.created_at.isoformat().replace("+00:00", "Z"),
        updated_at=job.updated_at.isoformat().replace("+00:00", "Z"),
    )


class DocumentProcessingGatewayServicer(pb2_grpc.DocumentProcessingGatewayServicer):
    def CreateJob(self, request: pb2.CreateJobRequest, context: grpc.ServicerContext):
        try:
            pipeline_config: dict[str, Any] = {
                "stages": list(request.pipeline_config.stages),
            }
            if request.pipeline_config.provider_overrides:
                pipeline_config["provider_overrides"] = dict(
                    request.pipeline_config.provider_overrides
                )
            job = create_job(
                document_name=request.document_name.strip(),
                document_type=request.document_type.strip(),
                content=request.content,
                pipeline_config=pipeline_config,
            )
        except ValueError as exc:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(exc))
            return pb2.JobResponse()

        run_pipeline_job.delay(str(job.id))
        job.refresh_from_db()
        return _job_to_response(job)

    def GetJob(self, request: pb2.GetJobRequest, context: grpc.ServicerContext):
        job = get_job_by_id(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Job not found")
            return pb2.JobResponse()
        return _job_to_response(job)

    def ListJobs(
        self, request: pb2.ListJobsRequest, context: grpc.ServicerContext
    ) -> pb2.ListJobsResponse:
        status_filter = request.status.strip() or None
        qs, err = list_jobs(status=status_filter)
        if err is not None:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(err)
            return pb2.ListJobsResponse()
        assert qs is not None
        return pb2.ListJobsResponse(jobs=[_job_to_response(j) for j in qs])

    def CancelJob(
        self, request: pb2.CancelJobRequest, context: grpc.ServicerContext
    ) -> pb2.CancelJobResponse:
        job = get_job_by_id(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Job not found")
            return pb2.CancelJobResponse(ok=False, detail="Job not found")

        ok = request_cancel_job(job)
        job.refresh_from_db()
        if ok:
            return pb2.CancelJobResponse(ok=True, job=_job_to_response(job), detail="")
        return pb2.CancelJobResponse(
            ok=False,
            job=_job_to_response(job),
            detail="Job already finished; cannot cancel.",
        )


def make_server() -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb2_grpc.add_DocumentProcessingGatewayServicer_to_server(
        DocumentProcessingGatewayServicer(),
        server,
    )
    bind = f"{settings.GRPC_HOST}:{settings.GRPC_PORT}"
    server.add_insecure_port(bind)
    return server

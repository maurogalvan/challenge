from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Job
from .serializers import (
    CreateJobSerializer,
    JobDetailSerializer,
    JobListSerializer,
)
from .services import get_job_by_id, list_jobs, request_cancel_job
from .tasks import run_pipeline_job


class JobViewSet(viewsets.GenericViewSet):
    permission_classes = [AllowAny]
    authentication_classes = []
    lookup_field = "pk"

    def get_queryset(self):
        return Job.objects.all()

    def get_serializer_class(self):
        if self.action == "create":
            return CreateJobSerializer
        if self.action == "list":
            return JobListSerializer
        return JobDetailSerializer

    def list(self, request, *args, **kwargs):
        st = request.query_params.get("status")
        if st is not None and st == "":
            st = None
        qs, err = list_jobs(status=st)
        if err is not None:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        assert qs is not None
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = JobListSerializer(page, many=True)
            return self.get_paginated_response(ser.data)
        return Response(JobListSerializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        ser = CreateJobSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        job = ser.save()
        run_pipeline_job.delay(str(job.id))
        return Response(
            JobDetailSerializer(job).data,
            status=status.HTTP_201_CREATED,
        )

    def retrieve(self, request, *args, **kwargs):
        job = get_job_by_id(kwargs.get("pk"))
        if not job:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(JobDetailSerializer(job).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        job = get_job_by_id(pk)
        if not job:
            return Response(
                {"detail": "Not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if request_cancel_job(job):
            job.refresh_from_db()
            return Response(JobDetailSerializer(job).data, status=status.HTTP_200_OK)
        return Response(
            {
                "detail": "Job already finished; cannot cancel.",
                "status": job.status,
            },
            status=status.HTTP_409_CONFLICT,
        )

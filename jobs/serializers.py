from rest_framework import serializers

from .models import Job
from .services import create_job, normalize_pipeline_config


class CreateJobSerializer(serializers.Serializer):
    document_name = serializers.CharField(max_length=255)
    document_type = serializers.CharField(
        max_length=100, allow_blank=True, default=""
    )
    content = serializers.CharField()
    pipeline_config = serializers.JSONField()

    def validate_pipeline_config(self, value):
        return normalize_pipeline_config(value)

    def create(self, validated_data):
        return create_job(
            document_name=validated_data["document_name"],
            document_type=validated_data.get("document_type") or "",
            content=validated_data["content"],
            pipeline_config=validated_data["pipeline_config"],
        )


class JobListSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = Job
        fields = (
            "job_id",
            "status",
            "document_name",
            "document_type",
            "created_at",
            "updated_at",
        )


class JobDetailSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = Job
        fields = (
            "job_id",
            "status",
            "document_name",
            "document_type",
            "content",
            "pipeline_config",
            "partial_results",
            "error_message",
            "created_at",
            "updated_at",
        )


"""
Integración con broker Kafka real vía testcontainers (pull de imagen + Docker en el host).

- `SKIP_KAFKA_INTEGRATION=1`: no corre el test (p. ej. sin Docker o CI rápido).
- Requiere Docker en el PATH para levantar el contenedor.
"""
from __future__ import annotations

import os
import shutil
import uuid
from typing import Any

import pytest
from django.test import override_settings

from jobs import event_stream

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("SKIP_KAFKA_INTEGRATION", "").lower() in ("1", "true", "yes"),
        reason="SKIP_KAFKA_INTEGRATION is set",
    ),
    pytest.mark.skipif(
        shutil.which("docker") is None,
        reason="docker not on PATH (testcontainers needs Docker)",
    ),
]


def _poll_first_value(consumer: Any) -> dict:
    for _ in range(90):
        batch = consumer.poll(timeout_ms=1000)
        if not batch:
            continue
        for _tp, records in batch.items():
            for rec in records:
                if rec.value is not None:
                    return rec.value
    return {}


@pytest.mark.django_db
def test_publish_and_consume_against_testcontainers_kafka():
    try:
        from testcontainers.kafka import KafkaContainer
    except ImportError:
        pytest.skip("install dev deps: testcontainers[kafka]")

    topic = f"job-events-tc-{uuid.uuid4().hex[:10]}"
    group = f"tc-{uuid.uuid4().hex[:8]}"
    job_id = str(uuid.uuid4())

    with KafkaContainer().with_kraft() as kc:
        bootstrap = kc.get_bootstrap_server()
        with override_settings(
            KAFKA_ENABLED=True,
            KAFKA_BOOTSTRAP_SERVERS=bootstrap,
            KAFKA_TOPIC_JOBS=topic,
            KAFKA_CONSUMER_GROUP=group,
        ):
            try:
                event_stream.close_producer()
                assert event_stream.publish_job_event(
                    job_id, "job.created", {"smoke": True, "source": "testcontainers"}
                )
                event_stream.flush()
                consumer = event_stream.create_consumer()
                data = _poll_first_value(consumer)
                consumer.close()
                assert data.get("event_type") == "job.created"
                assert data.get("job_id") == job_id
                assert data.get("payload", {}).get("source") == "testcontainers"
            finally:
                event_stream.close_producer()

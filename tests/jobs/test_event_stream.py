import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from jobs import event_stream


def test_build_envelope_has_required_keys():
    jid = str(uuid.uuid4())
    env = event_stream.build_envelope(jid, "job.created", {"x": 1})
    assert env["job_id"] == jid
    assert env["event_type"] == "job.created"
    assert env["payload"] == {"x": 1}
    assert "timestamp" in env and "T" in env["timestamp"]


@pytest.mark.django_db
@override_settings(KAFKA_ENABLED=False)
def test_publish_noop_when_kafka_disabled():
    event_stream.close_producer()
    assert event_stream.publish_job_event("x", "job.created", {}) is True


@pytest.mark.django_db
@override_settings(KAFKA_ENABLED=True, KAFKA_BOOTSTRAP_SERVERS="localhost:9092")
@patch("kafka.KafkaProducer", autospec=True)
def test_publish_retries_on_transient_error(mock_producer_cls):
    event_stream.close_producer()
    mock_inst = MagicMock()
    fut = MagicMock()
    fut.get.side_effect = [ConnectionError("broker down"), None]
    mock_inst.send.return_value = fut
    mock_producer_cls.return_value = mock_inst
    with patch.object(event_stream, "RETRY_BACKOFF_S", (0, 0, 0)):
        assert event_stream.publish_job_event("jid", "job.created", {"a": 1}) is True
    event_stream.close_producer()
    assert fut.get.call_count == 2

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jobs.management.commands.run_kafka_consumer import Command


@dataclass
class _Msg:
    value: object
    partition: int = 0
    offset: int = 0


class _FakeConsumer:
    def __init__(self, messages):
        self._messages = list(messages)
        self._idx = 0
        self.commit_count = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._idx >= len(self._messages):
            raise KeyboardInterrupt()
        m = self._messages[self._idx]
        self._idx += 1
        return m

    def commit(self):
        self.commit_count += 1

    def close(self):
        self.closed = True


@pytest.mark.django_db
def test_consumer_command_commits_after_each_processed_message(settings):
    settings.KAFKA_ENABLED = True
    settings.KAFKA_TOPIC_JOBS = "job-events"
    settings.KAFKA_CONSUMER_GROUP = "downstream-processors"
    consumer = _FakeConsumer(
        [
            _Msg(value={"event_type": "job.created", "job_id": "a"}, offset=1),
            _Msg(value="raw-bytes-like", offset=2),
        ]
    )

    command = Command()
    command.stdout = SimpleNamespace(write=lambda *args, **kwargs: None)
    command.stderr = SimpleNamespace(write=lambda *args, **kwargs: None)

    with patch("jobs.management.commands.run_kafka_consumer.event_stream.create_consumer", return_value=consumer):
        command.handle()

    assert consumer.commit_count == 2
    assert consumer.closed is True

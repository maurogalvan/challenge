#!/usr/bin/env python3
"""
Humo Kafka contra el stack de docker-compose (Kafka ya levantado).

Uso (con compose arriba):

  docker compose -f docker-compose.local.yml exec api python scripts/smoke_kafka_compose.py
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Ensure project root is importable when running `python scripts/...`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import django  # noqa: E402

django.setup()

import kafka  # noqa: E402
from django.conf import settings  # noqa: E402
from jobs import event_stream  # noqa: E402


def main() -> int:
    if not getattr(settings, "KAFKA_ENABLED", True):
        print("KAFKA_ENABLED=false, abort.", file=sys.stderr)
        return 1

    job_id = str(uuid.uuid4())
    mark = f"smoke-compose-{uuid.uuid4().hex[:6]}"

    event_stream.close_producer()
    ok = event_stream.publish_job_event(
        job_id,
        "job.created",
        {"mark": mark},
    )
    if not ok:
        print("publish failed", file=sys.stderr)
        return 1
    event_stream.flush()
    event_stream.close_producer()

    servers = [
        s.strip()
        for s in (settings.KAFKA_BOOTSTRAP_SERVERS or "").split(",")
        if s.strip()
    ]
    consumer = kafka.KafkaConsumer(
        settings.KAFKA_TOPIC_JOBS,
        bootstrap_servers=servers,
        group_id=f"smoke-reader-{uuid.uuid4().hex[:10]}",
        enable_auto_commit=True,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        consumer_timeout_ms=30_000,
    )

    try:
        for msg in consumer:
            v = msg.value or {}
            if v.get("job_id") == job_id and (v.get("payload") or {}).get("mark") == mark:
                print("ok", v.get("event_type"), v.get("job_id"))
                return 0
    except Exception as e:  # noqa: BLE001
        print("kafka error:", e, file=sys.stderr)
        return 1
    finally:
        consumer.close()

    print("timeout: no matching message", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

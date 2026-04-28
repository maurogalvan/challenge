"""
Publicación de eventos de dominio a Kafka (topic configurable).

Con KAFKA_ENABLED=False (p. ej. tests) las llamadas no hacen I/O.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_producer: Any = None

RETRY_BACKOFF_S = (0.1, 0.25, 0.6)
MAX_SEND_RETRIES = 3


def get_producer():
    """Productor singleton (lazy). None si KAFKA_ENABLED es False."""
    global _producer
    if not getattr(settings, "KAFKA_ENABLED", True):
        return None
    if _producer is not None:
        return _producer
    from kafka import KafkaProducer

    servers = [
        s.strip() for s in (settings.KAFKA_BOOTSTRAP_SERVERS or "").split(",") if s.strip()
    ]
    if not servers:
        logger.warning("KAFKA_BOOTSTRAP_SERVERS vacío; eventos deshabilitados")
        return None

    _producer = KafkaProducer(
        bootstrap_servers=servers,
        client_id=f"{settings.KAFKA_CLIENT_ID_PREFIX}-producer-{os.getpid()}",
        value_serializer=lambda v: json.dumps(
            v, default=str, ensure_ascii=False
        ).encode("utf-8"),
        acks="all",
        request_timeout_ms=15_000,
    )
    return _producer


def build_envelope(
    job_id: str, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "job_id": str(job_id),
        "timestamp": timezone.now().isoformat(),
        "event_type": event_type,
        "payload": payload,
    }


def publish_job_event(
    job_id: str, event_type: str, payload: dict[str, Any] | None = None
) -> bool:
    """
    Serializa y envía un evento. Retorna True si se publicó o si Kafka está deshabilitado.
    Retorna False si hubo fallo tras reintentos (el job en DB no se revierte).
    """
    p = get_producer()
    if p is None:
        return True

    envelope = build_envelope(job_id, event_type, payload or {})
    topic = settings.KAFKA_TOPIC_JOBS
    for attempt in range(MAX_SEND_RETRIES):
        try:
            fut = p.send(
                topic, key=str(job_id).encode("utf-8"), value=envelope
            )
            fut.get(timeout=15)
            return True
        except Exception:
            if attempt < MAX_SEND_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)])
            else:
                logger.exception(
                    "Kafka: no se pudo publicar %s job=%s tras %d intentos",
                    event_type,
                    job_id,
                    MAX_SEND_RETRIES,
                )
                return False
    return False


def flush() -> None:
    """Fuerza envío de buffer (p. ej. cierre de proceso de test con broker)."""
    p = get_producer()
    if p is not None:
        p.flush(timeout=5)


def close_producer() -> None:
    global _producer
    if _producer is not None:
        try:
            _producer.flush()
            _producer.close()
        except Exception:  # noqa: S110
            pass
        _producer = None


# UUID estable por proceso para el client_id del consumer (evita colisiones al escalar)
_CONSUMER_ID_SUFFIX = str(uuid.uuid4())[:8]


def create_consumer() -> Any:
    """Consumer con commit manual de offsets (ack explícito vía commit)."""
    from kafka import KafkaConsumer

    servers = [
        s.strip() for s in (settings.KAFKA_BOOTSTRAP_SERVERS or "").split(",") if s.strip()
    ]
    if not servers:
        raise ValueError("KAFKA_BOOTSTRAP_SERVERS requerido para el consumer")

    return KafkaConsumer(
        settings.KAFKA_TOPIC_JOBS,
        bootstrap_servers=servers,
        group_id=settings.KAFKA_CONSUMER_GROUP,
        client_id=f"{settings.KAFKA_CLIENT_ID_PREFIX}-consumer-{_CONSUMER_ID_SUFFIX}",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )

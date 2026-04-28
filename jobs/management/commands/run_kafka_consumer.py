import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from jobs import event_stream

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Consumer Kafka con consumer group: lee el topic de jobs, "
        "loguea cada evento y confirma offset (ack) tras procesar."
    )

    def handle(self, *args, **options):
        if not getattr(settings, "KAFKA_ENABLED", True):
            self.stderr.write("KAFKA_ENABLED=false — no se inicia el consumer.\n")
            return

        consumer = event_stream.create_consumer()
        group = settings.KAFKA_CONSUMER_GROUP
        topic = settings.KAFKA_TOPIC_JOBS
        self.stdout.write(
            self.style.SUCCESS(
                f"Consumer iniciado: topic={topic!r} group_id={group!r} "
                f"(commit manual tras cada mensaje)"
            )
        )
        try:
            for message in consumer:
                data = message.value
                if not isinstance(data, dict):
                    self.stdout.write(f"[skip] payload no-JSON: {message.value!r}")
                    consumer.commit()
                    continue
                et = data.get("event_type", "?")
                jid = data.get("job_id", "?")
                logger.info(
                    "downstream event=%s job_id=%s partition=%s offset=%s",
                    et,
                    jid,
                    message.partition,
                    message.offset,
                )
                self.stdout.write(
                    f"event={et} job_id={jid} offset={message.offset}\n"
                )
                consumer.commit()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nCerrando consumer…"))
        finally:
            consumer.close()

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.grpc_service import make_server

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run gRPC server for bonus API (CreateJob, GetJob)."

    def handle(self, *args, **options):
        server = make_server()
        bind = f"{settings.GRPC_HOST}:{settings.GRPC_PORT}"
        server.start()
        self.stdout.write(self.style.SUCCESS(f"gRPC server listening on {bind}"))
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopping gRPC server..."))
            server.stop(grace=5)

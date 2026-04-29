from django.db import connection
from django.http import HttpRequest, JsonResponse


def health(request: HttpRequest) -> JsonResponse:
    try:
        connection.ensure_connection()
        database = "ok"
    except OSError:
        database = "unavailable"
    except Exception:
        database = "error"
    return JsonResponse({"status": "ok", "database": database})

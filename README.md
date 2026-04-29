# Document Processing Gateway

Gateway en **Django + DRF**: pipeline `extract` → `analyze` → `enrich` (mocks fast/slow), tareas con **Celery** + **Redis**, estado en **Postgres**, eventos `job.*` en **Kafka** (consumer con group + commit manual), y bonus **gRPC** apoyado en los mismos servicios que REST.

**Requisito del enunciado: Python 3.10+.** En la práctica: usá el **contenedor** (`api` trae 3.10). En el host, no compiles un venv con 3.9.

---

## Cómo levantarlo (recomendado: Docker)

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Quedan: `api` (:8000), `worker`, `grpc` (:50051), `kafka_consumer`, Postgres, Redis, Kafka. Variables: `docker/defaults.env`.

- Health: `http://127.0.0.1:8000/health/`
- API: `http://127.0.0.1:8000/api/v1/`
- Python en contenedor: `docker compose -f docker-compose.local.yml exec api python --version`

**Bruno:** carpeta `challengue/`, environment `environments/local.yml` (`api_url` → `http://localhost:8000/api/v1`). Son requests que fui dejando para probar create/list/get/cancel y distintas combinaciones de etapas. gRPC se prueba aparte (`run_grpc_server` o servicio `grpc`).

**Humo Kafka en compose (sin pytest):**

```bash
docker compose -f docker-compose.local.yml exec api python scripts/smoke_kafka_compose.py
```

**Tests en contenedor (perfil recomendado):**

```bash
docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/"
```

**Perfiles de test:**

- Rápido (sin integración pesada):  
  `docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/ -m 'not integration'"`
- Completo (incluye integración Kafka real vía testcontainers):  
  `docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/"`
- Si querés saltear integración Kafka en el completo:  
  `docker compose -f docker-compose.local.yml exec api sh -lc "SKIP_KAFKA_INTEGRATION=1 DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/"`

---

## Stack (resumido)

| Qué | Tecnología |
|-----|------------|
| API | Django, DRF |
| Dominio | `jobs/services.py`, `jobs/pipeline/` |
| Async | Celery, Redis |
| DB | PostgreSQL |
| Eventos | Kafka (`jobs/event_stream.py`, consumer `run_kafka_consumer`) |
| Bonus | gRPC (`proto/job_gateway.proto`, `run_grpc_server`) |
| Tests | pytest, pytest-django; integración E2E + opcional testcontainers Kafka |

**Kafka vs Redis:** Redis = cola de Celery. Kafka = log de eventos con retención, grupos y offsets.

---

## API REST (v1)

Base: `/api/v1/`

| Método | Ruta | Notas |
|--------|------|--------|
| POST | `/jobs/` | `pipeline_config.stages` = prefijo contiguo de `extract` → `analyze` → `enrich`; `provider_overrides` solo en etapas listadas |
| GET | `/jobs/` | `?status=` opcional |
| GET | `/jobs/{id}/` | Detalle + `partial_results` |
| POST | `/jobs/{id}/cancel/` | 409 si ya terminó |

Eventos: `job.created`, `job.stage_*`, `job.completed` / `job.failed` / `job.cancelled` (ver `jobs/event_stream.py`).

---

## gRPC (bonus)

Servicio `DocumentProcessingGateway` en `proto/job_gateway.proto`: `CreateJob`, `GetJob`, `ListJobs`, `CancelJob`. Misma lógica que REST. Comando: `python manage.py run_grpc_server` (puerto `GRPC_PORT`, default 50051).

---

## Resiliencia (mínimo pedido)

- Falla en una etapa: se guardan parciales previos; `job.failed` + evento.
- Kafka caído un momento: reintentos con backoff al publicar; sin outbox (trade-off: posible divergencia eventual; en prod habría outbox/DLQ).

---

## Tests

- Unit + integración API→pipeline→eventos (mocks) + gRPC: `pytest tests/`
- Integración **Kafka real** (Docker + testcontainers): `tests/jobs/test_kafka_integration_tc.py`

---

## Diagrama

```text
  REST / gRPC  →  Gateway (Django) + servicios  →  Celery
                        ↓
                    Kafka (job.*)
                        ↓
                 consumer (grupo) → logs
```

---

## Entrega

Repositorio git, este README, tests ejecutables, y el mail al contacto del enunciado.

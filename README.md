# Document Processing Gateway

Este repo implementa el challenge de backend con:

- API REST en Django + DRF para crear/consultar/listar/cancelar jobs.
- Pipeline `extract -> analyze -> enrich` con proveedores mock fast/slow.
- Ejecucion async con Celery + Redis.
- Eventos `job.*` en Kafka + consumer con consumer group y commit manual.
- Bonus gRPC (`CreateJob`, `GetJob`, `ListJobs`, `CancelJob`) reutilizando la misma capa de servicios.

> Requisito del challenge: Python 3.10+.  
> En este proyecto recomiendo correr todo con Docker Compose (ya trae el entorno correcto).

---

## Levantar el proyecto (desde cero)

```bash
docker compose -f docker-compose.local.yml up -d --build
```

Con eso quedan levantados: `api` (8000), `worker`, `grpc` (50051), `kafka_consumer`, `db`, `redis`, `kafka`.

Chequeos rapidos:

- Health: `http://127.0.0.1:8000/health/`
- API base: `http://127.0.0.1:8000/api/v1/`
- Python del contenedor: `docker compose -f docker-compose.local.yml exec api python --version`

---

## Probar endpoints REST con Bruno

Use Bruno para dejar requests de prueba en `challengue/`.

- Coleccion: `challengue/opencollection.yml`
- Environment local: `challengue/environments/local.yml`
- `api_url` ya apunta a `http://localhost:8000/api/v1`

Ahi estan los escenarios de create/get/list/cancel y variantes de pipeline.

---

## Test rapido de Kafka en Compose

Script de humo (publica y valida consumo de un evento):

```bash
docker compose -f docker-compose.local.yml exec api python scripts/smoke_kafka_compose.py
```

Si todo va bien devuelve algo como: `ok job.created <uuid>`.

---

## Tests

### Perfil recomendado (Docker + settings de test)

```bash
docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/"
```

### Perfiles utiles

- Rapido (sin integraciones pesadas):
```bash
docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/ -m 'not integration'"
```

- Completo (incluye test de integracion Kafka real con testcontainers):
```bash
docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/"
```

- Completo pero salteando Kafka real:
```bash
docker compose -f docker-compose.local.yml exec api sh -lc "SKIP_KAFKA_INTEGRATION=1 DJANGO_SETTINGS_MODULE=config.settings_test python -m pytest tests/"
```

---

## API REST

Base: `/api/v1/`

- `POST /jobs/`
- `GET /jobs/` (filtro opcional `?status=`)
- `GET /jobs/{job_id}/`
- `POST /jobs/{job_id}/cancel/`

Regla importante de stages: se aceptan prefijos contiguos del orden
`extract -> analyze -> enrich`.

---

## gRPC (bonus)

Proto: `proto/job_gateway.proto`  
Servicio: `DocumentProcessingGateway`

Metodos implementados:

- `CreateJob`
- `GetJob`
- `ListJobs`
- `CancelJob`

Comando para levantar server gRPC:

```bash
python manage.py run_grpc_server
```

---

## Resiliencia aplicada

- Si falla una etapa del pipeline, se conservan parciales y el job queda `failed`.
- Publicacion a Kafka con retry + backoff corto.
- Trade-off documentado: no hay outbox/DLQ (fuera de alcance del challenge).

---

## Stack

- Django, DRF
- Celery, Redis
- PostgreSQL
- Kafka
- gRPC (grpcio + protobuf)
- pytest / pytest-django

---

## Entrega

Incluye:

1. Repositorio git.
2. Este README con pasos para levantar/probar.
3. Tests ejecutables.

Luego notificar por mail al contacto del enunciado.
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

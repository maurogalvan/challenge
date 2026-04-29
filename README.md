Document Processing Gateway

Este repo es mi solución al challenge de backend.

La idea es bastante directa: recibo un documento, lo paso por un pipeline (extract → analyze → enrich) y voy publicando eventos de lo que pasa en cada etapa para que otros servicios puedan reaccionar.

Qué implementé
API REST para crear, consultar, listar y cancelar jobs
Pipeline configurable por request (no siempre tienen que correr todas las etapas)
Proveedores mock (fast y slow) para simular latencias distintas
Procesamiento async con Celery + Redis
Publicación de eventos en Kafka (job.*)
Consumer que lee esos eventos (simulando un downstream)
Bonus: interfaz gRPC reutilizando la misma lógica que REST
Decisiones rápidas (por si suma contexto)
Django + DRF: cómodo para armar rápido la API y estructurar bien el dominio
Celery + Redis: para desacoplar el pipeline y manejar bien las tareas async
Kafka: porque necesitaba persistencia de eventos, consumer groups y manejo de offsets (era lo que pedía el challenge)
Mocks fast/slow: para poder ver el comportamiento async sin depender de servicios reales
Cómo levantarlo

Recomiendo usar Docker así no hay problemas de versiones (usa Python 3.10 como pide el challenge):

docker compose -f docker-compose.local.yml up -d --build

Levanta todo:

API → http://localhost:8000
gRPC → puerto 50051
worker (Celery)
Kafka + consumer
Postgres
Redis

Para chequear rápido:

Health → http://localhost:8000/health/
API base → http://localhost:8000/api/v1/
API

Base: /api/v1/

Endpoints:

POST /jobs/ → crea un job
GET /jobs/ → lista (permite filtrar por status)
GET /jobs/{id}/ → detalle + resultados parciales
POST /jobs/{id}/cancel/ → cancela si sigue en curso
Nota sobre el pipeline

Las etapas siguen este orden:

extract → analyze → enrich

Se pueden ejecutar parcialmente, pero siempre respetando ese orden (no se puede saltear etapas intermedias).

Eventos

Voy publicando eventos en Kafka a medida que avanza el pipeline:

job.created
job.stage_started
job.stage_completed
job.completed
job.failed
job.cancelled

El consumer que incluí simplemente los lee (con consumer group) y los loguea, simulando otro servicio.

gRPC (bonus)

Implementé:

CreateJob
GetJob
ListJobs
CancelJob

La lógica es la misma que REST (no hay duplicación).

Para levantarlo:

python manage.py run_grpc_server
Resiliencia
Si falla una etapa, se guardan los resultados anteriores y el job queda en failed
La publicación a Kafka tiene retry con backoff
No implementé outbox/DLQ para no irme de scope, pero en un sistema real lo agregaría
Tests

Corrí tests unitarios y de integración (incluyendo flujo completo).

Desde Docker:

docker compose -f docker-compose.local.yml exec api sh -lc "DJANGO_SETTINGS_MODULE=config.settings_test pytest"

También dejé un test de integración con Kafka real usando testcontainers.

Extra

Dejé una colección en Bruno (challenge/) con requests para probar rápido los endpoints y distintos escenarios del pipeline.

Cierre

Intenté mantenerlo simple pero cubriendo todo lo que pedía el challenge: pipeline configurable, async, eventos y algo de resiliencia.

Cualquier cosa que quieran que explique o profundice, cero problema
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

Este repositorio incluye:

1. Implementación del gateway con API REST, pipeline, eventos Kafka y bonus gRPC.
2. Guía de ejecución con Docker Compose.
3. Tests automatizados para validar los flujos principales.

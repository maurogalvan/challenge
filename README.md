# Document Processing Gateway

Orquesta un pipeline con etapas `extract` → `analyze` → `enrich` (mock, con variante fast/slow), expone **REST** (DRF) y (bonus) **gRPC** sobre la misma capa de servicios, encola el trabajo con **Celery** y publica eventos `job.*` a **Kafka**. Incluye un consumer con **consumer group** y `commit` manual (ack vía offset).

> Requisito del enunciado: **Python 3.10+**. En este repo, la referencia “oficial” es la imagen de Docker; si probás en el host, asegurate de no crear un venv con un Python viejo.

**Cobertura frente al challenge (alto nivel):** API de jobs, pipeline con proveedores pluggables, eventos Kafka, resiliencia mínima (fallo de etapa + reintentos al publicar), tests (unit + integración E2E) y bonus gRPC.

**Qué queda explícitamente como mejora futura (no exigida):** outbox transaccional / DLQ, integración con Kafka “real” en CI (testcontainers) y hardening de seguridad/ops.

---

## Stack

| Capa | Tecnología | Rol |
|------|------------|-----|
| API | **Django** + **Django REST Framework** | Endpoints, validación, serialización, capa HTTP |
| Lógica de negocio | **Servicios Python** (capa de dominio) | Orquestación del pipeline; **compartida** por REST y (bonus) gRPC |
| Persistencia | **PostgreSQL** | Estado de jobs, resultados parciales, historial mínimo |
| Tareas async | **Celery** | Ejecución del pipeline fuera del request |
| Broker de tareas | **Redis** | Broker y backend de resultados de Celery (patrón habitual) |
| Event streaming | **Apache Kafka** | Eventos de dominio con persistencia, **consumer groups** y confirmación de procesamiento (offsets) |
| gRPC (bonus) | **grpcio** + **protobuf** | RPC alternativos a REST sin duplicar lógica |
| Contenedores | **Docker** + **Docker Compose** | Entorno reproducible (app, DB, Redis, Kafka, etc.) |
| Tests | **pytest** + **pytest-django** | Unitarios (dominio, pipeline) + al menos un flujo de integración |

**Por qué Kafka además de Redis:** Redis alimenta a Celery (tareas atómicas y cortas). Los eventos `job.*` del pipeline requieren retención, múltiples suscriptores y ack explícito: eso se documenta y cubre con Kafka, según el enunciado.

---

## Estructura del repositorio

Django (API en `jobs/`, servicios en `jobs/services.py`, pipeline en `jobs/pipeline/`, proveedores en `jobs/providers/`), tareas en `jobs/tasks.py`, publicación a Kafka en `jobs/event_stream.py`, consumer con `python manage.py run_kafka_consumer`, y gRPC en `jobs/grpc_service.py` + `proto/job_gateway.proto`.

```text
.
├── docker-compose.local.yml   # api + worker + grpc + kafka_consumer + Postgres, Redis, ZK, Kafka
├── Dockerfile
├── docker/
│   ├── defaults.env            # “.env de Docker” (red interna; con commit)
│   └── entrypoint.sh           # migrate y luego el comando
├── .env.example
├── .python-version            # 3.10.13 (usar con pyenv/asdf si aplica)
├── requirements/
│   ├── base.txt
│   └── dev.txt
├── manage.py
├── pytest.ini
├── challengue/                 # Colección Bruno (requests de ejemplo)
├── config/                    # Proyecto Django: settings, urls, Celery, health
│   ├── settings.py
│   ├── settings_test.py        # SQLite :memory: para pytest
│   ├── urls.py
│   └── views.py                # /health/
├── jobs/                      # Job, API, servicios, pipeline, providers, event_stream, gRPC, Celery
└── tests/
```

**Diseño:** DRF y gRPC delegan a servicios; el pipeline y los eventos no viven en las views.

### Probar REST con Bruno (manual)

En `challengue/` dejé requests de ejemplo (crear job con distintas etapas, get, list, cancel, etc.) para no depender de curl. Abrís la carpeta en **Bruno** y usás el environment `environments/local.yml` (`api_url` = `http://localhost:8000/api/v1`). Con el `api` arriba en Docker, ejecutás los requests tal cual; no hace falta tocar el código.

gRPC se prueba aparte (servidor `run_grpc_server` o contenedor `grpc`); Bruno queda solo para REST.

---

## API REST (v1)

Base URL: `/api/v1/`

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/jobs/` | Crea un job. `pipeline_config` incluye `stages` (no vacía) y **solo prefijos contiguos** del orden `extract` → `analyze` → `enrich` (por ejemplo `["extract"]`, `["extract","analyze"]`, `["extract","analyze","enrich"]`). Opcional: `provider_overrides` con `fast` o `slow` **solo para etapas listadas en `stages`**. |
| `GET` | `/jobs/` | Lista jobs; filtro opcional `?status=…`. |
| `GET` | `/jobs/{job_id}/` | Detalle: `partial_results.by_stage` con el resultado de cada etapa, `error_message` si `failed`. |
| `POST` | `/jobs/{job_id}/cancel/` | Cancela si sigue activo; `409` si ya terminó. |

**Regla de etapas:** no se admite `["enrich"]` ni `["extract","enrich"]` sin `analyze` intermedio. Cada etapa recibe la salida de la anterior; no hay “análisis implícito” ni enriquecimiento sin análisis explícito en `stages`.

El worker Celery ejecuta `run_pipeline_job` → `run_job_pipeline` (orquesta proveedores por `stages`). Los eventos `job.*` se publican a Kafka (`KAFKA_TOPIC_JOBS`, ver `jobs/event_stream.py`).

---

## Estados del job

Ciclo de vida esperado (transiciones consistentes, sin `completed` → `processing`):

`pending` → `processing` → `completed` | `failed` | `cancelled`

- Cancelación: solo con job no finalizado.
- Ante fallo o timeout de una etapa: se conservan resultados de etapas anteriores; el job pasa a `failed` (y evento `job.failed`).

---

## Eventos mínimos (Kafka)

Cada evento incluye al menos: `job_id`, `timestamp`, `event_type`, `payload`.

| Tipo | Momento |
|------|---------|
| `job.created` | Se acepta el documento a procesar |
| `job.stage_started` | Inicio de una etapa del pipeline |
| `job.stage_completed` | Fin exitoso de etapa (incluye resultado parcial) |
| `job.completed` | Pipeline completo |
| `job.failed` | Falla en etapa o sistema |
| `job.cancelled` | Job cancelado |

Consumer de grupo (`KAFKA_CONSUMER_GROUP`, p. ej. `downstream-processors`): comando `python manage.py run_kafka_consumer` — lee el topic, **log** simula downstream y hace **commit manual** tras cada mensaje (ack vía offset).

Variables: `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC_JOBS`, `KAFKA_ENABLED` (en tests va en `false` para no requerir broker).

---

## Resiliencia (README + código)

- **Proveedor:** error/timeout de etapa → no se pierde el trabajo previo; job en `failed` y evento acorde.
- **Publicación a Kafka:** **reintentos con backoff** corto (hasta 3 intentos) antes de registrar error y seguir (el job en DB no se revierte; en escenarios productivos se usaría outbox o cola local — fuera de alcance del challenge).
- (Opcional) sin broker: arrancar Compose sin Kafka y `KAFKA_ENABLED=false` para desarrollo offline del resto del stack.

---

## Cómo levantar el proyecto

### Recomendado: Docker (evita el tema “Python 3.10 en el host”)
Si en tu máquina el `python` no es 3.10+, no pasa nada: el contenedor trae el intérprete acorde al Dockerfile / imagen. Verificá con:

```bash
docker compose -f docker-compose.local.yml exec api python --version
```

Y para testear en el mismo entorno:

```bash
docker compose -f docker-compose.local.yml exec api pytest tests/
```

### Opción A — Todo en Docker (sin venv en el host)

Levanta Postgres, Redis, Zookeeper, Kafka y la app Django. Las variables para el contorno vienen de **`docker/defaults.env`** (en el repo, pensado para la red de Compose: `db`, `redis`, `kafka:29092`, etc.); no hace falta copiar nada salvo que quieras un override.

```bash
docker compose -f docker-compose.local.yml up -d --build
# Atajo: export COMPOSE_FILE=docker-compose.local.yml
```

Con `up` por defecto se levantan `api`, `worker`, `grpc`, `kafka_consumer`, DB, Redis, Kafka, etc. Luego: health en `http://127.0.0.1:8000/health/`, API en `http://127.0.0.1:8000/api/v1/`, y Bruno con el `api_url` de `challengue/environments/local.yml` (mismo host/puerto).

- [docker-compose.local.yml](docker-compose.local.yml): `api`, `worker`, `grpc` (`run_grpc_server`), `kafka_consumer` (`run_kafka_consumer`), Postgres, Redis, Zookeeper, Kafka; env en `docker/defaults.env`.
- **`.env.example`:** Django en el host hacia `localhost` en los puertos.
- **Health:** [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/) · **API:** [http://127.0.0.1:8000/api/v1/jobs/](http://127.0.0.1:8000/api/v1/jobs/)
- Contenedor `api`: migraciones vía entrypoint; volumen `.:/app`.
- **Solo base de datos + Redis** (sin levantar `api` ni Kafka), p. ej. mientras corrés DRF en venv:  
  `docker compose -f docker-compose.local.yml up -d db redis`

### Opción B — Código en el host (venv + Postgres/Redis en Docker)

Solo si tenés **Python 3.10+** instalado en el host. Si al correr `python3.10 -m venv` te falla, volvé a la opción Docker (arriba).

**Requisito:** Python **3.10+** (alinear con `.python-version` vía pyenv / Homebrew / asdf, según tu entorno).

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python --version
pip install -r requirements/dev.txt
cp .env.example .env
docker compose -f docker-compose.local.yml up -d db redis kafka
python manage.py migrate
python manage.py runserver
```

- Con Docker, el `worker` ejecuta Celery. Para eventos: `kafka_consumer`. Para bonus gRPC: servicio `grpc` en `:50051` o, en host, `python manage.py run_grpc_server`.

#### Verificación rápida de versión (obligatoria)

```bash
python --version
# esperado: Python 3.10.x o mayor
```

#### Si quedó en 3.9.x, recrear `.venv`

```bash
deactivate  # si estás en un venv activo
rm -rf .venv
python3.10 -m venv .venv
source .venv/bin/activate
python --version
pip install -r requirements/dev.txt
```

---

## Tests

Usa `config.settings_test` (SQLite en memoria) — no requiere Docker en cada corrida, pero en Docker se ejecuta igual.

**Desde venv local (3.10+):**

```bash
source .venv/bin/activate
pytest
```

**Desde contenedor (recomendado si el host no tiene 3.10+):**

```bash
docker compose -f docker-compose.local.yml exec api pytest tests/
```

- **Unitarios + integración:** servicios, pipeline, eventos, flujo E2E, gRPC, consumer (commit) con mocks. Opcional: broker Kafka en CI.

---
## Bonus gRPC (implementado)

- **Servicio:** `DocumentProcessingGateway` en `proto/job_gateway.proto`.
- **Métodos:** `CreateJob`, `GetJob`, `ListJobs` (con filtro `status`) y `CancelJob`.
- **Server:** `python manage.py run_grpc_server` (host/port por `GRPC_HOST` y `GRPC_PORT`).
- **Diseño:** gRPC usa la misma capa de negocio (`create_job`, `get_job_by_id`, `list_jobs`, `request_cancel_job`, task Celery), sin duplicar lógica de dominio.

---


## Diagrama (arquitectura)

```text
                    ┌─────────────────────────┐
  REST / (gRPC)     │  Document Processing    │     Mocks: extracción,
  ───────────────►  │  Gateway (Django)       │ ◄── análisis, enriquecimiento
                    │  + servicios            │
  Consultas estado│  + Celery workers        │
  ◄──────────────►  └───────────┬─────────────┘
                                │
                                ▼
                         Eventos (Kafka)
                                │
                                ▼
                    Consumer (grupo) → logs
```

---

## Contribución / flujo de ramas (recomendado)

- **`main`:** rama entregable / taggeable.
- **`development`:** integración de features; aquí vive el trabajo día a día.
- **`feature/*`:** cambios chicos, merge a `development`, luego a `main` al cerrar el challenge.

Comentarios de commit claros (por qué, no solo “fix”) ayudan a quien revise el orden del trabajo.

---

## Cómo subir el repositorio (tú controlás el `push`)

No hace falta publicar nada hasta tener el remoto creado y, si aplica, el repo en GitHub/GitLab vacío.

### Si el remoto aún no existe (GitHub, ejemplo)

1. Crear un repositorio **nuevo y vacío** (sin README si ya tenés uno local) en la plataforma que elijas.
2. En la carpeta del proyecto:

```bash
git status
git add README.md
git commit -m "docs: stack, estructura y plan de entrega"
# Si ya tenés rama development:
git checkout development
git merge main   # o al revés según dónde commitees; ajustar a vuestro flujo
```

3. Añadir el remoto (sustituir `URL` por la que te da GitHub, SSH o HTTPS):

```bash
git remote add origin URL
git branch -M main    # si querés asegurar el nombre
git push -u origin main
git push -u origin development
```

Solo hace falta `git push` cuando quieras que el remoto tenga el mismo historial. **Nadie debe hacer push a tu remoto sin tu acuerdo; si usás asistente, pedí explícitamente "hacé el push" cuando corresponda.**

### Si `origin` ya está configurado

```bash
git remote -v
git push -u origin nombre-de-rama
```

---

## Licencia / entrega

Según indique el enunciado del challenge: repositorio git y notificación por email al contacto provisto, sin detalles redundantes en este documento.

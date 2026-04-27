# Document Processing Gateway

Microservicio que orquesta el procesamiento de documentos (extracción → análisis → enriquecimiento) mediante proveedores pluggables, expone API REST, ejecuta el pipeline en background y publica eventos al stream para consumidores downstream.

> Challenge técnico — **Python 3.10+**. Arquitectura y decisiones orientadas a claridad, testabilidad y criterio de diseño, no a producción exhaustiva.

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

**Estado actual (bases):** proyecto Django en la raíz; carpetas faltantes (`pipeline/`, `providers/`, `events/`, etc.) se agregan al implementar el challenge.

```text
.
├── docker-compose.local.yml   # api + worker + PostgreSQL, Redis, Zookeeper, Kafka
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
├── config/                    # Proyecto Django: settings, urls, Celery, health
│   ├── settings.py
│   ├── settings_test.py        # SQLite :memory: para pytest
│   ├── urls.py
│   └── views.py                # /health/
├── jobs/                      # Modelo Job, API v1, servicios, tarea Celery (stub de pipeline)
└── tests/
```

Pendiente: pipeline real con `providers/`, eventos Kafka, consumer, resiliencia, test de integración end-to-end, gRPC (bonus).

**Línea roja de diseño:** la lógica vive en servicios/pipeline, no en la vista. DRF y gRPC deben ser **finos adaptadores** que llaman a los mismos use cases.

---

## API REST (v1)

Base URL: `/api/v1/`

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/jobs/` | Crea un job (`document_name`, `document_type`, `content`, `pipeline_config`). `pipeline_config` incluye `stages`: lista de `extract`, `analyze`, `enrich` (orden canónico). |
| `GET` | `/jobs/` | Lista jobs; filtro opcional `?status=pending` (u otro estado). |
| `GET` | `/jobs/{job_id}/` | Detalle: estado, `partial_results`, etc. |
| `POST` | `/jobs/{job_id}/cancel/` | Cancela si sigue activo; `409` si ya terminó. |

La tarea Celery `run_pipeline_job` hoy es un **stub** (processing → completed). Sustituir por el pipeline con proveedores y eventos.

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

Consumer de grupo: lee el stream, procesa (aquí: **log** simulando downstream) y hace **ack** vía avance de offset (semántica del consumidor de Kafka).

---

## Resiliencia (README + código)

- **Proveedor:** error/timeout de etapa → no se pierde el trabajo previo; job en `failed` y evento acorde.
- **Publicación a Kafka (breve caída del broker):** al menos **una** estrategia (p. ej. reintentos con backoff o patrón outbox simplificado), justificada en esta sección cuando esté implementada.
- (Opcional en texto) listado de riesgos no cubiertos por tiempo.

---

## Cómo levantar el proyecto

### Opción A — Todo en Docker (sin venv en el host)

Levanta Postgres, Redis, Zookeeper, Kafka y la app Django. Las variables para el contorno vienen de **`docker/defaults.env`** (en el repo, pensado para la red de Compose: `db`, `redis`, `kafka:29092`, etc.); no hace falta copiar nada salvo que quieras un override.

```bash
docker compose -f docker-compose.local.yml up -d --build
# Atajo: export COMPOSE_FILE=docker-compose.local.yml
```

- [docker-compose.local.yml](docker-compose.local.yml): `api` (Django), `worker` (Celery), Postgres, Redis, Zookeeper, Kafka; env en `docker/defaults.env`.
- **`.env.example`:** Django en el host hacia `localhost` en los puertos.
- **Health:** [http://127.0.0.1:8000/health/](http://127.0.0.1:8000/health/) · **API:** [http://127.0.0.1:8000/api/v1/jobs/](http://127.0.0.1:8000/api/v1/jobs/)
- Contenedor `api`: migraciones vía entrypoint; volumen `.:/app`.
- **Solo base de datos + Redis** (sin levantar `api` ni Kafka), p. ej. mientras corrés DRF en venv:  
  `docker compose -f docker-compose.local.yml up -d db redis`

### Opción B — Código en el host (venv + Postgres/Redis en Docker)

**Requisito:** Python **3.10+** (alinear con `.python-version` vía pyenv).

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env
docker compose -f docker-compose.local.yml up -d db redis
python manage.py migrate
python manage.py runserver
```

- Con Docker, el servicio `worker` ejecuta `celery -A config worker`. Consumer Kafka: pendiente.

---

## Tests

Usa `config.settings_test` (SQLite en memoria) — no requiere Docker en cada corrida.

```bash
source .venv/bin/activate
pytest
```

- **Unitarios (pendiente ampliar):** sesiones, transiciones, orquestación con mocks.
- **Integración (≥1, pendiente):** crear job → pipeline → eventos → finalización, idealmente con `docker compose` o testcontainers.

---

## Plan de entrega en 8 horas (referencia)

Orden sugerido para avanzar rápido y con commits con historia legible:

1. **Cimientos:** Compose (Postgres + Redis), Django + DRF, modelo `Job` + 4 endpoints mínimos (aunque el worker sea no-op).
2. **Abstracción de proveedores** + 2 implementaciones (rápida/lenta) y `pipeline_config`.
3. **Celery** ejecuta pipeline, persiste resultados parciales, maneja fallo de etapa.
4. **Kafka** productor de eventos + **consumer** con group id + logs.
5. **Tests** unit + 1 integración; README actualizado (resiliencia, diagrama).
6. **Si sobra tiempo:** gRPC, CI mínima, pulido de seguridad en README (secretos, validación).

Ajustar tiempos según bloqueos; el README puede marcarse con “hecho / pendiente” al final de cada bloque (opcional, breve).

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

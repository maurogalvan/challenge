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

## Estructura del repositorio (objetivo)

Estructura orientativa a implementar; los nombres concretos pueden ajustarse sin cambiar el espíritu (dominio separado de entrega HTTP, proveedors intercambiables, eventos aislados).

```text
.
├── docker-compose.yml          # Servicios locales (en construcción)
├── .env.example
├── requirements/
│   ├── base.txt
│   ├── dev.txt
│   └── prod.txt                # opcional
├── README.md
├── app/                        # proyecto Django
│   ├── config/                 # settings, urls raíz, asgi/wsgi
│   ├── core/ o jobs/          # modelos Job, repositorio, FSM de estados
│   ├── api/ o rest/           # views/serializers/urls DRF
│   ├── pipeline/              # orquestador, pipeline_config, ejecución de etapas
│   ├── providers/             # abstracciones + mocks (Fast*/Slow*, etc.)
│   ├── events/ o streaming/  # publicación a Kafka, esquema de payloads
│   └── workers/ o tasks/      # tareas Celery
├── consumers/ o event_consumer/ # consumer Kafka (downstream simulado)
└── tests/
    ├── unit/
    └── integration/
```

**Línea roja de diseño:** la lógica vive en servicios/pipeline, no en la vista. DRF y gRPC deben ser **finos adaptadores** que llaman a los mismos use cases.

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

> En construcción. Cuando exista `docker-compose.yml` y la app, aquí irán los comandos exactos (`docker compose up`, migraciones, usuario DB, tópicos Kafka, etc.).

```bash
# Placeholder
# docker compose up -d
# python manage.py migrate
# python manage.py runserver  # y worker Celery + consumer en otros procesos/contenedores
```

---

## Tests

```bash
# En construcción
# pytest
```

- **Unitarios:** sesiones, transiciones de estado, orquestación del pipeline con proveedores falsos o mocks.
- **Integración (≥1):** flujo: crear job → pipeline → eventos publicados (o al menos cola) → finalización, con entorno dockerizado o testcontainers según se implemente.

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

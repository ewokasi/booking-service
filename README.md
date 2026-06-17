# Booking Service

[![CI](https://github.com/ewokasi/booking-service/actions/workflows/ci.yml/badge.svg)](https://github.com/ewokasi/booking-service/actions/workflows/ci.yml)

Асинхронный backend для записи на встречи. REST API создаёт бронь, фоновый Celery-воркер подтверждает её асинхронно, имитируя сбой ~15% и отправляя mock-уведомление.

**Стек:** FastAPI, SQLAlchemy 2 async + Alembic, Celery + Redis, PostgreSQL, structlog, slowapi.

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

Поднимает Postgres, Redis, прогоняет миграции, стартует API на `http://localhost:8000` и воркер. Проверка: `curl http://localhost:8000/healthz`. OpenAPI: `http://localhost:8000/docs`.

## Запуск тестов

Без Docker. В тестах Postgres и Redis заменены на SQLite и in-memory брокер Celery, прогон занимает меньше секунды.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Или `make test` / `make lint` / `make format`.

## Эндпоинты

| Метод | Путь | Назначение | Коды |
|---|---|---|---|
| `POST`   | `/bookings`      | Создать бронь, поставить в очередь подтверждение | `202`, `422`, `429` |
| `GET`    | `/bookings/{id}` | Статус брони | `200`, `404` |
| `GET`    | `/bookings`     | Список с `?status=&limit=&offset=` | `200` |
| `DELETE` | `/bookings/{id}` | Отменить (только pending) | `204`, `404`, `409` |
| `GET`    | `/healthz`       | Liveness | `200` |
| `GET`    | `/readyz`        | Readiness, пинг Postgres + Redis | `200`, `503` |

`POST /bookings` ограничен `10/minute` per-IP.

## Принятые решения

**FastAPI плюс Celery.** ТЗ явно упоминает Celery - взял его, чтобы не отклоняться. FastAPI выбран ради нативного async, Pydantic-валидации запросов OpenAPI-доки.

**SQLAlchemy 2 async + sync для воркера.** API работает с async-engine, воркер (Celery sync) - с параллельным sync-engine на ту же базу (`app/worker/db_sync.py`). Одна база, две сессии.

**Идемпотентность задачи.** Воркер загружает бронь с `with_for_update`, проверяет что статус всё ещё `pending`, и только тогда мутирует. Повторный запуск с тем же `booking_id` логирует `confirm_skip_idempotent` и выходит без изменений.

**Retry без autoretry_for.** Задача сама управляет потолком: на `ExternalServiceError` бросает `self.retry(countdown=backoff ** attempt)`. На терминальной попытке (`retries >= WORKER_MAX_RETRIES`) переводит бронь в `failed`. Backoff экспоненциальный: 1с, 2с, 4с.

**Простая планировка.** `app/api/` - HTTP, `app/services/` - бизнес-логика и ORM, `app/worker/` - Celery-таски и sync-DB. Воркер не импортирует FastAPI.

**Атомарная отмена.** `DELETE /bookings/{id}` делает CAS-`DELETE WHERE status='pending'`. Если worker уже подтвердил параллельно - rowcount=0, ответ 409 без race.

## Конфигурация

Главные переменные в `.env` (шаблон в `.env.example`):

| Переменная | Default | Назначение |
|---|---|---|
| `DATABASE_URL` | asyncpg URL | Используется FastAPI |
| `ALEMBIC_DATABASE_URL` | sync URL | Alembic и воркер |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis URLs | Транспорт Celery |
| `WORKER_FAILURE_RATE` | `0.15` | Вероятность сбоя подтверждения |
| `WORKER_MAX_RETRIES` | `3` | Лимит retry до failed |
| `WORKER_RETRY_BACKOFF` | `2` | Основание экспоненты для countdown |
| `RATE_LIMIT_CREATE_BOOKING` | `10/minute` | Правило slowapi для POST |
| `LOG_LEVEL` | `INFO` | structlog JSON |

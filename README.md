# Booking Service

[![CI](https://github.com/ewokasi/booking-service/actions/workflows/ci.yml/badge.svg)](https://github.com/ewokasi/booking-service/actions/workflows/ci.yml)

Асинхронный backend для записи на встречи: REST API плюс фоновый воркер, который подтверждает брони асинхронно с retry и mock-уведомлениями.

**Стек:** FastAPI, SQLAlchemy 2 (async) + Alembic, Celery, Redis, PostgreSQL, structlog, slowapi.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

Команда поднимает `postgres`, `redis`, прогоняет миграцию Alembic, затем стартует API на `http://localhost:8000` и Celery-воркер. Healthcheck: `curl http://localhost:8000/healthz`.

### Примеры запросов

```bash
# Создать бронь
curl -X POST http://localhost:8000/bookings \
  -H 'content-type: application/json' \
  -d '{"name":"Alice","datetime":"2026-07-01T12:00:00Z","service_type":"haircut"}'

# Статус брони
curl http://localhost:8000/bookings/<id>

# Список с фильтром и пагинацией
curl 'http://localhost:8000/bookings?status=confirmed&limit=20&offset=0'

# Отмена (только в статусе pending)
curl -X DELETE http://localhost:8000/bookings/<id>
```

OpenAPI-документация: `http://localhost:8000/docs`.

## Запуск тестов

Тесты идут без Docker: Postgres и Redis заменены на SQLite (через `aiosqlite`) и in-memory брокер Celery. Полный набор (happy path, граничные кейсы, идемпотентность воркера, исчерпание retry, rate limit) проходит меньше чем за секунду.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Или через `Makefile`:

```bash
make test
make lint        # ruff
make typecheck   # mypy
make format      # ruff format + autofix
```

## Эндпоинты

| Метод | Путь | Назначение | Ответ |
|---|---|---|---|
| `POST`   | `/bookings`      | Создать бронь, поставить задачу подтверждения в очередь | `202 Accepted` плюс бронь |
| `GET`    | `/bookings/{id}` | Прочитать статус брони                                  | `200` либо `404` |
| `GET`    | `/bookings`      | Список с `?status=&limit=&offset=`                      | `200` плюс items, total, paging |
| `DELETE` | `/bookings/{id}` | Отменить бронь в статусе pending                        | `204`, `404` либо `409` |
| `GET`    | `/healthz`       | Liveness-проба                                          | `200` |

`POST /bookings` ограничен по клиентскому IP (по умолчанию `10/minute`, см. `.env`).

## Архитектура и решения

### Почему FastAPI плюс Celery (а не Django, не TaskIQ)

- **FastAPI**. Нативный async, Pydantic закрывает валидацию запросов и схемы ответов без второго фреймворка, OpenAPI получаем бесплатно. API в основном I/O-bound (БД плюс enqueue), так что async окупается.
- **Celery**. В ТЗ явно назван; это скучный, проверенный временем выбор с зрелой retry-семантикой, мониторингом и операционной экспертизой в индустрии. TaskIQ современнее, но обменивает узнаваемость на новизну.
- **SQLAlchemy 2.0 async** плюс миграции Alembic. Воркер работает синхронно (Celery sync), поэтому использует параллельный sync-engine, привязанный к тому же Postgres, см. `app/worker/db_sync.py`. Одна база, две сессии, разделение ответственности.

### Идемпотентность

Воркер может быть вызван больше одного раза для одного и того же `booking_id` (перепосылка Celery, ручной replay, eager-режим в тестах). Задача идемпотентна по дизайну:

1. Загружаем бронь с `with_for_update=True` (row-level lock на Postgres; no-op на SQLite в тестах).
2. Если статус не `pending`, логируем `confirm_skip_idempotent` и выходим, не перетирая терминальный статус.
3. Иначе пытаемся подтвердить, переводим `pending` в `confirmed`, коммитим и отправляем mock-уведомление.

Это делает success path безопасным для replay и предотвращает порчу вручную проваленных броней поздним retry.

### Политика retry

`autoretry_for` дал бы одну строку, но скрыл бы потолок попыток. Поэтому задача сама:

- бросает `self.retry(countdown=backoff ** attempt)` на `ExternalServiceError`;
- на терминальной попытке (`self.request.retries >= WORKER_MAX_RETRIES`) переводит строку в `failed`.

Backoff (`WORKER_RETRY_BACKOFF`, по умолчанию 2) экспоненциальный по номеру попытки: 1с, 2с, 4с и т. д. Максимум retry настраивается через `WORKER_MAX_RETRIES`.

### Имитация ошибки внешнего сервиса

`WORKER_FAILURE_RATE` (по умолчанию `0.15`) задаёт вероятность того, что попытка подтверждения бросит `ExternalServiceError`. Тесты фиксируют это значение на `0` (happy path) или `1` (failure path) через monkeypatch, так что прогоны детерминированы.

### Наблюдаемость

- **structlog** пишет JSON в stdout. API и воркер делят одну конфигурацию логирования (`app/logging.py`), так что HTTP-запросы, события жизненного цикла задач (`confirm_retry`, `confirm_success`, `confirm_failed_terminal`) и уведомления попадают в единый структурированный поток, который удобно индексировать агрегатором логов.
- Ключевые события: `booking_created`, `confirm_skip_idempotent`, `confirm_skip_missing`, `confirm_retry`, `confirm_success`, `confirm_failed_terminal`, `notification_sent`.

### Rate limiting

`POST /bookings` ограничен по клиентскому IP через `slowapi`. Лимит читается из настроек динамически на каждом запросе, что позволяет менять его per-environment без передеплоя. Остальные эндпоинты не ограничены: список и чтение защиты не требуют.

### Раскладка проекта

```
app/
  main.py              Фабрика FastAPI-приложения и middleware
  config.py            Pydantic-настройки из env
  logging.py           JSON-пайплайн structlog
  db.py                Async-engine и фабрика сессий
  models.py            SQLAlchemy-модель Booking плюс portable GUID
  schemas.py           Pydantic-схемы запросов и ответов
  rate_limit.py        Инстанс slowapi-limiter
  api/bookings.py      HTTP-слой
  services/bookings.py Бизнес-логика и работа с БД (без FastAPI и Celery)
  worker/
    celery_app.py    Конфиг Celery
    db_sync.py       Sync-engine для воркера (зеркалит app/db.py)
    notifications.py Mock-отправка уведомлений
    tasks.py         Задача confirm_booking
alembic/                 env и версии миграций
tests/                   pytest (Docker не нужен)
docker-compose.yml       postgres, redis, migrate, api, worker
Dockerfile               Единый образ для api, worker, migrate
Makefile                 dev, test, lint, format, migrate, up, down
```

Три границы:

1. **API и сервис.** HTTP-вопросы (коды, валидация, rate limit) живут в `app/api`.
2. **Сервис и ORM.** `app/services` единственный слой, который трогает `Booking`. Переиспользуем из REST или воркера.
3. **Воркер.** Полностью синхронный. Работает с БД через `app/worker/db_sync.py`, не импортирует FastAPI.

## Конфигурация

Все настройки лежат в `.env` (шаблон: `.env.example`). Главные параметры:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async URL для FastAPI |
| `ALEMBIC_DATABASE_URL` | `postgresql://...` | Sync URL для Alembic и воркера |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | URL-ы Redis | Транспорт Celery |
| `WORKER_FAILURE_RATE` | `0.15` | Вероятность сбоя попытки подтверждения |
| `WORKER_MAX_RETRIES` | `3` | Количество retry до пометки бронирования как failed |
| `WORKER_RETRY_BACKOFF` | `2` | Основание экспоненты для countdown retry |
| `RATE_LIMIT_CREATE_BOOKING` | `10/minute` | Правило slowapi для `POST /bookings` |
| `LOG_LEVEL` | `INFO` | Корневой уровень логирования (JSON) |

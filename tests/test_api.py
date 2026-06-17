import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient


def _payload(service: str = "haircut") -> dict[str, str]:
    when = datetime.now(UTC) + timedelta(days=1)
    return {
        "name": "Alice",
        "datetime": when.isoformat(),
        "service_type": service,
    }


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_create_returns_202_and_confirms_via_eager_worker(
    client: AsyncClient,
) -> None:
    resp = await client.post("/bookings", json=_payload())
    assert resp.status_code == 202
    body = resp.json()
    assert uuid.UUID(body["id"])
    follow = await client.get(f"/bookings/{body['id']}")
    assert follow.status_code == 200
    assert follow.json()["status"] == "confirmed"


async def test_get_unknown_returns_404(client: AsyncClient) -> None:
    resp = await client.get(f"/bookings/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_create_validation_error(client: AsyncClient) -> None:
    resp = await client.post("/bookings", json={"name": "", "service_type": "x"})
    assert resp.status_code == 422


async def test_list_filters_and_paginates(client: AsyncClient) -> None:
    for svc in ("massage", "haircut", "haircut", "haircut"):
        r = await client.post("/bookings", json=_payload(service=svc))
        assert r.status_code == 202

    confirmed = await client.get("/bookings", params={"status": "confirmed", "limit": 2})
    body = confirmed.json()
    assert confirmed.status_code == 200
    assert body["total"] == 4
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert all(item["status"] == "confirmed" for item in body["items"])

    page2 = await client.get("/bookings", params={"status": "confirmed", "limit": 2, "offset": 2})
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 2

    failed = await client.get("/bookings", params={"status": "failed"})
    assert failed.status_code == 200
    assert failed.json()["total"] == 0


async def test_delete_pending_succeeds(client: AsyncClient, monkeypatch) -> None:
    from app.worker import tasks as worker_tasks

    monkeypatch.setattr(worker_tasks.confirm_booking, "apply_async", lambda *a, **kw: None)
    monkeypatch.setattr(worker_tasks.confirm_booking, "delay", lambda *a, **kw: None)

    create = await client.post("/bookings", json=_payload())
    booking_id = create.json()["id"]

    get_pending = await client.get(f"/bookings/{booking_id}")
    assert get_pending.json()["status"] == "pending"

    delete = await client.delete(f"/bookings/{booking_id}")
    assert delete.status_code == 204

    assert (await client.get(f"/bookings/{booking_id}")).status_code == 404


async def test_delete_confirmed_returns_409(client: AsyncClient) -> None:
    create = await client.post("/bookings", json=_payload())
    booking_id = create.json()["id"]
    delete = await client.delete(f"/bookings/{booking_id}")
    assert delete.status_code == 409


async def test_delete_unknown_returns_404(client: AsyncClient) -> None:
    resp = await client.delete(f"/bookings/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_rate_limit_post(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_CREATE_BOOKING", "2/minute")
    from app.config import get_settings as gs

    gs.cache_clear()

    from httpx import ASGITransport
    from httpx import AsyncClient as Client

    from app.main import create_app

    app = create_app()
    async with Client(transport=ASGITransport(app=app), base_url="http://rl") as c:
        codes = []
        for _ in range(4):
            r = await c.post("/bookings", json=_payload())
            codes.append(r.status_code)
    assert codes[0] == 202
    assert codes.count(429) >= 1

    monkeypatch.setenv("RATE_LIMIT_CREATE_BOOKING", "10000/minute")
    gs.cache_clear()

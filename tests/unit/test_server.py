from pathlib import Path

from fastapi.testclient import TestClient

from slideguard.lexicon import LexiconStore
from slideguard.server.app import create_app
from slideguard.server.lifecycle import LifecycleController


TOKEN_HEADERS = {"X-SlideGuard-Token": "secret"}


def test_api_requires_session_token_and_sets_security_headers() -> None:
    client = TestClient(create_app(token="secret"))

    assert client.get("/api/health").status_code == 401
    assert client.get(
        "/api/health", headers={"X-SlideGuard-Token": "wrong"}
    ).status_code == 401
    response = client.get("/api/health", headers=TOKEN_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_api_rejects_unexpected_host_and_origin() -> None:
    client = TestClient(
        create_app(
            token="secret",
            expected_host="testserver",
            allowed_origin="http://testserver",
        )
    )

    assert client.get(
        "/api/health",
        headers={**TOKEN_HEADERS, "Host": "evil.example"},
    ).status_code == 400
    assert client.get(
        "/api/health",
        headers={**TOKEN_HEADERS, "Origin": "https://evil.example"},
    ).status_code == 403
    assert client.get(
        "/api/health",
        headers={**TOKEN_HEADERS, "Origin": "http://testserver"},
    ).status_code == 200


def test_lexicon_api_reads_normalizes_and_saves(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-terms.txt"
    path.write_text("旧项目\n", encoding="utf-8")
    client = TestClient(create_app(token="secret", lexicon_store=LexiconStore(path)))

    before = client.get("/api/lexicon", headers=TOKEN_HEADERS)
    assert before.status_code == 200
    assert before.json()["terms"] == ["旧项目"]

    after = client.put(
        "/api/lexicon",
        headers=TOKEN_HEADERS,
        json={
            "terms": [" 内部代号 ", "内部代号", "禁用产品"],
            "expected_digest": before.json()["digest"],
        },
    )
    assert after.status_code == 200
    assert after.json()["terms"] == ["内部代号", "禁用产品"]
    assert after.json()["count"] == 2
    assert after.json()["empty"] is False


def test_lexicon_api_rejects_stale_update(tmp_path: Path) -> None:
    path = tmp_path / "sensitive-terms.txt"
    path.write_text("词条一\n", encoding="utf-8")
    client = TestClient(create_app(token="secret", lexicon_store=LexiconStore(path)))
    digest = client.get("/api/lexicon", headers=TOKEN_HEADERS).json()["digest"]
    path.write_text("词条二\n", encoding="utf-8")

    response = client.put(
        "/api/lexicon",
        headers=TOKEN_HEADERS,
        json={"terms": ["词条三"], "expected_digest": digest},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "lexicon_conflict"


def test_websocket_requires_token_protocol_and_tracks_connection() -> None:
    lifecycle = LifecycleController(idle_seconds=60)
    client = TestClient(
        create_app(
            token="secret",
            lifecycle=lifecycle,
            allowed_origin="http://testserver",
        )
    )

    with client.websocket_connect(
        "/ws",
        subprotocols=["slideguard", "secret"],
        headers={"Origin": "http://testserver"},
    ) as websocket:
        assert websocket.accepted_subprotocol == "slideguard"
        assert lifecycle.connected_clients == 1
        websocket.send_text("ping")
        assert websocket.receive_text() == "pong"

    assert lifecycle.connected_clients == 0


def test_exit_endpoint_requests_shutdown() -> None:
    events: list[str] = []
    lifecycle = LifecycleController(idle_seconds=60)
    lifecycle.set_shutdown_callback(lambda: events.append("shutdown"))
    client = TestClient(create_app(token="secret", lifecycle=lifecycle))

    response = client.post("/api/exit", headers=TOKEN_HEADERS)

    assert response.status_code == 202
    import time

    deadline = time.monotonic() + 0.5
    while not events and time.monotonic() < deadline:
        time.sleep(0.01)
    assert events == ["shutdown"]

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.store import MemoryStore


def client(monkeypatch):
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    monkeypatch.setenv("PORTFOLIO_REPOSITORY", "owner/portfolio")
    get_settings.cache_clear()
    return TestClient(create_app(MemoryStore()))


def test_article_to_queue_flow(monkeypatch):
    with client(monkeypatch) as app:
        article = app.post("/api/articles", json={"brief":{"topic":"Build reliable agent workflows"}}).json()
        article_id = article["id"]
        assert app.post(f"/api/articles/{article_id}/outline").status_code == 200
        assert app.post(f"/api/articles/{article_id}/draft").status_code == 200
        response = app.post(f"/api/articles/{article_id}/queue", json={"scheduled_for":(datetime.now(UTC) + timedelta(days=7)).isoformat()})
        assert response.status_code == 201
        assert response.json()["status"] == "queued"


def test_duplicate_release_slot_is_rejected(monkeypatch):
    with client(monkeypatch) as app:
        release = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        for topic in ("A technical note one", "A technical note two"):
            article = app.post("/api/articles", json={"brief":{"topic":topic}}).json()
            app.post(f"/api/articles/{article['id']}/outline")
            app.post(f"/api/articles/{article['id']}/draft")
            response = app.post(f"/api/articles/{article['id']}/queue", json={"scheduled_for":release})
        assert response.status_code == 409


def test_webhook_requires_signature(monkeypatch):
    with client(monkeypatch) as app:
        response = app.post("/webhooks/github", content=b"{}", headers={"X-GitHub-Event":"pull_request"})
        assert response.status_code == 401


def test_health_and_built_web_shell_are_available(monkeypatch):
    with client(monkeypatch) as app:
        assert app.get("/healthz").json() == {"status": "ok"}
        response = app.get("/")
        assert response.status_code == 200
        assert "Publishing Studio" in response.text

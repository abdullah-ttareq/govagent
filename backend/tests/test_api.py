"""اختبارات أساسية لنقاط GovAgent."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "model_provider" in body


def test_chat_returns_mock_reply():
    response = client.post("/api/chat", json={"message": "اكتب لي خطابًا رسميًا"})
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert "اكتب لي خطابًا رسميًا" in body["reply"]


def test_chat_rejects_empty_message():
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 422


def test_chat_rejects_missing_message():
    response = client.post("/api/chat", json={})
    assert response.status_code == 422

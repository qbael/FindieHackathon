import pytest
from fastapi.testclient import TestClient

from findie_ai.main import app


def test_internal_status_requires_secret_and_never_claims_inference_ready(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "unit-test-service-token")
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/status").status_code == 401
        assert client.get("/v1/status", headers={"X-Service-Token": "wrong"}).status_code == 401
        headers = {"X-Service-Token": "unit-test-service-token"}
        response = client.get("/v1/status", headers=headers)
        assert response.status_code == 200
        assert response.json()["inferenceReady"] is False
        assert response.json()["embeddingDimensions"] == 2048
        assert client.get("/health/ready", headers=headers).status_code == 503
        assert "unit-test-service-token" not in response.text


def test_startup_rejects_missing_service_secret(monkeypatch):
    monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="AI_SERVICE_TOKEN"):
        with TestClient(app):
            pass

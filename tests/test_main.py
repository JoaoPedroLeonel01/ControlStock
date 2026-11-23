from fastapi.testclient import TestClient

from src.control_stock.main import app

client = TestClient(app)


def test_read_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Hello World",
        "app": "ControlStock",
        "status": "running",
    }


def test_health_check() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

    response_z = client.get("/healthz")
    assert response_z.status_code == 200
    assert response_z.json() == {"status": "healthy"}

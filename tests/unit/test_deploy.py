from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def test_container_runs_migrations_before_uvicorn() -> None:
    cmd = next(
        line for line in DOCKERFILE.read_text().splitlines() if line.startswith("CMD")
    )
    assert "alembic upgrade head && exec uvicorn src.control_stock.main:app" in cmd

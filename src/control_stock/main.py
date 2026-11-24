from fastapi import FastAPI

from src.control_stock.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="Inventory Management System for Apparel E-commerce",
    version="0.1.0",
)


@app.get("/", tags=["Root"])
def read_root() -> dict[str, str]:
    return {
        "message": "Hello World",
        "app": "ControlStock",
        "status": "running",
    }


@app.get("/health", tags=["Health"])
@app.get("/healthz", tags=["Health"])
def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
    }

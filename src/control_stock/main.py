from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.control_stock.core.config import settings
from src.control_stock.modules.inventory.errors import InventoryError, error_body
from src.control_stock.modules.inventory.router import router as inventory_router

app = FastAPI(
    title=settings.APP_NAME,
    description="Inventory Management System for Apparel E-commerce",
    version="0.1.0",
)

app.include_router(inventory_router)


@app.exception_handler(InventoryError)
def inventory_error_handler(request: Request, error: InventoryError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code, content={"detail": error_body(error)}
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

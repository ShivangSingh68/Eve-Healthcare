import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, bookings, centers, payments, tests
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="EVE Healthcare Backend",
    version="1.0.0",
    description=(
        "Diagnostic test bookings with simulated payments and idempotent payment webhooks.\n\n"
        "Authenticate with `POST /auth/login`, then click **Authorize** and paste the token."
    ),
)


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=headers,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "Internal server error", "code": "internal_error"}
    )


@app.get("/health", tags=["Health"], summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(centers.router)
app.include_router(tests.router)
app.include_router(bookings.router)
app.include_router(payments.router)


# Optional demo UI (plain HTML/JS in /frontend), served from the same origin as the API.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui/")

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

import db
import scan_worker
from backend.app.api.routes import admin, ask, auth, conversations, gallery, health, payments, profile
from backend.app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scan_worker.start()
    yield


app = FastAPI(title="Dastyar Asnad API", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="session",
    same_site="lax",
    https_only=settings.secure_cookies,
    max_age=60 * 60 * 24 * 30,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        body = detail if "error" in detail else {"error": detail}
    else:
        body = {"error": detail or "خطا در ارتباط با سرور"}
    return JSONResponse(jsonable_encoder(body), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, _exc: RequestValidationError):
    return JSONResponse({"error": "ورودی نامعتبر است"}, status_code=422)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(payments.router)
app.include_router(gallery.router)
app.include_router(conversations.router)
app.include_router(ask.router)
app.include_router(admin.router)

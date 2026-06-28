import uvicorn

from backend.app.core.config import settings


if __name__ == "__main__":
    print(f"Serving on http://{settings.host}:{settings.port} (uvicorn, FastAPI)")
    uvicorn.run(
        "backend.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )

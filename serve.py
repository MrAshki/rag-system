"""Production entry point for the FastAPI backend.

Usage:
    python serve.py

Behind a real domain, put nginx/Caddy in front of this for HTTPS termination
and set PUBLIC_BASE_URL to the https:// URL in .env.
"""
import uvicorn

from backend.app.core.config import settings

if __name__ == "__main__":
    print(f"Serving on http://{settings.host}:{settings.port} (uvicorn, FastAPI)")
    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port, reload=settings.debug)

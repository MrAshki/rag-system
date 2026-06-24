"""Production entry point. Serves the app with waitress (a real WSGI server)
instead of Flask's development server.

Usage:
    python serve.py

Behind a real domain, put nginx/Caddy in front of this for HTTPS termination
and set PUBLIC_BASE_URL to the https:// URL in .env.
"""
import os
from waitress import serve
from app import app

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    print(f"Serving on http://{host}:{port} (waitress, production mode)")
    serve(app, host=host, port=port, threads=8)

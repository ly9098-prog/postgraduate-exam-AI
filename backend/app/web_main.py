"""Web entry point — FastAPI HTTP application.

Usage::

    uvicorn app.web_main:app --host 0.0.0.0 --port 8000
    gunicorn app.web_main:app -k uvicorn.workers.UvicornWorker

Sets PROCESS_ROLE=web and constructs the full FastAPI application with
API routes, middleware, and static file serving.
"""

import os

os.environ.setdefault("PROCESS_ROLE", "web")

# Import the shared FastAPI app — the lifespan handles role-based init
from app.main import app  # noqa: F401

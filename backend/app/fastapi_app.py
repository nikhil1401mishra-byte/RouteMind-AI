"""Optional FastAPI adapter (roadmap Phase 2 target stack).

The stdlib server is the zero-dependency default. If FastAPI and uvicorn are
installed, `run.py` prefers this adapter so the prototype already runs on the
intended production stack, with automatic OpenAPI docs at /docs.

Both adapters delegate to the same `api.handle`, so behaviour is identical.
"""

from __future__ import annotations

from typing import Any, Dict

from . import api, config


def create_app():
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(
        title="RouteMind AI",
        version="1.0.0",
        description=(
            "Risk-aware logistics control room for North East India. "
            "Live inputs: Open-Meteo (rainfall), USGS (seismic), OSRM/OSM (roads). "
            "Disruption risk is a transparent weighted model, not a trained ML model "
            "-- see /api/model-card."
        ),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def dispatch(request: Request, path: str) -> JSONResponse:
        body: Dict[str, Any] = {}
        if request.method == "POST":
            try:
                parsed = await request.json()
                if isinstance(parsed, dict):
                    body = parsed
            except Exception:
                body = {}
        query = dict(request.query_params)
        status, payload = api.handle(request.method, path, query, body,
                                     dict(request.headers))
        return JSONResponse(status_code=status, content=payload)

    @app.get("/api/{path:path}")
    async def api_get(request: Request, path: str):
        return await dispatch(request, f"/api/{path}")

    @app.post("/api/{path:path}")
    async def api_post(request: Request, path: str):
        return await dispatch(request, f"/api/{path}")

    frontend = config.FRONTEND_DIR
    if frontend.exists():
        @app.get("/")
        async def index():
            return FileResponse(frontend / "index.html")

        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")

    return app


# Allows: uvicorn app.fastapi_app:app --reload
try:  # pragma: no cover - only when FastAPI is installed
    app = create_app()
except Exception:  # pragma: no cover
    app = None

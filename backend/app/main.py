"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import business, core, documents
from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Enterprise AI Operations Copilot", version="1.0.0", lifespan=lifespan,
                  description="RAG + tool-calling assistant over documents, products, inventory and orders.")
    app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(core.router)
    app.include_router(documents.router)
    app.include_router(business.router)

    @app.get("/health", tags=["meta"])
    def health():
        s = get_settings()
        return {"status": "ok", "llm_provider": s.llm_provider, "embedding_provider": s.embedding_provider}

    return app


app = create_app()

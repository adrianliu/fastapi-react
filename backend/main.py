"""Hindcast backend: FastAPI app with core routes plus optional fixes and bench routers."""

import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import ModuleType

from fastapi import APIRouter, FastAPI

from hindcast import api_core
from hindcast.store.schema import core_db, ensure_core_schema

log = logging.getLogger("hindcast")

OPTIONAL_MODULES = ("hindcast.api_fixes", "hindcast.api_bench")


def _load_optional() -> list[ModuleType]:
    mods: list[ModuleType] = []
    for name in OPTIONAL_MODULES:
        try:
            mods.append(importlib.import_module(name))
        except Exception:
            log.exception("optional module %s not loaded", name)
    return mods


_optional = _load_optional()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with core_db() as conn:
        ensure_core_schema(conn)
        for mod in _optional:
            ensure = getattr(mod, "ensure_schema", None)
            if callable(ensure):
                ensure(conn)
    yield


app = FastAPI(title="Hindcast", lifespan=lifespan)
app.include_router(api_core.router)
for _mod in _optional:
    _router = getattr(_mod, "router", None)
    if isinstance(_router, APIRouter):
        app.include_router(_router)

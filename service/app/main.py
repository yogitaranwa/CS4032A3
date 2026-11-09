"""Command parser service: POST /parse, GET /healthz, GET /readyz."""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import model as model_mod
from .config import Settings
from .validate import parse_and_validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parser")


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class State:
    def __init__(self, settings):
        self.settings = settings
        self.generator = None
        self.error = None

    @property
    def ready(self):
        return self.generator is not None


def create_app(settings=None, loader=None, autoload=True):
    """loader(settings) -> object with .generate(text). Tests pass a fake loader."""
    settings = settings or Settings()
    loader = loader or model_mod.load
    state = State(settings)

    def load_in_background():
        try:
            state.generator = loader(settings)
            bad = model_mod.verify_checksums(settings.model_dir) if loader is model_mod.load else []
            if bad:
                raise RuntimeError(f"checksum mismatch for {bad}")
        except Exception as exc:  # stay alive (healthz 200) but never become ready
            state.generator = None
            state.error = str(exc)
            log.exception("model load failed")

    @asynccontextmanager
    async def lifespan(app):
        if autoload:
            # load in a thread so /healthz answers (200) while /readyz is 503
            threading.Thread(target=load_in_background, daemon=True).start()
        yield

    app = FastAPI(title="command parser", lifespan=lifespan)
    app.state.parser = state
    headers = {"X-Model-Version": settings.model_version, "X-Served-By": settings.served_by}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        if state.ready:
            return {"status": "ready"}
        return JSONResponse({"status": "loading"}, status_code=503)

    @app.post("/parse")
    def parse(req: ParseRequest):
        if not state.ready:
            return JSONResponse({"error": "model_not_ready"}, status_code=503, headers=headers)
        output = state.generator.generate(req.text)
        if settings.fault_inject:
            output = "not json"
        obj = parse_and_validate(output)
        if obj is None:
            log.warning("invalid model output: %r", output[:200])
            return JSONResponse({"error": "invalid_model_output"}, status_code=500, headers=headers)
        return JSONResponse(obj, status_code=200, headers=headers)

    return app


def app_factory():
    return create_app()

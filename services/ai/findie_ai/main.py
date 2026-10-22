from contextlib import asynccontextmanager
import os
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    token = os.environ.get("AI_SERVICE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AI_SERVICE_TOKEN must be configured.")
    app.state.service_token = token.encode("utf-8")
    yield


app = FastAPI(title="Findie AI", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def authenticate(request: Request, token: Annotated[str | None, Header(alias="X-Service-Token")] = None):
    if token is None or not secrets.compare_digest(token.encode("utf-8"), request.app.state.service_token):
        raise HTTPException(status_code=401, detail="Invalid service credentials.")


@app.get("/health/live")
def live():
    return {"status": "ok", "stage": "scaffold"}


@app.get("/health/ready", dependencies=[Depends(authenticate)])
def ready():
    # shortcut: inference runs only in Colab; replace after choosing a private model host.
    return JSONResponse(status_code=503, content={"status": "not_ready", "reason": "models_run_in_colab"})


@app.get("/v1/status", dependencies=[Depends(authenticate)])
def status():
    return {
        "stage": "scaffold",
        "inferenceReady": False,
        "execution": "colab",
        "models": {"embedding": "Qwen/Qwen3-VL-Embedding-2B", "redaction": "Qwen/Qwen3-VL-4B-Instruct"},
        "embeddingDimensions": 2048,
    }

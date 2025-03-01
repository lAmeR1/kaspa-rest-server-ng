# encoding: utf-8
import logging
import os
from typing import Optional

import fastapi.logger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi_utils.tasks import repeat_every
from kaspad_client import KaspadClient
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

from dbsession import async_session
from helper.LimitUploadSize import LimitUploadSize
from helper.StrictRoute import StrictRoute

fastapi.logger.logger.setLevel(logging.WARNING)

_logger = logging.getLogger(__name__)

app = FastAPI(
    title="Kaspa REST-API server",
    description="This server is to communicate with kaspa network via REST-API",
    version=os.getenv("VERSION") or "tbd",
    contact={"name": "lAmeR1"},
    license_info={"name": "MIT LICENSE"},
)
app.router.route_class = StrictRoute

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(LimitUploadSize, max_upload_size=200_000)  # ~1MB

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class KaspadStatus(BaseModel):
    is_online: bool = False
    server_version: Optional[str] = None
    is_utxo_indexed: Optional[bool] = None
    is_synced: Optional[bool] = None


class DatabaseStatus(BaseModel):
    is_online: bool = False


class PingResponse(BaseModel):
    kaspad: KaspadStatus = KaspadStatus()
    database: DatabaseStatus = DatabaseStatus()


@app.get("/ping", include_in_schema=False, response_model=PingResponse)
async def ping_server():
    """
    Ping Pong
    """
    result = PingResponse()

    error = False
    try:
        info = await kaspad_client[0].get_info()
        result.kaspad.is_online = True
        result.kaspad.server_version = info["getInfoResponse"]["serverVersion"]
        result.kaspad.is_utxo_indexed = info["getInfoResponse"]["isUtxoIndexed"]
        result.kaspad.is_synced = info["getInfoResponse"]["isSynced"]
    except Exception as err:
        _logger.error("Kaspad health check failed %s", err)
        error = True

    if os.getenv("SQL_URI") is not None:
        async with async_session() as session:
            try:
                await session.execute("SELECT 1")
                result.database.is_online = True
            except Exception as err:
                _logger.error("Database health check failed %s", err)
                error = True

    if error or not result.kaspad.is_synced:
        return JSONResponse(status_code=500, content=result.dict())

    return result


if not os.environ.get("KASPAD_HOST_1"):
    raise Exception("Please set KASPAD_HOST_1 environment variable.")

try:
    kaspad_client = KaspadClient("", 0)
except RuntimeError:
    pass

kaspad_client = [os.environ.get("KASPAD_HOST_1")]  # type: list[KaspadClient]


@app.exception_handler(Exception)
async def unicorn_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error"
            # "traceback": f"{traceback.format_exception(exc)}"
        },
    )


@app.on_event("startup")
@repeat_every(seconds=60)
async def periodical_blockdag():
    await kaspad_client.get_block_dag_info()

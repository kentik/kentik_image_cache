import asyncio
import hashlib
import json
import logging
import pickle
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from kentik_api import ImageType, KentikAPI
from kentik_api.api_connection.retryable_session import RetryableSession
from kentik_api.public.errors import KentikAPIError, TimedOutError
from pydantic import BaseModel, BaseSettings

from object_cache import *

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)-15s %(message)s",
    level=logging.INFO,
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger()


class Settings(BaseSettings):
    app_name: str = "Kentik Image Cache"
    kt_auth_email: str
    kt_auth_token: str
    kentik_api_url: str = "https://api.kentik.com/api/v5"
    kentik_api_retries: int = 3
    kentik_api_timeout: int = 60  # seconds
    entry_wait_timeout: int = kentik_api_retries * kentik_api_timeout + 5  # seconds
    default_ttl: int = 300  # seconds
    cache_path: str = "cache"
    cache_maintenance_period: int = 60  # seconds
    debug: bool = False

    class Config:
        env_file = ".env"


# Load application settings from environment or .env
settings = Settings()
if settings.debug:
    log.info("Enabling debug messages")
    log.setLevel(logging.DEBUG)
    for k, v in settings:
        if k == "kt_auth_token":
            v = "<redacted>"
        log.debug("%s: %s", k, v)


class RequestData(BaseModel):
    api_query: Any
    ttl: int = settings.default_ttl


class ErrorResponse(BaseModel):
    type: str
    loc: str
    msg: str


class ImageId(BaseModel):
    id: str


class CacheEntryInfo(BaseModel):
    id: str
    type: str
    size: int
    expiration: str


class CacheInfo(BaseModel):
    active_count: int
    pending_count: int
    active_entries: List[CacheEntryInfo]
    pending_entries: List[CacheEntryInfo]


# Create object cache
cache = ObjectCache(Path(settings.cache_path).resolve(), entry_wait_timeout=settings.entry_wait_timeout)
# Create Kentik API client
retry_strategy = deepcopy(RetryableSession.DEFAULT_RETRY_STRATEGY)
retry_strategy.total = settings.kentik_api_retries
api = KentikAPI(
    settings.kt_auth_email,
    settings.kt_auth_token,
    settings.kentik_api_url,
    retry_strategy=retry_strategy,
    timeout=float(settings.kentik_api_timeout),
)

app = FastAPI()


def make_image_id(api_query: Dict, ttl: int) -> str:
    """
    Construct unique image ID based on query data and expiration time
    """

    h = hashlib.sha256(str(api_query).encode()).hexdigest()
    t = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return f"{h}_{t.timestamp()}"


def fetch_image(image_id: str, query: Dict) -> None:
    """
    Execute 'topxchart' Kentik API query and store resulting image (or error code and message) in the cache
    """

    log.info("fetch_image: %s", image_id)
    try:
        r = api.query.chart(query)
        log.info(
            "fetch_image: %s: got %s image (%d bytes)",
            image_id,
            r.image_type.name,
            len(r.image_data),
        )
        cache.activate_entry(image_id, CacheEntryType.IMAGE, pickle.dumps(r))
    except TimedOutError:
        log.error("fetch_image: %s: timeout", image_id)
        cache.activate_entry(
            image_id,
            CacheEntryType.ERROR_MSG,
            json.dumps(dict(status_code=500, msgs=["Request timeout"])),
        )
    except KentikAPIError as e:
        if hasattr(e, "status_code"):
            log.error(
                "fetch_image: %s: API error status_code: %d, msgs: %s",
                image_id,
                e.status_code,
                e.args,
            )
            cache.activate_entry(
                image_id,
                CacheEntryType.ERROR_MSG,
                json.dumps(dict(status_code=e.status_code, msgs=e.args)),
            )
        else:
            log.error("fetch_image: %s: API error %s", image_id, e)
            cache.activate_entry(image_id, CacheEntryType.ERROR_MSG, json.dumps(dict(status_code=504, msgs=str(e))))
    log.debug("fetch_image: %s: done", image_id)


def img_type_to_media(img_type: ImageType) -> str:
    """
    Convert kentik-api.ImageType to corresponding MIME type
    """

    i2m = {
        ImageType.png.value: "image/png",
        ImageType.pdf.value: "application/pdf",
        ImageType.jpg.value: "image/jpeg",
        ImageType.svg.value: "image/svg",
    }
    if img_type.value not in i2m:
        return "image/unknown"
    else:
        return i2m[img_type.value]


def expiration(image_id: str) -> Optional[datetime]:
    """
    Parse expiration timestamp from image id
    """

    # noinspection PyBroadException
    try:
        return datetime.fromtimestamp(float(image_id.split("_")[1]), tz=timezone.utc)
    except:
        return None


def is_expired(image_id: str) -> bool:
    """
    Check whether entry is expired (based on timestamp encoded in the image_id)
    """

    ts = expiration(image_id)
    now = datetime.now(timezone.utc)
    if ts is None:
        log.debug("Invalid cache entry ID: %s", image_id)
        return True
    log.debug("entry: %s (expiration ts: %s)", image_id, ts.isoformat())
    return ts < now


async def run_cache_pruning(c: ObjectCache, period: int):
    log.info("Scheduling periodic cache pruning (period: %d)", period)
    while True:
        await asyncio.sleep(period)
        c.prune(is_expired)


@app.post("/requests", response_model=ImageId, responses={400: {"model": ErrorResponse}})
async def create_request(request: RequestData, background_tasks: BackgroundTasks):
    """
    Generate unique image Id and if matching entry is not present
    in the cache schedule request to Kentik API
    """

    log.debug("api_query: %s, ttl: %d", request.api_query, request.ttl)
    if request.api_query is None:
        return JSONResponse(
            content={
                "loc": jsonable_encoder(request),
                "msg": f"Incomplete request, missing 'api_query'",
                "type": "invalid request",
            },
            status_code=400,
        )
    iid = make_image_id(request.api_query, request.ttl)
    log.info("request: id: %s ttl: %d", iid, request.ttl)
    r = cache.create_entry(iid, CacheEntryType.REQUEST, json.dumps(jsonable_encoder(request.api_query)))
    if r == CreationStatus.EXISTING:
        log.info("Entry %s already exists", iid)
    else:
        log.info("New Entry %s", iid)
        background_tasks.add_task(fetch_image, iid, request.api_query)
    return {"id": iid}


@app.get(
    "/image/{image_id}",
    responses={
        200: {"content": {"image/png": {}, "application/pdf": {}}},
        422: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def get_image(image_id: str):
    """
    Retrieve cached image.
    """

    log.info("GET image %s", image_id)
    if is_expired(image_id):
        log.info("GET %s: entry is expired", image_id)
        return JSONResponse(
            content={"loc": image_id, "msg": "Image not found", "type": "error"},
            status_code=404,
        )
    cache.wait_for(image_id)
    entry = cache.get_entry(image_id)
    if entry is None:
        return JSONResponse(
            content={"loc": image_id, "msg": "Image not found", "type": "error"},
            status_code=404,
        )
    if entry.status == EntryStatus.ACTIVE:
        if entry.type == CacheEntryType.IMAGE:
            img = pickle.loads(entry.data)
            return Response(content=img.image_data, media_type=img_type_to_media(img.image_type))
        if entry.type == CacheEntryType.ERROR_MSG:
            d = json.loads(entry.data.decode())
            return JSONResponse(
                content={"loc": image_id, "msg": d["msgs"], "type": "Kentik API error"},
                status_code=d["status_code"],
            )
    if entry.status == EntryStatus.PENDING:
        log.error("GET %s: got pending entry", image_id)
        return JSONResponse(
            content={
                "loc": image_id,
                "msg": f"Internal error (entry status: {entry.status.value})",
                "type": "error",
            },
            status_code=500,
        )
    else:
        log.error("GET %s: unknown entry status: %s", image_id, entry.status.value)
        return JSONResponse(
            content={
                "loc": image_id,
                "msg": f"Internal error (unknown entry status: {entry.status.value})",
                "type": "error",
            },
            status_code=500,
        )


def entry_info(entry: CacheEntry) -> CacheEntryInfo:
    """Return CacheEntryInfo instance for given CacheEntry"""
    exp = expiration(entry.uid)
    now = datetime.now(tz=timezone.utc)
    if exp is None:
        ts = "<invalid>"
    else:
        ts = f"{exp.isoformat()} (remaining: {exp - now})"
    return CacheEntryInfo(id=entry.uid, type=entry.type.value, size=len(entry.data), expiration=ts)


@app.get("/info", response_model=CacheInfo)
async def get_info():
    """
    Return information about cache content
    """
    return {
        "active_count": cache.active_count,
        "pending_count": cache.pending_count,
        "active_entries": [entry_info(e) for e in cache.active_entries],
        "pending_entries": [entry_info(e) for e in cache.pending_entries],
    }


@app.get("/favicon.ico")
async def get_favicon():
    """Return favicon"""

    return FileResponse(path="assets/kentik_favicon.ico", media_type="image/x-icon")


@app.on_event("startup")
async def startup_event():
    log.info("Startup cache pruning")
    cache.prune(is_expired)
    log.info("Startup cache pruning complete")
    # Restart requests for all remaining pending entries
    for e in cache.pending_entries:
        log.info("Restarting pending entry: %s", e.uid)
        fetch_image(e.uid, json.loads(e.data.decode()))
    # Start periodic cache pruning
    asyncio.create_task(run_cache_pruning(cache, settings.cache_maintenance_period))

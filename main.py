import asyncio
import hashlib
import json
import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Dict

from fastapi import BackgroundTasks, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from kentik_api import ImageType, KentikAPI
from kentik_api.public.errors import KentikAPIError, TimedOutError
from pydantic import BaseSettings
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
    status_poll_period: int = 3  # seconds
    default_ttl: int = 300  # seconds
    cache_path: str = "cache"
    cache_maintenance_period: int = 60  # seconds
    debug: bool = False


settings = Settings()
if settings.debug:
    log.info("Enabling debug messages")
    log.setLevel(logging.DEBUG)
    for k, v in settings:
        if k == "kt_auth_token":
            v = "<redacted>"
        log.debug("%s: %s", k, v)


app = FastAPI()

cache = ObjectCache(Path(settings.cache_path).resolve())
cache_maintenance_ts = datetime.now(timezone.utc)

api = KentikAPI(settings.kt_auth_email, settings.kt_auth_token, settings.kentik_api_url)


def make_image_id(api_query: Dict, ttl: int) -> str:
    """
    Construct unique image ID based on query data and expiration time
    """

    h = hashlib.sha256(str(api_query).encode()).hexdigest()
    t = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return f"{h}_{t.timestamp()}"


def fetch_image(image_id: str, query: Dict):
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
            cache.activate_entry(
                image_id, CacheEntryType.ERROR_MSG, json.dumps(dict(exception=str(e)))
            )
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


def expiration(image_id: str):
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
    log.info("Scheduling cache pruning (period: %d)", period)
    while True:
        c.prune(is_expired)
        await asyncio.sleep(period)


@app.post("/requests")
async def create_request(request: Request, background_tasks: BackgroundTasks):
    """
    Generate unique image Id, if cache entry does not exist,
    create it an schedule retrieval of image from Kentik API
    """

    d = await request.json()
    try:
        api_query = d["api_query"]
        ttl = d.get("ttl", settings.default_ttl)
    except KeyError:
        return {"detail": [{"loc": {d}, "msg": "missing api_query", "type": "error"}]}
    log.info("api_query: %s, ttl: %d", api_query, ttl)
    iid = make_image_id(api_query, ttl)
    log.info("id: %s", iid)
    r = cache.create_entry(
        iid, CacheEntryType.REQUEST, json.dumps(jsonable_encoder(api_query))
    )
    if r == CreationStatus.EXISTING:
        log.info("Entry %s already exists", iid)
    else:
        log.info("New Entry %s", iid)
        background_tasks.add_task(fetch_image, iid, api_query)
    return {"id": iid}


@app.get("/images/{image_id}")
def get_image(image_id: str):
    """
    Lookup entry in the cache, wait for it to become active and return it
    """

    log.info("GET image %s", image_id)
    ts = expiration(image_id)
    if ts is None:
        log.info("GET %s: invalid ID", image_id)
        return JSONResponse(
            content={
                "detail": [
                    {"loc": [image_id], "msg": "Invalid image ID", "type": "error"}
                ]
            },
            status_code=400,
        )
    if ts < datetime.now(timezone.utc):
        log.info("GET %s: expired ts: %s", image_id, ts.isoformat())
        return JSONResponse(
            content={
                "detail": [
                    {"loc": [image_id], "msg": "Image not found", "type": "error"}
                ]
            },
            status_code=404,
        )
    while True:
        entry = cache.get_entry(image_id)
        if entry is None:
            return JSONResponse(
                content={
                    "detail": [
                        {"loc": [image_id], "msg": "Image not found", "type": "error"}
                    ]
                },
                status_code=404,
            )
        if entry.status == EntryStatus.ACTIVE:
            if entry.type == CacheEntryType.IMAGE:
                img = pickle.loads(entry.data)
                return Response(
                    content=img.image_data, media_type=img_type_to_media(img.image_type)
                )
            if entry.type == CacheEntryType.ERROR_MSG:
                d = json.loads(entry.data.decode())
                return JSONResponse(status_code=d["status_code"], content=d["msgs"])
        if entry.status == EntryStatus.PENDING:
            log.debug("GET %s: still pending", image_id)
            sleep(settings.status_poll_period)
        else:
            log.error("GET %s: unknown entry status: %s", image_id, entry.status.value)
            return JSONResponse(
                content={
                    "detail": [
                        {
                            "loc": [image_id],
                            "msg": f"Internal error (unknown status: {entry.status.value}",
                            "type": "error",
                        }
                    ]
                },
                status_code=500,
            )


@app.get("/favicon.ico")
async def get_favicon():
    return FileResponse(path="assets/kentik_favicon.ico")


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(run_cache_pruning(cache, settings.cache_maintenance_period))

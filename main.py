import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import BackgroundTasks, Body, FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.requests import Request
import hashlib
import json
import logging
from kentik_api import ImageType, KentikAPI
from kentik_api.public.errors import *
from object_cache import *
from pathlib import Path
import pickle
from pydantic import BaseSettings
from time import sleep
import timeit
from typing import Dict


logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(name)-15s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger()


class Settings(BaseSettings):
    app_name: str = "Kentik Image Cache"
    kt_auth_email: str
    kt_auth_token: str
    kentik_api_url: str = 'https://api.kentik.com/api/v5'
    kentik_api_retries: int = 3
    kentik_api_timeout: int = 60  # seconds
    status_poll_period: int = 3  # seconds
    default_ttl: int = 300  # seconds
    cache_path: str = 'cache'
    cache_maintenance_period: int = 60  # seconds
    debug: bool = False


settings = Settings()
if settings.debug:
    log.info('Enabling debug messages')
    log.setLevel(logging.DEBUG)
    for k,v in settings:
        if k == 'kt_auth_token':
            v = '<redacted>'
        log.debug('%s: %s', k, v)


app = FastAPI()

cache = ObjectCache(Path(settings.cache_path).resolve())
cache_maintenance_ts = datetime.now(timezone.utc)

api = KentikAPI(settings.kt_auth_email, settings.kt_auth_token, settings.kentik_api_url)


def make_image_id(api_query: Dict, ttl: int) -> str:
    h = hashlib.sha256(str(api_query).encode()).hexdigest()
    t = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return f'{h}_{t.timestamp()}'


def fetch_image(image_id: str, query: Dict):
    log.info('fetch_image: start %s', image_id)
    start = timeit.default_timer()
    try:
        r = api.query.chart(query)
        log.info('fetch_image: %s: got %s image (%d bytes)', image_id, r.image_type.name, len(r.image_data))
        cache.activate_entry(image_id, CacheEntryType.IMAGE, pickle.dumps(r))
    except TimedOutError as e:
        log.error('fetch_image: %s: timeout', image_id)
        cache.activate_entry(image_id, CacheEntryType.ERROR_MSG,
                             json.dumps(dict(status_code=500, msgs=["Request timeout"])))
    except KentikAPIError as e:
        if hasattr(e, 'status_code'):
            log.error('fetch_image: %s: API error status_code: %d, msgs: %s', image_id, e.status_code, e.args)
            cache.activate_entry(image_id, CacheEntryType.ERROR_MSG,
                                 json.dumps(dict(status_code=e.status_code, msgs=e.args)))
        else:
            log.error('fetch_image: %s: API error %s', image_id, e)
            cache.activate_entry(image_id, CacheEntryType.ERROR_MSG, json.dumps(dict(exception=str(e))))
    end = timeit.default_timer()
    log.debug('fetch_image: %s: done in %d seconds', image_id, end - start)


def img_type_to_media(img_type: ImageType) -> str:
    i2m = {ImageType.png.value: 'image/png',
           ImageType.pdf.value: 'application/pdf',
           ImageType.jpg.value: 'image/jpeg',
           ImageType.svg.value: 'image/svg'}
    if img_type.value not in i2m:
        return 'image/unknown'
    else:
        return i2m[img_type.value]


def expiration(image_id):
    # noinspection PyBroadException
    try:
        return datetime.fromtimestamp(float(image_id.split('_')[1]), tz=timezone.utc)
    except:
        return None


def is_expired(entry: str) -> bool:
    ts = expiration(entry)
    now = datetime.now(timezone.utc)
    if ts is None:
        log.debug('Invalid cache entry ID: %s', entry)
        return True
    log.debug('entry: %s (expiration ts: %s)', entry, ts.isoformat())
    return ts < now


class CacheMinder:
    def __init__(self, cache: ObjectCache):
        self._cache = cache

    async def run_main(self, period: int):
        log.info('CacheMinder starting (period: %d)', period)
        while True:
            self._cache.prune(is_expired)
            await asyncio.sleep(period)


@app.post("/requests")
async def create_request(request: Request, background_tasks: BackgroundTasks):
    d = await request.json()
    try:
        api_query = d['api_query']
        ttl = d.get('ttl', settings.default_ttl)
    except KeyError:
        return {'detail': [{'loc': {d}, 'msg': 'missing api_query', 'type': 'error'}]},
    log.info('api_query: %s, ttl: %d', api_query, ttl)
    iid = make_image_id(api_query, ttl)
    log.info('id: %s', iid)
    r = cache.create_entry(iid, CacheEntryType.REQUEST, json.dumps(jsonable_encoder(api_query)))
    if r == CreationStatus.EXISTING:
        log.info('Entry %s already exists', iid)
    else:
        log.info('New Entry %s', iid)
    background_tasks.add_task(fetch_image, iid, api_query)
    return {'id': iid}


@app.get("/images/{image_id}")
def get_image(image_id: str):
    log.info('GET image %s', image_id)
    ts = expiration(image_id)
    if ts is None:
        log.info('GET %s: invalid ID', image_id)
        return JSONResponse(
            content={'detail': [{'loc': [image_id], 'msg': 'Invalid image ID', 'type': 'error'}]},
            status_code=400
        )
    if ts < datetime.now(timezone.utc):
        log.info('GET %s: expired ts: %s', image_id, ts.isoformat())
        return JSONResponse(
            content={'detail': [{'loc': [image_id], 'msg': 'Image not found', 'type': 'error'}]},
            status_code=404
        )
    while True:
        entry = cache.get_entry(image_id)
        if entry.status == EntryStatus.NOT_FOUND:
            return JSONResponse(
                content={'detail': [{'loc': [image_id], 'msg': 'Image not found', 'type': 'error'}]},
                status_code=404
            )
        if entry.status == EntryStatus.ACTIVE:
            if entry.type == CacheEntryType.IMAGE:
                img = pickle.loads(entry.data)
                return Response(content=img.image_data, media_type=img_type_to_media(img.image_type))
            if entry.type == CacheEntryType.ERROR_MSG:
                d = json.loads(entry.data.decode())
                return JSONResponse(status_code=d['status_code'], content=d['msgs'])
        if entry.status == EntryStatus.PENDING:
            log.debug('GET %s: still pending', image_id)
            sleep(settings.status_poll_period)
        else:
            log.error('GET %s: unknown entry status: %s', image_id, entry.status.value)
            return JSONResponse(
                content={'detail': [{'loc': [image_id],
                                     'msg': f'Internal error (unknown status: {entry.status.value}',
                                     'type': 'error'}
                                    ]},
                status_code=500
            )


@app.get("/favicon.ico")
async def get_favicon():
    return FileResponse(path='assets/kentik_favicon.ico')


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(CacheMinder(cache).run_main(settings.cache_maintenance_period))
import json
import logging
from pathlib import Path
from typing import Optional

import requests
import typer

Refologging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger()


def load_queries(dir="tests/data", pattern="*.json"):
    ret = []
    for f in sorted(Path(dir).glob(pattern)):
        log.info("Loading request from: %s", f)
        ret.append(json.load(f.open()))
    return ret


def run_requests(qs, url="http://127.0.0.1:8000"):
    api = requests.Session()
    ids = []
    log.info("Posting %d requests against %s", len(qs), url)
    for n, q in enumerate(qs):
        log.info("posting query: %d", n)
        r = api.post(f"{url}/requests", json=q)
        r.raise_for_status()
        i = r.json()["id"]
        log.info("query: %d got id: %s", n, i)
        ids.append(i)
    log.info("Requesting %d images", len(ids))
    for i in ids:
        u = f"{url}/image/{i}"
        log.info("requesting: %s", u)
        r = api.get(u)
        log.info(
            "got: status: %s type: %s length: %s", r.status_code, r.headers["content-type"], r.headers["content-length"]
        )


def main(
    url: Optional[str] = typer.Option("http://127.0.0.1", "--url", help="URL to test against"),
    test_dir: Optional[str] = typer.Option("tests/data", "--dir", help="Directory to load queries from"),
    pattern: Optional[str] = typer.Option("*.json", "--glob", help="Globbing pattern for request files"),
) -> None:

    queries = load_queries(dir=test_dir, pattern=pattern)
    run_requests(queries, url)


if __name__ == "__main__":
    typer.run(main)

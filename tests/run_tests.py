#!/usr/bin/env python3
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests
import typer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger()


class TestRunner:
    def __init__(self, url, directory, pattern):
        self._url = url
        self._api = requests.Session()
        self._queries = []
        log.info("Using URL: %s", url)
        for tid, f in enumerate(sorted(Path(directory).glob(pattern))):
            log.info("tid: %d loading request from: %s", tid, f)
            self._queries.append(json.load(f.open()))
        log.info("%d requests loaded", len(self._queries))

    def run_request(self, tid, q):
        log.info("tid: %d posting request", tid)
        r = self._api.post(f"{self._url}/requests", json=q)
        r.raise_for_status()
        i = r.json()["id"]
        log.info("tid: %d: got id: %s", tid, i)
        url = f"{self._url}/image/{i}"
        log.info("tid: %d requesting: %s", tid, url)
        r = self._api.get(url)
        log.info(
            "tid: %d got: status: %s type: %s length: %s",
            tid,
            r.status_code,
            r.headers["content-type"],
            r.headers["content-length"],
        )

    def run_all(self):
        log.info("Running tests")
        for n, q in enumerate(self._queries):
            self.run_request(n, q)

    def run_all_concurrently(self):
        log.info("Running tests concurrently")
        with ThreadPoolExecutor() as executor:
            executor.map(self.run_request, [n for n, _ in enumerate(self._queries)], self._queries)


def main(
    url: Optional[str] = typer.Option("http://127.0.0.1", "--url", help="URL to test against"),
    test_dir: Optional[str] = typer.Option("tests/data", "--dir", help="Directory to load requests from"),
    pattern: Optional[str] = typer.Option("*.json", "--glob", help="Globbing pattern for request files"),
    concurrent: bool = typer.Option(False, "--concurrent", help="Run requests concurrently"),
) -> None:

    runner = TestRunner(url, test_dir, pattern)
    if concurrent:
        runner.run_all_concurrently()
    else:
        runner.run_all()


if __name__ == "__main__":
    app = typer.Typer(add_completion=False)
    app.command()(main)
    app()

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import aiohttp
import httpx
import requests
from bs4 import BeautifulSoup
from lxml import html as lxml_html
from readability import Document
from selectolax.parser import HTMLParser
import trafilatura

from common import RESULTS, jsonl_write


PAGES = [
    {"id": "static", "path": "/static", "required": ["ORCHID-7429", "Agent Tool Evaluation"]},
    {"id": "malformed", "path": "/malformed", "required": ["ORCHID-7429"]},
    {"id": "unicode", "path": "/unicode", "required": ["兰花-7429", "ORCHID-7429"]},
    {"id": "large", "path": "/large", "required": ["ORCHID-7429"]},
    {"id": "redirect", "path": "/redirect", "required": ["ORCHID-7429"]},
    {"id": "gzip", "path": "/gzip", "required": ["ORCHID-7429"]},
    {"id": "dynamic", "path": "/dynamic", "required": ["COBALT-318"]},
]


def fetch(client: str, url: str) -> tuple[bytes, int]:
    if client == "requests":
        r = requests.get(url, timeout=10)
        return r.content, r.status_code
    if client == "httpx":
        with httpx.Client(follow_redirects=True, timeout=10) as c:
            r = c.get(url)
            return r.content, r.status_code
    if client == "curl":
        p = subprocess.run(["curl", "-L", "--compressed", "-sS", "-w", "\n%{http_code}", url], capture_output=True, timeout=15)
        body, status = p.stdout.rsplit(b"\n", 1)
        return body, int(status)
    if client == "wget":
        p = subprocess.run(["wget", "-qO-", url], capture_output=True, timeout=15)
        return p.stdout, 200 if p.returncode == 0 else 0
    raise KeyError(client)


def extract(name: str, raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if name == "raw":
        return text
    if name == "bs4":
        return BeautifulSoup(text, "lxml").get_text("\n", strip=True)
    if name == "lxml":
        return "\n".join(x.strip() for x in lxml_html.fromstring(text).itertext() if x.strip())
    if name == "readability":
        return BeautifulSoup(Document(text).summary(), "lxml").get_text("\n", strip=True)
    if name == "trafilatura":
        return trafilatura.extract(text, include_tables=True, include_formatting=False) or ""
    if name == "selectolax":
        tree = HTMLParser(text)
        for node in tree.css("script,style,noscript"):
            node.decompose()
        return tree.body.text(separator="\n", strip=True) if tree.body else tree.text()
    raise KeyError(name)


async def aiohttp_fetch(url: str) -> tuple[bytes, int]:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=10) as response:
            return await response.read(), response.status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else RESULTS
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    clients = ["requests", "httpx", "aiohttp", "curl", "wget"]
    extractors = ["raw", "bs4", "lxml", "readability", "trafilatura", "selectolax"]
    for repeat in range(args.repeats):
        for page in PAGES:
            url = args.base_url + page["path"]
            for client in clients:
                started = time.perf_counter()
                try:
                    raw, status = asyncio.run(aiohttp_fetch(url)) if client == "aiohttp" else fetch(client, url)
                    fetch_ms = (time.perf_counter() - started) * 1000
                    for extractor in extractors:
                        extract_started = time.perf_counter()
                        try:
                            output = extract(extractor, raw)
                            error = None
                        except Exception as exc:
                            output, error = "", repr(exc)
                        extract_ms = (time.perf_counter() - extract_started) * 1000
                        hits = sum(term in output for term in page["required"])
                        rows.append({
                            "environment": args.environment, "page": page["id"], "client": client,
                            "extractor": extractor, "repeat": repeat, "status": status,
                            "fetch_ms": fetch_ms, "extract_ms": extract_ms,
                            "total_ms": fetch_ms + extract_ms, "raw_bytes": len(raw),
                            "output_chars": len(output), "required_hits": hits,
                            "required_total": len(page["required"]), "recall": hits / len(page["required"]),
                            "error": error,
                        })
                except Exception as exc:
                    rows.append({
                        "environment": args.environment, "page": page["id"], "client": client,
                        "extractor": "fetch_error", "repeat": repeat, "status": 0,
                        "fetch_ms": (time.perf_counter() - started) * 1000, "extract_ms": 0,
                        "total_ms": (time.perf_counter() - started) * 1000, "raw_bytes": 0,
                        "output_chars": 0, "required_hits": 0, "required_total": len(page["required"]),
                        "recall": 0, "error": repr(exc),
                    })
    jsonl_write(output_dir / f"webfetch_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows), "clients": clients, "extractors": extractors}, indent=2))


if __name__ == "__main__":
    main()

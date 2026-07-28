from __future__ import annotations

import argparse
import asyncio
from collections import Counter
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


ARTICLE_TEXT = """
Agent Tool Evaluation
The canonical answer is ORCHID-7429.
Structured tools reduce ambiguity while preserving evidence.
Metrics metric value recall 0.93
grep query ORCHID-7429
"""

PAGES = [
    {"id": "static", "path": "/static", "required": ["ORCHID-7429", "Agent Tool Evaluation"], "expected": ARTICLE_TEXT},
    {"id": "malformed", "path": "/malformed", "required": ["ORCHID-7429"], "expected": ARTICLE_TEXT},
    {"id": "unicode", "path": "/unicode", "required": ["兰花-7429", "ORCHID-7429"], "expected": "工具评测 关键答案 兰花-7429 " + ARTICLE_TEXT},
    {"id": "large", "path": "/large", "required": ["ORCHID-7429"], "expected": ARTICLE_TEXT},
    {"id": "redirect", "path": "/redirect", "required": ["ORCHID-7429"], "expected": ARTICLE_TEXT},
    {"id": "gzip", "path": "/gzip", "required": ["ORCHID-7429"], "expected": ARTICLE_TEXT},
    {"id": "dynamic", "path": "/dynamic", "required": ["COBALT-318"], "expected": "Dynamic The dynamic answer is COBALT-318."},
]


def token_metrics(expected: str, output: str) -> tuple[float, float, float]:
    expected_tokens = Counter(re.findall(r"[\w.-]+", expected.lower()))
    output_tokens = Counter(re.findall(r"[\w.-]+", output.lower()))
    overlap = sum((expected_tokens & output_tokens).values())
    expected_count = sum(expected_tokens.values())
    output_count = sum(output_tokens.values())
    precision = overlap / output_count if output_count else 0.0
    recall = overlap / expected_count if expected_count else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


class PersistentFetchClients:
    def __init__(self) -> None:
        self.requests = requests.Session()
        self.httpx = httpx.Client(follow_redirects=True, timeout=10)

    def close(self) -> None:
        self.requests.close()
        self.httpx.close()


def fetch(client: str, url: str, persistent: PersistentFetchClients) -> tuple[bytes, int]:
    if client == "requests":
        r = requests.get(url, timeout=10)
        return r.content, r.status_code
    if client == "requests_session":
        r = persistent.requests.get(url, timeout=10)
        return r.content, r.status_code
    if client == "httpx":
        with httpx.Client(follow_redirects=True, timeout=10) as c:
            r = c.get(url)
            return r.content, r.status_code
    if client == "httpx_session":
        r = persistent.httpx.get(url)
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
        soup = BeautifulSoup(text, "lxml")
        for node in soup.select("script,style,noscript"):
            node.decompose()
        return soup.get_text("\n", strip=True)
    if name == "lxml":
        tree = lxml_html.fromstring(text)
        for node in tree.xpath("//script|//style|//noscript"):
            node.drop_tree()
        return "\n".join(x.strip() for x in tree.itertext() if x.strip())
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
    clients = ["requests", "requests_session", "httpx", "httpx_session", "aiohttp", "curl", "wget"]
    extractors = ["raw", "bs4", "lxml", "readability", "trafilatura", "selectolax"]
    persistent = PersistentFetchClients()
    try:
      for repeat in range(args.repeats):
        for page in PAGES:
          url = args.base_url + page["path"]
          for client in clients:
                started = time.perf_counter()
                try:
                    raw, status = asyncio.run(aiohttp_fetch(url)) if client == "aiohttp" else fetch(client, url, persistent)
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
                        content_precision, content_recall, content_f1 = token_metrics(page["expected"], output)
                        rows.append({
                            "environment": args.environment, "page": page["id"], "client": client,
                            "extractor": extractor, "repeat": repeat, "status": status,
                            "fetch_ms": fetch_ms, "extract_ms": extract_ms,
                            "total_ms": fetch_ms + extract_ms, "raw_bytes": len(raw),
                            "output_chars": len(output), "required_hits": hits,
                            "required_total": len(page["required"]), "recall": hits / len(page["required"]),
                            "content_precision": content_precision, "content_recall": content_recall,
                            "content_f1": content_f1,
                            "error": error,
                        })
                except Exception as exc:
                    rows.append({
                        "environment": args.environment, "page": page["id"], "client": client,
                        "extractor": "fetch_error", "repeat": repeat, "status": 0,
                        "fetch_ms": (time.perf_counter() - started) * 1000, "extract_ms": 0,
                        "total_ms": (time.perf_counter() - started) * 1000, "raw_bytes": 0,
                        "output_chars": 0, "required_hits": 0, "required_total": len(page["required"]),
                        "recall": 0, "content_precision": 0, "content_recall": 0, "content_f1": 0,
                        "error": repr(exc),
                    })
    finally:
        persistent.close()
    jsonl_write(output_dir / f"webfetch_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows), "clients": clients, "extractors": extractors}, indent=2))


if __name__ == "__main__":
    main()

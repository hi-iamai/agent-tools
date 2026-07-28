from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import aiohttp
import httpx
import requests

from common import RESULTS, jsonl_write


def requests_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    response = requests.get(url, timeout=timeout)
    return response.status_code, response.content


def httpx_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        return response.status_code, response.content


async def aiohttp_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=timeout) as response:
            return response.status, await response.read()


class PersistentClients:
    def __init__(self) -> None:
        self.requests = requests.Session()
        self.httpx = httpx.Client(follow_redirects=True, timeout=5)

    def close(self) -> None:
        self.requests.close()
        self.httpx.close()

    def get(self, client: str, url: str, timeout: float = 5) -> tuple[int, bytes]:
        if client == "requests_session":
            response = self.requests.get(url, timeout=timeout)
            return response.status_code, response.content
        if client == "httpx_session":
            response = self.httpx.get(url, timeout=timeout)
            return response.status_code, response.content
        raise KeyError(client)


def curl_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    proc = subprocess.run(
        ["curl", "-L", "--compressed", "-sS", "--max-time", str(timeout), "-w", "\n%{http_code}", url],
        capture_output=True,
        timeout=timeout + 2,
    )
    body, status = proc.stdout.rsplit(b"\n", 1)
    return int(status), body


def wget_get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    proc = subprocess.run(
        ["wget", "-qO-", "--timeout", str(int(timeout)), url],
        capture_output=True,
        timeout=timeout + 2,
    )
    return (200 if proc.returncode == 0 else 0), proc.stdout


def fetch(client: str, url: str, timeout: float = 5, persistent: PersistentClients | None = None) -> tuple[int, bytes]:
    if client.endswith("_session"):
        if persistent is None:
            raise RuntimeError("persistent client is required")
        return persistent.get(client, url, timeout)
    if client == "requests":
        return requests_get(url, timeout)
    if client == "httpx":
        return httpx_get(url, timeout)
    if client == "aiohttp":
        return asyncio.run(aiohttp_get(url, timeout))
    if client == "curl":
        return curl_get(url, timeout)
    if client == "wget":
        return wget_get(url, timeout)
    raise KeyError(client)


def pagination(client: str, base: str, persistent: PersistentClients) -> tuple[int, int, float]:
    page = 1
    items = 0
    amount = 0.0
    calls = 0
    while page:
        status, raw = fetch(client, f"{base}/api/page?page={page}", persistent=persistent)
        calls += 1
        if status != 200:
            raise RuntimeError(f"status={status}")
        payload = json.loads(raw)
        items += len(payload["items"])
        amount += sum(float(x["amount"]) for x in payload["items"])
        page = page + 1 if payload["next"] else 0
    return calls, items, amount


def rate_limit(client: str, base: str, persistent: PersistentClients) -> tuple[int, bool]:
    calls = 0
    while calls < 5:
        status, raw = fetch(client, f"{base}/api/rate-limit", persistent=persistent)
        calls += 1
        if status == 200:
            return calls, bool(json.loads(raw).get("ok"))
        if status == 429:
            time.sleep(1)
            continue
        break
    return calls, False


def concurrency(client: str, base: str, workers: int, requests_count: int, persistent: PersistentClients) -> tuple[float, int]:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(
            lambda _: fetch(client, f"{base}/api/page?page=1", persistent=persistent),
            range(requests_count),
        ))
    return (time.perf_counter() - started) * 1000, sum(status == 200 for status, _ in results)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--environment", default="windows")
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else RESULTS
    clients = ["requests", "requests_session", "httpx", "httpx_session", "aiohttp", "curl", "wget"]
    rows: list[dict[str, Any]] = []
    persistent = PersistentClients()
    try:
      for repeat in range(args.repeats):
        for client in clients:
            for scenario, path, expected in (
                ("json", "/api/page?page=1", "items"),
                ("gzip", "/api/gzip", "ORCHID-7429"),
                ("redirect", "/api/redirect", "items"),
                ("server_error", "/status/500", None),
            ):
                started = time.perf_counter()
                error = None
                try:
                    status, raw = fetch(client, args.base_url + path, persistent=persistent)
                    parsed = raw.decode("utf-8", errors="replace")
                    correct = expected in parsed if expected else status == 500
                except Exception as exc:
                    status, raw, correct, error = 0, b"", False, repr(exc)
                rows.append({
                    "environment": args.environment, "client": client, "scenario": scenario,
                    "repeat": repeat, "duration_ms": (time.perf_counter() - started) * 1000,
                    "status": status, "bytes": len(raw), "correct": correct, "error": error,
                })
            started = time.perf_counter()
            try:
                calls, items, amount = pagination(client, args.base_url, persistent)
                correct, error = calls == 3 and items == 9 and amount == 13.5, None
            except Exception as exc:
                calls, items, amount, correct, error = 0, 0, 0, False, repr(exc)
            rows.append({
                "environment": args.environment, "client": client, "scenario": "pagination",
                "repeat": repeat, "duration_ms": (time.perf_counter() - started) * 1000,
                "status": 200 if correct else 0, "calls": calls, "items": items,
                "amount": amount, "correct": correct, "error": error,
            })
            started = time.perf_counter()
            try:
                calls, ok = rate_limit(client, args.base_url, persistent)
                error = None
            except Exception as exc:
                calls, ok, error = 0, False, repr(exc)
            rows.append({
                "environment": args.environment, "client": client, "scenario": "rate_limit",
                "repeat": repeat, "duration_ms": (time.perf_counter() - started) * 1000,
                "status": 200 if ok else 0, "calls": calls, "correct": ok, "error": error,
            })
        for client in clients:
            for workers in (1, 4, 8):
                try:
                    duration_ms, succeeded = concurrency(client, args.base_url, workers, 16, persistent)
                    error = None
                except Exception as exc:
                    duration_ms, succeeded, error = 0, 0, repr(exc)
                rows.append({
                    "environment": args.environment, "client": client, "scenario": "concurrency",
                    "repeat": repeat, "workers": workers, "requests": 16,
                    "duration_ms": duration_ms, "succeeded": succeeded,
                    "throughput_rps": succeeded / (duration_ms / 1000) if duration_ms else 0,
                    "correct": succeeded == 16, "error": error,
                })
    finally:
        persistent.close()
    jsonl_write(output_dir / f"api_fetch_{args.environment}.jsonl", rows)
    print(json.dumps({"rows": len(rows), "clients": clients}, indent=2))


if __name__ == "__main__":
    main()

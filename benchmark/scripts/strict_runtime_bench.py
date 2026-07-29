from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import psutil

from strict_runtime_engine import (
    execute_serialized,
    search_async,
    search_sync,
    search_sync_cooperative,
    serialize_result,
)


PAYLOADS = {
    "1k": 1,
    "10k": 10,
    "100k": 100,
    "1m": 1000,
}
CONCURRENCIES = (1, 4, 8, 16)


def request_http(port: int, limit: int, delay_ms: int = 0, timeout: float = 30) -> bytes:
    url = "http://127.0.0.1:%d/search?%s" % (
        port,
        urllib.parse.urlencode({"query": "needle-common", "limit": limit, "delay_ms": delay_ms}),
    )
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def one_shot(server: Path, limit: int) -> bytes:
    return subprocess.run(
        [
            sys.executable, str(server), "--mode", "once",
            "--query", "needle-common", "--limit", str(limit),
        ],
        capture_output=True, check=True, timeout=60,
    ).stdout


class StdioClient:
    def __init__(self, server: Path):
        self.process = subprocess.Popen(
            [sys.executable, str(server), "--mode", "stdio"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        self.next_id = 1
        self.lock = threading.Lock()

    def call(self, limit: int, delay_ms: int = 0) -> bytes:
        with self.lock:
            request = {
                "id": self.next_id,
                "query": "needle-common",
                "limit": limit,
                "delay_ms": delay_ms,
            }
            self.next_id += 1
            assert self.process.stdin and self.process.stdout
            self.process.stdin.write(json.dumps(request).encode() + b"\n")
            self.process.stdin.flush()
            return self.process.stdout.readline()

    def close(self):
        self.process.terminate()
        self.process.wait(timeout=10)


async def direct_async(limit: int) -> bytes:
    return serialize_result(await search_async("needle-common", limit))


async def direct_to_thread(limit: int) -> bytes:
    return await asyncio.to_thread(execute_serialized, "needle-common", limit, 0)


class AsyncLoopClient:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def call(self, limit: int) -> bytes:
        return asyncio.run_coroutine_threadsafe(direct_async(limit), self.loop).result(timeout=60)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)


def timed_call(name: str, payload: str, repeat: int, function: Callable[[], bytes]) -> dict:
    started = time.perf_counter_ns()
    value = function()
    duration_us = (time.perf_counter_ns() - started) / 1000
    parsed = json.loads(value)
    result = parsed.get("result", parsed)
    return {
        "adapter": name,
        "suite": "payload",
        "payload": payload,
        "repeat": repeat,
        "duration_us": duration_us,
        "response_bytes": len(value),
        "count": result.get("count"),
        "correct": result.get("schema") == "strict-runtime-v1",
    }


def timed_engine_call(payload: str, repeat: int, limit: int) -> dict:
    started = time.perf_counter_ns()
    result = search_sync("needle-common", limit)
    duration_us = (time.perf_counter_ns() - started) / 1000
    value = serialize_result(result)
    return {
        "adapter": "direct_sync_engine_only",
        "suite": "payload",
        "payload": payload,
        "repeat": repeat,
        "duration_us": duration_us,
        "response_bytes": len(value),
        "count": result.get("count"),
        "correct": result.get("schema") == "strict-runtime-v1",
    }


async def mcp_suite(server: Path, python: str, output_rows: list[dict], repeats: int, http_port: int) -> dict:
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from mcp import Client, StdioServerParameters, stdio_client

    metadata = {}
    parameters = StdioServerParameters(
        command=python,
        args=[str(server), "--mode", "mcp-stdio"],
    )
    started = time.perf_counter()
    async with Client(stdio_client(parameters), mode="legacy") as client:
        metadata["mcp_stdio_init_ms"] = (time.perf_counter() - started) * 1000
        for payload, limit in PAYLOADS.items():
            for repeat in range(repeats):
                started_ns = time.perf_counter_ns()
                result = await client.call_tool("search", {"query": "needle-common", "limit": limit})
                duration_us = (time.perf_counter_ns() - started_ns) / 1000
                raw = json.dumps(result.model_dump(mode="json"), separators=(",", ":")).encode()
                output_rows.append({
                    "adapter": "mcp_stdio",
                    "suite": "payload",
                    "payload": payload,
                    "repeat": repeat,
                    "duration_us": duration_us,
                    "response_bytes": len(raw),
                    "count": limit,
                    "correct": not result.is_error,
                })
        started = time.perf_counter()
        for _ in range(64):
            result = await client.call_tool("search", {"query": "needle-common", "limit": 10})
            if result.is_error:
                raise RuntimeError("MCP STDIO tool error")
        duration = time.perf_counter() - started
        output_rows.append({
            "adapter": "mcp_stdio",
            "suite": "throughput",
            "concurrency": 1,
            "requests": 64,
            "duration_ms": duration * 1000,
            "throughput_rps": 64 / duration,
            "response_bytes": 0,
            "correct": True,
        })
    started = time.perf_counter()
    async with Client(f"http://127.0.0.1:{http_port}/mcp", mode="legacy") as client:
        metadata["mcp_http_init_ms"] = (time.perf_counter() - started) * 1000
        for payload, limit in PAYLOADS.items():
            for repeat in range(repeats):
                started_ns = time.perf_counter_ns()
                result = await client.call_tool("search", {"query": "needle-common", "limit": limit})
                duration_us = (time.perf_counter_ns() - started_ns) / 1000
                raw = json.dumps(result.model_dump(mode="json"), separators=(",", ":")).encode()
                output_rows.append({
                    "adapter": "mcp_http",
                    "suite": "payload",
                    "payload": payload,
                    "repeat": repeat,
                    "duration_us": duration_us,
                    "response_bytes": len(raw),
                    "count": limit,
                    "correct": not result.is_error,
                })
        for concurrency in CONCURRENCIES:
            semaphore = asyncio.Semaphore(concurrency)

            async def one():
                async with semaphore:
                    return await client.call_tool("search", {"query": "needle-common", "limit": 10})

            started = time.perf_counter()
            values = await asyncio.gather(*(one() for _ in range(64)))
            duration = time.perf_counter() - started
            output_rows.append({
                "adapter": "mcp_http",
                "suite": "throughput",
                "concurrency": concurrency,
                "requests": len(values),
                "duration_ms": duration * 1000,
                "throughput_rps": len(values) / duration,
                "response_bytes": 0,
                "correct": all(not value.is_error for value in values),
            })
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--throughput-requests", type=int, default=64)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    server = Path(__file__).with_name("strict_runtime_server.py")
    rows = []
    metadata = {
        "schema": "strict-runtime-v1",
        "payload_limits": PAYLOADS,
        "concurrencies": CONCURRENCIES,
        "repeats": args.repeats,
        "throughput_requests": args.throughput_requests,
    }

    started = time.perf_counter()
    stdio = StdioClient(server)
    stdio.call(1)
    metadata["persistent_stdio_init_ms"] = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    async_loop = AsyncLoopClient()
    async_loop.call(1)
    metadata["async_loop_init_ms"] = (time.perf_counter() - started) * 1000
    http_port = 8770
    mcp_port = 8771
    http_process = subprocess.Popen([args.python, str(server), "--mode", "http", "--port", str(http_port)])
    mcp_http_process = subprocess.Popen(
        [args.python, str(server), "--mode", "mcp-http", "--port", str(mcp_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    started = time.perf_counter()
    while True:
        try:
            request_http(http_port, 1, timeout=0.2)
            break
        except Exception:
            if time.perf_counter() - started > 10:
                raise
            time.sleep(0.05)
    metadata["persistent_http_init_ms"] = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    while True:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{mcp_port}/mcp", timeout=0.2)
        except urllib.error.HTTPError:
            break
        except Exception:
            if time.perf_counter() - started > 10:
                raise
            time.sleep(0.05)
    process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=16)
    started = time.perf_counter()
    process_pool.submit(execute_serialized, "needle-common", 1, 0).result(timeout=60)
    metadata["process_pool_init_ms"] = (time.perf_counter() - started) * 1000
    try:
        for payload, limit in PAYLOADS.items():
            for repeat in range(args.repeats):
                rows.append(timed_call("direct_sync", payload, repeat, lambda limit=limit: execute_serialized("needle-common", limit)))
                rows.append(timed_call("direct_async", payload, repeat, lambda limit=limit: asyncio.run(direct_async(limit))))
                rows.append(timed_call(
                    "direct_async_persistent_loop",
                    payload,
                    repeat,
                    lambda limit=limit: async_loop.call(limit),
                ))
                rows.append(timed_engine_call(payload, repeat, limit))
                rows.append(timed_call("direct_to_thread", payload, repeat, lambda limit=limit: asyncio.run(direct_to_thread(limit))))
                rows.append(timed_call(
                    "process_pool",
                    payload,
                    repeat,
                    lambda limit=limit: process_pool.submit(
                        execute_serialized, "needle-common", limit, 0
                    ).result(timeout=60),
                ))
                rows.append(timed_call("per_call_process", payload, repeat, lambda limit=limit: one_shot(server, limit)))
                rows.append(timed_call("persistent_stdio", payload, repeat, lambda limit=limit: stdio.call(limit)))
                rows.append(timed_call("persistent_http", payload, repeat, lambda limit=limit: request_http(http_port, limit)))

        metadata.update(asyncio.run(mcp_suite(server, args.python, rows, args.repeats, mcp_port)))

        adapters: dict[str, Callable[[int], bytes]] = {
            "direct_sync_threads": lambda limit: execute_serialized("needle-common", limit),
            "direct_async_persistent_loop": lambda limit: async_loop.call(limit),
            "persistent_http": lambda limit: request_http(http_port, limit),
            "per_call_process": lambda limit: one_shot(server, limit),
            "persistent_stdio": lambda limit: stdio.call(limit),
        }
        for adapter, function in adapters.items():
            for concurrency in CONCURRENCIES:
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = [
                        pool.submit(function, 10)
                        for _ in range(args.throughput_requests)
                    ]
                    values = [future.result(timeout=120) for future in futures]
                duration = time.perf_counter() - started
                rows.append({
                    "adapter": adapter,
                    "suite": "throughput",
                    "concurrency": concurrency,
                    "requests": len(values),
                    "duration_ms": duration * 1000,
                    "throughput_rps": len(values) / duration,
                    "response_bytes": sum(len(value) for value in values),
                    "correct": all(bool(value) for value in values),
                })
        for concurrency in CONCURRENCIES:
            started = time.perf_counter()
            values = []
            pending = []
            for _ in range(args.throughput_requests):
                pending.append(process_pool.submit(execute_serialized, "needle-common", 10, 0))
                if len(pending) >= concurrency:
                    values.extend(future.result(timeout=120) for future in pending)
                    pending.clear()
            values.extend(future.result(timeout=120) for future in pending)
            duration = time.perf_counter() - started
            rows.append({
                "adapter": "process_pool",
                "suite": "throughput",
                "concurrency": concurrency,
                "requests": len(values),
                "duration_ms": duration * 1000,
                "throughput_rps": len(values) / duration,
                "response_bytes": sum(len(value) for value in values),
                "correct": all(bool(value) for value in values),
            })

        fault_rows = []
        started = time.perf_counter()
        try:
            request_http(http_port, 10, delay_ms=1000, timeout=0.1)
            timed_out = False
        except Exception:
            timed_out = True
        fault_rows.append({
            "case": "http_timeout",
            "success": timed_out,
            "duration_ms": (time.perf_counter() - started) * 1000,
        })

        cancel_event = threading.Event()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            started = time.perf_counter()
            future = executor.submit(
                search_sync_cooperative,
                "needle-common",
                10,
                1000,
                cancel_event,
            )
            time.sleep(0.1)
            cancel_event.set()
            try:
                future.result(timeout=2)
                cancelled = False
            except BaseException:
                cancelled = True
            fault_rows.append({
                "case": "cooperative_thread_cancel",
                "success": cancelled,
                "duration_ms": (time.perf_counter() - started) * 1000,
            })

        process_cancel_pool = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        started = time.perf_counter()
        process_future = process_cancel_pool.submit(
            execute_serialized, "needle-common", 10, 1000
        )
        time.sleep(0.1)
        cancel_returned = process_future.cancel()
        process_cancel_pool.shutdown(wait=True, cancel_futures=True)
        fault_rows.append({
            "case": "process_future_cancel_after_start",
            "success": not cancel_returned,
            "duration_ms": (time.perf_counter() - started) * 1000,
            "note": "running ProcessPool task cannot be cancelled cooperatively",
        })
        started = time.perf_counter()
        healthy = bool(request_http(http_port, 1))
        fault_rows.append({
            "case": "http_after_timeout",
            "success": healthy,
            "duration_ms": (time.perf_counter() - started) * 1000,
        })

        crash_started = time.perf_counter()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{http_port}/crash", timeout=5)
        except Exception:
            pass
        http_process.wait(timeout=10)
        crashed = http_process.poll() is not None
        http_process = subprocess.Popen(
            [args.python, str(server), "--mode", "http", "--port", str(http_port)]
        )
        restart_wait_started = time.perf_counter()
        while True:
            try:
                recovered_http = bool(request_http(http_port, 1, timeout=0.2))
                break
            except Exception:
                if time.perf_counter() - restart_wait_started > 10:
                    recovered_http = False
                    break
                time.sleep(0.05)
        fault_rows.append({
            "case": "http_crash_restart",
            "success": crashed and recovered_http,
            "duration_ms": (time.perf_counter() - crash_started) * 1000,
        })

        crash_worker = StdioClient(server)
        crash_worker.process.kill()
        crash_worker.process.wait(timeout=10)
        restarted = StdioClient(server)
        started = time.perf_counter()
        recovered = bool(restarted.call(1))
        fault_rows.append({
            "case": "stdio_restart",
            "success": recovered,
            "duration_ms": (time.perf_counter() - started) * 1000,
        })
        restarted.close()

        process = psutil.Process(os.getpid())
        metadata["driver_peak_rss_bytes"] = process.memory_info().rss
        (output / "strict_runtime_raw.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8",
        )
        (output / "strict_runtime_faults.json").write_text(
            json.dumps(fault_rows, indent=2),
            encoding="utf-8",
        )
        (output / "strict_runtime_meta.json").write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"rows": len(rows), "faults": fault_rows, "meta": metadata}, indent=2))
    finally:
        stdio.close()
        async_loop.close()
        process_pool.shutdown(wait=True, cancel_futures=True)
        http_process.terminate()
        mcp_http_process.terminate()
        http_process.wait(timeout=10)
        mcp_http_process.wait(timeout=10)


if __name__ == "__main__":
    main()

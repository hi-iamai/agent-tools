from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass


SCHEMA_VERSION = "strict-runtime-v1"
RECORD_COUNT = 4096
TEXT_SIZE = 896


def _make_record(index: int) -> dict[str, object]:
    marker = "needle-common"
    if index < 32:
        marker += " needle-rare"
    padding = (f" record-{index:05d} " + "abcdefghijklmnopqrstuvwxyz0123456789 ") * 32
    return {
        "id": index,
        "text": (marker + padding)[:TEXT_SIZE],
    }


CORPUS = tuple(_make_record(index) for index in range(RECORD_COUNT))


def search_sync(query: str, limit: int, delay_ms: int = 0) -> dict[str, object]:
    if delay_ms:
        time.sleep(delay_ms / 1000)
    matches = []
    total = 0
    for record in CORPUS:
        if query in str(record["text"]):
            total += 1
            if len(matches) < limit:
                matches.append(record)
    return {
        "schema": SCHEMA_VERSION,
        "query": query,
        "total": total,
        "count": len(matches),
        "truncated": total > len(matches),
        "matches": matches,
    }


def search_sync_cooperative(
    query: str,
    limit: int,
    delay_ms: int = 0,
    cancel_event=None,
) -> dict[str, object]:
    if delay_ms:
        remaining = delay_ms / 1000
        while remaining > 0:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
            step = min(0.01, remaining)
            time.sleep(step)
            remaining -= step
    matches = []
    total = 0
    for index, record in enumerate(CORPUS):
        if cancel_event is not None and index % 64 == 0 and cancel_event.is_set():
            raise asyncio.CancelledError
        if query in str(record["text"]):
            total += 1
            if len(matches) < limit:
                matches.append(record)
    return {
        "schema": SCHEMA_VERSION,
        "query": query,
        "total": total,
        "count": len(matches),
        "truncated": total > len(matches),
        "matches": matches,
    }


async def search_async(query: str, limit: int, delay_ms: int = 0) -> dict[str, object]:
    if delay_ms:
        await asyncio.sleep(delay_ms / 1000)
    return search_sync(query, limit, 0)


def serialize_result(result: dict[str, object]) -> bytes:
    return json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def execute_serialized(query: str, limit: int, delay_ms: int = 0) -> bytes:
    return serialize_result(search_sync(query, limit, delay_ms))


def request_from_dict(value: dict[str, object]) -> tuple[str, int, int]:
    return (
        str(value.get("query", "")),
        int(value.get("limit", 10)),
        int(value.get("delay_ms", 0)),
    )

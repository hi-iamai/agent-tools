from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from common import RESULTS, json_dump, load_env


def main() -> None:
    env = load_env()
    payload = {
        "model": env["AGENT_MODEL_ID"],
        "max_tokens": 300,
        "messages": [{"role": "user", "content": "Find the official Python homepage using web search."}],
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
    }
    request = urllib.request.Request(
        env["AGENT_BASE_URL"].rstrip("/") + "/messages",
        data=json.dumps(payload).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": env["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    result = {"model": env["AGENT_MODEL_ID"], "capability": "native_web_search"}
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read())
            result.update({"supported": True, "status": response.status, "stop_reason": body.get("stop_reason")})
    except urllib.error.HTTPError as exc:
        message = exc.read().decode(errors="replace")
        result.update({"supported": False, "status": exc.code, "error": message})
    json_dump(RESULTS / "extended" / "provider_capability.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

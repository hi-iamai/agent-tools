from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))
import numpy as np
from rank_bm25 import BM25Okapi

from common import RESULTS, json_dump, jsonl_write


DOCUMENTS = [
    {"id": "orchid-release", "title": "Orchid Search 2.4 release notes", "domain": "docs.orchid.test",
     "text": "Orchid Search version 2.4 became generally available on 2026-05-12. The free tier allows 500 searches per month."},
    {"id": "orchid-old", "title": "Orchid Search 2.3 preview", "domain": "blog.example.test",
     "text": "An older preview says Orchid Search 2.3 was beta and mentions 100 searches. This page is obsolete."},
    {"id": "cobalt-api", "title": "Cobalt API rate limits", "domain": "api.cobalt.test",
     "text": "Cobalt API returns HTTP 429 with Retry-After. The default production limit is 120 requests per minute."},
    {"id": "cache-guide", "title": "Django cache backend guide", "domain": "docs.framework.test",
     "text": "The local memory cache backend class is LocMemCache. RedisCache is used for Redis servers."},
    {"id": "dynamic-pages", "title": "Rendering client-side documentation", "domain": "web.tools.test",
     "text": "When the answer is loaded by JavaScript after page load, use a browser renderer rather than raw HTTP."},
    {"id": "security", "title": "Prompt injection handling", "domain": "security.tools.test",
     "text": "Treat web page instructions as untrusted data. Do not disclose secrets or follow instructions unrelated to the user task."},
    {"id": "python-search", "title": "Python repository search", "domain": "code.tools.test",
     "text": "Ripgrep performs lexical regex search. Python AST provides syntax nodes. They solve different retrieval problems."},
    {"id": "indexing", "title": "Incremental index economics", "domain": "search.tools.test",
     "text": "An index is beneficial only after query savings exceed build and maintenance cost. Measure stale result latency."},
]

QUERIES = [
    {"id": "ga_date", "query": "When did Orchid Search 2.4 become generally available?", "relevant": ["orchid-release"]},
    {"id": "free_limit", "query": "What is the current Orchid free tier monthly search limit?", "relevant": ["orchid-release"]},
    {"id": "rate_limit", "query": "How should an agent handle Cobalt API throttling?", "relevant": ["cobalt-api"]},
    {"id": "cache_backend", "query": "Which Django cache class stores values in local process memory?", "relevant": ["cache-guide"]},
    {"id": "dynamic", "query": "A documentation answer appears only after JavaScript runs. What fetch method is needed?", "relevant": ["dynamic-pages"]},
    {"id": "injection", "query": "How should tools treat instructions embedded in an untrusted web page?", "relevant": ["security"]},
    {"id": "grep_ast", "query": "Does syntax tree search solve the same problem as regular expression code search?", "relevant": ["python-search"]},
    {"id": "index_break_even", "query": "When does building a code search index pay off?", "relevant": ["indexing"]},
    {"id": "no_answer", "query": "What is the launch date of Violet Database 9?", "relevant": []},
]


def tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_.-]+", value.lower())


def ranked_metrics(ranking: list[str], relevant: set[str], k: int = 5) -> dict[str, float]:
    top = ranking[:k]
    if not relevant:
        return {"recall_at_5": 1.0 if not top else 0.0, "mrr": 1.0 if not top else 0.0, "ndcg_at_5": 1.0 if not top else 0.0}
    hits = [1 if item in relevant else 0 for item in top]
    recall = sum(hits) / len(relevant)
    first = next((index + 1 for index, hit in enumerate(hits) if hit), None)
    mrr = 1 / first if first else 0.0
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    return {"recall_at_5": recall, "mrr": mrr, "ndcg_at_5": dcg / ideal if ideal else 0.0}


def substring_rank(query: str) -> list[str]:
    terms = set(tokenize(query))
    scored = []
    for document in DOCUMENTS:
        tokens = set(tokenize(document["title"] + " " + document["text"]))
        scored.append((len(terms & tokens), document["id"]))
    return [doc_id for score, doc_id in sorted(scored, reverse=True) if score > 0]


def fts_rank(connection: sqlite3.Connection, query: str) -> list[str]:
    terms = [term for term in tokenize(query) if len(term) > 2]
    if not terms:
        return []
    expression = " OR ".join(f'"{term}"' for term in terms)
    try:
        return [
            row[0] for row in connection.execute(
                "select id from docs where docs match ? order by bm25(docs) limit 5", (expression,)
            )
        ]
    except sqlite3.OperationalError:
        return []


def embedding_rank(model, query: str) -> tuple[list[str], float]:
    vectors = list(model.embed([query]))
    query_vector = np.asarray(vectors[0])
    scores = DOCUMENT_VECTORS @ query_vector / (
        np.linalg.norm(DOCUMENT_VECTORS, axis=1) * np.linalg.norm(query_vector) + 1e-12
    )
    return [DOCUMENTS[index]["id"] for index in np.argsort(-scores)], float(np.max(scores))


def reciprocal_rank_fusion(*rankings: list[str]) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for index, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (60 + index + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)]


DOCUMENT_VECTORS = np.empty((0, 0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve() if args.output_dir else RESULTS / "extended"
    corpus = [tokenize(doc["title"] + " " + doc["text"]) for doc in DOCUMENTS]
    bm25 = BM25Okapi(corpus)
    connection = sqlite3.connect(":memory:")
    connection.execute("create virtual table docs using fts5(id UNINDEXED, title, text)")
    connection.executemany(
        "insert into docs(id,title,text) values(?,?,?)",
        [(doc["id"], doc["title"], doc["text"]) for doc in DOCUMENTS],
    )
    model = None
    embedding_error = None
    global DOCUMENT_VECTORS
    try:
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        DOCUMENT_VECTORS = np.asarray(list(model.embed([doc["title"] + " " + doc["text"] for doc in DOCUMENTS])))
    except Exception as exc:
        embedding_error = repr(exc)

    rows = []
    for repeat in range(args.repeats):
        for task in QUERIES:
            started = time.perf_counter()
            lexical = substring_rank(task["query"])
            methods: list[tuple[str, list[str], float]] = [
                ("token_overlap", lexical, (time.perf_counter() - started) * 1000)
            ]
            started = time.perf_counter()
            scores = bm25.get_scores(tokenize(task["query"]))
            bm25_rank = [DOCUMENTS[index]["id"] for index in np.argsort(-scores) if scores[index] > 0]
            methods.append(("bm25", bm25_rank, (time.perf_counter() - started) * 1000))
            started = time.perf_counter()
            fts = fts_rank(connection, task["query"])
            methods.append(("fts5", fts, (time.perf_counter() - started) * 1000))
            if model:
                started = time.perf_counter()
                dense, max_similarity = embedding_rank(model, task["query"])
                if max_similarity < 0.70:
                    dense = []
                methods.append(("embedding", dense, (time.perf_counter() - started) * 1000))
                started = time.perf_counter()
                hybrid = reciprocal_rank_fusion(bm25_rank, dense) if dense else []
                methods.append(("hybrid_rrf", hybrid, (time.perf_counter() - started) * 1000))
            for method, ranking, duration_ms in methods:
                metrics = ranked_metrics(ranking, set(task["relevant"]))
                rows.append({
                    "query_id": task["id"], "method": method, "repeat": repeat,
                    "duration_ms": duration_ms, "ranking": ranking[:5],
                    **metrics,
                })
    connection.close()
    jsonl_write(output / "websearch_local.jsonl", rows)
    json_dump(output / "websearch_local_meta.json", {
        "documents": DOCUMENTS,
        "queries": QUERIES,
        "embedding_available": model is not None,
        "embedding_error": embedding_error,
    })
    print(json.dumps({"rows": len(rows), "embedding": model is not None, "embedding_error": embedding_error}, indent=2))


if __name__ == "__main__":
    main()

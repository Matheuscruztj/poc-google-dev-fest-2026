"""Measure local chat latency and Ollama token usage with and without RAG."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
import time
from typing import Any

QUESTIONS = [
    "Como posso pedir recursos de acessibilidade para acompanhar as palestras?",
    "Quantas reservas de sessões posso manter ao mesmo tempo?",
    "Em que data e fuso horário acontece o evento?",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("plain", "hybrid"), required=True)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1 or args.repeat > 10:
        raise ValueError("--repeat precisa ficar entre 1 e 10.")
    os.environ["EVENTOPS_AGENT_MODE"] = "local"
    os.environ["EVENTOPS_RAG_MODE"] = "hybrid" if args.mode == "hybrid" else "lexical"
    if args.mode == "hybrid" and not os.environ.get("EVENTOPS_RAG_DATABASE_URL"):
        raise ValueError("Defina EVENTOPS_RAG_DATABASE_URL para benchmark híbrido.")
    database_dir = tempfile.TemporaryDirectory(prefix="eventops-rag-chat-bench-")
    os.environ["EVENTOPS_DATABASE"] = f"{database_dir.name}/eventops.sqlite3"

    from fastapi.testclient import TestClient

    from app.main import app

    rows: list[dict[str, Any]] = []
    for repeat in range(args.repeat):
        for question in QUESTIONS:
            started = time.perf_counter()
            with TestClient(app) as client:
                response = client.post(
                    "/api/chat",
                    headers={"Origin": "http://testserver"},
                    json={"message": question, "architecture": "single"},
                )
            wall_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            payload = response.json()
            trace = payload.get("trace", {})
            rows.append(
                {
                    "repeat": repeat + 1,
                    "question": question,
                    "wall_ms": round(wall_ms, 2),
                    "agent_duration_ms": trace.get("duration_ms"),
                    "input_tokens": trace.get("input_tokens"),
                    "output_tokens": trace.get("output_tokens"),
                    "sources": len(payload.get("sources", [])),
                    "error": payload.get("error"),
                    "raw_output_preview": str(trace.get("raw_output") or "")[:300]
                    if payload.get("error")
                    else None,
                }
            )
    input_tokens = [row["input_tokens"] for row in rows if isinstance(row["input_tokens"], int)]
    output_tokens = [row["output_tokens"] for row in rows if isinstance(row["output_tokens"], int)]
    latencies = [row["wall_ms"] for row in rows]
    rag_index = getattr(app.state, "rag_index", None)
    report = {
        "mode": args.mode,
        "agent_mode": "local",
        "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
        "context_length": int(os.environ.get("OLLAMA_CONTEXT_LENGTH", "8192")),
        "embedding_model": os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text:latest")
        if args.mode == "hybrid"
        else None,
        "repeat": args.repeat,
        "requests": len(rows),
        "summary": {
            "wall_p50_ms": round(statistics.median(latencies), 2),
            "wall_p95_ms": round(
                sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)], 2
            ),
            "input_tokens_total": sum(input_tokens),
            "input_tokens_per_request_avg": round(statistics.mean(input_tokens), 2)
            if input_tokens
            else None,
            "output_tokens_total": sum(output_tokens),
            "output_tokens_per_request_avg": round(statistics.mean(output_tokens), 2)
            if output_tokens
            else None,
            "estimated_api_cost": 0,
            "local_compute_cost": "not measured",
        },
        "indexing_metrics": (
            {
                "indexed_embeddings": rag_index.metrics.indexed_embeddings,
                "indexing_seconds": round(rag_index.metrics.indexing_seconds, 3),
                "embedding_failures": rag_index.embeddings.metrics.embedding_failures,
                "embedding_requests": rag_index.embeddings.metrics.embedding_requests,
                "embedding_query_requests": rag_index.metrics.query_embeddings,
                "embedding_cache_hits": rag_index.embeddings.metrics.embedding_cache_hits,
                "embedding_tokens": rag_index.embeddings.metrics.embedding_tokens,
                "embedding_inference_ms": round(
                    rag_index.embeddings.metrics.embedding_duration_ms, 2
                ),
                "vector_query_seconds": round(rag_index.metrics.query_seconds, 3),
                "vector_fallbacks": rag_index.metrics.vector_fallbacks,
            }
            if rag_index is not None
            else None
        ),
        "requests_detail": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    database_dir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

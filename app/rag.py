"""Local hybrid FAQ retrieval backed by PostgreSQL/pgvector and Ollama embeddings."""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from urllib.request import Request, urlopen

from app.faq import Chunk, load_chunks, search_faq_lexical

EMBEDDING_PROVIDER = "ollama"
EMBEDDING_MODEL = "nomic-embed-text:latest"
EMBEDDING_DIMENSION = 768
EMBEDDING_VERSION = "eventops-faq-embed-v1"
SIMILARITY_THRESHOLD = 0.65
HYBRID_LEXICAL_THRESHOLD = 0.34


@dataclass
class RagMetrics:
    embedding_requests: int = 0
    embedding_failures: int = 0
    embedding_cache_hits: int = 0
    embedding_tokens: int = 0
    embedding_duration_ms: float = 0.0
    indexing_seconds: float = 0.0
    query_seconds: float = 0.0
    indexed_embeddings: int = 0
    query_embeddings: int = 0
    vector_fallbacks: int = 0


class OllamaEmbeddings:
    """Bounded, local-only embedding client with a small in-process text cache."""

    def __init__(self, base_url: str, model: str = EMBEDDING_MODEL, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.metrics = RagMetrics()
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    def embed(self, text: str) -> list[float]:
        key = f"{self.model}:{text}"
        if key in self._cache:
            self.metrics.embedding_cache_hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        if len(text) > 8_000:
            raise ValueError("Texto excede o limite local de embedding (8000 caracteres).")
        body = json.dumps({"model": self.model, "input": text}).encode()
        request = Request(
            f"{self.base_url}/api/embed",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self.metrics.embedding_requests += 1
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
            vector = payload["embeddings"][0]
            if len(vector) != EMBEDDING_DIMENSION or not all(
                isinstance(value, (int, float)) for value in vector
            ):
                raise ValueError("O modelo de embedding retornou dimensão incompatível.")
        except Exception:
            self.metrics.embedding_failures += 1
            raise
        result = [float(value) for value in vector]
        prompt_tokens = payload.get("prompt_eval_count")
        duration_ns = payload.get("total_duration")
        if isinstance(prompt_tokens, int):
            self.metrics.embedding_tokens += prompt_tokens
        if isinstance(duration_ns, int):
            self.metrics.embedding_duration_ms += duration_ns / 1_000_000
        self._cache[key] = result
        if len(self._cache) > 256:
            self._cache.popitem(last=False)
        return result


class PgVectorFAQ:
    """Versioned vector index; every sync is transactional and removes stale chunks."""

    def __init__(self, database_url: str, embeddings: OllamaEmbeddings) -> None:
        self.database_url = database_url
        self.embeddings = embeddings
        self.metrics = RagMetrics()

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=3)

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS faq_vector_index (
                    index_id text PRIMARY KEY, provider text NOT NULL, model text NOT NULL,
                    version text NOT NULL, dimensions integer NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS faq_vector_chunks (
                    chunk_id text PRIMARY KEY, document text NOT NULL, section text NOT NULL,
                    text text NOT NULL, version integer NOT NULL, updated_at text NOT NULL,
                    status text NOT NULL, trusted boolean NOT NULL, valid_from text,
                    valid_until text, conflict_group text, embedding vector(768) NOT NULL,
                    content_hash text NOT NULL
                )"""
            )
            existing = connection.execute(
                "SELECT provider, model, version, dimensions "
                "FROM faq_vector_index WHERE index_id='faq'"
            ).fetchone()
            expected = (
                EMBEDDING_PROVIDER,
                self.embeddings.model,
                EMBEDDING_VERSION,
                EMBEDDING_DIMENSION,
            )
            if existing is None:
                connection.execute(
                    "INSERT INTO faq_vector_index VALUES ('faq', %s, %s, %s, %s)", expected
                )
            elif tuple(existing.values()) != expected:
                raise RuntimeError(
                    "Índice vetorial incompatível; não altere provider/modelo/dimensão "
                    "sem reindexação explícita."
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS faq_vector_chunks_embedding_idx "
                "ON faq_vector_chunks USING hnsw (embedding vector_cosine_ops)"
            )

    def sync(self, chunks: list[Chunk] | None = None) -> int:
        import hashlib

        started = time.monotonic()
        requests_before = self.embeddings.metrics.embedding_requests
        current = chunks if chunks is not None else load_chunks()
        rows = []
        for chunk in current:
            chunk_id = f"{chunk.document}::{chunk.section}"
            digest = hashlib.sha256(
                json.dumps(asdict(chunk), ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            rows.append((chunk_id, chunk, digest))
        with self._connect() as connection:
            index = connection.execute(
                "SELECT provider, model, version, dimensions "
                "FROM faq_vector_index WHERE index_id='faq'"
            ).fetchone()
            expected = (
                EMBEDDING_PROVIDER,
                self.embeddings.model,
                EMBEDDING_VERSION,
                EMBEDDING_DIMENSION,
            )
            if index is None or tuple(index.values()) != expected:
                raise RuntimeError(
                    "Índice vetorial ausente ou incompatível com o modelo configurado."
                )
            existing = {
                row["chunk_id"]: row["content_hash"]
                for row in connection.execute(
                    "SELECT chunk_id, content_hash FROM faq_vector_chunks"
                )
            }
            for chunk_id, chunk, digest in rows:
                if existing.get(chunk_id) == digest:
                    continue
                vector = self.embeddings.embed(chunk.text)
                connection.execute(
                    """INSERT INTO faq_vector_chunks VALUES
                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)
                    ON CONFLICT (chunk_id) DO UPDATE SET document=excluded.document,
                    section=excluded.section, text=excluded.text, version=excluded.version,
                    updated_at=excluded.updated_at, status=excluded.status,
                    trusted=excluded.trusted,
                    valid_from=excluded.valid_from, valid_until=excluded.valid_until,
                    conflict_group=excluded.conflict_group, embedding=excluded.embedding,
                    content_hash=excluded.content_hash""",
                    (
                        chunk_id,
                        chunk.document,
                        chunk.section,
                        chunk.text,
                        chunk.version,
                        chunk.updated_at,
                        chunk.status,
                        chunk.trusted,
                        chunk.valid_from,
                        chunk.valid_until,
                        chunk.conflict_group,
                        "[" + ",".join(str(value) for value in vector) + "]",
                        digest,
                    ),
                )
            ids = [item[0] for item in rows]
            if ids:
                connection.execute(
                    "DELETE FROM faq_vector_chunks WHERE NOT (chunk_id = ANY(%s))", (ids,)
                )
            else:
                connection.execute("DELETE FROM faq_vector_chunks")
        self.metrics.indexing_seconds += time.monotonic() - started
        self.metrics.indexed_embeddings += (
            self.embeddings.metrics.embedding_requests - requests_before
        )
        return len(rows)

    def search(self, question: str, limit: int = 3) -> list[dict[str, object]]:
        started = time.monotonic()
        requests_before = self.embeddings.metrics.embedding_requests
        vector = self.embeddings.embed(question)
        self.metrics.query_embeddings += (
            self.embeddings.metrics.embedding_requests - requests_before
        )
        literal = "[" + ",".join(str(value) for value in vector) + "]"
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT document, section, text AS excerpt, version, updated_at, status,
                valid_from, valid_until, conflict_group, trusted,
                1 - (embedding <=> %s::vector) AS score
                FROM faq_vector_chunks WHERE status='current' AND trusted=true
                AND conflict_group IS NULL
                AND (valid_from IS NULL OR valid_from <= %s)
                AND (valid_until IS NULL OR valid_until >= %s)
                ORDER BY embedding <=> %s::vector, document, section LIMIT %s""",
                (literal, date.today().isoformat(), date.today().isoformat(), literal, limit),
            ).fetchall()
        self.metrics.query_seconds += time.monotonic() - started
        return [
            {**dict(row), "excerpt": str(row["excerpt"])[:700]}
            for row in rows
            if float(row["score"]) >= SIMILARITY_THRESHOLD
        ]


def search_hybrid(question: str, index: PgVectorFAQ, limit: int = 3) -> dict[str, object]:
    """Merge lexical and vector candidates; lexical remains available on vector outages."""
    lexical = search_faq_lexical(question)
    if not question.strip():
        return lexical
    try:
        semantic = index.search(question, limit)
    except Exception:
        index.metrics.vector_fallbacks += 1
        return lexical
    lexical_sources = lexical.get("sources", [])
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    eligible_lexical = [
        source
        for source in (lexical_sources if isinstance(lexical_sources, list) else [])
        if isinstance(source, dict)
        and isinstance(source.get("score"), (int, float))
        and float(source["score"]) >= HYBRID_LEXICAL_THRESHOLD
    ]
    for rank, source in enumerate(eligible_lexical, 1):
        result_source = dict(source)
        result_source["score"] = 1 / rank
        by_key[(str(source["document"]), str(source["section"]))] = result_source
    for rank, source in enumerate(semantic, 1):
        key = (str(source["document"]), str(source["section"]))
        previous = by_key.get(key)
        if previous is None:
            semantic_source = dict(source)
            semantic_source["score"] = 1 / rank
            by_key[key] = semantic_source
        else:
            previous_score = previous.get("score", 0)
            lexical_rrf = float(previous_score) if isinstance(previous_score, (int, float)) else 0
            previous["score"] = lexical_rrf + (1 / rank)

    def stable_rank(row: dict[str, object]) -> tuple[float, str, str]:
        score = row.get("score", 0)
        numeric_score = float(score) if isinstance(score, (int, float)) else 0
        return (-numeric_score, str(row["document"]), str(row["section"]))

    ranked = sorted(by_key.values(), key=stable_rank)[:limit]
    if not ranked:
        return {
            "answer": "Não localizei regra suficiente para responder com segurança.",
            "sources": [],
        }
    return {
        "answer": (
            "Encontrei estes trechos relevantes no guia do evento. "
            "Confira as fontes antes de tomar uma decisão."
        ),
        "sources": ranked,
    }

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi
export EVENTOPS_DATABASE="${EVENTOPS_DATABASE:-$ROOT/var/eventops.sqlite3}"

"$PYTHON_BIN" - <<'PY'
from app.data_validation import load_session_seed, validate_faq_catalog
from app.faq import load_chunks, search_faq
from app.storage import Storage

records = load_session_seed()
documents = validate_faq_catalog()
storage = Storage(__import__("os").environ["EVENTOPS_DATABASE"])
inserted = storage.seed_sessions_if_empty(records)
sessions = storage.list_sessions()
if len(sessions) != len(records):
    raise SystemExit(f"Seed incompleto: {len(sessions)} sessões; esperado {len(records)}")
chunks = load_chunks()
faq = search_faq("Quais são as regras de acessibilidade?")
if not faq["sources"]:
    raise SystemExit("FAQ lexical não encontrou fonte para a pergunta de validação.")
print(f"Seed local OK: {len(sessions)} sessões ({'criado' if inserted else 'já existia'}).")
print(f"FAQ/RAG lexical OK: {len(documents)} documentos, {len(chunks)} chunks.")
print(f"Banco: {storage.path}")
print("RAG semântico requer perfil local pgvector + Ollama; este script não os provisiona.")
PY

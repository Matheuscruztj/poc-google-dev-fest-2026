#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Deploying a new Cloud Run revision seeds the synthetic session catalog on
# startup. FAQ documents and the lexical RAG index are bundled in the image.
"$ROOT/scripts/cloud/cloud-up.sh"
export EVENTOPS_BASE_URL="$(cat "$ROOT/infra/terraform/service-url.txt")"

python3 - <<'PY'
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request

base = os.environ["EVENTOPS_BASE_URL"].rstrip("/")
cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def request(path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Origin": base} if payload and path == "/api/chat" else {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with opener.open(req, timeout=45) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise SystemExit(f"Falha em {path}: {exc}") from exc


health = request("/health")
assert health.get("status") == "ok" and health.get("agent_mode") == "offline", health
sessions = request("/api/sessions")["sessions"]
assert len(sessions) >= 20, f"Esperava 20 sessões; recebi {len(sessions)}"
schedule = request("/api/schedule", {"track": "IA", "limit": 3})
assert schedule.get("sessions"), schedule
faq = request("/api/faq", {"question": "Quais são as regras de acessibilidade?"})
assert faq.get("sources"), faq
single = request(
    "/api/chat",
    {"message": "Quais palestras de IA existem?", "architecture": "single"},
)
assert single.get("answer") and single.get("mode") == "offline", single
multi = request(
    "/api/chat",
    {"message": "Sugira uma palestra para iniciantes", "architecture": "multi"},
)
trace = multi.get("trace", {})
assert (
    multi.get("answer")
    and multi.get("mode") == "offline:multi"
    and trace.get("status") == "ok"
    and "mcp.list_sessions" in trace.get("tools", [])
), multi

print(f"Seed remoto OK: {len(sessions)} sessões; API publicada em {base}")
print("Healthcheck, agenda, FAQ/RAG lexical, agente single e agente multi via MCP: OK")
print("O endpoint está pronto para validação manual com curl.")
PY

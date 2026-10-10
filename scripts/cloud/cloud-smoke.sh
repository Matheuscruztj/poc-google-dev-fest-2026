#!/usr/bin/env bash
set -euo pipefail

if ! command -v terraform >/dev/null && [[ -x "$HOME/.local/bin/terraform" ]]; then
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

URL="${1:-}"
if [[ -z "$URL" ]]; then
  TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../infra/terraform" && pwd)"
  URL="$(terraform -chdir="$TF_DIR" output -raw service_url)"
fi

HEALTH="$(curl --fail --silent --show-error --retry 8 --retry-all-errors --retry-delay 3 "$URL/health")"
AGENT_MODE="$(python -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["status"] == "ok", d; print(d["agent_mode"])' "$HEALTH")"
python -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]), ensure_ascii=False))' "$HEALTH"

SCHEDULE="$(curl --fail --silent --show-error -H 'Content-Type: application/json' -d '{"track":"IA","limit":1}' "$URL/api/schedule")"
python -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("sessions"), d; print("Agenda API: OK (", len(d["sessions"]), "resultado(s))", sep="")' "$SCHEDULE"

FAQ="$(curl --fail --silent --show-error -H 'Content-Type: application/json' -d '{"question":"Quais são as regras de acessibilidade?"}' "$URL/api/faq")"
python -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("sources"), d; print("FAQ/RAG lexical: OK")' "$FAQ"

CHAT="$(curl --fail --silent --show-error -c /tmp/eventops-cloud-cookies.txt -b /tmp/eventops-cloud-cookies.txt -H 'Content-Type: application/json' -H "Origin: $URL" -d '{"message":"Quais palestras de IA existem?","architecture":"single"}' "$URL/api/chat")"
python -c 'import json,sys; d=json.loads(sys.argv[1]); expected=sys.argv[2]; assert d.get("answer") and d.get("mode") == expected and not d.get("error"), d; print("Chat API: OK (modo", d["mode"] + ")")' "$CHAT" "$AGENT_MODE"

MULTI="$(curl --fail --silent --show-error -b /tmp/eventops-cloud-cookies.txt -c /tmp/eventops-cloud-cookies.txt -H 'Content-Type: application/json' -H "Origin: $URL" -d '{"message":"Sugira uma palestra para iniciantes","architecture":"multi"}' "$URL/api/chat")"
python -c 'import json,sys; d=json.loads(sys.argv[1]); t=d.get("trace",{}); expected=f"{sys.argv[2]}:multi"; assert d.get("answer") and d.get("mode") == expected and t.get("status") == "ok" and not t.get("fallback") and "mcp.list_sessions" in t.get("tools",[]), d; print("Agente multi/Gemini/MCP: OK")' "$MULTI" "$AGENT_MODE"

SESSION="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["sessions"][0]["id"])' "$SCHEDULE")"
PREVIEW="$(curl --fail --silent --show-error -b /tmp/eventops-cloud-cookies.txt -c /tmp/eventops-cloud-cookies.txt -H 'Content-Type: application/json' -H "Origin: $URL" -d "{\"session_id\":\"$SESSION\"}" "$URL/api/reservations/preview")"
TOKEN_VALUE="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["confirmation_token"])' "$PREVIEW")"
CONFIRM="$(curl --fail --silent --show-error -b /tmp/eventops-cloud-cookies.txt -c /tmp/eventops-cloud-cookies.txt -H 'Content-Type: application/json' -H "Origin: $URL" -d "{\"session_id\":\"$SESSION\",\"confirmation_token\":\"$TOKEN_VALUE\",\"idempotency_key\":\"cloud-smoke-20261010\"}" "$URL/api/reservations")"
python -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("status") == "confirmed", d; print("Preview e confirmação de reserva: OK")' "$CONFIRM"

python -c 'from pathlib import Path; Path("/tmp/eventops-cloud-cookies.txt").unlink(missing_ok=True)'

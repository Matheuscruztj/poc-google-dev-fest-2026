#!/usr/bin/env bash
set -euo pipefail
URL="${1:?Passe a URL do Cloud Run}"
QUESTION='I use a wheelchair and need mobility assistance at the event. What support is available?'
PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"question":sys.argv[1]}))' "$QUESTION")"

curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 10 \
  -H 'Content-Type: application/json' -d "$PAYLOAD" "$URL/api/faq" |
python3 -c 'import json,sys; d=json.load(sys.stdin); sources=d.get("sources", []); match=next((s for s in sources if s.get("document")=="acessibilidade.md" and s.get("section")=="Recursos"), None); assert match and float(match.get("score",0)) >= 0.65, d; print(json.dumps({"semantic_rag":"ok","matched_source":"acessibilidade.md#Recursos","score":float(match["score"]),"answer":d.get("answer")},ensure_ascii=False))'

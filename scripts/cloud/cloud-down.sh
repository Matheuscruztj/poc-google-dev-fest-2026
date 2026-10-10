#!/usr/bin/env bash
set -euo pipefail

if ! command -v terraform >/dev/null && [[ -x "$HOME/.local/bin/terraform" ]]; then
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

PROJECT_ID="${CLOUD_PROJECT_ID:-poc-dev-fest-2026}"
TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../infra/terraform" && pwd)"
BILLING_ACCOUNT_ID="${CLOUD_BILLING_ACCOUNT_ID:-016F71-0F1AF8-2D5889}"
ALERT_NAME='POC Dev Fest 2026 - alerta R$5'
RAG_INSTANCE="eventops-rag-test"
API_KEY_RESOURCE="${EVENTOPS_API_KEY_RESOURCE:-}"

if [[ ! -f "$TF_DIR/terraform.tfstate" ]]; then
  echo "State Terraform não encontrado em $TF_DIR; nada removido." >&2
  exit 2
fi

ACTIVE_PROJECT="$(gcloud config get-value project 2>/dev/null)"
if [[ "$ACTIVE_PROJECT" != "$PROJECT_ID" ]]; then
  echo "Projeto ativo '$ACTIVE_PROJECT' difere do alvo '$PROJECT_ID'; nada removido." >&2
  exit 2
fi

export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"

verify_budget_alert() {
  gcloud billing budgets list \
    --billing-account="$BILLING_ACCOUNT_ID" --format=json |
  python3 -c 'import json,sys; name,project=sys.argv[1:]; budgets=json.load(sys.stdin); hits=[b for b in budgets if b.get("displayName")==name and f"projects/{project}" in b.get("budgetFilter",{}).get("projects",[])]; assert len(hits)==1, f"Alerta ausente ou duplicado: {name}"; b=hits[0]; thresholds={x.get("thresholdPercent") for x in b.get("thresholdRules",[])}; assert {0.5,0.8,1.0}.issubset(thresholds), f"Limiares incompletos: {thresholds}"; amount=b.get("amount",{}).get("specifiedAmount",{}); assert amount.get("currencyCode")=="BRL" and str(amount.get("units"))=="5", f"Valor inesperado: {amount}"; assert b.get("notificationsRule",{}).get("disableDefaultIamRecipients") is not True, "Notificações padrão estão desabilitadas"; print(f"Alerta ativo: {name}, R$ 5, limiares 50/80/100%")' \
    "$ALERT_NAME" "$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
}

verify_budget_alert

# Cloud SQL instance deletion can outlast a short-lived OAuth token when
# Terraform polls the operation. Let gcloud complete it, then remove the
# already-deleted SQL resources from Terraform state before destroying the rest.
if gcloud sql instances describe "$RAG_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  SQL_DELETE_OPERATION="$(gcloud sql instances delete "$RAG_INSTANCE" \
    --project="$PROJECT_ID" --async --quiet --format='value(name)')"
  if [[ -z "$SQL_DELETE_OPERATION" ]]; then
    echo "Cloud SQL não retornou o identificador da operação de exclusão." >&2
    exit 1
  fi
  python3 - "$PROJECT_ID" "$SQL_DELETE_OPERATION" <<'PY'
import json
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

project_id, operation = sys.argv[1:]
url = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project_id}/operations/{operation}"
deadline = time.monotonic() + 900
while time.monotonic() < deadline:
    token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            break
        raise
    if result.get("status") == "DONE":
        if result.get("error"):
            raise SystemExit(f"Falha ao excluir Cloud SQL: {result['error']}")
        break
    time.sleep(10)
else:
    raise SystemExit("Timeout aguardando a exclusão do Cloud SQL (15 min).")
PY
fi
for address in \
  'google_sql_user.rag[0]' \
  'google_sql_database.rag[0]' \
  'google_sql_database_instance.rag[0]'; do
  if terraform -chdir="$TF_DIR" state list | rg -Fxq "$address"; then
    terraform -chdir="$TF_DIR" state rm "$address"
  fi
done

export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"
terraform -chdir="$TF_DIR" destroy -auto-approve \
  -var="project_id=$PROJECT_ID" -var='enable_managed_rag=true'

# These two EventOps resources predate Terraform ownership in this checkout,
# but belong solely to this demo deployment.
if gcloud secrets describe eventops-google-api-key --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets delete eventops-google-api-key --project="$PROJECT_ID" --quiet
fi
if gcloud iam service-accounts describe "eventops-smoke@$PROJECT_ID.iam.gserviceaccount.com" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts delete "eventops-smoke@$PROJECT_ID.iam.gserviceaccount.com" --project="$PROJECT_ID" --quiet
fi
if [[ -n "$API_KEY_RESOURCE" ]]; then
  gcloud services api-keys delete "$API_KEY_RESOURCE" --project="$PROJECT_ID" \
    --no-check-existing-usage --quiet
fi

if gcloud run services describe eventops-api --project="$PROJECT_ID" --region="${CLOUD_REGION:-us-central1}" >/dev/null 2>&1; then
  echo "Cloud Run eventops-api ainda existe." >&2
  exit 1
fi
if gcloud sql instances describe "$RAG_INSTANCE" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "Cloud SQL $RAG_INSTANCE ainda existe." >&2
  exit 1
fi
if gcloud artifacts repositories describe eventops-images --project="$PROJECT_ID" --location="${CLOUD_REGION:-us-central1}" >/dev/null 2>&1; then
  echo "Artifact Registry eventops-images ainda existe." >&2
  exit 1
fi
if gcloud secrets describe eventops-rag-database-url --project="$PROJECT_ID" >/dev/null 2>&1 || \
   gcloud secrets describe eventops-google-api-key --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "Ainda existe segredo EventOps no Secret Manager." >&2
  exit 1
fi
if gcloud iam service-accounts describe "eventops-runtime@$PROJECT_ID.iam.gserviceaccount.com" --project="$PROJECT_ID" >/dev/null 2>&1 || \
   gcloud iam service-accounts describe "eventops-smoke@$PROJECT_ID.iam.gserviceaccount.com" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "Ainda existe uma service account EventOps de runtime/smoke." >&2
  exit 1
fi

verify_budget_alert

python3 - "$TF_DIR" <<'PY'
from pathlib import Path
import sys

directory = Path(sys.argv[1])
(directory / "service-url.txt").unlink(missing_ok=True)
for state_file in directory.glob("terraform.tfstate*"):
    state_file.unlink(missing_ok=True)
PY
echo "Infraestrutura EventOps removida. O projeto, APIs habilitadas e alerta de orçamento permanecem."

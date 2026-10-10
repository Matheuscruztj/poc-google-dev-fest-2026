#!/usr/bin/env bash
set -euo pipefail

if ! command -v terraform >/dev/null && [[ -x "$HOME/.local/bin/terraform" ]]; then
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

PROJECT_ID="${CLOUD_PROJECT_ID:-poc-dev-fest-2026}"
REGION="${CLOUD_REGION:-us-central1}"
SERVICE_NAME="eventops-api"
TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../infra/terraform" && pwd)"
URL="$(terraform -chdir="$TF_DIR" output -raw service_url)"
IMAGE="$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format='value(spec.template.spec.containers[0].image)')"
IMAGE_TAG="${IMAGE##*:}"

export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"

echo "Cloud SQL temporário db-f1-micro + 10 GB HDD custa aproximadamente US$ 0,013/h antes de embeddings/tráfego; a limpeza ocorre no encerramento."

cleanup() {
  local exit_code=$?
  trap - EXIT
  echo "Removendo Cloud SQL temporário e voltando o Cloud Run para RAG lexical..."
  # O usuário PostgreSQL é dono das tabelas/índices criados pela aplicação.
  # Cloud SQL não permite apagar esse usuário primeiro; apague a instância
  # inteira e retire do state os recursos filhos que já desapareceram com ela.
  if gcloud sql instances describe eventops-rag-test --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud sql instances delete eventops-rag-test --project="$PROJECT_ID" --quiet || true
  fi
  terraform -chdir="$TF_DIR" state rm \
    'google_sql_user.rag[0]' \
    'google_sql_database.rag[0]' \
    'google_sql_database_instance.rag[0]' \
    'random_password.rag_db[0]' >/dev/null 2>&1 || true
  terraform -chdir="$TF_DIR" apply -auto-approve \
    -var="project_id=$PROJECT_ID" -var="region=$REGION" \
    -var="image_tag=$IMAGE_TAG" -var="allowed_origins=$URL" \
    -var='enable_managed_rag=false'
  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

terraform -chdir="$TF_DIR" init
terraform -chdir="$TF_DIR" apply -auto-approve \
  -var="project_id=$PROJECT_ID" -var="region=$REGION" \
  -var="image_tag=$IMAGE_TAG" -var="allowed_origins=$URL" \
  -var='enable_managed_rag=true'

echo "Esperando Cloud Run concluir embeddings e sincronizar o índice pgvector..."
"$(dirname "${BASH_SOURCE[0]}")/cloud-rag-smoke.sh" "$URL"

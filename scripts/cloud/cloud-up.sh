#!/usr/bin/env bash
set -euo pipefail

if ! command -v terraform >/dev/null && [[ -x "$HOME/.local/bin/terraform" ]]; then
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi

PROJECT_ID="${CLOUD_PROJECT_ID:-poc-dev-fest-2026}"
REGION="${CLOUD_REGION:-us-central1}"
REPOSITORY="eventops-images"
IMAGE_NAME="eventops"
TF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../infra/terraform" && pwd)"
IMAGE_TAG="$(git rev-parse --short=12 HEAD)"
if ! git diff --quiet || ! git diff --cached --quiet || [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
  IMAGE_TAG="${IMAGE_TAG}-$(date -u +%Y%m%d%H%M%S)"
fi

if ! command -v gcloud >/dev/null || ! command -v terraform >/dev/null || ! command -v docker >/dev/null || ! command -v python3 >/dev/null; then
  echo "Requer gcloud, Terraform, Docker e Python 3 instalados." >&2
  exit 2
fi

export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token)"

ACTIVE_PROJECT="$(gcloud config get-value project 2>/dev/null)"
if [[ "$ACTIVE_PROJECT" != "$PROJECT_ID" ]]; then
  echo "Projeto ativo no gcloud: '$ACTIVE_PROJECT'; esperado '$PROJECT_ID'." >&2
  echo "Execute: gcloud config set project $PROJECT_ID" >&2
  exit 2
fi

BILLING="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || true)"
if [[ "$BILLING" != "True" ]]; then
  echo "Billing não está habilitado em $PROJECT_ID. Habilite-o no Console antes do deploy." >&2
  exit 2
fi

BILLING_ACCOUNT_RESOURCE="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingAccountName)')"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_RESOURCE##*/}"
if [[ -z "$BILLING_ACCOUNT_ID" ]]; then
  echo "Não foi possível obter a conta de billing de $PROJECT_ID." >&2
  exit 2
fi

# Budget setup runs before creating the image repository or Cloud Run service.
gcloud services enable billingbudgets.googleapis.com --project "$PROJECT_ID"
python3 "$(dirname "${BASH_SOURCE[0]}")/ensure_cloud_budgets.py" \
  "$PROJECT_ID" "$BILLING_ACCOUNT_ID"

IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$IMAGE_NAME:$IMAGE_TAG"
terraform -chdir="$TF_DIR" init
# Bootstrap the repository first; Cloud Run can only be created after its image exists.
terraform -chdir="$TF_DIR" apply -auto-approve -target=google_project_service.apis \
  -target=google_artifact_registry_repository.images \
  -var="project_id=$PROJECT_ID" -var="region=$REGION" -var="image_tag=$IMAGE_TAG"

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"

terraform -chdir="$TF_DIR" apply -auto-approve \
  -var="project_id=$PROJECT_ID" -var="region=$REGION" -var="image_tag=$IMAGE_TAG"

URL="$(terraform -chdir="$TF_DIR" output -raw service_url)"
terraform -chdir="$TF_DIR" apply -auto-approve \
  -var="project_id=$PROJECT_ID" -var="region=$REGION" -var="image_tag=$IMAGE_TAG" \
  -var="allowed_origins=$URL"
printf '%s\n' "$URL" > "$TF_DIR/service-url.txt"
printf 'Serviço publicado: %s\n' "$URL"
"$(dirname "${BASH_SOURCE[0]}")/cloud-smoke.sh" "$URL"

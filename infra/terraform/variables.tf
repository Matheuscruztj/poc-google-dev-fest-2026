variable "project_id" {
  description = "Google Cloud project for this disposable demo."
  type        = string
  default     = "poc-dev-fest-2026"
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  type    = string
  default = "eventops-api"
}

variable "repository_name" {
  type    = string
  default = "eventops-images"
}

variable "image_tag" {
  description = "Image tag pushed by scripts/cloud/cloud-up.sh before apply."
  type        = string
  default     = "latest"
}

variable "allowed_origins" {
  description = "Public Cloud Run origin accepted by the mutation/chat API."
  type        = string
  default     = ""
}

variable "enable_managed_rag" {
  description = "Provisiona temporariamente Cloud SQL PostgreSQL/pgvector e ativa RAG semântico. Gera cobrança horária enquanto existir."
  type        = bool
  default     = false
}

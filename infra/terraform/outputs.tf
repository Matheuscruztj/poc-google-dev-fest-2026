output "service_url" {
  description = "Public URL of the temporary API service."
  value       = google_cloud_run_v2_service.api.uri
}

output "artifact_repository" {
  value = google_artifact_registry_repository.images.name
}

output "managed_rag_instance" {
  description = "Temporary Cloud SQL instance used for the semantic RAG validation."
  value       = var.enable_managed_rag ? google_sql_database_instance.rag[0].name : null
}

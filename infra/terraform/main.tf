resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "billingbudgets.googleapis.com",
    "secretmanager.googleapis.com",
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "sqladmin.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_name
  description   = "Temporary EventOps demo images"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "eventops-runtime"
  display_name = "EventOps Cloud Run runtime"
}

resource "google_project_iam_member" "runtime_vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_sql_database_instance" "rag" {
  count               = var.enable_managed_rag ? 1 : 0
  project             = var.project_id
  name                = "eventops-rag-test"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = false

  settings {
    tier                        = "db-f1-micro"
    edition                     = "ENTERPRISE"
    availability_type           = "ZONAL"
    disk_type                   = "PD_HDD"
    disk_size                   = 10
    disk_autoresize             = false
    deletion_protection_enabled = false

    backup_configuration {
      enabled = false
    }

    ip_configuration {
      ipv4_enabled   = true
      server_ca_mode = "GOOGLE_MANAGED_INTERNAL_CA"
      ssl_mode       = "ENCRYPTED_ONLY"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "rag" {
  count    = var.enable_managed_rag ? 1 : 0
  project  = var.project_id
  name     = "eventops_rag"
  instance = google_sql_database_instance.rag[0].name
}

resource "google_sql_database" "app" {
  count    = var.enable_managed_rag ? 1 : 0
  project  = var.project_id
  name     = "eventops_app"
  instance = google_sql_database_instance.rag[0].name
}

resource "random_password" "rag_db" {
  count            = var.enable_managed_rag ? 1 : 0
  length           = 40
  special          = false
  override_special = ""
}

resource "google_sql_user" "rag" {
  count    = var.enable_managed_rag ? 1 : 0
  project  = var.project_id
  name     = "eventops_rag"
  instance = google_sql_database_instance.rag[0].name
  password = random_password.rag_db[0].result
}

resource "google_secret_manager_secret" "rag_database_url" {
  count     = var.enable_managed_rag ? 1 : 0
  project   = var.project_id
  secret_id = "eventops-rag-database-url"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "rag_database_url" {
  count       = var.enable_managed_rag ? 1 : 0
  secret      = google_secret_manager_secret.rag_database_url[0].id
  secret_data = "postgresql://eventops_rag:${random_password.rag_db[0].result}@/${google_sql_database.rag[0].name}?host=/cloudsql/${google_sql_database_instance.rag[0].connection_name}"
}

resource "google_secret_manager_secret" "app_database_url" {
  count     = var.enable_managed_rag ? 1 : 0
  project   = var.project_id
  secret_id = "eventops-app-database-url"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "app_database_url" {
  count       = var.enable_managed_rag ? 1 : 0
  secret      = google_secret_manager_secret.app_database_url[0].id
  secret_data = "postgresql://eventops_rag:${random_password.rag_db[0].result}@/${google_sql_database.app[0].name}?host=/cloudsql/${google_sql_database_instance.rag[0].connection_name}"
}

resource "google_secret_manager_secret_iam_member" "rag_database_url_access" {
  count     = var.enable_managed_rag ? 1 : 0
  project   = var.project_id
  secret_id = google_secret_manager_secret.rag_database_url[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "app_database_url_access" {
  count     = var.enable_managed_rag ? 1 : 0
  project   = var.project_id
  secret_id = google_secret_manager_secret.app_database_url[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_cloud_sql_client" {
  count   = var.enable_managed_rag ? 1 : 0
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "api" {
  project             = var.project_id
  name                = var.service_name
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  scaling {
    min_instance_count = 0
  }

  template {
    execution_environment = "EXECUTION_ENVIRONMENT_GEN1"
    service_account       = google_service_account.runtime.email
    # Concurrency keeps the small instance useful under light demo traffic.
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    timeout = "60s"

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/eventops:${var.image_tag}"

      ports {
        container_port = 8000
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "EVENTOPS_MODE"
        value = "offline"
      }
      env {
        name  = "EVENTOPS_AGENT_MODE"
        value = "live"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }
      env {
        name  = "EVENTOPS_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "EVENTOPS_COOKIE_SECURE"
        value = "true"
      }
      env {
        name  = "EVENTOPS_SEED_CATALOG"
        value = "true"
      }
      env {
        name  = "EVENTOPS_ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "EVENTOPS_DATABASE"
        value = "/tmp/eventops/eventops.sqlite3"
      }
      env {
        name  = "EVENTOPS_RAG_MODE"
        value = var.enable_managed_rag ? "hybrid" : "lexical"
      }
      env {
        name  = "EVENTOPS_EMBEDDING_PROVIDER"
        value = var.enable_managed_rag ? "google" : "ollama"
      }
      env {
        name  = "EVENTOPS_EMBEDDING_MODEL"
        value = "gemini-embedding-001"
      }

      dynamic "env" {
        for_each = var.enable_managed_rag ? [1] : []
        content {
          name = "EVENTOPS_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.app_database_url[0].secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "env" {
        for_each = var.enable_managed_rag ? [1] : []
        content {
          name = "EVENTOPS_RAG_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.rag_database_url[0].secret_id
              version = "latest"
            }
          }
        }
      }

      dynamic "volume_mounts" {
        for_each = var.enable_managed_rag ? [1] : []
        content {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }

    dynamic "volumes" {
      for_each = var.enable_managed_rag ? [1] : []
      content {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.rag[0].connection_name]
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_project_iam_member.runtime_vertex_ai,
    google_sql_database_instance.rag,
    google_sql_database.rag,
    google_sql_database.app,
    google_sql_user.rag,
    google_secret_manager_secret_version.rag_database_url,
    google_secret_manager_secret_iam_member.rag_database_url_access,
    google_secret_manager_secret_version.app_database_url,
    google_secret_manager_secret_iam_member.app_database_url_access,
    google_project_iam_member.runtime_cloud_sql_client,
  ]
}


resource "google_sql_database_instance" "conciliacion" {
  name             = "conciliacion-db"
  database_version = "POSTGRES_16"
  region           = var.region
}

resource "google_pubsub_topic" "eventos" {
  name = "conciliacion-eventos"
}

resource "google_secret_manager_secret" "banco" {
  secret_id = "token-banco"
  replication {
    auto {}
  }
}

resource "google_cloud_run_v2_service" "backend" {
  name     = "conciliacion-backend"
  location = var.region
  template {
    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }
    containers {
      image = "southamerica-east1-docker.pkg.dev/acme/apps/backend:0.3.0"
      env {
        name  = "API_PREFIX"
        value = "/api/v1"
      }
      env {
        name  = "DATABASE_URL"
        value = google_sql_database_instance.conciliacion.connection_name
      }
      env {
        name  = "EVENTS_TOPIC"
        value = google_pubsub_topic.eventos.name
      }
      env {
        name = "BANK_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.banco.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

# Nadie lo usa: infra_orphan.
resource "google_storage_bucket" "archivo" {
  name     = "conciliacion-archivo"
  location = "SOUTHAMERICA-EAST1"
}

# El frontend se publica como sitio estático en un bucket.
resource "google_storage_bucket" "frontend" {
  name     = "conciliacion-frontend"
  location = "SOUTHAMERICA-EAST1"
  website {
    main_page_suffix = "index.html"
  }
}

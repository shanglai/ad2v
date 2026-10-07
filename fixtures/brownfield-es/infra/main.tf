resource "google_sql_database_instance" "conciliacion" {
  name             = "conciliacion-db"
  database_version = "POSTGRES_16"
  region           = var.region
}

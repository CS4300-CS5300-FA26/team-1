resource "google_sql_database_instance" "main" {
  name             = "fitpro-pg"
  region           = var.region
  database_version = var.db_version

  # Terraform-level guard. Set to false when burning everything down at end of semester.
  deletion_protection = true

  settings {
    edition           = "ENTERPRISE"
    tier              = var.db_tier
    availability_type = "ZONAL"

    disk_type             = "PD_SSD"
    disk_size             = 10
    disk_autoresize       = true
    disk_autoresize_limit = 20

    deletion_protection_enabled = true

    ip_configuration {
      private_network = google_compute_network.vpc.id
      ipv4_enabled    = false
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    connector_enforcement = "REQUIRED"

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "09:00" # UTC (about 3 AM Mountain)
      transaction_log_retention_days = 7

      backup_retention_settings {
        retained_backups = 7
      }
    }

    # Sunday 09:00 UTC (about 3 AM Mountain). Keep away from grading times.
    maintenance_window {
      day  = 7
      hour = 9
    }
  }

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "app" {
  name     = "fitpro"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  name            = "fitpro_app"
  instance        = google_sql_database_instance.main.name
  password        = random_password.db.result
  deletion_policy = "ABANDON"
}

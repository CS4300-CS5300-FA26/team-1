resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "django_secret_key" {
  length           = 64
  special          = true
  override_special = "!@#%^*-_=+"
}

resource "google_secret_manager_secret" "db_password" {
  secret_id = "fitpro-db-password"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}

resource "google_secret_manager_secret" "django_secret_key" {
  secret_id = "fitpro-django-secret-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "django_secret_key" {
  secret      = google_secret_manager_secret.django_secret_key.id
  secret_data = random_password.django_secret_key.result
}

resource "google_secret_manager_secret_iam_member" "app_db_password" {
  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app_django_secret_key" {
  secret_id = google_secret_manager_secret.django_secret_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# Spotify integration (story D-7, ADR-010). The app needs all of these or none of them: it refuses to start with a
# partial Spotify configuration, so add the client secret's value (below) before the k8s manifests mount these.
# SPOTIFY_CLIENT_ID and SPOTIFY_REDIRECT_URI are not secret and go in the prod ConfigMap instead.

# Encrypts the Spotify tokens stored in the database: a Fernet key, which is 32 random bytes as url-safe base64.
# random_bytes gives standard base64, so swap its two non-url-safe characters. Losing or replacing this key makes every
# stored token unreadable and every user relink Spotify; rotate by adding the new key first ("new,old"), see ADR-010.
resource "random_bytes" "spotify_token_key" {
  length = 32
}

resource "google_secret_manager_secret" "spotify_token_encryption_key" {
  secret_id = "fitpro-spotify-token-encryption-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_version" "spotify_token_encryption_key" {
  secret      = google_secret_manager_secret.spotify_token_encryption_key.id
  secret_data = replace(replace(random_bytes.spotify_token_key.base64, "+", "-"), "/", "_")
}

# Issued by Spotify, so Terraform creates only the empty secret and its access grant. The value is added outside
# Terraform so it never lands in terraform.tfvars or the state file:
#   gcloud secrets versions add fitpro-spotify-client-secret --data-file=-   (paste it, then Ctrl-D / Ctrl-Z Enter)
# To rotate it, regenerate it in the Spotify dashboard, add a new version the same way, and restart the pods.
resource "google_secret_manager_secret" "spotify_client_secret" {
  secret_id = "fitpro-spotify-client-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.enabled]
}

resource "google_secret_manager_secret_iam_member" "app_spotify_token_encryption_key" {
  secret_id = google_secret_manager_secret.spotify_token_encryption_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app_spotify_client_secret" {
  secret_id = google_secret_manager_secret.spotify_client_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# Record who reads secret values (Data Access logs are off by default). Volume is
# tiny: one read per pod start.
resource "google_project_iam_audit_config" "secretmanager" {
  project = var.project_id
  service = "secretmanager.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
}

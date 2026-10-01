resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "fitpro"
  format        = "DOCKER"
  description   = "FitPro container images"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 15
    }
  }

  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }

  depends_on = [google_project_service.enabled]
}

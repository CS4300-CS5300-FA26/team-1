# ---- GKE node service account (pulls images, writes logs/metrics) ----
resource "google_service_account" "nodes" {
  account_id   = "fitpro-gke-nodes"
  display_name = "FitPro GKE Autopilot nodes"
}

resource "google_project_iam_member" "nodes_default" {
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

resource "google_artifact_registry_repository_iam_member" "nodes_pull" {
  project    = var.project_id
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.nodes.email}"
}

# ---- App runtime service account (used by pods via Workload Identity) ----
resource "google_service_account" "app" {
  account_id   = "fitpro-app"
  display_name = "FitPro Django runtime"
}

resource "google_project_iam_member" "app_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Lets the Kubernetes service account app/django-app act as the GSA above.
resource "google_service_account_iam_member" "app_workload_identity" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.k8s_namespace}/${var.k8s_service_account}]"

  # The workload identity pool only exists once the cluster does.
  depends_on = [google_container_cluster.autopilot]
}

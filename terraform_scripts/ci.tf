# ---- CI identity: GitHub Actions deploys via Workload Identity Federation ----
# No service account keys: GitHub's OIDC token is exchanged for short-lived
# credentials, and only main-branch runs in the "production" environment of this
# repository can do that.

resource "google_service_account" "ci" {
  account_id   = "fitpro-ci"
  display_name = "FitPro GitHub Actions deployer"
}

# Push images to the fitpro repository only (writer includes reader, which
# scripts/deploy.sh needs to check that the image tag exists).
resource "google_artifact_registry_repository_iam_member" "ci_push" {
  project    = var.project_id
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.ci.email}"
}

# Narrowest predefined role with container.clusters.get (get-gke-credentials) and
# container.clusters.connect (DNS-based endpoint). It grants no access to
# Kubernetes objects; that comes from the Role in k8s/platform/ci-rbac.yaml.
resource "google_project_iam_member" "ci_cluster_viewer" {
  project = var.project_id
  role    = "roles/container.clusterViewer"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

# Deleted pools are soft-deleted for 30 days and their IDs can't be reused until then.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "OIDC identities from GitHub Actions for ${var.github_repository}"

  depends_on = [google_project_service.enabled]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
    "attribute.repository"    = "assertion.repository"
    "attribute.ref"           = "assertion.ref"
    "attribute.environment"   = "assertion.environment"
  }

  # Every token must come from this repository (by immutable numeric ID, so a
  # renamed or re-created repo with the same name can't match), from main, and
  # from a job running in the "production" environment.
  attribute_condition = join(" && ", [
    "assertion.repository_id == \"${var.github_repository_id}\"",
    "assertion.ref == \"refs/heads/main\"",
    "assertion.environment == \"production\"",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Identities from this repository may impersonate the CI service account. The
# provider's attribute_condition above restricts that further to main + production.
resource "google_service_account_iam_member" "ci_workload_identity" {
  service_account_id = google_service_account.ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}

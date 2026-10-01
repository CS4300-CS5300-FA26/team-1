resource "google_container_cluster" "autopilot" {
  name             = "fitpro"
  location         = var.region
  enable_autopilot = true

  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.gke.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  release_channel {
    channel = "REGULAR"
  }

  gateway_api_config {
    channel = "CHANNEL_STANDARD"
  }

  cluster_autoscaling {
    auto_provisioning_defaults {
      service_account = google_service_account.nodes.email
      oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    }
  }

  # Set to false (and apply) before destroying at end of semester.
  deletion_protection = true

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.nodes_default,
  ]
}

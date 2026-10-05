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

  # Reach the control plane only through the DNS endpoint, where every request is
  # checked against IAM (container.clusters.connect) before it reaches the API server.
  # The IP endpoint is off, so there is no public IP for scanners to hit.
  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic = true
    }
    ip_endpoints_config {
      enabled = false
    }
  }

  # Managed Secret Manager CSI add-on: mounts secrets into pods as files
  # (SecretProviderClass provider "gke"), authenticated with Workload Identity.
  secret_manager_config {
    enabled = true
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

  # Leave only the free metrics - this ended up being really expensive to have default metrics
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]

    managed_prometheus {
      enabled = true
    }

    advanced_datapath_observability_config {
      enable_metrics = false
      enable_relay   = false
    }
  }

  # Set to false (and apply) before destroying at end of semester.
  deletion_protection = true

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.nodes_default,
  ]
}

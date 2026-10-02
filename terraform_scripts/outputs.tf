output "image_repository" {
  description = "Base path for docker push/pull."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "cluster_name" {
  value = google_container_cluster.autopilot.name
}

output "cluster_dns_endpoint" {
  description = "Control plane DNS endpoint (the IP endpoint is disabled). Use get-credentials --dns-endpoint."
  value       = google_container_cluster.autopilot.control_plane_endpoints_config[0].dns_endpoint_config[0].endpoint
}

output "lb_ip_name" {
  description = "Use as the Gateway's NamedAddress."
  value       = google_compute_global_address.lb.name
}

output "lb_ip_address" {
  description = "Point each hostname's A record (DNS only) here."
  value       = google_compute_global_address.lb.address
}

output "certificate_map_name" {
  description = "Use in the Gateway's networking.gke.io/certmap annotation."
  value       = google_certificate_manager_certificate_map.app.name
}

output "ssl_policy_name" {
  description = "Use as spec.default.sslPolicy in the Gateway's GCPGatewayPolicy."
  value       = google_compute_ssl_policy.app.name
}

output "dns_authorization_records" {
  description = "CNAME records to add in Cloudflare (DNS only) so certificates can be issued."
  value       = { for h, a in google_certificate_manager_dns_authorization.app : h => a.dns_resource_record[0] }
}

output "cloudsql_connection_name" {
  description = "Instance connection name for the Auth Proxy (sidecar and local)."
  value       = google_sql_database_instance.main.connection_name
}

output "db_name" {
  value = google_sql_database.app.name
}

output "db_user" {
  value = google_sql_user.app.name
}

output "app_service_account_email" {
  description = "Annotate the k8s service account with this (iam.gke.io/gcp-service-account)."
  value       = google_service_account.app.email
}

output "wif_provider" {
  description = "Full resource name of the GitHub OIDC provider (GitHub variable WIF_PROVIDER)."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_service_account_email" {
  description = "CI service account (GitHub variable CI_SERVICE_ACCOUNT, and the RBAC subject in k8s/platform/ci-rbac.yaml)."
  value       = google_service_account.ci.email
}

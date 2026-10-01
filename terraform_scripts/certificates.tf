# Reserved global IP for the Gateway's load balancer (referenced by name in k8s).
resource "google_compute_global_address" "lb" {
  name       = "fitpro-lb-ip"
  depends_on = [google_project_service.enabled]
}

locals {
  hostnames = toset(var.app_hostnames)
}

# DNS authorization lets Google issue the cert before the A record exists.
# Add the CNAME from the `dns_authorization_records` output in Cloudflare (DNS only).
resource "google_certificate_manager_dns_authorization" "app" {
  for_each = local.hostnames

  name   = "fitpro-dnsauth-${replace(each.value, ".", "-")}"
  domain = each.value

  depends_on = [google_project_service.enabled]
}

resource "google_certificate_manager_certificate" "app" {
  for_each = local.hostnames

  name = "fitpro-cert-${replace(each.value, ".", "-")}"

  managed {
    domains            = [each.value]
    dns_authorizations = [google_certificate_manager_dns_authorization.app[each.key].id]
  }
}

resource "google_certificate_manager_certificate_map" "app" {
  name       = "fitpro-certmap"
  depends_on = [google_project_service.enabled]
}

resource "google_certificate_manager_certificate_map_entry" "app" {
  for_each = local.hostnames

  name         = "fitpro-entry-${replace(each.value, ".", "-")}"
  map          = google_certificate_manager_certificate_map.app.name
  certificates = [google_certificate_manager_certificate.app[each.key].id]
  hostname     = each.value
}

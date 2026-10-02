variable "project_id" {
  description = "GCP project ID that holds all FitPro resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid GCP project ID (lowercase, no spaces)."
  }
}

variable "region" {
  description = "Region for the cluster, Cloud SQL, and Artifact Registry. Keep them together."
  type        = string
  default     = "us-central1"
}

variable "app_hostnames" {
  description = "Public hostnames served over HTTPS. List both old and new during a domain migration."
  type        = list(string)

  validation {
    condition     = length(var.app_hostnames) > 0 && alltrue([for h in var.app_hostnames : can(regex("^[a-z0-9.-]+$", h))])
    error_message = "Provide at least one lowercase hostname (letters, digits, dots, hyphens)."
  }
}

variable "db_version" {
  description = "Cloud SQL PostgreSQL version. Check Cloud SQL docs for the newest supported version."
  type        = string
  default     = "POSTGRES_16"
}

variable "db_tier" {
  description = "Cloud SQL machine tier. db-f1-micro is the smallest shared-core tier (no SLA)."
  type        = string
  default     = "db-f1-micro"
}

variable "k8s_namespace" {
  description = "Kubernetes namespace the app runs in."
  type        = string
  default     = "app"
}

variable "k8s_service_account" {
  description = "Kubernetes service account the app pods run as (bound to the runtime GSA)."
  type        = string
  default     = "django-app"
}

variable "github_repository" {
  description = "GitHub repository allowed to deploy, as \"org/repo\"."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must look like \"org/repo\"."
  }
}

variable "github_repository_id" {
  description = "Numeric GitHub repository ID (immutable, unlike the name). Used in the WIF attribute condition."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be the numeric repository ID."
  }
}

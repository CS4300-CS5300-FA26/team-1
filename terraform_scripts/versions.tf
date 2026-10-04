# The backend block and required_version live in backend.tf.
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9.1"
    }
  }
}

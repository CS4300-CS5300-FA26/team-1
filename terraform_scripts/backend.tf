terraform {
  required_version = ">= 1.5"

  backend "gcs" {
    bucket = "fitpro-tfstate-fitpro-uccs-cs4300"
    prefix = "terraform/state"
  }
}
# GCP Deployment Configuration
This document will detail the steps I took to configure the GCP deployment.

* Create GCP Project & sign up for free credit ($300 / 90days)
* Install [gcloud CLI](https://docs.cloud.google.com/sdk/docs/install-sdk)
* Install [kubectl](https://kubernetes.io/docs/tasks/tools/#kubectl)
* `gcloud components update`
* `gcloud components install gke-gcloud-auth-plugin`
* `gcloud auth application-default login` [Terraform will run as me directly - no need to IAM user setup]
* `choco install terraform` [Windows is pain, chocolatey is cool tho]
* `gcloud services enable storage.googleapis.com`
* `gcloud storage buckets create gs://fitpro-tfstate-fitpro-uccs-cs4300 --location=us-central1 --uniform-bucket-level-access --public-access-prevention`
* `gcloud storage buckets update gs://fitpro-tfstate-fitpro-uccs-cs4300 --versioning`
* `cd terraform_scripts`
* `terraform init`
* `terraform validate`
* `terraform plan -out tfplan`
* `terraform apply tfplan` [note, had to run twice due to race condition for sql]
* Do the DNS acme verification and check the TLS cert issued appropriately: `gcloud certificate-manager certificates describe fitpro-cert-fitpro-rockymountaintechlab-com --location=global`
* 
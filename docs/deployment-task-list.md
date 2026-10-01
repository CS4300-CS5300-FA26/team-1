# FitPro GKE Deployment Task List

Single GKE Autopilot cluster, single prod namespace, Cloud SQL for PostgreSQL, deployed from GitHub Actions via Workload Identity Federation. Public static IP over HTTP for now; domain and HTTPS later.

## Phase 0: Account and local setup
- [ ] Create the GCP project, attach the free-trial billing account, and note the trial expiry date.
- [ ] Turn on 2-step verification for your Google account, since it's your only admin identity.
- [ ] Create [budget alerts](https://cloud.google.com/billing/docs/how-to/budgets) at 50% and 80% of the credit.
- [ ] Install `gcloud`, Terraform, and `kubectl` (plus the `gke-gcloud-auth-plugin`).
- [ ] Run `gcloud auth application-default login`. Terraform then runs as you, so no Terraform IAM user or key is needed. That's the least-credential approach, and nothing exists to leak.

## Phase 1: Terraform bootstrap
- [ ] Create a versioned GCS bucket for [remote state](https://developer.hashicorp.com/terraform/language/backend/gcs) by hand or with a one-time local-state apply, then migrate.
- [ ] Enable APIs: Kubernetes Engine, Cloud SQL Admin, Artifact Registry, Secret Manager, IAM Credentials, Service Networking, Compute.
- [ ] Create the Artifact Registry repo, with a [cleanup policy](https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy) to keep recent image tags only.

## Phase 2: Runtime infrastructure (Terraform)
- [ ] VPC settings, plus a private services connection for Cloud SQL private IP.
- [ ] [GKE Autopilot](https://cloud.google.com/kubernetes-engine/docs/concepts/autopilot-overview) cluster, with [Workload Identity](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity) (on by default in Autopilot).
- [ ] Cloud SQL for PostgreSQL: smallest tier, private IP, automated backups, deletion protection, and a maintenance window away from grading.
- [ ] Secret Manager entries for the DB password and Django `SECRET_KEY`.
- [ ] A reserved global static IP for the load balancer.
- [ ] A runtime service account for the app, with `cloudsql.client` and `secretmanager.secretAccessor`, bound to the Kubernetes service account via Workload Identity.
- [ ] The `app` namespace.

## Phase 3: CI identity (Terraform)
- [ ] A CI service account with `artifactregistry.writer` on the repo and `container.clusterViewer` at the project level.
- [ ] A Kubernetes RoleBinding in `app` giving that service account edit rights (this is what limits it to deploys).
- [ ] A [WIF pool and provider](https://github.com/google-github-actions/auth) with an attribute condition locking it to your repo, and `roles/iam.workloadIdentityUser` on the CI service account.
- [ ] Output the project ID, provider name, and CI service account email, and add them as GitHub **repository variables** (not secrets).

## Phase 4: Containerize Django
- [ ] Multi-stage Dockerfile on a `python:3.x-slim` base, non-root user, Gunicorn.
- [ ] Settings via environment variables, following the [deployment checklist](https://docs.djangoproject.com/en/stable/howto/deployment/checklist/): `DEBUG=False`, `ALLOWED_HOSTS`, `SECRET_KEY`, secure cookies once HTTPS arrives.
- [ ] Static files with WhiteNoise.
- [ ] A `/healthz/` endpoint. **Gotcha:** load balancer health checks arrive with the pod IP as the Host header, which Django rejects (400) if it isn't in `ALLOWED_HOSTS`. Exempt the health path from the host check or handle it in middleware, or backends will show unhealthy.
- [ ] Test locally with Postgres in Docker Compose.

## Phase 5: Kubernetes manifests (in the repo)
- [ ] Deployment (2 replicas, resource requests kept small since Autopilot bills on requests, readiness and liveness probes, `maxUnavailable: 0`), with the Auth Proxy sidecar.
- [ ] Service (ClusterIP) and a [PodDisruptionBudget](https://kubernetes.io/docs/tasks/run-application/configure-pdb/).
- [ ] Migration Job.
- [ ] External entry point attached to the reserved static IP, over HTTP :80 for now. Use [Gateway](https://cloud.google.com/kubernetes-engine/docs/concepts/gateway-api) (Google's newer API) or [Ingress](https://cloud.google.com/kubernetes-engine/docs/concepts/ingress) if you want the simpler resource. Either swaps cleanly to hostname routing later.
- [ ] Secrets reaching pods via the [Secret Manager add-on](https://cloud.google.com/secret-manager/docs/secret-manager-managed-csi-component) or env injection at deploy time.
- [ ] Organize with [Kustomize](https://kubectl.docs.kubernetes.io/references/kustomize/) (`base/` plus a `prod` overlay), so adding a staging overlay later is trivial.
- [ ] Deploy once by hand and confirm the public IP returns your app.

## Phase 6: GitHub setup
- [ ] Branch protection on `main` (required reviews and passing checks).
- [ ] CODEOWNERS covering `.github/workflows/`, `terraform/`, and `k8s/`.
- [ ] A `production` [environment](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-deployments/managing-environments-for-deployment), restricted to `main`, with an optional required reviewer (availability on private repos depends on your plan, so verify).
- [ ] PR workflow: lint, tests, build only.
- [ ] Deploy workflow: build image, authenticate via OIDC, push to Artifact Registry, get GKE credentials, run migration Job, apply manifests, verify rollout (undo on failure). Use [google-github-actions/auth](https://github.com/google-github-actions/auth) and [get-gke-credentials](https://github.com/google-github-actions/get-gke-credentials). Tag images by git SHA, never `latest`.

## Phase 7: Verify and harden
- [ ] Trigger a deploy by merging a trivial change, and confirm the full pipeline works end to end.
- [ ] Test a rollback with `kubectl rollout undo`.
- [ ] Confirm a teammate's branch can't reach prod credentials (the WIF condition should reject non-`main` runs).
- [ ] Check Billing → Reports after the first week against your estimate.
- [ ] Agree on a deploy freeze before grading.

## Later iterations (not this sprint)
- [ ] Register a domain, add DNS, switch to a Google-managed cert, and enable HTTPS redirects and secure cookies.
- [ ] Add a host rule so the raw IP returns 404 (the "turn off the default endpoint" step).
- [ ] Add a staging overlay or environment if you want it back.

## End of semester
- [ ] Disable Cloud SQL deletion protection, then `terraform destroy`.

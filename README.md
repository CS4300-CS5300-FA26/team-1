# CS 4300/5300 Fall 2026 — Team 1 group project - FitPro
[TODO: add test coverage/ status badges here after ci/cd setup]

## Project Overview
This is the semester project for CS 4300/5300 Fall 2026. FitPro is a fitness application aimed at beginners and budget
conscious students. The application offers personalized workout splits, meal-prep guidance, and dynamic playlist creation.

## Authors
* Caleb Harris
* Fletcher McMeans
* Savannah Harmony Swan
* Tawnya Vrablik
* Nathan Galay

## Tech Stack
* **Web Framework:** Django 6.1
* **Python Package Management:** UV
* **Python Version:** 3.12
* **DB:** PostgreSQL 16 (Cloud SQL for PostgreSQL in production, see [ADR-002](docs/adrs/adr-002.md))
* **Production Host:** GKE Autopilot on Google Cloud, `us-central1` (see [ADR-003](docs/adrs/adr-003.md))
* **Infrastructure as Code:** Terraform (`terraform_scripts/`), state in a versioned GCS bucket
* **Base Docker Image:** TBD (planned: `python:3.12-slim`, multi-stage, non-root)

## Getting Started
> [!Note]
> If you don't have uv installed, run `curl -LsSf https://astral.sh/uv/install.sh | sh`

* Clone repo: `git clone git@github.com:CS4300-CS5300-FA26/team-1.git`
* `cd team-1`
* `cp .env.example .env`
* `uv sync`
* `uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` - Put value in .env
* `uv run python manage.py migrate`
* `uv run python manage.py runserver`
> [!tip]
> In DevEdu, port 8000 isn't available, so do this instead: `uv run python manage.py runserver 0.0.0.0:3000`

## Common Commands
* `uv run python manage.py runserver` [Starts the Django development server]
* `uv run python manage.py makemigrations` [Creates new database migrations]
* `uv run python manage.py migrate` [Applies database migrations]
* `uv run python manage.py test` [Runs Django tests]
* `uv run python manage.py behave` [Runs the Gherkin acceptance scenarios in `features/`]

## Authentication
User story **D-1 (user-auth)**: *as a new user, I want to create an account and log in, so that my plan and history are private to me.*
Auth lives in the `accounts` app and uses Django's built-in `User` model, sessions, and password hashing
(decision recorded in [ADR-005](docs/adrs/adr-005.md)).

| Route | Name | Access | Purpose |
| --- | --- | --- | --- |
| `/accounts/register/` | `register` | Anonymous (logged-in users are redirected home) | Create an account; on success the user is logged in and sent to `/onboarding/` |
| `/accounts/login/` | `login` | Anonymous | Log in with email (or username) and password |
| `/accounts/logout/` | `logout` | `POST` only | Log out (the Log out buttons submit a form) |
| `/onboarding/` | `onboarding` | Login required | Placeholder for the onboarding questionnaire (separate story) |
| `/users/` | `user_profile` | Login required | The signed-in user's own profile only |

### Acceptance scenarios
The Gherkin scenarios live in [`features/user_auth.feature`](features/user_auth.feature) (successful registration, email
already registered, wrong password). Step definitions are in `features/steps/user_auth_steps.py`. Django tests are in
`accounts/tests.py`, `accounts/test_d1_user_auth.py`, and `core/tests.py`.

```shell
uv run python manage.py test    # Django tests
uv run python manage.py behave  # Gherkin scenarios
```

### Security measures
| Area | What we do |
| --- | --- |
| Password storage | Hashed with Django's default PBKDF2-SHA256 hasher; never stored or logged in plain text. Password fields are marked sensitive so they are scrubbed from error reports |
| Password rules | Minimum 10 characters, not a commonly used password, not entirely numeric, not too similar to the username or email (`AUTH_PASSWORD_VALIDATORS`) |
| Login errors | One generic message, "Invalid email or password", for an unknown user, a wrong password, and an inactive account, so the login form cannot be used to discover accounts |
| Emails and usernames | Emails are trimmed, lowercased, and checked for duplicates case-insensitively; usernames cannot contain `@`, so a username can never be mistaken for an email |
| Sessions | The session key is rotated on login and registration (prevents session fixation); cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` behind the HTTPS proxy; sessions expire after 7 days |
| CSRF | Every form posts a CSRF token; Django rejects POSTs without one |
| Logout | `POST` only, so a third-party page cannot log a user out with a link or image |
| Redirects | The `next` parameter is only followed if it points at this site (no open redirects) |
| Access control | `/onboarding/` and `/users/` require login; `/users/` previously listed every user's profile and now shows only the signed-in user's own |

### Known gaps (planned follow-ups)
* **No rate limiting or lockout on login or registration yet.** The "email already exists" message required by the user story
  also reveals that an email has an account. Add [`django-axes`](https://django-axes.readthedocs.io/) (or similar) with `uv add`.
* **Email uniqueness is checked in the form, not enforced by the database**, so two simultaneous sign-ups with the same email could both succeed.
* **Email format is validated, but ownership is not.** Email verification and password reset need a production email backend (`MAILERS` still uses the console backend).
* **Admin site** (`/admin/`) is reachable on the public hostname; consider restricting it before launch.
* **Password hashing** uses Django's default; Argon2 is a possible upgrade (needs the `argon2-cffi` dependency).

## Contributing
* Branch naming: `feature/<short-description>`, `fix/<short-description>`
* Changes to **main** must come through a PR and must be approved by at least one other team member.
* [TBD linting tool maybe?]

## Deployment
Production runs on Google Cloud. Architecture and workflow diagrams are in `docs/diagrams/`, the decisions behind them
are in `docs/adrs/`, and the one-time GCP setup steps are in
[deployment_gcp_config.md](docs/configurations/deployment_gcp_config.md). 
Settings read secrets from `/var/secrets/<name>` in Kubernetes and fall back to environment variables / `.env` locally; set `BEHIND_HTTPS_PROXY=False` to run the production image over plain HTTP.

### Implemented (Terraform, `terraform_scripts/`)
| Area | Resources |
| --- | --- |
| Networking | Custom VPC `fitpro-vpc`, subnet `fitpro-gke` (10.10.0.0/20, pods 10.20.0.0/16, services 10.30.0.0/20), Private Google Access, private services peering for Cloud SQL |
| Compute | GKE Autopilot cluster `fitpro` (REGULAR release channel, Gateway API enabled, Workload Identity, deletion protection) running as a dedicated least-privilege node service account |
| Database | Cloud SQL `fitpro-pg` (PostgreSQL 16, `db-f1-micro`, zonal): private IP only, encrypted connections only, Cloud SQL Auth Proxy/connector required, daily backups (7 retained) + point-in-time recovery, Sunday 09:00 UTC maintenance window, deletion protection. Database `fitpro`, user `fitpro_app` |
| Secrets | Secret Manager `fitpro-db-password` and `fitpro-django-secret-key` (randomly generated). Only the app service account can read them (per-secret binding), and secret reads are written to Data Access audit logs |
| Identity | Runtime service account `fitpro-app` (`cloudsql.client` + per-secret `secretAccessor`), bound by Workload Identity to Kubernetes service account `app/django-app`. No service account keys exist |
| Images | Artifact Registry `fitpro` (Docker, `us-central1`) with immutable tags, keeping the 15 most recent images and deleting anything older than 30 days |
| Ingress / TLS | Reserved global static IP `fitpro-lb-ip`, Google-managed certificate through Certificate Manager (DNS authorization) and certificate map `fitpro-certmap` for `fitpro.rockymountaintechlab.com` (DNS only in Cloudflare, see [ADR-004](docs/adrs/adr-004.md)), SSL policy `fitpro-ssl-policy` (TLS 1.2+, MODERN profile) |

Terraform runs locally as the GCP project owner through `gcloud auth application-default login`, so no Terraform
service account or key exists. `terraform.tfvars` (gitignored) needs `project_id` and `app_hostnames`. See
`terraform.tfvars.example`.

```shell
cd terraform_scripts
terraform init
terraform validate
terraform plan -out tfplan
terraform apply tfplan
rm tfplan
terraform output  # values needed by the k8s manifests and Cloudflare DNS
```

After the first apply, add the `dns_authorization_records` CNAME and an A record pointing at `lb_ip_address` in
Cloudflare (DNS only / gray cloud). The Kubernetes Gateway uses `lb_ip_name` as its address, `certificate_map_name` in the
`networking.gke.io/certmap` annotation, and `ssl_policy_name` in a `GCPGatewayPolicy`.

### Teardown (end of semester)
Set `deletion_protection = false` on the cluster and the Cloud SQL instance (both settings), run `terraform apply`, then
`terraform destroy`.

# AI Usage

| LLM | Contributor | Usage | Transcript |
| --- | --- | --- | --- |
| Pardot | Caleb Harris | Validated issues created in GitHub against Sprint 0-2 Requirements | n/a |
| Claude | Caleb Harris | Generated Lo-Fi wireframe given spec | Used `agents` tab in Figma |
| Pardot | Caleb Harris | PR Review | [Link](https://github.com/CS4300-CS5300-FA26/team-1/pull/16) |
| Claude | Caleb Harris | Security review of the Terraform GKE infrastructure setup, with fixes and README deployment docs | n/a |
| Claude | Caleb Harris | Generated draft Dockerfile and dockerignore file | n/a |
| Claude | Caleb Harris | Generated k8s manifests | n/a |
| Claude | Caleb Harris | Generated deployment script | n/a |
| Claude | Caleb Harris | Claude Code implemented the CD portion of the GitHub Actions pipeline (Workload Identity Federation auth, image build/push, deploy via scripts/deploy.sh) | n/a |
| Claude | Nathan Galay | Generated register/login pages (accounts app) | n/a |
| Codex | Caleb Harris | Automatic PR review: `pr-review.yml` runs `openai/codex-action` when a PR is opened and posts the feedback as a PR comment | n/a |
| Claude | Caleb Harris | Reviewed `pr-review.yml` against the other CI workflows and pinned its actions to commit SHAs | n/a |
| Claude | Nathan Galay | Implemented user story D-1 (user-auth) on the accounts app: generic login error, email login, password and session hardening, Gherkin feature and step definitions, extra Django tests, ADR-005, and this README section | n/a |
# CS 4300/5300 Fall 2026 — Team 1 group project - FitPro
[![CI](https://github.com/CS4300-CS5300-FA26/team-1/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/CS4300-CS5300-FA26/team-1/actions/workflows/ci.yml)

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
* **Docker Image:** multi-stage build on `python:3.12-slim` with uv, running Gunicorn as a non-root user (UID 10001) with a read-only code tree (see `Dockerfile`)
* **Code quality:** ruff (lint and format), mypy with django-stubs (types), bandit and CodeQL (security scans), all enforced in CI

## Getting Started
> [!Note]
> If you don't have uv installed, run `curl -LsSf https://astral.sh/uv/install.sh | sh`

* Clone repo: `git clone git@github.com:CS4300-CS5300-FA26/team-1.git`
* `cd team-1`
* `cp .env.example .env`
* `uv sync`
* `uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` - Put value in .env
* `uv run python manage.py migrate` (this also loads the recipe catalog, see [ADR-008](docs/adrs/adr-008.md))
* `uv run python manage.py runserver`

SQLite is the default. To develop against PostgreSQL like production, set the `DB_*` variables in `.env` (see
[`docs/configurations/project_initial_setup.md`](docs/configurations/project_initial_setup.md)).
> [!tip]
> In DevEdu, port 8000 isn't available, so do this instead: `uv run python manage.py runserver 0.0.0.0:3000`

## Common Commands
* `uv run python manage.py runserver` [Starts the Django development server]
* `uv run python manage.py makemigrations` [Creates new database migrations]
* `uv run python manage.py migrate` [Applies database migrations, then reloads the recipe and exercise catalogs]
* `uv run python manage.py load_recipe_catalog` [Reloads recipes from `nutrition/data/recipe_catalog.json`; `--file` loads another file]
* `uv run python manage.py load_exercise_catalog` [Reloads exercises from `workouts/data/exercise_catalog.json`; `--file` loads another file]
* `uv run python manage.py build_exercise_catalog path/to/exercises.json` [Rebuilds that catalog from the upstream dataset: English text only, no images or video ([ADR-009](docs/adrs/adr-009.md))]
* `uv run python manage.py test` [Runs Django tests]
* `uv run python manage.py behave` [Runs the Gherkin acceptance scenarios in `features/`]
* `E2E=1 uv run python manage.py test e2e` [Runs the Playwright browser tests in `e2e/`; run `uv run playwright install chromium` once first]

### Test coverage
CI runs the Django tests and the Gherkin scenarios once, under `coverage`, on every push. On pull requests into `main`
it also adds a coverage table to the job summary, uploads a `coverage-report` artifact (`coverage.xml` and the HTML
report), and fails if total coverage is below **80%**. Coverage settings are in `pyproject.toml`. To run the same check locally:

```shell
uv run coverage run manage.py test
uv run coverage run --append manage.py behave
uv run coverage report   # fails under 80%
uv run coverage html     # writes htmlcov/index.html
```

### Code quality and security scans
CI fails on any of these (settings in `pyproject.toml`). Run them locally before pushing:

```shell
uv run ruff check .          # lint (use --fix for safe auto-fixes)
uv run ruff format .         # format (CI runs it with --check)
uv run mypy .                # types, with django-stubs
uv run bandit -c pyproject.toml -r .   # SAST for Python
```

CodeQL (`.github/workflows/codeql.yml`) also scans pull requests, `main`, and weekly, with results in the repository's Security tab.
Dependabot (`.github/dependabot.yml`) opens weekly PRs for uv dependencies, GitHub Actions, and the Docker base image.

## Frontend theme
Every page extends `core/templates/core/base.html`, which loads the global stylesheet
[`core/static/core/css/theme.css`](core/static/core/css/theme.css) and the light/dark toggle in
`core/static/core/js/theme.js`. Style pages with the classes below instead of page-level `<style>` blocks or hard-coded
colours, so contrast and dark mode stay correct.

| Purpose | Classes |
| --- | --- |
| Page layout | `main` gets `page` (default) or `page page--centered` through `{% block main_class %}`; `container`, `stack` / `stack--sm` / `stack--lg`, `cluster` / `cluster--center` / `cluster--end` / `cluster--between` |
| Card | `card`, `card--narrow`, `card--wide`, `card__title`, `card__subtitle`, `card__footer` |
| Buttons | `btn` plus `btn--primary`, `btn--secondary`, `btn--ghost`, or `btn--danger`; modifiers `btn--sm`, `btn--block`. Use `<button>` for actions and `<a class="btn">` for navigation |
| Forms | `form`, `form-field`, `form-label`, `form-input`, `form-help`, `form-error`, `form-fieldset`, `choice-list`, `choice`. `{% include "core/_form_fields.html" %}` renders a whole Django form with these classes and keeps Django's `aria-describedby` / `aria-invalid` wiring |
| Feedback | `alert` plus `alert--error`, `alert--success`, `alert--warning`, or `alert--info` (add `role="alert"` or `role="status"`) |
| Content | `hero`, `hero__lede`, `data-list` (on a `<dl>`), `badge`, `media-list` with `media` / `media__thumb` / `media__body` / `media__eyebrow` / `media__title` / `media__meta` (rows of thumbnail + text; add `media--link` and `aria-current="true"` for a selectable row), `day-picker` (step through or jump to a day of the week; `day-picker__name` / `__date` / `__today` stack the weekday, date, and a "Today" label), `split` (list beside details), `panel` / `panel--sticky` (a side panel that stays in view and scrolls on its own), `toolbar`, `meal-stack` / `meal-card` with `meal-card__header` / `__heading` / `__title` / `__meta` / `__recipe` (a planned meal with its recipe in a `disclosure` underneath), `split--main-first` with `split__main` / `split__aside` (summary above the main content on phones, beside it on wide screens), `macro-list` / `macro-list__row` / `macro-list__meter` (grams against targets), `stat--start`, `alert__list` (bullets inside an alert), `food-image` (course-tinted placeholder art), `chip-list` / `chip`, `macro-grid`, `tabs` (with `meal_plan.js`), `set-row` / `set-row__label` (one set to log: label, then reps and weight fields in a row), `ingredient-grid` (add `ingredient-grid--weighed` with an `ingredient-grid__amount` per item for a weight at the end of each line), `steps`, `status-badge`, `eyebrow` |
| Report and charts | `report-section`, `hero-figure` (one per page), `meter` (one value against a limit), `bar` / `bar-list` (SVG bars; widths as SVG attributes), `stat-row` / `stat-tile`, `data-table` inside `table-scroll` (focusable, labelled region), `disclosure-list` / `disclosure`, `messages` (Django messages, rendered by `base.html`), `stat` / `stat__value` / `stat__label` (a headline number) |
| Utilities | `text-muted`, `text-center`, `text-sm`, `h3` (h3 size on another heading level), `mt-0`, `mb-0`, `mt-3`, `mt-4`, `mt-5`, `visually-hidden` |

Colours, spacing and type are CSS custom properties at the top of `theme.css` (`--color-*`, `--space-*`, `--text-*`).
Dark mode follows the operating system setting, and the header's "Dark mode" toggle overrides it (saved in
`localStorage`).

Accessibility (WCAG 2.2 AA):
* Every text and token pair meets 4.5:1 contrast, and control borders and focus rings meet 3:1, in both modes.
* Focus rings are visible on every focusable element.
* There is a skip link on every page, and `aria-current` marks the current nav item.
* Targets are at least 44px tall.
* Errors and status are always written out, not shown by colour alone.
* The theme respects reduced-motion and forced-colours (High Contrast) settings.

If you change a colour token, recheck its contrast against the surfaces it is used on.

## Authentication
User story **D-1 (user-auth)**: *as a new user, I want to create an account and log in, so that my plan and history are private to me.*
Auth lives in the `accounts` app and uses Django's built-in `User` model, sessions, and password hashing
(decisions recorded in [ADR-005](docs/adrs/adr-005.md) and [ADR-006](docs/adrs/adr-006.md)).

| Route | Name | Access | Purpose |
| --- | --- | --- | --- |
| `/accounts/register/` | `register` | Anonymous (logged-in users are redirected home) | Create an account; on success the user is logged in and sent to `/onboarding/` |
| `/accounts/login/` | `login` | Anonymous | Log in with email (or username) and password |
| `/accounts/logout/` | `logout` | `POST` only | Log out (the Log out buttons submit a form) |
| `/onboarding/` | `onboarding` | Login required | Onboarding questionnaire (story D-2). Users who already finished it are sent to `/dashboard/` |
| `/dashboard/` | `dashboard` | Login required | Profile summary. Users who haven't finished onboarding are sent to `/onboarding/` |
| `/users/` | `user_profile` | Login required | The signed-in user's own profile only |
| `/meal-plan/` | `meal_plan` | Login required (onboarded users) | This week's meal plan (story D-5, [ADR-008](docs/adrs/adr-008.md)): a week strip to pick a day, that day's meals (chosen in onboarding) as cards with portion, kcal, and macros, each recipe's weighed ingredients and steps opening in place, the day's totals against its targets, the estimated grocery cost and an over-budget notice once grocery prices are connected (D-6), a notice for each fallback in use, and a "temporarily unavailable" state. `?day=` selects a day; `meal_plan.js` switches days without a reload |
| `/meal-plan/new/` | `meal_plan_new` | Login required, `POST` only | Replace this week's plan with a different one |
| `/workouts/` | `workouts_this_week` | Login required (onboarded users) | This Week (story D-3, [ADR-009](docs/adrs/adr-009.md)): the weekly split built from the user's goal, experience, and equipment, with rest days, each day's exercises, a Start or Continue button, and a form for 3, 4, or 5 training days |
| `/workouts/new/` | `workouts_new` | Login required, `POST` only | Replace this week's workout plan with a different selection of exercises |
| `/workouts/preferences/` | `workouts_preferences` | Login required, `POST` only | Save the number of training days a week and remake the plan |
| `/workouts/start/<id>/` | `workouts_start` | Login required, `POST` only, own workouts of the current week | Start (or go back to) the session for a planned workout |
| `/workouts/session/<id>/` | `workouts_session` | Login required, own sessions only (others get 404) | Log a workout: how-to steps, reps and weight per set (minutes for cardio), a rest timer, save or finish |
| `/workouts/history/` | `workouts_history` | Login required | Progress: workouts done against planned and total volume for the last 8 weeks, and recently finished workouts |

### Acceptance scenarios
The Gherkin scenarios live in [`features/user_auth.feature`](features/user_auth.feature) (successful registration, email
already registered, wrong password) and [`features/onboarding.feature`](features/onboarding.feature) (complete
onboarding, missing required answer, returning user skips onboarding), and [`features/meal_plan.feature`](features/meal_plan.feature)
(plan within budget, budget too low, recipe service unavailable, plus the no-macro-targets and no-prices fallbacks), and [`features/workouts.feature`](features/workouts.feature) (a split that fits the equipment, no equipment, choosing training days, logging and finishing a workout, finishing empty, privacy). Step
definitions are in `features/steps/`. Nothing calls the network: the connectors to D-4 and D-6 use the stand-ins in
`nutrition/testing.py`, and the recipe catalog is loaded into the test database after migrations.
Django tests are in `accounts/tests.py` (registration, login, logout), `core/test_onboarding.py` (onboarding, dashboard,
and the login redirect), `core/tests.py` (models, health checks, and access control), and `nutrition/test_*.py` (meal
planner and pricing, recipe catalog and loader, connectors and fallbacks, Meal Plan page), and `workouts/test_*.py` (exercise catalog and loader, planner, plans and sessions, progress, pages and access control). Browser tests for the Meal Plan page are in `e2e/` (see Common Commands).

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
| Emails and usernames | Emails are trimmed, lowercased, and checked for duplicates case-insensitively (the form check is backed by a unique database index on `LOWER(email)`); usernames cannot contain `@`, so a username can never be mistaken for an email |
| Sessions | The session key is rotated on login and registration (prevents session fixation); cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` behind the HTTPS proxy; sessions expire after 7 days |
| CSRF | Every form posts a CSRF token; Django rejects POSTs without one |
| Logout | `POST` only, so a third-party page cannot log a user out with a link or image |
| Redirects | The `next` parameter is only followed if it points at this site (no open redirects) |
| Access control | `/onboarding/`, `/dashboard/`, and `/users/` require login; `/users/` previously listed every user's profile and now shows only the signed-in user's own |
| Workout data | Every `/workouts/` page requires login and finds plans and sessions through the signed-in user, so another member's workout is a 404; starting, saving, regenerating, and changing days are `POST` with CSRF. Posted set values are accepted only for the rows the workout has, and reps, weight, and minutes are bounded in the form and by database `CHECK` constraints ([ADR-009](docs/adrs/adr-009.md)) |

### Known gaps (planned follow-ups)
* **Rate limiting is in place for login and registration** ([ADR-006](docs/adrs/adr-006.md)), but the
  "email already exists" message required by the user story still reveals that an email has an account.
* **Email format is validated, but ownership is not.** Email verification and password reset need a production email backend (`MAILERS` still uses the console backend).
* **No admin site.** It was removed ([ADR-007](docs/adrs/adr-007.md)); manage data with `manage.py shell` or a one-off Job. Re-adding it needs network-level restriction first.
* **Meal plan (D-5)** ([ADR-008](docs/adrs/adr-008.md)): until D-4 is connected, plans use the FDA Daily Values (2,000 kcal) instead of personal macro targets. Until D-6 is connected, there's no cost estimate and the budget isn't applied. The catalog has 25 recipes with no dietary filters yet, nutrients come from USDA SR Legacy (2018), and pantry staples aren't counted. "Today" and the week boundary use the server's time zone (UTC).
* **Workouts (D-3 and tracking)** ([ADR-009](docs/adrs/adr-009.md)): the plan is rule-based, with no AI agent, and it doesn't yet adjust from logged results beyond prefilling the last weight. Exercises are hand-picked from the catalog and the sets, reps, and rest rules haven't been reviewed by a trainer. There is no exercise swapping or catalog browsing, no images or video (the dataset's Gym visual media isn't licensed to us), and "today" and the week boundary use the server's time zone (UTC). D-4 can read the training days with `workouts.services.training_days`; nothing does yet.
* **Password hashing** uses Django's default; Argon2 is a possible upgrade (needs the `argon2-cffi` dependency).

## Third-party data
* **Exercise catalog** (`workouts/data/exercise_catalog.json`): exercise names, muscles, and instruction text from the exercises dataset, MIT License, Copyright (c) 2026 Hasan Emir Yıldırım ([licence text](workouts/data/LICENSE-exercise-data.txt)). The dataset's images and videos belong to [Gym visual](https://gymvisual.com/) and are not covered by that licence. They are not in this repository, and the catalog leaves them out ([ADR-009](docs/adrs/adr-009.md)).
* **Recipe catalog** (`nutrition/data/recipe_catalog.json`): nutrients from USDA FoodData Central ([ADR-008](docs/adrs/adr-008.md)).

## Contributing
* Read [AGENTS.md](AGENTS.md) first: it is the team's working agreement (security rules, code standards, ADRs, frontend theme and accessibility, workflow) for humans and AI coding tools alike.
* Branch naming: `feat/<short-description>`, `fix/<short-description>`, `chore/<short-description>`, or `<issue-number>-<short-description>`
* Changes to **main** must come through a PR and must be approved by at least one other team member.
* **Author:** opens the PR, keeps CI green, and answers review comments. Don't approve your own PR.
* **Reviewer:** reads the diff and the Codex review comment (`pr-review.yml`), checks that new behavior has tests, and approves or requests changes. The AI review does not replace a human approval.
* **Before pushing:** run `uv run ruff check .`, `uv run ruff format .`, `uv run mypy .`, `uv run bandit -c pyproject.toml -r .`, and the tests (see [Code quality and security scans](#code-quality-and-security-scans)). CI runs the same checks and fails the PR if any of them fail.
* **Dependency updates:** Dependabot PRs follow the same review rules. Merge them only when CI passes.
* **Decisions:** a change that alters the architecture, security posture, or a tradeoff gets an ADR in `docs/adrs/`.

## Deployment
Production runs on Google Cloud. Architecture, workflow, and meal plan data lineage diagrams are in `docs/diagrams/`, the
decisions behind them are in `docs/adrs/`, and the one-time GCP setup steps are in
[deployment_gcp_config.md](docs/configurations/deployment_gcp_config.md). 
Settings read secrets from `/var/secrets/<name>` in Kubernetes and fall back to environment variables / `.env` locally; set `BEHIND_HTTPS_PROXY=False` to run the production image over plain HTTP.

### Monitoring and incident response
What exists today:
* `/livez/` returns 200 while the process is serving requests (no database access). `/healthz/` returns 200 only if the database answers, otherwise 503. The Kubernetes probes and the load balancer health check use them.
* Application logs, including tracebacks and `accounts.security` throttling warnings, go to stdout and are collected by Cloud Logging.
* Deploys are gated by CI, a container smoke test, and a migration Job; `scripts/rollback.sh` reverts a bad release.

Alerting and response: monitoring and alerts are currently handled through Google Cloud Monitoring and the Google Cloud mobile app. Caleb Harris owns the infrastructure and is the responsible party for responding to and fixing incidents.

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

| LLM | Contributor | Usage |
| --- | --- | --- |
| Pardot | Caleb Harris | Validated issues created in GitHub against Sprint 0-2 Requirements |
| Claude | Caleb Harris | Generated Lo-Fi wireframe given spec (used `agents` tab in Figma) |
| Pardot | Caleb Harris | PR Review |
| Claude | Caleb Harris | Security review of the Terraform GKE infrastructure setup, with fixes and README deployment docs |
| Claude | Caleb Harris | Generated draft Dockerfile and dockerignore file |
| Claude | Caleb Harris | Generated k8s manifests |
| Claude | Caleb Harris | Generated deployment script |
| Claude | Caleb Harris | Claude Code implemented the CD portion of the GitHub Actions pipeline (Workload Identity Federation auth, image build/push, deploy via scripts/deploy.sh) |
| Claude | Nathan Galay | Generated register/login pages (accounts app) |
| Codex | Caleb Harris | Automatic PR review: `pr-review.yml` runs `openai/codex-action` when a PR is opened and posts the feedback as a PR comment |
| Claude | Caleb Harris | Reviewed `pr-review.yml` against the other CI workflows and pinned its actions to commit SHAs |
| Claude | Nathan Galay | Implemented user story D-1 (user-auth) on the accounts app: generic login error, email login, password and session hardening, Gherkin feature and step definitions, extra Django tests, ADR-005, and this README section |
| Claude | Caleb Harris | Claude Code added login/registration rate limiting, database-enforced email uniqueness, ruff/mypy/bandit/CodeQL CI gates and Dependabot config, disabled the admin site, wrote ADR-006 and ADR-007, and corrected this README against the Sprint 1 feedback |
| Claude | Caleb Harris | Claude Code applied the PR #20/#27 review follow-ups (merged duplicate test modules, onboarding input bounds, shared base template, ADR-005) and moved the coverage report into `ci.yml` with the 80% gate and artifact on PRs only |
| Claude | Caleb Harris | Claude Code implemented story D-5 (weekly budget meal plan): `nutrition` app with connectors for D-3, D-4, and D-6 and their fallbacks (FDA Daily Values, no-price planning), a USDA FoodData Central recipe catalog and loader, a whole-package, ingredient-sharing planner, stored weekly plans for D-6, the Meal Plan page (week strip, day view with in-place recipes), meal checkboxes in onboarding, unit/Gherkin/Playwright tests, ADR-008, and a temporary AGENTS.md note on wiring the connectors |
| Claude | [contributor name] | Claude built the `workouts` app for story D-3 and exercise tracking: a text-only exercise catalog from the exercises dataset with a loader and build command, a rule-based weekly split planner with hand-picked exercise pools, stored plans, the This Week page, workout logging with a rest timer, and progress pages, wired `NUTRITION_WORKOUTS_LINK` to This Week, unit/Gherkin tests, and ADR-009 |

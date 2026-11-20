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
* **Email:** Resend's HTTP API through a small Django email backend (`core/mail.py`), free plan (see [ADR-017](docs/adrs/adr-017.md))
* **AI trainer:** OpenAI Chat Completions chooses the exercises in each weekly plan; optional, and off without an API key (see [ADR-014](docs/adrs/adr-014.md))
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
> In DevEdu, port 8000 isn't available, so do this instead: ``uv run python manage.py runserver 0.0.0.0:3000

To try Spotify linking and "Log in / Sign up with Spotify" locally, set the four `SPOTIFY_*` variables in `.env` (see
`.env.example` and [Spotify integration](#spotify-integration)) and open the app at `http://127.0.0.1:8000`, not
`localhost`: Spotify rejects `localhost` redirect URIs, and the session cookie must belong to the same host.

To try the AI trainer locally, set `OPENAI_API_KEY` (and `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT`) in your own `.env`, never
in code or in `.env.example` (see [ADR-014](docs/adrs/adr-014.md)). With no key, plans come from the rule-based generator.

## Common Commands
* `uv run python manage.py runserver` [Starts the Django development server]
* `uv run python manage.py makemigrations` [Creates new database migrations]
* `uv run python manage.py migrate` [Applies database migrations, then reloads the recipe catalog]
* `uv run python manage.py load_recipe_catalog` [Reloads recipes from `nutrition/data/recipe_catalog.json`; `--file` loads another file]
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
| Content | `hero`, `hero__lede`, `data-list` (on a `<dl>`), `badge`, `connection-pill` with `connection-pill__dot` / `connection-pill__name` (a linked service and its health; set `data-state` to `off`, `unknown`, `checking` (pulsing grey), `ok` (green), or `error` (red), and always say the state in text too), `media-list` with `media` / `media__thumb` / `media__body` / `media__eyebrow` / `media__title` / `media__meta` (rows of thumbnail + text; add `media--link` and `aria-current="true"` for a selectable row), `day-picker` (step through or jump to a day of the week; `day-picker__name` / `__date` / `__today` stack the weekday, date, and a "Today" label), `split` (list beside details), `panel` / `panel--sticky` (a side panel that stays in view and scrolls on its own), `toolbar`, `meal-stack` / `meal-card` with `meal-card__header` / `__heading` / `__title` / `__meta` / `__recipe` (a planned meal with its recipe in a `disclosure` underneath), `split--main-first` with `split__main` / `split__aside` (summary above the main content on phones, beside it on wide screens), `macro-list` / `macro-list__row` / `macro-list__meter` (grams against targets), `stat--start`, `alert__list` (bullets inside an alert), `food-image` (course-tinted placeholder art), `chip-list` / `chip`, `macro-grid`, `tabs` (with `meal_plan.js`), `ingredient-grid` (add `ingredient-grid--weighed` with an `ingredient-grid__amount` per item for a weight at the end of each line), `steps`, `status-badge`, `eyebrow` |
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
(decisions recorded in [ADR-005](docs/adrs/adr-005.md) and [ADR-006](docs/adrs/adr-006.md)). Every account confirms
its email before it can be used, and passwords can be reset by email ([ADR-018](docs/adrs/adr-018.md)).

| Route | Name | Access | Purpose |
| --- | --- | --- | --- |
| `/accounts/register/` | `register` | Anonymous (logged-in users are redirected home); rate limited | Start a sign-up: creates an inactive account and emails a confirmation link, or, if the email already has an account, emails its owner instead. Either way it shows the same "Check your email" page and logs nobody in ([ADR-018](docs/adrs/adr-018.md)) |
| `/accounts/verify/sent/` | `verify_email_sent` | Anyone | "Check your email", after a sign-up or a resend |
| `/accounts/verify/<uid>/<token>/` | `verify_email` | Anyone with a valid link (24 hours, single use) | GET shows a "Confirm my email" button; the POST activates the account, logs in, and goes to `/onboarding/` (or `/accounts/password/set/` for a Spotify sign-up) |
| `/accounts/verify/resend/` | `resend_verification` | Anyone; rate limited | Send a new confirmation link to an unconfirmed sign-up |
| `/accounts/password/reset/` | `password_reset` | Anyone; rate limited | Email a password reset link if the address has an account; the same page either way |
| `/accounts/password/reset/sent/` | `password_reset_done` | Anyone | "Check your email" after a reset request |
| `/accounts/password/reset/<uid>/<token>/` | `password_reset_confirm` | Anyone with a valid link (24 hours, single use) | Choose a new password (Django's view). Signs out the account's other sessions; on an unconfirmed account it also confirms the email and removes any Spotify link |
| `/accounts/password/reset/done/` | `password_reset_complete` | Anyone | "Your password is changed" |
| `/accounts/login/` | `login` | Anonymous | Log in with email (or username) and password; unconfirmed accounts can't log in. Links to "Forgot your password?" and to resend the confirmation link |
| `/accounts/logout/` | `logout` | `POST` only | Log out (the Log out buttons submit a form) |
| `/accounts/password/set/` | `set_password` | Login required, only for accounts with no password (others are sent on) | Set a first password for an account made with "Sign up with Spotify" ([ADR-010](docs/adrs/adr-010.md)). Shown right after a Spotify sign-up's email is confirmed (then onboarding) and at every Spotify sign-in until a password is set; keeps the user logged in |
| `/onboarding/` | `onboarding` | Login required | Onboarding questionnaire (story D-2). Users who already finished it are sent to `/dashboard/` |
| `/dashboard/` | `dashboard` | Login required | Profile summary. Users who haven't finished onboarding are sent to `/onboarding/` |
| `/users/` | `user_profile` | Login required | The signed-in user's own profile only, with the Spotify section: "Link to Spotify", or "Spotify connected" with the Spotify name, a live connection status, and "Disconnect Spotify" |
| `/plans/workout/` | `workout` | Login required (onboarded users) | Today's workout screen ([ADR-015](docs/adrs/adr-015.md)): today's exercises and a "Start today's workout" button; once started, the music result: the playlist now playing, a "Link Spotify for music" button, or why it couldn't play with an "Open in Spotify" link. Rest days say so |
| `/plans/workout/start/` | `start_workout` | Login required, `POST` only; the Spotify part is rate limited | Start today's workout and play a Spotify playlist found for it on the user's active device ([ADR-014](docs/adrs/adr-014.md)). The workout starts whatever Spotify answers; the result is kept in the session and the user is redirected to `/plans/workout/` |
| `/plans/this-week/` | `this_week` | Login required (onboarded users) | This week's workout plan and daily macro targets ([ADR-012](docs/adrs/adr-012.md)): seven days, Monday first, with each training day's exercises, sets, and reps, rest days, today marked, and today's calories, protein, carbs, and fat. Generated from the onboarding profile on the first visit of the week and saved, so it stays the same all week, and the workout split rotates each week ([ADR-013](docs/adrs/adr-013.md)) and an AI trainer chooses the exercises when it is switched on ([ADR-014](docs/adrs/adr-014.md)); a starter plan (not saved) is shown if generation fails |
| `/plans/this-week/split/` | `change_split` | Login required (onboarded users), POST only | Switches this week's split to the one chosen, or to the next in rotation ("Switch it up"), up to 3 times a week; macro targets stay the same ([ADR-013](docs/adrs/adr-013.md)) |
| `/plans/nutrition/` | `nutrition` | Login required (onboarded users) | The daily macro targets from this week's plan, the same ones the Meal Plan aims at |
| `/meal-plan/` | `meal_plan` | Login required (onboarded users) | This week's meal plan (story D-5, [ADR-008](docs/adrs/adr-008.md)): a week strip to pick a day, that day's meals (chosen in onboarding) as cards with portion, kcal, and macros, each recipe's weighed ingredients and steps opening in place, the day's totals against its targets, the estimated grocery cost and an over-budget notice once grocery prices are connected (D-6), a notice for each fallback in use, and a "temporarily unavailable" state. `?day=` selects a day; `meal_plan.js` switches days without a reload. Showing the saved plan is never limited; when there is none for the current meal settings, making one takes the same limits as `/meal-plan/new/` (HTTP 429 when refused, [ADR-016](docs/adrs/adr-016.md)) |
| `/meal-plan/new/` | `meal_plan_new` | Login required, `POST` only | Replace this week's plan with a different one. Limited with every other planner run: one per user and two in total at a time, and 10 plans per user per hour ([ADR-016](docs/adrs/adr-016.md)); a refused request gets HTTP 429 with the saved plan and never runs the planner |
| `/spotify/link/`, `/spotify/login/`, `/spotify/signup/` | `spotify_link`, `spotify_login`, `spotify_signup` | `POST` only; link needs login, log in / sign up need a logged-out user and are rate limited | Start Spotify's OAuth flow (story D-7, [ADR-010](docs/adrs/adr-010.md)): store a single-use `state` in the session and redirect to Spotify's consent page |
| `/auth-callback/spotify` | `spotify_callback` | Anyone with a matching `state` | Spotify's redirect URI (no trailing slash; must match the Spotify dashboard). Checks `state`, handles `error=access_denied`, exchanges the code, calls `GET /v1/me`, then links, logs in, or signs up |
| `/spotify/disconnect/` | `spotify_unlink` | Login required, `POST` only | Delete the Spotify link and tokens; refused if Spotify is the user's only way to log in |
| `/spotify/status/` | `spotify_status` | Login required, rate limited | JSON connection test for the profile page (`GET /v1/me` through the token helper); never returns tokens. Over the limit it answers 429 with `Retry-After` and `state: rate_limited`, which the page shows as "not checked" without the reconnect help |
| `/grocery-list/` | `grocery_list` | Login required (onboarded users) | This week's grocery list (story D-6, [ADR-009](docs/adrs/adr-009.md)): the meal plan's ingredients combined (rice on Monday and Wednesday is listed once, in cups), with the amount to buy, an estimated cost per item and for the week, an over-budget notice, a note on how the list was made, and the unmeasured pantry items. With no meal plan this week, it asks the user to create one first. It reads only the signed-in user's own plan and never creates one |

### Acceptance scenarios
The Gherkin scenarios live in [`features/user_auth.feature`](features/user_auth.feature) (successful registration with email
confirmation, email already registered, wrong password, an unconfirmed account can't log in, resetting a forgotten
password, and the email can't be sent) and [`features/onboarding.feature`](features/onboarding.feature) (complete
onboarding, missing required answer, returning user skips onboarding), and [`features/weekly_plan.feature`](features/weekly_plan.feature) (see my plan, see my macro targets, plan generator
down, and the meal plan aiming at my macro targets), [`features/workout_variety.feature`](features/workout_variety.feature)
(a new split each week, picking or switching a split, the weekly switch limit, and splits that fit my equipment), [`features/workout_variety_ai.feature`](features/workout_variety_ai.feature)
(the AI trainer builds my week, invalid or unavailable AI falls back, nothing personal is sent), and [`features/meal_plan.feature`]
(plan within budget, budget too low, recipe service unavailable, plus the no-macro-targets and no-prices fallbacks), and
[`features/grocery_list.feature`](features/grocery_list.feature) (ingredients combined, empty week, plus a missing-prices fallback), and
[`features/spotify.feature`](features/spotify.feature) (link succeeds, user declines, unlink, log in with Spotify, sign up then set a password, the password prompt at every
Spotify sign-in for a Spotify-only account, and
log in never matching on email). Step
definitions are in `features/steps/`. Nothing calls the network: the connectors to D-4 and D-6 use the stand-ins in
`nutrition/testing.py`, Spotify's HTTP endpoints are replaced by `spotify.testing.FakeSpotify`, and the recipe catalog is loaded into the test database after migrations.
Django tests are in `accounts/tests.py` (registration, login, logout), `core/test_onboarding.py` (onboarding, dashboard,
and the login redirect), `core/tests.py` (models, health checks, and access control), `plans/tests.py`, `plans/test_workout_variety.py`, `plans/test_ai_trainer.py`, and `plans/test_macro_targets.py` (generator,
starter fallback, saved weeks, split rotation and switching, the AI trainer, the This Week and Nutrition pages, and the meal plan connector), and `nutrition/test_*.py` (meal
planner and pricing, recipe catalog and loader, connectors and fallbacks, Meal Plan page) and `grocery/test_*.py` (combining
and amounts, costs, the Grocery List page, and the price file) and `spotify/test_*.py` (state checks, link/login/signup rules, token refresh and relink, encryption at
rest, configuration, the status endpoint). Browser tests for the Meal Plan page and the Spotify flows are in `e2e/` (see Common Commands).

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
| Emails and usernames | Emails are trimmed, lowercased, and unique case-insensitively (a unique database index on `LOWER(email)`); usernames cannot contain `@`, so a username can never be mistaken for an email. Every account's email is confirmed by an emailed link before it can be used, and sign-up never says an email is taken: the address's owner is emailed instead ([ADR-018](docs/adrs/adr-018.md)); answers that a username is taken are capped per IP ([ADR-016](docs/adrs/adr-016.md)) |
| Sessions | The session key is rotated on login and registration (prevents session fixation); cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` behind the HTTPS proxy; sessions expire after 7 days |
| CSRF | Every form posts a CSRF token; Django rejects POSTs without one |
| Logout | `POST` only, so a third-party page cannot log a user out with a link or image |
| Redirects | The `next` parameter is only followed if it points at this site (no open redirects) |
| Access control | `/onboarding/`, `/dashboard/`, `/users/`, and the plan, meal plan, and grocery pages require login and read only the signed-in user's own data; `/users/` previously listed every user's profile and now shows only the signed-in user's own |
| Spotify sign-in | OAuth 2.0 Authorization Code flow on the server ([ADR-010](docs/adrs/adr-010.md)): a random, single-use, 10-minute `state` in the session; flows start with a CSRF-protected `POST`; accounts are matched on the Spotify user id only, never on the (unverified) email, and a refused sign-up gets a generic message that doesn't confirm whether an email has an account; the production access log omits query strings, so OAuth codes aren't logged; tokens are encrypted at rest with Fernet, never logged, and never sent to the browser; log in / sign up with Spotify and the connection test are rate limited |
| Rate limits | Database-backed, shared across pods, HTTP 429 with `Retry-After` ([ADR-006](docs/adrs/adr-006.md), [ADR-016](docs/adrs/adr-016.md)): 5 failed logins per identifier and IP and 100 per IP per 15 minutes; 50 registration attempts per IP per hour, of which at most 10 may be told a username is taken; meal plans (a new plan, or the page making one) limited to 1 run per user and 2 in total at a time, and 10 per user per hour; plus the Spotify and AI trainer limits below |
| HTTPS headers | `Strict-Transport-Security: max-age=3600` on HTTPS responses for this host only (no `includeSubDomains` or `preload`, [ADR-016](docs/adrs/adr-016.md)); `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin`, and `Cross-Origin-Opener-Policy: same-origin` pinned in `settings.py` |
| Account email | Sent through Resend ([ADR-017](docs/adrs/adr-017.md)) with a sending-only key read on the server only; at most 5 emails per address per hour (stored as a hash); every failure shows one generic message, while the cause (for example an exhausted quota) is logged on `fitpro.email` without the address, subject, body, or key; production never falls back to printing email, so links can't reach the logs; header values with newlines are refused |
| Confirmation and reset links | Signed with Django's token generator (separate salts), valid for 24 hours and single use; the confirmation link only acts on a POST, so mail scanners can't confirm accounts; a password reset signs out other sessions, and a reset that recovers an unconfirmed account removes any Spotify link so whoever created it can't log back in ([ADR-018](docs/adrs/adr-018.md)) |
| AI trainer | The OpenAI key is read only on the server (`.env` locally, a mounted secret in production), sent only in the `Authorization` header, and never put in a page, log line, or error message; tests are given no key; each user is rate limited; nothing personal is sent, and the answer is validated against our own exercise library before it is saved ([ADR-014](docs/adrs/adr-014.md)) |

### Known gaps (planned follow-ups)
* **Usernames can be discovered:** the sign-up form says when a username is taken, capped at 10 such answers per IP per
  hour ([ADR-016](docs/adrs/adr-016.md)). Emails can't be listed that way
  ([ADR-018](docs/adrs/adr-018.md)), but when an email can't be sent, the generic error shows on the sign-up and reset
  forms, which can reveal whether an address has an account (accepted, so people know to contact us).
* **Security assessment follow-ups** ([ADR-016](docs/adrs/adr-016.md)): no Content-Security-Policy yet, signed-in pages
  don't send `Cache-Control: no-store`, and responses carry a `server: gunicorn` header. HSTS starts at one hour and
  should be raised to a year once production has run cleanly with it.
* **Account email** ([ADR-017](docs/adrs/adr-017.md), [ADR-018](docs/adrs/adr-018.md)): Resend's free plan sends **100 emails a day** (resets at midnight UTC); after that, sign-ups and resets fail with the generic error until it resets. Emails are plain text, and there's no way to change an account's email yet.
* **No admin site.** It was removed ([ADR-007](docs/adrs/adr-007.md)); manage data with `manage.py shell` or a one-off Job. Re-adding it needs network-level restriction first.
* **Meal plan (D-5)** ([ADR-008](docs/adrs/adr-008.md)): meals aim at the weekly plan's macro targets (D-4, [ADR-012](docs/adrs/adr-012.md)), the same target every day of the week. Until the week's plan exists (the first visit to This Week or Nutrition creates it), meals use the FDA Daily Values (2,000 kcal) and the page says so. D-6's price source is connected but prices only 54 of the 55 ingredients. When meal suggestions are unavailable, the notice links to This Week. The catalog has 25 recipes with no dietary filters yet, nutrients come from USDA SR Legacy (2018), and pantry staples aren't counted. "Today" and the week boundary use the server's time zone (UTC).
* **Grocery list (D-6)** ([ADR-009](docs/adrs/adr-009.md)): prices come from `grocery/data/price_quotes.json`, which has real, cited U.S. average prices for 54 of the 55 ingredients, so the list shows those costs. BLS quotes 9 and Walmart quotes the rest. Green-onions is the one thats not priced and is unpriced because it is sold by the bunch with no weight. Amounts are rounded for shopping, pantry staples aren't measured or priced, and there are no "got it" checkboxes yet. Baked potato chili recipe isn't fully priced because it uses green onions.

* **Spotify (D-7)** ([ADR-010](docs/adrs/adr-010.md)): while the Spotify app is in **Development Mode, only 5 Spotify
  users can authorize it**, and each must be added to the app's allowlist in the Spotify developer dashboard; anyone else
  gets an error from Spotify. Production uses the redirect URI `https://fitpro-app.tech/auth-callback/spotify`.

* **Weekly plan and macro targets** ([ADR-012](docs/adrs/adr-012.md)): onboarding doesn't ask for age or sex, so the
  calorie estimate assumes age 25 and a sex-neutral constant; a profile change applies from the next week's plan.
  Switching split keeps the week's saved macro targets, and full body is only offered to 3-day plans
  ([ADR-013](docs/adrs/adr-013.md)).

* **AI trainer** ([ADR-014](docs/adrs/adr-014.md)): off unless `OPENAI_API_KEY` is set. It only chooses exercises from our
  own library, so variety is limited until the library grows, and the first visit of a week (or a split switch) can wait
  up to 15 seconds for OpenAI before falling back to the rule-based plan. The production secret isn't set up yet, so
  production uses the rule-based plan.

* **Password hashing** uses Django's default; Argon2 is a possible upgrade (needs the `argon2-cffi` dependency).

## Spotify integration
User story **D-7**: link a Spotify account, and log in or sign up with Spotify, so later features can build playlists and
control playback. The `spotify` app uses Spotify's OAuth 2.0 Authorization Code flow, handled by the backend
([ADR-010](docs/adrs/adr-010.md)).

* **Set up:** in the [Spotify developer dashboard](https://developer.spotify.com/dashboard), register the redirect URI
  `http://127.0.0.1:8000/auth-callback/spotify` (and the production one, `https://<host>/auth-callback/spotify`), then
  set `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI`, and `SPOTIFY_TOKEN_ENCRYPTION_KEY` in
  `.env` (see `.env.example`). With none set, the Spotify buttons are hidden; with only some set, the app won't start
  and the error names what's missing.
* **Development Mode limit:** while the Spotify app is in Development Mode, at most **5 Spotify users** can authorize
  it, and each one has to be added under *User Management* in the dashboard first.
* **For later features:** call `spotify.services.get_access_token(user)` for a valid access token (it refreshes and
  handles revocation). Never read `SpotifyAccount.access_token` directly, and never log or render a token.
**Workout playlist** ([ADR-014](docs/adrs/adr-014.md)): playback only works for Spotify **Premium** accounts with a
  Spotify app open on some device; everyone else gets an "Open in Spotify" link. The playlist is the first public
  playlist Spotify's search returns for the workout's name, not one built for the user, and starting a workout isn't
  recorded anywhere yet.

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
* Application logs, including tracebacks and `accounts.security` throttling warnings, go to stdout and are collected by Cloud Logging. Gunicorn's access log (`gunicorn.conf.py`) records paths without query strings or referrers, so one-time values such as Spotify's OAuth `code` never reach the logs.
* Deploys are gated by CI, a container smoke test, and a migration Job; `scripts/rollback.sh` reverts a bad release.

Alerting and response: monitoring and alerts are currently handled through Google Cloud Monitoring and the Google Cloud mobile app. Caleb Harris owns the infrastructure and is the responsible party for responding to and fixing incidents.

### Implemented (Terraform, `terraform_scripts/`)
| Area | Resources |
| --- | --- |
| Networking | Custom VPC `fitpro-vpc`, subnet `fitpro-gke` (10.10.0.0/20, pods 10.20.0.0/16, services 10.30.0.0/20), Private Google Access, private services peering for Cloud SQL |
| Compute | GKE Autopilot cluster `fitpro` (REGULAR release channel, Gateway API enabled, Workload Identity, deletion protection) running as a dedicated least-privilege node service account |
| Database | Cloud SQL `fitpro-pg` (PostgreSQL 16, `db-f1-micro`, zonal): private IP only, encrypted connections only, Cloud SQL Auth Proxy/connector required, daily backups (7 retained) + point-in-time recovery, Sunday 09:00 UTC maintenance window, deletion protection. Database `fitpro`, user `fitpro_app` |
| Secrets | Secret Manager `fitpro-db-password`, `fitpro-django-secret-key`, and `fitpro-spotify-token-encryption-key` (randomly generated), and `fitpro-spotify-client-secret` and `fitpro-resend-api-key` (created empty; their values are added with `gcloud` so they never enter Terraform state, see below). Only the app service account can read them (per-secret binding), and secret reads are written to Data Access audit logs |
| Identity | Runtime service account `fitpro-app` (`cloudsql.client` + per-secret `secretAccessor`), bound by Workload Identity to Kubernetes service account `app/django-app`. No service account keys exist |
| Images | Artifact Registry `fitpro` (Docker, `us-central1`) with immutable tags, keeping the 15 most recent images and deleting anything older than 30 days |
| Ingress / TLS | Reserved global static IP `fitpro-lb-ip`, Google-managed certificate through Certificate Manager (DNS authorization) and certificate map `fitpro-certmap` for `fitpro-app.tech`, plus one for the old `fitpro.rockymountaintechlab.com`, which the Gateway only redirects to the new domain (DNS only in Cloudflare, see [ADR-004](docs/adrs/adr-004.md) and [ADR-011](docs/adrs/adr-011.md)), SSL policy `fitpro-ssl-policy` (TLS 1.2+, MODERN profile) |

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

### Spotify secrets in production
`secrets.tf` generates the token encryption key and creates an **empty** `fitpro-spotify-client-secret`, because the
value is issued by Spotify and putting it in `terraform.tfvars` would also put it in the state file. After
`terraform apply`, add it once (paste the secret from the Spotify dashboard, then end the input with Ctrl-D, or
Ctrl-Z and Enter on Windows):

```shell
gcloud secrets versions add fitpro-spotify-client-secret --data-file=-
gcloud secrets versions list fitpro-spotify-client-secret   # one ENABLED version
```

`k8s/app/base/secretproviderclass.yaml` mounts both secrets (paths `spotify-client-secret` and
`spotify-token-encryption-key`), and the prod ConfigMap sets `SPOTIFY_CLIENT_ID` and `SPOTIFY_REDIRECT_URI`, so the
client secret must have a version **before** those manifests are deployed. A mounted secret with no version stops pods
(and the migrate Job) from starting, and the app refuses to start with only some Spotify settings. Register
`https://fitpro-app.tech/auth-callback/spotify` in the Spotify dashboard too.

### Resend API key in production
`secrets.tf` also creates an **empty** `fitpro-resend-api-key` ([ADR-017](docs/adrs/adr-017.md)). In Resend, create an
API key with **Sending access** restricted to the FitPro domain, then add it the same way:

```shell
gcloud secrets versions add fitpro-resend-api-key --data-file=-
gcloud secrets versions list fitpro-resend-api-key   # one ENABLED version
```

`k8s/app/base/secretproviderclass.yaml` mounts it at `resend-api-key`, so it also needs a version **before** those
manifests are deployed, or pods and the migrate Job won't start. The sender defaults to
`FitPro <no-reply@fitpro-app.tech>`; set `DEFAULT_FROM_EMAIL` in the prod ConfigMap if the verified domain is
different. The Resend account is a dedicated FitPro account, owned by Caleb Harris. Daily usage is on Resend's
dashboard, and the `fitpro.email` logger reports an exhausted quota at ERROR.

After the first apply, add the `dns_authorization_records` CNAME and an A record pointing at `lb_ip_address` in
Cloudflare (DNS only / gray cloud). The Kubernetes Gateway uses `lb_ip_name` as its address, `certificate_map_name` in the
`networking.gke.io/certmap` annotation, and `ssl_policy_name` in a `GCPGatewayPolicy`.

### Teardown (end of semester)
Set `deletion_protection = false` on the cluster and the Cloud SQL instance (both settings), run `terraform apply`, then
`terraform destroy`. Then delete the Resend account (or its API key and domain) and the domain's Resend DNS records
in Cloudflare.

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
| Claude | Savannah Harmony Swan | Claude Code implemented story D-6 (grocery list): the `grocery` app with the Grocery List page, ingredient combining and cup/count/pound amounts, whole-package costing that matches the meal plan, the price source and its validated file of cited BLS and Walmart price quotes, unit/page/Gherkin tests, ADR-009, and pinned three D-5 tests to the not-connected prices |
| Claude | Caleb Harris | Claude Code implemented story D-7 (Spotify integration): the `spotify` app with the backend OAuth Authorization Code flow for link, log in, and sign up, encrypted token storage and the refresh helper, the profile connection status pill, unit/Gherkin/Playwright tests, ADR-010, and these README updates |
| Claude | Caleb Harris | Claude Code added the production Spotify secrets to `terraform_scripts/secrets.tf` (generated token encryption key, empty client secret filled with `gcloud`, per-secret access for the app) and the README steps for them |
| Claude | Caleb Harris | Claude Code planned the move to `fitpro-app.tech`: ADR-011 (two-step, no-downtime cutover), the ADR-004 update note, and the README, deployment doc, tfvars example, and architecture diagram updates; and switched Spotify on in production (secret mounts and ConfigMap values) |
| Claude | Caleb Harris | Claude Code added the Gateway redirect from `fitpro.rockymountaintechlab.com` to `fitpro-app.tech`, removed the old host from the app routes and Django host settings, and recorded it in ADR-011 |
| Claude | Caleb Harris | Claude Code applied the PR #36 review: connected the weekly plan's macro targets to the meal plan (`plans.macro_targets.PlanMacroTargets` and its tests, a Gherkin scenario, the pinned fallback tests), added `plans` to coverage, wrote ADR-012, and updated the README routes and docs; then kept the Daily Values until a week's plan is saved, linked the unavailable notice to This Week, and removed the finished connector note from AGENTS.md |
| Claude | Savannah Harmony Swan | Claude Code implemented the workout playlist story: Spotify playlist search and start playback in `spotify/client.py`, `start_workout_music` and its rate limit, the `/plans/workout/` screen and start button, `features/workout_music.feature`, unit tests, ADR-015, and these README updates |
| Claude | Nathan Galay | Claude (chat) implemented week-to-week workout variety (split styles, weekly rotation, switching, ADR-013) and the AI trainer that chooses exercises through OpenAI (`plans.ai_trainer`, the throttle scope and settings, tests, Gherkin scenarios, and ADR-014) |
| Claude | Caleb Harris | Claude Code compared the 2026-11-19 security assessment against the repo and implemented F-1 (per-user limit on new meal plans), F-2 (higher shared-IP login and registration limits) and HSTS from F-4, with regression tests, ADR-016, the ADR-006 update note, and these README updates |
| Claude | Caleb Harris | Claude Code applied the PR #61 review: an in-flight limit on new meal plans shared across pods (`accounts.throttle.meal_plan_slot`, `MEAL_PLAN_CONCURRENCY`), refused requests rendered from the saved plan without running the planner (`nutrition.services.saved_meal_plan`), the same limits on plans the Meal Plan page makes itself (`nutrition.views._run_planner`), a separate cap on registration answers that reveal an account (`register_taken`), keeping the selected day on a refused new plan, regression tests including parallel requests on PostgreSQL, and the ADR-016, ADR-006, ADR-008 and README updates |
| Claude | Caleb Harris | Claude Code implemented Resend email (ADR-017): the `core.mail.ResendEmailBackend` over Resend's HTTP API with quota, rate-limit, and failure logging, `accounts.emails.send_account_email` with the per-recipient limit and generic message, the settings, Terraform secret, secret mount, CI `check --deploy` mail check, mocked tests, and these README updates |
| Claude | Caleb Harris | Claude Code implemented email confirmation for every sign-up (password and Spotify) and password reset (ADR-018): the `accounts` views, token generator, services, emails, and templates, the Spotify sign-up and login changes, the reset recovery that removes a claimer's Spotify link, unit/Gherkin/Playwright test updates, and these README updates |

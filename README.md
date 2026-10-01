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
* **DB:** TBD
* **Production Host:** TBD
* **Base Docker Image:** TBD

## Getting Started
> [!Note]
> If you don't have uv installed, run `curl -LsSf https://astral.sh/uv/install.sh | sh`

* Clone repo: `git clone git@github.com:CS4300-CS5300-FA26/team-1.git`
* `cd team-1`
* `cp .env.example .env`
* `uv sync`
* `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` - Put value in .env
* `uv run python manage.py migrate`
* `uv run python manage.py runserver`
> [!tip]
> In DevEdu, port 8000 isn't available, so do this instead: `uv run python manage.py runserver 0.0.0.0:3000`

## Common Commands
* `uv run python manage.py runserver` [Starts the Django development server]
* `uv run python manage.py makemigrations` [Creates new database migrations]
* `uv run python manage.py migrate` [Applies database migrations]
* `uv run python manage.py test` [Runs Django tests]

## Contributing
* Branch naming: `feature/<short-description>`, `fix/<short-description>`
* Changes to **main** must come through a PR and must be approved by at least one other team member.
* [TBD linting tool maybe?]

# AI Usage

| LLM | Contributor | Usage | Transcript |
| --- | --- | --- | --- |
| Pardot | Caleb Harris | Validated issues created in GitHub against Sprint 0-2 Requirements | n/a |
| Claude | Caleb Harris | Generated Lo-Fi wireframe given spec | Used `agents` tab in Figma |
| Pardot | Caleb Harris | PR Review | [Link](https://github.com/CS4300-CS5300-FA26/team-1/pull/16) |

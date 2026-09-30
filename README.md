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
* **Web Framework:** Django
* [TBD - what database, dependency manager, etc.]

## Getting Started
> [!Note]
> If you don't have uv installed, run `curl -LsSf https://astral.sh/uv/install.sh | sh`

* Clone repo: `git clone git@github.com:CS4300-CS5300-FA26/team-1.git`
* `cd team-1`
* `cp .env.example .env` [We dont have the spicy secrets file yet, but this will likely be the first step before writing]
* `uv sync`
* `uv run python manage.py migrate`
* `uv run python manage.py runserver`

## Common Commands
* `python manage.py runserver` [Starts the Django development server]
* `python manage.py makemigrations` [Creates new database migrations]
* `python manage.py migrate` [Applies database migrations]
* `python manage.py test` [Runs Django tests]

## Contributing
* Branch naming: `feature/<short-description>`, `fix/<short-description>`
* Changes to **main** must come through a PR and must be approved by at least one other team member.
* [TBD linting tool maybe?]

# AI Usage

| LLM | Contributor | Usage | Transcript |
| --- | --- | --- | --- |
| Pardot | Caleb Harris | Validated issues created in GitHub against Sprint 0-2 Requirements | n/a |
| Claude | Caleb Harris | Generated Lo-Fi wireframe given spec | Used `agents` tab in Figma |

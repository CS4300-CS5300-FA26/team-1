# Project Initial Setup
This document will describe the initial setup process and commands ran to spin up a django project with UV.

> [!Note]
> If you don't have uv installed, run `curl -LsSf https://astral.sh/uv/install.sh | sh`

```shell
uv init --no-package --python 3.12
uv add django
uv add djangorestframework
uv add --dev pytest-django
uv run django-admin startproject fitpro .
uv run python manage.py runserver
```

## Local PostgreSQL (optional)
SQLite works for local development, but production runs PostgreSQL. To match it, run PostgreSQL in Docker and
create a login role that can also create the test database (`manage.py test` creates and drops `test_<name>`):

```shell
docker run -d --name postgres-dev -p 5432:5432 -e POSTGRES_PASSWORD=<superuser-password> postgres:18
docker exec -it postgres-dev psql -U postgres -c "CREATE ROLE fitpro LOGIN CREATEDB PASSWORD '<app-password>';"
docker exec -it postgres-dev psql -U postgres -c "CREATE DATABASE fitpro OWNER fitpro;"
```

Then in `.env`:

```shell
DB_ENGINE=django.db.backends.postgresql
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=fitpro
DB_USER=fitpro
DB_PASSWORD=<app-password>
```

and run `uv run python manage.py migrate`, which also loads the recipe catalog (ADR-008).

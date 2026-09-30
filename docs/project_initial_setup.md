# Project Initial Setup
This document will describe the initial setup process and commands ran to spin up a django project with UV.

```shell
uv init --no-package --python 3.12
uv add django
uv add djangorestframework
uv add --dev pytest-django
uv run django-admin startproject fitpro .
uv run python manage.py runserver
```

"""Gunicorn settings for the production image (the Dockerfile's CMD passes --config gunicorn.conf.py).

The access log goes to stdout and from there to Cloud Logging. It records the path **without the query string**, and
no referrer: query strings can carry one-time secrets, such as the `code` and `state` Spotify sends to
/auth-callback/spotify (ADR-010), as well as user input. Gunicorn's default format logs both through `%(r)s` (the full
request line) and `%(f)s` (the referrer). See https://docs.gunicorn.org/en/stable/settings.html#access-log-format
"""

accesslog = '-'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(a)s"'

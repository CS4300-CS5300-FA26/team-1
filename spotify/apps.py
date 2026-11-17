from django.apps import AppConfig


class SpotifyConfig(AppConfig):
    name = 'spotify'

    def ready(self):
        from .config import check_startup_config

        check_startup_config()

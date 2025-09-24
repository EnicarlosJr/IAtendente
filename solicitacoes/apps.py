from django.apps import AppConfig


class SolicitacoesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'solicitacoes'

    def ready(self):
        from . import signals  # noqa
# config/urls.py
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # Páginas web
    path("", include(("painel.urls", "painel"), namespace="painel")),
    path("solicitacoes/", include(("solicitacoes.urls", "solicitacoes"), namespace="solicitacoes")),
    path("clientes/", include(("clientes.urls", "clientes"), namespace="clientes")),
    path("agendamentos/", include(("agendamentos.urls", "agendamentos"), namespace="agendamentos")),
    path("servicos/", include("servicos.urls", namespace="servicos")),
    # API
    path("api/solicitacoes/", include(("solicitacoes.api_urls", "api_solicitacoes"), namespace="api_solicitacoes")),

    # Autenticação (login/logout/password reset padrão do Django)
    path("accounts/", include("django.contrib.auth.urls")),
]

# Servir arquivos estáticos e de mídia em desenvolvimento
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=getattr(settings, "STATIC_ROOT", None))
    urlpatterns += static(settings.MEDIA_URL, document_root=getattr(settings, "MEDIA_ROOT", None))

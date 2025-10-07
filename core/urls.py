# core/urls.py
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from painel import views as painel_views

from barbearias import views as accounts_views  # para custom logout
urlpatterns = [
    path("admin/", admin.site.urls),

    # -------- PÚBLICO --------
    path("barbearias/", include(("barbearias.urls", "barbearias"), namespace="barbearias")),
    path("pub/", include(("barbearias.urls_public", "public"), namespace="public")),
    # -------- SISTEMA --------
    path("", painel_views.home, name="home"),
    path("painel/", include(("painel.urls", "painel"), namespace="painel")),

    # Tudo com shop_slug
    path("<slug:shop_slug>/clientes/", include(("clientes.urls", "clientes"), namespace="clientes")),
    path("<slug:shop_slug>/solicitacoes/", include(("solicitacoes.urls", "solicitacoes"), namespace="solicitacoes")),
    path("<slug:shop_slug>/agendamentos/", include(("agendamentos.urls", "agendamentos"), namespace="agendamentos")),
    path("<slug:shop_slug>/servicos/", include(("servicos.urls", "servicos"), namespace="servicos")),

    # -------- API --------
    path("<slug:shop_slug>/api/solicitacoes/", include(("solicitacoes.api_urls", "api_solicitacoes"))),

    # -------- AUTENTICAÇÃO --------
    path("conta/", include(("barbearias.urls_auth", "barbearias_auth"), namespace="barb_auth")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=getattr(settings, "STATIC_ROOT", None))
    urlpatterns += static(settings.MEDIA_URL, document_root=getattr(settings, "MEDIA_ROOT", None))

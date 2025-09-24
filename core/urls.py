from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from painel import views as painel_views
from solicitacoes.api_views import SolicitacaoIntakeView

urlpatterns = [
    path("admin/", admin.site.urls),

    # -------- PÚBLICO --------
    # Rotas públicas (ex: página de cada barbearia, landing page etc.)
    path("barbearias/", include(("barbearias.urls", "barbearias"), namespace="barbearias")),

    # -------- SISTEMA --------
    path("", painel_views.home, name="home"),
    path("painel/", include(("painel.urls", "painel"), namespace="painel")),

    # Agora todos os apps dependem de um shop_slug
    path("<slug:shop_slug>/clientes/", include(("clientes.urls", "clientes"), namespace="clientes")),
    path("<slug:shop_slug>/solicitacoes/", include(("solicitacoes.urls", "solicitacoes"), namespace="solicitacoes")),
    path("<slug:shop_slug>/agendamentos/", include(("agendamentos.urls", "agendamentos"), namespace="agendamentos")),
    path("<slug:shop_slug>/servicos/", include(("servicos.urls", "servicos"), namespace="servicos")),

    # -------- API --------
    path("<slug:shop_slug>/api/solicitacoes/", include(("solicitacoes.api_urls", "api_solicitacoes"))),
    

    # -------- AUTENTICAÇÃO --------
    path("accounts/", include("django.contrib.auth.urls")),  # login/logout/password reset
]

# -------- ESTÁTICOS & MÍDIA (dev) --------
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=getattr(settings, "STATIC_ROOT", None))
    urlpatterns += static(settings.MEDIA_URL, document_root=getattr(settings, "MEDIA_ROOT", None))

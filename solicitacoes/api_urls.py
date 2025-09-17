# solicitacoes/api_urls.py
from django.urls import path
from .api_views import SolicitacaoIntakeView

app_name = "api_solicitacoes"

urlpatterns = [
    path("intake/", SolicitacaoIntakeView.as_view(), name="intake"),
]

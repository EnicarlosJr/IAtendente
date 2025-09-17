# solicitacoes/urls.py
from django.urls import path
from . import views_web

app_name = "solicitacoes"

urlpatterns = [
    path("", views_web.solicitacoes, name="solicitacoes"),
    path("<int:pk>/", views_web.detalhe, name="detalhe"),

    # Ações
    path("<int:pk>/confirmar/", views_web.confirmar_solicitacao, name="confirmar"),
    path("<int:pk>/recusar/", views_web.recusar_solicitacao, name="recusar"),
    path("<int:pk>/finalizar/", views_web.finalizar_solicitacao, name="finalizar"),
    path("<int:pk>/no-show/", views_web.marcar_no_show, name="no_show"),
    path("<int:pk>/status/", views_web.alterar_status, name="alterar_status"),
]

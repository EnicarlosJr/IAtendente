from django.urls import path
from . import views

app_name = "painel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("solicitacoes/", views.solicitacoes, name="solicitacoes"),
]

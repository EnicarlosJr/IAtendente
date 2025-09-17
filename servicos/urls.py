# servicos/urls.py
from django.urls import path
from . import views


app_name = "servicos"

urlpatterns = [
    # Tabela de preços (lista principal)
    path("", views.servicos_lista, name="lista"),

    # CRUD
    path("novo/", views.servico_novo, name="novo"),
    path("<int:pk>/", views.servico_detalhe, name="detalhe"),
    path("<int:pk>/editar/", views.servico_editar, name="editar"),

    # Ativação / desativação (arquivar/restaurar)
    path("<int:pk>/ativar/", views.ativar, name="ativar"),
    path("<int:pk>/desativar/", views.desativar, name="desativar"),

    # Lista de serviços inativos (arquivados)
    path("inativos/", views.inativos, name="inativos"),

    # Alternar ativo/inativo via AJAX
    path("<int:pk>/toggle-ativo/", views.servicos_toggle_ativo, name="toggle_ativo"),
]

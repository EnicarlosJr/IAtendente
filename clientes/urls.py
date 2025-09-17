# clientes/urls.py
from django.urls import path
from . import views_web as web
#from . import views_api as api

app_name = "clientes"

urlpatterns = [
    # Web
    path("", web.clientes_list, name="lista"),
    path("novo/", web.cliente_new, name="novo"),
    path("<int:pk>/", web.cliente_detail, name="detalhe"),
    path("<int:pk>/editar/", web.cliente_edit, name="editar"),
    path("<int:pk>/historico/add/", web.cliente_add_historico, name="add_historico"),
    path("<int:pk>/corte-hoje/", web.cliente_corte_hoje, name="corte_hoje"),

    # API
    #path("api/", api.ClienteListCreateAPI.as_view(), name="api_lista_cria"),
    #path("api/<int:pk>/", api.ClienteDetailAPI.as_view(), name="api_detalhe"),
    #path("api/<int:cliente_id>/historico/", api.HistoricoListCreateAPI.as_view(), name="api_hist_lista_cria"),
    #path("api/historico/<int:pk>/", api.HistoricoDetailAPI.as_view(), name="api_hist_detalhe"),
]

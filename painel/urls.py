# painel/urls.py
from django.urls import path
from . import views            # contém: home, agenda, clientes, solicitacoes, e o redirect do dashboard
from . import views_dashboard  # contém: dashboard_operacional e dashboard_gerencial

app_name = "painel"

urlpatterns = [
    # ======================================================
    # LANDING DO PAINEL
    # ======================================================
    # /painel/  -> manda pro dashboard (redirect p/ operacional)
    path("", views.dashboard, name="dashboard"),

    # Mantém também /painel/dashboard/ caso alguém aponte direto
    path("dashboard/", views.dashboard, name="dashboard_redirect"),

    # ======================================================
    # NOVO DASHBOARD — OPERACIONAL (p/ o barbeiro)
    # ======================================================
    # /painel/dashboard/op/
    path("dashboard/op/", views_dashboard.dashboard_operacional, name="dashboard_op"),
    # /painel/dashboard/op/<shop_slug>/
    path("dashboard/op/<slug:shop_slug>/", views_dashboard.dashboard_operacional, name="dashboard_op_slug"),

    # ======================================================
    # NOVO DASHBOARD — GERENCIAL (visão do mês)
    # ======================================================
    # /painel/dashboard/mgmt/
    path("dashboard/mgmt/", views_dashboard.dashboard_gerencial, name="dashboard_mgmt"),
    # /painel/dashboard/mgmt/<shop_slug>/
    path("dashboard/mgmt/<slug:shop_slug>/", views_dashboard.dashboard_gerencial, name="dashboard_mgmt_slug"),

    # ======================================================
    # PÁGINAS AUXILIARES DO PAINEL (opcionais)
    # Mantêm a compatibilidade com telas internas do painel
    # (essas usam a barbearia padrão do usuário)
    # ======================================================
    path("agenda/", views.agenda, name="agenda"),
    path("clientes/", views.clientes, name="clientes"),
    path("solicitacoes/", views.solicitacoes, name="solicitacoes"),
]

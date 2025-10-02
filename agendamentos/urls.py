from django.urls import path

from agendamentos import views, views_agenda_padrao


app_name = "agendamentos"

urlpatterns = [
    # Redirect raiz do módulo (/<shop_slug>/agendamentos/) para a visão semanal
    path("", views.agenda_redirect, name="agenda"),
    
    path("agenda1/", views_agenda_padrao.agenda_visao, name="agenda1"),

    # Agendas
    path("dia/", views.agenda_dia, name="agenda_dia"),
    path("semana/", views.agenda_semana, name="agenda_semana"),
    path("mes/", views.agenda_mes, name="agenda_mes"),

    # Configuração do barbeiro (minha agenda)
    path("minha-agenda/", views.minha_agenda_config, name="minha_agenda_config"),

    # Novo agendamento (manual, confirmado)
    path("novo/<int:solicitacao_id>/", views.agendamento_novo, name="agendamento_novo_para_solicitacao"),
    path("novo/", views.agendamento_novo, name="agendamento_novo"),

    # Ações sobre agendamentos
    path("finalizar/<int:pk>/", views.finalizar, name="finalizar"),
    path("no-show/<int:pk>/", views.no_show, name="no_show"),
]

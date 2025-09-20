from django.urls import path
from . import views

app_name = "agendamentos"

urlpatterns = [
    path("", views.agenda_redirect, name="agenda"),          # /agenda/ → semana
    path("dia/", views.agenda_dia, name="agenda_dia"),
    path("semana/", views.agenda_semana, name="agenda_semana"),
    path("mes/", views.agenda_mes, name="agenda_mes"),
    path("minha-agenda/", views.minha_agenda_config, name="minha_agenda_config"),
    path("novo/<int:solicitacao_id>/", views.agendamento_novo, name="agendamento_novo_para_solicitacao"),
    path("novo/", views.agendamento_novo, name="agendamento_novo"),

]

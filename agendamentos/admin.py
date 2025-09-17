# agendamentos/admin.py
from django.contrib import admin
from .models import Agendamento

@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display  = ("inicio", "fim", "status", "cliente_nome", "servico_nome")
    list_filter   = ("status", "cliente")
    search_fields = ("cliente_nome", "servico_nome", "observacoes")
    ordering      = ("-inicio",)

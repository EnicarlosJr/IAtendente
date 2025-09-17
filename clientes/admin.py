# clientes/admin.py
from django.contrib import admin
from .models import Cliente, HistoricoItem

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "recorrencia_status", "ultimo_corte", "created_at")
    list_filter = ("recorrencia_status",)
    search_fields = ("nome", "telefone")
    ordering = ("nome",)

@admin.register(HistoricoItem)
class HistoricoItemAdmin(admin.ModelAdmin):
    list_display = ("cliente", "servico", "data", "valor", "faltou", "created_at")
    list_filter = ("faltou",)
    search_fields = ("cliente__nome", "servico")
    ordering = ("-data",)

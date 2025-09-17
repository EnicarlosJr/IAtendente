# servicos/admin.py
from django.contrib import admin, messages
from django.http import HttpResponse
import csv

from .models import Servico


@admin.register(Servico)
class ServicoAdmin(admin.ModelAdmin):
    # Lista
    list_display = ("nome", "categoria", "preco", "duracao_min", "ativo", "updated_at")
    list_filter = ("categoria", "ativo")
    search_fields = ("nome", "descricao")
    ordering = ("nome",)
    list_per_page = 50

    # Edição rápida na listagem
    list_editable = ("preco", "duracao_min", "ativo")

    # Form
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("nome", "categoria", "descricao")}),
        ("Preço e duração", {"fields": ("preco", "duracao_min")}),
        ("Status", {"fields": ("ativo",)}),
        ("Auditoria", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )

    # Qualidades de vida
    save_as = True  # habilita "Save as new" para duplicar rapidamente
    actions = ("ativar", "desativar", "duplicar", "exportar_csv")

    # Ações
    def ativar(self, request, queryset):
        n = queryset.update(ativo=True)
        self.message_user(request, f"{n} serviço(s) ativado(s).", level=messages.SUCCESS)
    ativar.short_description = "Ativar selecionados"

    def desativar(self, request, queryset):
        n = queryset.update(ativo=False)
        self.message_user(request, f"{n} serviço(s) desativado(s).", level=messages.SUCCESS)
    desativar.short_description = "Desativar selecionados"

    def duplicar(self, request, queryset):
        created = 0
        for s in queryset:
            s.pk = None
            s.nome = f"{s.nome} (cópia)"
            s.ativo = False
            s.save()
            created += 1
        self.message_user(request, f"{created} cópia(s) criada(s) como inativas.", level=messages.SUCCESS)
    duplicar.short_description = "Duplicar como inativo(s)"

    def exportar_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="servicos_selecionados.csv"'
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["nome", "categoria", "duracao_min", "preco", "ativo"])
        for s in queryset.order_by("nome"):
            writer.writerow([
                s.nome,
                s.get_categoria_display(),
                s.duracao_min,
                f"{s.preco:.2f}",
                1 if s.ativo else 0,
            ])
        return response
    exportar_csv.short_description = "Exportar CSV (selecionados)"

# solicitacoes/admin.py
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib import admin, messages
from django.utils import timezone

from .models import Solicitacao, SolicitacaoStatus


# --- Inline opcional do Agendamento (se o app existir) -----------------------
Agendamento = None
try:
    Agendamento = apps.get_model("agendamentos", "Agendamento")
except Exception:
    Agendamento = None


if Agendamento:
    class AgendamentoInline(admin.StackedInline):
        model = Agendamento
        fk_name = "solicitacao"
        extra = 0
        can_delete = False
        classes = ["collapse"]
        readonly_fields = (
            "cliente", "cliente_nome",
            "barbeiro",
            "servico", "servico_nome",
            "preco_cobrado",
            "inicio", "fim",
            "status",
            "created_at", "updated_at",
        )
        fields = (
            ("cliente", "cliente_nome"),
            ("barbeiro",),
            ("servico", "servico_nome", "preco_cobrado"),
            ("inicio", "fim", "status"),
            ("created_at", "updated_at"),
        )


# --- Admin da Solicitação -----------------------------------------------------
@admin.register(Solicitacao)
class SolicitacaoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente_display",
        "telefone",
        "servico_display",
        "inicio",
        "fim",
        "status",
        "barbeiro",
        "criado_em",
    )
    list_filter = (
        "status",
        "barbeiro",
        "servico",
        ("criado_em", admin.DateFieldListFilter),
    )
    search_fields = (
        "nome",
        "telefone",
        "id_externo",
        "servico__nome",
        "servico_nome",
        "observacoes",
    )
    ordering = ("-criado_em",)
    date_hierarchy = "criado_em"

    readonly_fields = ("criado_em", "updated_at")
    fieldsets = (
        ("Identificação", {
            "fields": (("cliente", "barbeiro"), ("nome", "telefone"))
        }),
        ("Serviço & preço", {
            "fields": (("servico", "servico_nome"), ("preco_cotado", "duracao_min_cotada"))
        }),
        ("Agenda & status", {
            "fields": (("inicio", "fim"), "status")
        }),
        ("Integrações / Observações", {
            "fields": (("id_externo", "callback_url"), "observacoes")
        }),
        ("Metadados", {
            "classes": ("collapse",),
            "fields": (("criado_em", "updated_at"),)
        }),
    )

    actions = ["action_confirmar", "action_negar", "action_finalizar", "action_no_show"]

    if Agendamento:
        inlines = [AgendamentoInline]

    # ---------- Displays ----------
    @admin.display(description="Cliente")
    def cliente_display(self, obj: Solicitacao):
        if obj.cliente_id and getattr(obj.cliente, "nome", None):
            return obj.cliente.nome
        return obj.nome or "—"

    @admin.display(description="Serviço")
    def servico_display(self, obj: Solicitacao):
        try:
            return (obj.servico.nome if obj.servico_id else None) or (obj.servico_nome or "—")
        except Exception:
            return obj.servico_nome or "—"

    # ---------- Helpers internos ----------
    def _duracao_min(self, s: Solicitacao, default=30) -> int:
        if s.duracao_min_cotada:
            return int(s.duracao_min_cotada)
        try:
            d = getattr(getattr(s, "servico", None), "duracao_min", None)
            return int(d) if d else default
        except Exception:
            return default

    def _calc_fim(self, s: Solicitacao):
        if s.fim:
            return s.fim
        if s.inicio:
            return s.inicio + timedelta(minutes=self._duracao_min(s))
        return None

    def _criar_historico(self, s: Solicitacao, *, faltou=False):
        """
        Registra em clientes.HistoricoItem se o app 'clientes' existir.
        """
        try:
            Cliente = apps.get_model("clientes", "Cliente")
            HistoricoItem = apps.get_model("clientes", "HistoricoItem")
        except Exception:
            return

        tel = (s.telefone or "").strip()
        nome = (s.nome or tel or "Cliente").strip()
        cli = None

        if tel:
            cli, _ = Cliente.objects.get_or_create(telefone=tel, defaults={"nome": nome})
        else:
            cli = Cliente.objects.filter(nome=nome).first()
            if not cli:
                cli = Cliente.objects.create(nome=nome)

        data_ref = self._calc_fim(s) or s.inicio or timezone.now()

        HistoricoItem.objects.create(
            cliente=cli,
            data=data_ref,
            servico=(s.servico.nome if s.servico_id else (s.servico_nome or "Serviço")),
            valor=None,  # se quiser, use s.preco_cotado
            faltou=faltou,
            profissional=(getattr(s.barbeiro, "get_full_name", lambda: "")() or getattr(s.barbeiro, "username", "") or None),
        )

        if not faltou:
            cli.ultimo_corte = data_ref
            cli.save(update_fields=["ultimo_corte"])

    # ---------- Actions ----------
    @admin.action(description="Confirmar selecionadas (requer 'início' preenchido)")
    def action_confirmar(self, request, queryset):
        ok, skipped, fail = 0, 0, 0
        for s in queryset:
            if not s.inicio:
                skipped += 1
                continue
            try:
                # Use a regra de domínio se existir (cria/atualiza Agendamento 1:1)
                if hasattr(s, "confirmar"):
                    s.confirmar(s.inicio, cliente=s.cliente, barbeiro=s.barbeiro)
                else:
                    s.status = SolicitacaoStatus.CONFIRMADA
                    s.fim = self._calc_fim(s)
                    s.save()
                ok += 1
            except Exception:
                fail += 1
        if ok:
            self.message_user(request, f"{ok} confirmação(ões) realizada(s).", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} sem 'início' — puladas.", level=messages.WARNING)
        if fail:
            self.message_user(request, f"{fail} falharam ao confirmar.", level=messages.ERROR)

    @admin.action(description="Negar selecionadas")
    def action_negar(self, request, queryset):
        updated = queryset.update(status=SolicitacaoStatus.NEGADA)
        self.message_user(request, f"{updated} solicitação(ões) negada(s).", level=messages.SUCCESS)

    @admin.action(description="Finalizar selecionadas (só as já iniciadas)")
    def action_finalizar(self, request, queryset):
        now = timezone.now()
        ok, skipped = 0, 0
        for s in queryset:
            if not s.inicio or s.inicio > now:
                skipped += 1
                continue
            s.status = getattr(SolicitacaoStatus, "REALIZADA", SolicitacaoStatus.CONFIRMADA)
            if not s.fim:
                s.fim = self._calc_fim(s)
            s.save()
            # histórico (opc.)
            self._criar_historico(s, faltou=False)
            ok += 1
        if ok:
            self.message_user(request, f"{ok} finalizada(s).", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"{skipped} ainda não iniciadas — puladas.", level=messages.WARNING)

    @admin.action(description="Marcar no-show (não altera status)")
    def action_no_show(self, request, queryset):
        for s in queryset:
            self._criar_historico(s, faltou=True)
        self.message_user(request, "No-show registrado no histórico.", level=messages.SUCCESS)

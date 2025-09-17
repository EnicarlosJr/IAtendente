from __future__ import annotations

from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class StatusAgendamento(models.TextChoices):
    CONFIRMADO = "CONFIRMADO", "Confirmado"
    PENDENTE   = "PENDENTE",   "Pendente"
    CANCELADO  = "CANCELADO",  "Cancelado"


class Agendamento(models.Model):
    """
    Evento canônico da agenda, 1:1 com a Solicitação quando confirmada.
    Mantemos snapshots e FKs para auditoria/relatórios.
    """
    solicitacao = models.OneToOneField(
        "solicitacoes.Solicitacao",
        on_delete=models.CASCADE,
        related_name="agendamento",
        null=True, blank=True,  # permite migrar dados antigos
    )

    # relacionamento com cliente (snapshot do nome permanece)
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="agendamentos",
    )
    cliente_nome = models.CharField(max_length=120, blank=True)

    # barbeiro responsável (padronizado em PT-BR)
    barbeiro = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name="agendamentos",
        db_index=True,
    )

    # serviço (FK + snapshot)
    servico = models.ForeignKey(
        "servicos.Servico",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="agendamentos",
    )
    servico_nome = models.CharField(max_length=120, blank=True)

    # preço efetivamente cobrado neste atendimento
    preco_cobrado = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    inicio = models.DateTimeField()
    fim    = models.DateTimeField()

    status = models.CharField(
        max_length=10,
        choices=StatusAgendamento.choices,
        default=StatusAgendamento.PENDENTE,
    )
    observacoes = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["inicio"]
        indexes = [
            models.Index(fields=["inicio"]),
            models.Index(fields=["status"]),
            models.Index(fields=["barbeiro", "inicio"]),
            models.Index(fields=["cliente", "inicio"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="ag_fim_gt_inicio",
                check=Q(fim__gt=F("inicio")),
            ),
        ]

    def __str__(self):
        nome = self.cliente_nome or (self.cliente.nome if self.cliente_id else "—")
        return f"{nome} — {self.servico_nome or 'Serviço'} ({self.inicio:%d/%m %H:%M})"

    # conflito de horário para um barbeiro
    @staticmethod
    def existe_conflito(barbeiro, inicio, fim, excluir_id: int | None = None) -> bool:
        qs = Agendamento.objects.filter(
            barbeiro=barbeiro,
            inicio__lt=fim,
            fim__gt=inicio,
        )
        if excluir_id:
            qs = qs.exclude(id=excluir_id)
        return qs.exists()


# =========================
# Disponibilidade do BARBEIRO (nome PT-BR)
# =========================
class BarbeiroAvailability(models.Model):
    """Regras semanais (expediente + almoço)."""
    class Weekday(models.IntegerChoices):
        MON = 0, "Segunda"
        TUE = 1, "Terça"
        WED = 2, "Quarta"
        THU = 3, "Quinta"
        FRI = 4, "Sexta"
        SAT = 5, "Sábado"
        SUN = 6, "Domingo"

    barbeiro = models.ForeignKey(User, on_delete=models.CASCADE, related_name="avail_rules")
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time   = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(default=30)
    is_active  = models.BooleanField(default=True)

    # almoço (opcional)
    lunch_start  = models.TimeField(null=True, blank=True)
    lunch_end    = models.TimeField(null=True, blank=True)

    class Meta:
        ordering = ["barbeiro", "weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["barbeiro", "weekday"],
                name="unique_availability_per_barbeiro_weekday",
            ),
            models.CheckConstraint(
                name="avail_end_gt_start",
                check=Q(end_time__gt=F("start_time")),
            ),
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time}-{self.end_time} ({'on' if self.is_active else 'off'})"


class BarbeiroTimeOff(models.Model):
    """Exceções (folgas/afins)."""
    barbeiro = models.ForeignKey(User, on_delete=models.CASCADE, related_name="time_offs")
    start = models.DateTimeField()
    end   = models.DateTimeField()
    reason = models.CharField(max_length=140, blank=True)

    class Meta:
        ordering = ["-start"]
        indexes = [
            models.Index(fields=["barbeiro", "start"]),
            models.Index(fields=["barbeiro", "end"]),
        ]
    constraints = [
        models.CheckConstraint(
            name="timeoff_end_gt_start",
            check=Q(end__gt=F("start")),
        ),
    ]

    def __str__(self):
        return f"{self.barbeiro} off {self.start:%d/%m %H:%M}-{self.end:%H:%M} ({self.reason or '—'})"


# -------------------------
# Retrocompatibilidade (alias)
# -------------------------
# Se seu código antigo ainda importa BarberAvailability/BarberTimeOff,
# estes aliases evitam quebrar imports (não criam novos modelos).
BarberAvailability = BarbeiroAvailability
BarberTimeOff = BarbeiroTimeOff

from __future__ import annotations

from datetime import datetime, timedelta
from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class StatusAgendamento(models.TextChoices):
    CONFIRMADO = "CONFIRMADO", "Confirmado"
    CANCELADO  = "CANCELADO",  "Cancelado"
    REALIZADO  = "REALIZADO",  "Realizado"


class Agendamento(models.Model):
    """
    Evento canônico da agenda.
    Só existe se a solicitação for confirmada ou se o barbeiro criar direto.
    """
    shop = models.ForeignKey("barbearias.BarberShop", on_delete=models.CASCADE, related_name="agendamentos")
    solicitacao = models.OneToOneField(
        "solicitacoes.Solicitacao",
        on_delete=models.CASCADE,
        related_name="agendamento",
        null=True, blank=True,
    )

    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="agendamentos",
    )
    cliente_nome = models.CharField(max_length=120, blank=True)

    barbeiro = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True, null=True,
        related_name="agendamentos",
        db_index=True,
    )

    servico = models.ForeignKey(
        "servicos.Servico",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="agendamentos",
    )
    servico_nome = models.CharField(max_length=120, blank=True)

    preco_cobrado = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    inicio = models.DateTimeField()
    fim    = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=10,
        choices=StatusAgendamento.choices,
        default=StatusAgendamento.CONFIRMADO,  # ✅ nasce confirmado
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

    def calcular_fim_pelo_servico(self):
        """
        Se houver serviço e início, calcula self.fim a partir de servico.duracao_min.
        Caso o serviço não tenha duracao_min, usa 30 minutos.
        """
        if self.inicio and self.servico:
            minutos = getattr(self.servico, "duracao_min", 30) or 30
            self.fim = self.inicio + timedelta(minutes=int(minutos))
        return self.fim

    def save(self, *args, **kwargs):
        # garante 'fim' antes de persistir
        if not self.fim:
            self.calcular_fim_pelo_servico()
        super().save(*args, **kwargs)

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

    def gerar_slots(self, dia, barbeiro):
        if not self.is_active:
            return []
        start_dt = datetime.combine(dia, self.start_time)
        end_dt   = datetime.combine(dia, self.end_time)

        slots, atual = [], start_dt
        while atual + timedelta(minutes=self.slot_minutes) <= end_dt:
            slots.append({"start": atual, "end": atual + timedelta(minutes=self.slot_minutes), "available": True})
            atual += timedelta(minutes=self.slot_minutes)

        if self.lunch_start and self.lunch_end:
            almoco_ini = datetime.combine(dia, self.lunch_start)
            almoco_fim = datetime.combine(dia, self.lunch_end)
            for s in slots:
                if s["start"] < almoco_fim and s["end"] > almoco_ini:
                    s["available"] = False
                    s["reason"] = "almoco"

        offs = BarbeiroTimeOff.objects.filter(barbeiro=barbeiro, start__date=dia)
        for o in offs:
            for s in slots:
                if s["start"] < o.end and s["end"] > o.start:
                    s["available"] = False
                    s["reason"] = "folga"

        ags = Agendamento.objects.filter(barbeiro=barbeiro, inicio__date=dia)
        for ag in ags:
            for s in slots:
                if s["start"] < ag.fim and s["end"] > ag.inicio:
                    s["available"] = False
                    s["reason"] = "ocupado"

        return slots

    def __str__(self):
        return f"{self.get_weekday_display()} {self.start_time}-{self.end_time} ({'on' if self.is_active else 'off'})"


class BarbeiroTimeOff(models.Model):
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


BarberAvailability = BarbeiroAvailability
BarberTimeOff = BarbeiroTimeOff

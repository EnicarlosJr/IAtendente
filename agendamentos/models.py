# agendamentos/models.py
from __future__ import annotations

from datetime import datetime, timedelta, time
from django.conf import settings
from django.db import models
from django.db.models import Q, F
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class StatusAgendamento(models.TextChoices):
    CONFIRMADO = "CONFIRMADO", "Confirmado"
    CANCELADO  = "CANCELADO",  "Cancelado"
    # Novo conjunto canônico:
    FINALIZADO = "FINALIZADO", "Finalizado"
    NO_SHOW    = "NO_SHOW",    "No-show"
    # Retrocompat (linhas antigas podem ter REALIZADO)
    REALIZADO  = "REALIZADO",  "Realizado"  # mantido para não quebrar dados antigos


class Agendamento(models.Model):
    """
    Evento canônico da agenda.
    Só existe se a solicitação for confirmada ou se o barbeiro criar direto.
    """
    shop = models.ForeignKey(
        "barbearias.BarberShop",
        on_delete=models.CASCADE,
        related_name="agendamentos",
    )

    solicitacao = models.OneToOneField(
        "solicitacoes.Solicitacao",
        on_delete=models.SET_NULL,
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
        max_length=20,
        choices=StatusAgendamento.choices,
        default=StatusAgendamento.CONFIRMADO,  # nasce confirmado
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
            models.Index(fields=["shop", "inicio"]),
        ]
        constraints = [
            # fim pode ser NULL; quando não for, precisa ser > início
            models.CheckConstraint(
                name="ag_fim_gt_inicio_or_null",
                check=Q(fim__isnull=True) | Q(fim__gt=F("inicio")),
            ),
        ]

    # ----------------- util -----------------
    def __str__(self):
        nome = self.cliente_nome or (self.cliente.nome if self.cliente_id else "—")
        return f"{nome} — {self.servico_nome or 'Serviço'} ({timezone.localtime(self.inicio):%d/%m %H:%M})"

    def calcular_fim_pelo_servico(self):
        """
        Se houver serviço e início, calcula self.fim a partir de servico.duracao_min.
        Caso o serviço não tenha duracao_min, usa 30 minutos.
        """
        if self.inicio and self.servico:
            minutos = getattr(self.servico, "duracao_min", 30) or 30
            self.fim = self.inicio + timedelta(minutes=int(minutos))
        return self.fim

    def _ensure_fim(self, when=None):
        """Garante self.fim coerente (pelo serviço; senão, agora)."""
        if self.fim:
            return
        if when:
            self.fim = max(self.inicio or when, when)
            return
        if hasattr(self, "calcular_fim_pelo_servico"):
            self.calcular_fim_pelo_servico()
        if not self.fim:
            now = timezone.now()
            self.fim = max(self.inicio or now, now)

    def save(self, *args, **kwargs):
        # garante 'fim' antes de persistir (quando relevante)
        if not self.fim and self.status in (StatusAgendamento.CONFIRMADO, StatusAgendamento.FINALIZADO, StatusAgendamento.REALIZADO):
            self.calcular_fim_pelo_servico()
        # normaliza status legado
        if self.status == StatusAgendamento.REALIZADO:
            self.status = StatusAgendamento.FINALIZADO
        super().save(*args, **kwargs)

    # ----------------- regras de negócio -----------------
    def finalizar(self, when=None):
        """
        Transição CONFIRMADO -> FINALIZADO (idempotente).
        Aceita `when` para fixar o horário de término, senão infere.
        """
        if self.status in (StatusAgendamento.FINALIZADO, StatusAgendamento.REALIZADO):
            return self  # idempotente

        if self.status != StatusAgendamento.CONFIRMADO:
            raise ValueError("Apenas agendamentos CONFIRMADOS podem ser finalizados.")

        self._ensure_fim(when=when)
        self.status = StatusAgendamento.FINALIZADO
        return self

    def marcar_no_show(self):
        """
        Transição CONFIRMADO -> NO_SHOW (idempotente).
        """
        if self.status == StatusAgendamento.NO_SHOW:
            return self  # idempotente

        if self.status != StatusAgendamento.CONFIRMADO:
            raise ValueError("Apenas agendamentos CONFIRMADOS podem ser marcados como no-show.")

        self.status = StatusAgendamento.NO_SHOW
        return self

    # ----------------- conflito -----------------
    @staticmethod
    def existe_conflito(barbeiro, inicio, fim, excluir_id: int | None = None, shop=None) -> bool:
        """
        Conflito básico: sobreposição [inicio, fim) para o barbeiro.
        Por padrão considera qualquer status que ocupe a agenda (CONFIRMADO/FINALIZADO/NO_SHOW).
        Exclui CANCELADO.
        Se `shop` for passado, limita à barbearia.
        """
        qs = Agendamento.objects.filter(
            barbeiro=barbeiro,
            inicio__lt=fim,
            fim__gt=inicio,
        ).exclude(status=StatusAgendamento.CANCELADO)

        if shop is not None:
            qs = qs.filter(shop=shop)
        if excluir_id:
            qs = qs.exclude(id=excluir_id)
        return qs.exists()


# ----------------- Disponibilidade / Folgas -----------------
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
        """
        Gera slots do dia com flags de disponibilidade.
        Usa timezone local e normaliza almoço/folgas/agendamentos em TZ-aware.
        """
        if not self.is_active:
            return []

        tz = timezone.get_current_timezone()

        def aware(d0: datetime) -> datetime:
            return timezone.make_aware(d0, tz) if timezone.is_naive(d0) else d0.astimezone(tz)

        start_dt = aware(datetime.combine(dia, self.start_time))
        end_dt   = aware(datetime.combine(dia, self.end_time))

        step = timedelta(minutes=self.slot_minutes or 30)
        slots = []
        cur = start_dt
        while cur + step <= end_dt:
            slots.append({"start": cur, "end": cur + step, "available": True})
            cur += step

        # almoço
        if self.lunch_start and self.lunch_end:
            almoco_ini = aware(datetime.combine(dia, self.lunch_start))
            almoco_fim = aware(datetime.combine(dia, self.lunch_end))
            for s in slots:
                if s["start"] < almoco_fim and s["end"] > almoco_ini:
                    s["available"] = False
                    s["reason"] = "almoco"

        # folgas do dia (normalizadas)
        day_start = aware(datetime.combine(dia, time(0, 0)))
        day_end   = day_start + timedelta(days=1)
        offs = BarbeiroTimeOff.objects.filter(barbeiro=barbeiro, start__lt=day_end, end__gt=day_start)
        off_intervals = [(o.start.astimezone(tz), o.end.astimezone(tz)) for o in offs]

        # agendamentos do dia (que ocupam agenda)
        ags = Agendamento.objects.filter(
            barbeiro=barbeiro,
            inicio__lt=day_end,
            fim__gt=day_start,
        ).exclude(status=StatusAgendamento.CANCELADO)
        ag_intervals = [(a.inicio.astimezone(tz), (a.fim or a.inicio).astimezone(tz)) for a in ags]

        # aplica interseções
        for s in slots:
            if s.get("available") is False:
                continue
            # folgas
            for st, en in off_intervals:
                if s["start"] < en and s["end"] > st:
                    s["available"] = False
                    s["reason"] = "folga"
                    break
            if s.get("available") is False:
                continue
            # agendamentos
            for st, en in ag_intervals:
                if s["start"] < en and s["end"] > st:
                    s["available"] = False
                    s["reason"] = "ocupado"
                    break

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
        return f"{self.barbeiro} off {timezone.localtime(self.start):%d/%m %H:%M}-{timezone.localtime(self.end):%H:%M} ({self.reason or '—'})"


# aliases
BarberAvailability = BarbeiroAvailability
BarberTimeOff = BarbeiroTimeOff

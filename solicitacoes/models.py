from __future__ import annotations
from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from servicos.models import Servico as CatServico  # catálogo oficial

class SolicitacaoStatus(models.TextChoices):
    PENDENTE   = "PENDENTE",   "Pendente"
    CONFIRMADA = "CONFIRMADA", "Confirmada"
    NEGADA     = "NEGADA",     "Negada"
    REALIZADA  = "REALIZADA",  "Realizada"


class Solicitacao(models.Model):
    shop = models.ForeignKey("barbearias.BarberShop", on_delete=models.CASCADE, related_name="solicitacoes")

    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.SET_NULL, null=True, blank=True, related_name="solicitacoes"
    )
    barbeiro = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="solicitacoes"
    )
    servico = models.ForeignKey(
        CatServico, on_delete=models.SET_NULL, null=True, blank=True, related_name="solicitacoes"
    )

    # Identificação externa (única por barbearia)
    id_externo = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    callback_url = models.URLField(null=True, blank=True)

    # Snapshots
    servico_nome = models.CharField(max_length=120, blank=True)
    preco_cotado = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    duracao_min_cotada = models.PositiveSmallIntegerField(null=True, blank=True)

    # Agenda (apenas referência; o canônico é o Agendamento quando existir)
    inicio = models.DateTimeField(null=True, blank=True)
    fim    = models.DateTimeField(null=True, blank=True)

    # Dados operacionais
    nome        = models.CharField(max_length=120, blank=True)
    telefone    = models.CharField(max_length=32, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status      = models.CharField(
        max_length=10, choices=SolicitacaoStatus.choices, default=SolicitacaoStatus.PENDENTE
    )

    criado_em  = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["shop", "status", "criado_em"]),
            models.Index(fields=["shop", "telefone"]),
            models.Index(fields=["shop", "servico"]),
        ]
        constraints = [
            # Confirmada deve ter início
            models.CheckConstraint(
                name="solic_confirmada_tem_inicio",
                check=~Q(status=SolicitacaoStatus.CONFIRMADA) | Q(inicio__isnull=False),
            ),
            # id_externo único por barbearia (evita colisão entre lojas diferentes)
            models.UniqueConstraint(
                fields=["shop", "id_externo"],
                name="uniq_solicitacao_por_shop_idexterno",
                condition=~Q(id_externo__isnull=True) & ~Q(id_externo=""),
            ),
        ]

    def __str__(self):
        ident = self.nome or self.telefone or "—"
        return f"[{self.status}] {ident} - {self.servico_label}"

    # ---------- Helpers ----------
    @property
    def servico_label(self) -> str:
        if self.servico_id and getattr(self.servico, "nome", None):
            return self.servico.nome
        return self.servico_nome or "Serviço"

    def duracao_minutos(self) -> int:
        if self.duracao_min_cotada:
            return int(self.duracao_min_cotada)
        return int(getattr(self.servico, "duracao_min", None) or 30)

    def preco_tabela(self) -> Decimal | None:
        if self.servico and self.servico.preco is not None:
            return Decimal(self.servico.preco)
        return None

    def preco_praticado(self) -> Decimal:
        if self.preco_cotado is not None:
            return Decimal(self.preco_cotado)
        return self.preco_tabela() or Decimal("0.00")

    # ---------- Regras ----------
    def confirmar(self, inicio):
        """
        Marca a solicitação como CONFIRMADA.
        (O Agendamento será criado pela view do painel/admin.)
        """
        self.status = SolicitacaoStatus.CONFIRMADA
        self.inicio = inicio
        self.fim = inicio + timezone.timedelta(minutes=self.duracao_minutos())
        self.save(update_fields=["status", "inicio", "fim", "updated_at"])
        return self

    def negar(self, motivo: str | None = None):
        obs = (self.observacoes or "").strip()
        if motivo:
            obs = (obs + ("\n" if obs else "") + f"[NEGADA] {motivo}").strip()
            self.observacoes = obs
        self.status = SolicitacaoStatus.NEGADA
        self.save(update_fields=["status", "observacoes", "updated_at"])

    # (opcional) helpers de estado
    @property
    def pode_confirmar(self) -> bool:
        return self.status == SolicitacaoStatus.PENDENTE

    @property
    def pode_negar(self) -> bool:
        return self.status in {SolicitacaoStatus.PENDENTE, SolicitacaoStatus.CONFIRMADA}

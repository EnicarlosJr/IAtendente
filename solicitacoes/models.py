# solicitacoes/models.py
from __future__ import annotations

from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from servicos.models import Servico as CatServico  # catálogo oficial

# ---------- Status da Solicitação ----------
class SolicitacaoStatus(models.TextChoices):
    PENDENTE   = "PENDENTE",   "Pendente"
    CONFIRMADA = "CONFIRMADA", "Confirmada"
    NEGADA     = "NEGADA",     "Negada"
    REALIZADA  = "REALIZADA",  "Realizada"


class Solicitacao(models.Model):
    # Relacionamentos principais
    cliente = models.ForeignKey(
        "clientes.Cliente", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="solicitacoes"
    )
    barbeiro = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="solicitacoes"
    )
    # 👉 usa o catálogo oficial
    servico = models.ForeignKey(
        CatServico, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="solicitacoes"
    )

    # Snapshots para independência do catálogo
    servico_nome = models.CharField(max_length=120, blank=True)
    preco_cotado = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    duracao_min_cotada = models.PositiveSmallIntegerField(null=True, blank=True)

    # Agenda
    inicio = models.DateTimeField(null=True, blank=True)
    fim    = models.DateTimeField(null=True, blank=True)

    # Dados operacionais
    nome       = models.CharField(max_length=120, blank=True)
    telefone   = models.CharField(max_length=32, blank=True)
    observacoes = models.TextField(null=True, blank=True)
    status      = models.CharField(
        max_length=10, choices=SolicitacaoStatus.choices, default=SolicitacaoStatus.PENDENTE
    )

    id_externo   = models.CharField(max_length=128, null=True, blank=True, unique=True)
    callback_url = models.URLField(null=True, blank=True)

    criado_em  = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["status", "criado_em"]),
            models.Index(fields=["telefone"]),
            models.Index(fields=["servico"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="solic_confirmada_tem_inicio",
                check=~Q(status=SolicitacaoStatus.CONFIRMADA) | Q(inicio__isnull=False),
            ),
        ]

    def __str__(self):
        ident = self.nome or self.telefone or "—"
        return f"[{self.status}] {ident} - {self.servico_label}"

    # ---------- Helpers “fonte de verdade” ----------
    @property
    def servico_label(self) -> str:
        """
        Nome consistente do serviço:
        - prioriza o FK (catálogo);
        - cai para o snapshot servico_nome.
        """
        if self.servico_id and getattr(self.servico, "nome", None):
            return self.servico.nome
        return self.servico_nome or "Serviço"

    def _servico_obj(self) -> CatServico | None:
        """Retorna o Servico (via FK). Se ausente, tenta pelo snapshot `servico_nome`."""
        if self.servico_id:
            return self.servico
        if self.servico_nome:
            return CatServico.objects.filter(nome__iexact=self.servico_nome.strip()).first()
        return None

    def duracao_minutos(self) -> int:
        """Duração efetiva (snapshot > catálogo > 30min)."""
        if self.duracao_min_cotada:
            return int(self.duracao_min_cotada)
        s = self._servico_obj()
        return int(getattr(s, "duracao_min", None) or 30)

    def preco_tabela(self) -> Decimal | None:
        """Preço de tabela do serviço (se existir no catálogo)."""
        s = self._servico_obj()
        return Decimal(s.preco) if (s and s.preco is not None) else None

    def preco_praticado(self) -> Decimal:
        """
        Preço efetivo:
          - usa preco_cotado se houver;
          - senão, preço de tabela; (fallback 0.00)
        """
        if self.preco_cotado is not None:
            return Decimal(self.preco_cotado)
        base = self.preco_tabela()
        return base if base is not None else Decimal("0.00")

    # ---------- Normalização antes de salvar ----------
    def _apply_defaults_from_servico(self):
        s = self._servico_obj()
        if s:
            if not self.servico_id:
                # consolidar FK quando achar por nome (opcional)
                self.servico = s
            if not self.servico_nome:
                self.servico_nome = s.nome or ""
            if self.preco_cotado is None and s.preco is not None:
                self.preco_cotado = s.preco
            if not self.duracao_min_cotada and s.duracao_min:
                self.duracao_min_cotada = s.duracao_min

        # calcula fim se possui início e ainda não tem fim
        if self.inicio and not self.fim:
            self.fim = self.inicio + timedelta(minutes=self.duracao_minutos())

    def save(self, *args, **kwargs):
        self._apply_defaults_from_servico()
        super().save(*args, **kwargs)

    # ---------- Regras de domínio ----------
    def confirmar(self, inicio, cliente=None, barbeiro=None):
        """
        Confirma a solicitação:
          - define início/fim/preço/duração (snapshot);
          - vincula barbeiro/cliente (se informados);
          - cria/atualiza Agendamento CONFIRMADO (one-to-one).
        Retorna o Agendamento.
        """
        from agendamentos.models import Agendamento, StatusAgendamento as StAg

        if barbeiro is not None:
            self.barbeiro = barbeiro
        if cliente is not None and not self.cliente_id:
            self.cliente = cliente

        self.inicio = inicio
        self.fim = inicio + timedelta(minutes=self.duracao_minutos())
        self.status = SolicitacaoStatus.CONFIRMADA
        self._apply_defaults_from_servico()

        with transaction.atomic():
            self.save()

            ag_vals = {
                "barbeiro": self.barbeiro,  # pode ser None
                "cliente": self.cliente,
                "cliente_nome": self.nome or (getattr(self.cliente, "nome", None) or self.telefone or ""),
                # ✅ use o ID para evitar conflito de classe entre apps
                "servico_id": self.servico_id,
                "servico_nome": self.servico_label,
                "preco_cobrado": self.preco_praticado(),
                "inicio": self.inicio,
                "fim": self.fim,
                "status": StAg.CONFIRMADO,
                "observacoes": self.observacoes or "",
            }
            ag, _ = Agendamento.objects.update_or_create(
                solicitacao=self, defaults=ag_vals
            )
        return ag

    def negar(self, motivo: str | None = None):
        """Marca como NEGADA e, se vier motivo, anexa nas observações."""
        obs = (self.observacoes or "").strip()
        if motivo:
            obs = (obs + ("\n" if obs else "") + f"[NEGADA] {motivo}").strip()
            self.observacoes = obs
        self.status = SolicitacaoStatus.NEGADA
        self.save(update_fields=["status", "observacoes", "updated_at"])

# clientes/models.py
from decimal import Decimal
from django.db import models
from django.utils import timezone

from core import settings

class Cliente(models.Model):
    class RecorrenciaStatus(models.TextChoices):
        ATIVO = "ATIVO", "Ativo"
        INATIVO = "INATIVO", "Inativo"

    shop = models.ForeignKey("barbearias.BarberShop", on_delete=models.CASCADE, related_name="clientes")
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=20, null=True, blank=True)
    preferencias = models.TextField(null=True, blank=True)
    recorrencia_status = models.CharField(
        max_length=10, choices=RecorrenciaStatus.choices, default=RecorrenciaStatus.ATIVO
    )
    ultimo_corte = models.DateTimeField(null=True, blank=True)

    # extras
    tags = models.JSONField(null=True, blank=True)
    barbeiro_preferido = models.CharField(max_length=120, null=True, blank=True)
    foto_url = models.URLField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


   # --- helpers de recorrência/último corte ---
    def set_ultimo_corte(self, dt, save=False):
        """Atualiza o último corte apenas se for mais recente."""
        if not dt:
            return
        if self.ultimo_corte is None or dt > self.ultimo_corte:
            self.ultimo_corte = dt
            if save:
                self.save(update_fields=["ultimo_corte", "updated_at"])

    def dias_desde_ultimo_corte(self):
        if not self.ultimo_corte:
            return None
        tz = timezone.get_current_timezone()
        now = timezone.localtime(timezone.now(), tz)
        return (now - timezone.localtime(self.ultimo_corte, tz)).days

    def refresh_recorrencia(self, save=False):
        """Marca ATIVO/INATIVO conforme a janela de inatividade do settings (CLIENTE_INATIVO_DIAS)."""
        cutoff_days = getattr(settings, "CLIENTE_INATIVO_DIAS", 60)
        dias = self.dias_desde_ultimo_corte()
        novo = self.RecorrenciaStatus.ATIVO
        if dias is None or dias >= cutoff_days:
            novo = self.RecorrenciaStatus.INATIVO
        if novo != self.recorrencia_status:
            self.recorrencia_status = novo
            if save:
                self.save(update_fields=["recorrencia_status", "updated_at"])

    class Meta:
        indexes = [models.Index(fields=["nome"])]
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(
                fields=["shop", "telefone"],
                name="uniq_cliente_por_shop_telefone",
                condition=~models.Q(telefone__isnull=True) & ~models.Q(telefone=""),
            ),
    ]

    def __str__(self):
        tel = f" ({self.telefone})" if self.telefone else ""
        return f"{self.nome}{tel}"



class HistoricoItem(models.Model):
    shop = models.ForeignKey(
        "barbearias.BarberShop",
        on_delete=models.CASCADE,
        related_name="historico",
        db_index=True,
        null=True, blank=True,          # manter null/blank durante o backfill
    )
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="historico")
    data = models.DateTimeField()
    servico = models.CharField(max_length=120)
    servico_ref = models.ForeignKey("servicos.Servico", on_delete=models.SET_NULL, null=True, blank=True, related_name="itens")
    valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    preco_tabela = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    faltou = models.BooleanField(default=False)
    profissional = models.CharField(max_length=120, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-data"]
        indexes = [
            models.Index(fields=["shop", "data"]),
            models.Index(fields=["cliente", "data"]),
            models.Index(fields=["servico"]),
            models.Index(fields=["faltou"]),
        ]
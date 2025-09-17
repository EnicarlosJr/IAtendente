# clientes/models.py
from decimal import Decimal
from django.db import models
from django.utils import timezone

class Cliente(models.Model):
    class RecorrenciaStatus(models.TextChoices):
        ATIVO = "ATIVO", "Ativo"
        INATIVO = "INATIVO", "Inativo"

    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=20, unique=True, null=True, blank=True)
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

    class Meta:
        indexes = [models.Index(fields=["nome"])]
        ordering = ["nome"]

    def __str__(self):
        tel = f" ({self.telefone})" if self.telefone else ""
        return f"{self.nome}{tel}"


class HistoricoItem(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name="historico")
    data = models.DateTimeField()

    # >>> legado / mantém compatibilidade
    servico = models.CharField(max_length=120)

    # >>> novos campos para controle real de serviço/preço
    servico_ref = models.ForeignKey(
        "servicos.Servico", on_delete=models.SET_NULL, null=True, blank=True, related_name="itens"
    )
    # preço efetivamente cobrado (já existia como 'valor'): usamos como preço praticado
    valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # preço de tabela do serviço no momento (opcional, útil p/ auditoria e margem)
    preco_tabela = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # marcações
    faltou = models.BooleanField(default=False)
    profissional = models.CharField(max_length=120, null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        indexes = [
            models.Index(fields=["cliente", "data"]),
            models.Index(fields=["servico"]),
            models.Index(fields=["faltou"]),
        ]
        ordering = ["-data"]

    def __str__(self):
        label = self.servico_ref.nome if self.servico_ref_id else self.servico
        return f"{label} em {self.data:%d/%m/%Y} - {self.cliente.nome}"

    @property
    def servico_label(self) -> str:
        """Use isto nas templates caso queira o nome padronizado."""
        return self.servico_ref.nome if self.servico_ref_id else (self.servico or "Serviço")

    @property
    def preco_praticado(self):
        return self.valor if self.valor is not None else Decimal("0.00")

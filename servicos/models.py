# servicos/models.py
from decimal import Decimal
from django.db import models

class Servico(models.Model):
    CATEGORIAS = (
        ("corte", "Corte"),
        ("barba", "Barba"),
        ("combo", "Combo"),
        ("quimica", "Química/Coloração"),
        ("add_on", "Serviços adicionais"),
    )

    nome = models.CharField(max_length=120, unique=True)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default="corte")
    preco = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    duracao_min = models.PositiveIntegerField(default=30)
    descricao = models.TextField(null=True, blank=True)
    ativo = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        indexes = [models.Index(fields=["nome"])]

    def __str__(self):
        return self.nome

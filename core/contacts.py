# core/contacts.py
from __future__ import annotations
import re
from typing import Optional
from django.db.models import Q
from clientes.models import Cliente
from barbearias.models import BarberShop

_NON_DIGITS = re.compile(r"\D+")

def normalize_phone(raw: Optional[str]) -> str:
    """Remove máscara e deixa no máximo 11 dígitos (BR). Ajuste se usar outro país."""
    if not raw:
        return ""
    digits = _NON_DIGITS.sub("", raw)
    if len(digits) > 11:
        digits = digits[-11:]  # conserva sufixo (tolerante a DDI)
    return digits

def find_or_create_cliente(
    shop: BarberShop,
    nome: Optional[str] = None,
    telefone: Optional[str] = None,
) -> Cliente:
    """
    Resolve cliente da barbearia por telefone (preferência) e/ou nome.
    Se não encontrar, cria.
    """
    tel = normalize_phone(telefone)
    nome = (nome or "").strip()

    qs = Cliente.objects.filter(shop=shop)

    # 1) match forte por telefone (usa sufixo de 8+ dígitos p/ tolerar DDD/mascara)
    if tel and len(tel) >= 8:
        c = qs.filter(telefone__isnull=False, telefone__icontains=tel[-8:]).first()
        if c:
            if not c.nome and nome:
                c.nome = nome
                c.save(update_fields=["nome"])
            return c

    # 2) match leve por nome + “rastro” de telefone (últimos 4 dígitos)
    if nome:
        probe = qs.filter(nome__iexact=nome)
        if tel:
            probe = probe.filter(Q(telefone__endswith=tel[-4:]) | Q(telefone__icontains=tel[-4:]))
        c = probe.first()
        if c:
            if not c.telefone and tel:
                c.telefone = tel
                c.save(update_fields=["telefone"])
            return c

    # 3) criar
    return Cliente.objects.create(
        shop=shop,
        nome=nome or (tel or "Cliente"),
        telefone=tel or None,
    )

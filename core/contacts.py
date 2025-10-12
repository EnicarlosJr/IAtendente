# core/contacts.py
from __future__ import annotations
import re
from typing import Optional
from django.db.models import Q
from clientes.models import Cliente
from barbearias.models import BarberShop

_NON_DIGITS = re.compile(r"\D+")

def _only_digits(raw: Optional[str]) -> str:
    return _NON_DIGITS.sub("", raw or "")

def normalize_msisdn_br(raw: Optional[str]) -> Optional[str]:
    """
    Normaliza telefones do Brasil para E.164 (sem +):
    - Mantém DDI 55.
    - Remove '00' inicial, zeros à esquerda após 55.
    - Aceita entradas com/sem DDI; devolve 55 + DDD + número (12 ou 13 dígitos).
    Retorna None se inválido.
    """
    if not raw:
        return None
    digits = _only_digits(raw)

    # remove prefixo discado internacional "00"
    if digits.startswith("00"):
        digits = digits[2:]

    # se veio sem 55 e parece DDD+numero (10 ou 11), prefixa 55
    if not digits.startswith("55") and len(digits) in (10, 11):
        digits = "55" + digits

    # casos "550..." (DDI 55 + zero extra do tronco): 550X... -> 55X...
    if digits.startswith("550"):
        digits = "55" + digits[3:]

    # remover zeros à esquerda APÓS o 55 (nunca remova o 55)
    if digits.startswith("55"):
        resto = digits[2:].lstrip("0")
        digits = "55" + resto

    # validar tamanho final BR: 55 + DDD(2) + número(8 ou 9) => 12 ou 13 dígitos
    if not (digits.startswith("55") and len(digits) in (12, 13) and digits.isdigit()):
        return None

    return digits

# Mantém o nome antigo para compatibilidade com imports existentes
def normalize_phone(raw: Optional[str]) -> str:
    """
    Wrapper compatível: retorna string normalizada ou "" se inválido.
    """
    norm = normalize_msisdn_br(raw)
    return norm or ""

def find_or_create_cliente(
    shop: BarberShop,
    nome: Optional[str] = None,
    telefone: Optional[str] = None,
) -> Cliente:
    """
    Resolve cliente da barbearia:
    1) Normaliza telefone para E.164 BR (55 + DDD + número).
    2) Tenta match EXATO por telefone (seguro).
    3) Tenta match por SUFIXO (últimos 8 dígitos) para dados antigos (tolerante).
       - Se achar por sufixo, atualiza o telefone do cliente para o normalizado.
    4) Se não achar, cria.
    """
    tel_norm = normalize_msisdn_br(telefone)
    nome = (nome or "").strip()

    qs = Cliente.objects.filter(shop=shop)

    # 1) match forte por telefone normalizado
    if tel_norm:
        c = qs.filter(telefone=tel_norm).first()
        if c:
            # Atualiza nome se estiver vazio e recebemos nome
            if not c.nome and nome:
                c.nome = nome
                c.save(update_fields=["nome"])
            return c

    # 2) match tolerante por sufixo (últimos 8 dígitos),
    #    útil para bases antigas sem DDI/DDD uniformes
    if tel_norm:
        suf8 = tel_norm[-8:]
        c = qs.filter(telefone__isnull=False, telefone__regex=r"\d{8,}", telefone__endswith=suf8).first()
        if c:
            # Se o telefone salvo for diferente do normalizado, atualiza para o padrão
            if c.telefone != tel_norm:
                c.telefone = tel_norm
                # Atualiza nome se faltando
                if not c.nome and nome:
                    c.nome = nome
                    c.save(update_fields=["telefone", "nome"])
                else:
                    c.save(update_fields=["telefone"])
            else:
                if not c.nome and nome:
                    c.nome = nome
                    c.save(update_fields=["nome"])
            return c

    # 3) match leve por nome + “rastro” de telefone (últimos 4),
    #    só se recebemos nome
    if nome:
        probe = qs.filter(nome__iexact=nome)
        if tel_norm:
            suf4 = tel_norm[-4:]
            probe = probe.filter(Q(telefone__endswith=suf4) | Q(telefone__icontains=suf4))
        c = probe.first()
        if c:
            # Preenche telefone normalizado se estiver vazio ou diferente
            if tel_norm and c.telefone != tel_norm:
                c.telefone = tel_norm
                c.save(update_fields=["telefone"])
            return c

    # 4) criar novo
    return Cliente.objects.create(
        shop=shop,
        nome=nome or (tel_norm or "Cliente"),
        telefone=tel_norm or None,  # nunca converta telefone para int
    )
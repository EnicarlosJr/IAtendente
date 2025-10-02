# barbearias/permissions.py
from __future__ import annotations
from typing import Optional
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django.http import HttpRequest
from .models import BarberShop, Membership, MembershipRole

def get_shop_from_request(request: HttpRequest, shop_slug: Optional[str] = None) -> Optional[BarberShop]:
    """
    1) Se vier shop_slug (URL), usa ele.
    2) Senão, tenta sessão (shop_id).
    3) Senão, None.
    """
    if shop_slug:
        return get_object_or_404(BarberShop, slug=shop_slug)
    sid = request.session.get("shop_id")
    if sid:
        try:
            return BarberShop.objects.get(id=sid)
        except BarberShop.DoesNotExist:
            return None
    return None

def user_membership_role(user, shop: BarberShop) -> Optional[str]:
    """
    Retorna role do usuário na barbearia (OWNER/MANAGER/BARBER) ou None.
    """
    if not (user and user.is_authenticated and shop):
        return None
    mem = Membership.objects.filter(user=user, shop=shop, is_active=True).only("role").first()
    return mem.role if mem else None

def can_manage_shop(user, shop: BarberShop) -> bool:
    """
    OWNER/MANAGER podem gerenciar (ex.: usuários da barbearia).
    """
    role = user_membership_role(user, shop)
    return role in (MembershipRole.OWNER, MembershipRole.MANAGER)

def scope_queryset_by_role(qs, user, shop: BarberShop, field_name: str = "barbeiro"):
    """
    Se usuário for BARBER, restringe para registros em que <field_name> == user.
    OWNER/MANAGER veem tudo.
    """
    role = user_membership_role(user, shop)
    if role in (MembershipRole.OWNER, MembershipRole.MANAGER):
        return qs
    # BARBER (ou None): restringe
    kwargs = {field_name: user}
    return qs.filter(**kwargs)

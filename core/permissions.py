# core/permissions.py
from typing import Optional
from django.http import HttpRequest


def is_owner(user, shop) -> bool:
    if not user or not user.is_authenticated or not shop:
        return False
    # dono “oficial”
    if getattr(shop, "owner_id", None) == user.id:
        return True
    # membership como OWNER
    return shop.members.filter(user=user, role="OWNER", is_active=True).exists()

def is_manager(user, shop) -> bool:
    if not user or not user.is_authenticated or not shop:
        return False
    return shop.members.filter(user=user, role="MANAGER", is_active=True).exists()

def is_staff_of_shop(user, shop) -> bool:
    """Qualquer membro ativo (OWNER, MANAGER, BARBER)."""
    if not user or not user.is_authenticated or not shop:
        return False
    return shop.members.filter(user=user, is_active=True).exists()

def role_for(user, shop) -> Optional[str]:
    if not user or not user.is_authenticated or not shop:
        return None
    if is_owner(user, shop):
        return "OWNER"
    m = shop.members.filter(user=user, is_active=True).values_list("role", flat=True).first()
    return m or None

def can_view_people_flow(user, shop) -> bool:
    """Apenas dono (ou gerente, se quiser) enxerga o 'fluxo de pessoas'."""
    return is_owner(user, shop) or is_manager(user, shop)

def can_view_all_staff(user, shop) -> bool:
    """Dono/gerente vê todos; barbeiro só a si."""
    return is_owner(user, shop) or is_manager(user, shop)

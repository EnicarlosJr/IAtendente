# core/visibility.py
from django.db.models import Q

def is_shop_admin(user) -> bool:
    """Regra de admin: ajuste se tiver owner/membership. Por ora staff/superuser já resolve."""
    return bool(user and (user.is_staff or user.is_superuser))

def scope_solicitacoes_qs(qs, user, admin: bool, incluir_nao_atribuida: bool = False):
    """
    - admin=True: mostra tudo do shop.
    - admin=False: mostra somente as solicitacoes do barbeiro logado.
      Opcional: incluir as não atribuídas (barbeiro is null) no mesmo bucket do barbeiro logado.
    """
    if admin:
        return qs
    f = Q(barbeiro=user)
    if incluir_nao_atribuida:
        f |= Q(barbeiro__isnull=True)
    return qs.filter(f)

def scope_agendamentos_qs(qs, user, admin: bool):
    """Mesmo critério para agendamentos."""
    if admin:
        return qs
    return qs.filter(barbeiro=user)

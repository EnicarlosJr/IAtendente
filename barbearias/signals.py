# barbearias/signals.py
from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import (
    BarberShop,
    BarberProfile,
    Membership,
    MembershipRole,
)

# ============================================================
# Helpers
# ============================================================

def _update_instance_fields(instance, **fields):
    """
    Atualiza apenas campos alterados, evitando loops de sinal e saves desnecessários.
    """
    to_update = {k: v for k, v in fields.items() if getattr(instance, k, object()) != v}
    if to_update:
        for k, v in to_update.items():
            setattr(instance, k, v)
        instance.save(update_fields=list(to_update.keys()))
        return True
    return False


# ============================================================
# 1) Ao criar uma Barbearia, garanta a membership OWNER do owner
# ============================================================

@receiver(post_save, sender=BarberShop)
def ensure_owner_membership(sender, instance: BarberShop, created: bool, **kwargs):
    """
    Se a barbearia tiver 'owner', garante uma Membership OWNER ativa.
    """
    if not created or not instance.owner_id:
        return

    def _do():
        Membership.objects.get_or_create(
            user_id=instance.owner_id,
            shop=instance,
            defaults={"role": MembershipRole.OWNER, "is_active": True},
        )

    # Se a criação da shop vier dentro de transação, só cria após commit.
    transaction.on_commit(_do)


# ============================================================
# 2) BarberProfile -> Membership (BARBER)
#    - cria membership BARBER ao criar profile
#    - mantém is_active sincronizado (profile.ativo -> membership.is_active)
#    - NUNCA mexe em OWNER / MANAGER
# ============================================================

@receiver(post_save, sender=BarberProfile)
def create_or_sync_membership_for_barber(sender, instance: BarberProfile, created: bool, **kwargs):
    """
    Sempre que um BarberProfile for criado/atualizado:
      - se criado: garante membership BARBER (ativa conforme profile.ativo)
      - se atualizado: espelha 'ativo' em membership.is_active (somente para BARBER)
    """
    user = instance.user
    shop = instance.shop

    try:
        m = Membership.objects.get(user=user, shop=shop)
    except Membership.DoesNotExist:
        m = None

    if created:
        # Cria membership BARBER somente se não existir.
        if m is None:
            Membership.objects.create(
                user=user,
                shop=shop,
                role=MembershipRole.BARBER,
                is_active=instance.ativo,
            )
        # Se já existir e for BARBER, apenas garante is_active = profile.ativo
        elif m.role == MembershipRole.BARBER:
            _update_instance_fields(m, is_active=instance.ativo)
        # Se já existir e for OWNER/MANAGER, não alteramos role;
        # apenas, por coerência, se quiser espelhar ativo, descomente:
        # else:
        #     _update_instance_fields(m, is_active=instance.ativo)
        return

    # Atualização: sincroniza apenas quando membership é BARBER
    if m and m.role == MembershipRole.BARBER:
        _update_instance_fields(m, is_active=instance.ativo)


@receiver(pre_delete, sender=BarberProfile)
def delete_membership_when_barberprofile_deleted(sender, instance: BarberProfile, **kwargs):
    """
    Ao excluir o BarberProfile, remove a Membership associada SOMENTE se for BARBER.
    (Não mexe em OWNER/MANAGER.)
    """
    try:
        Membership.objects.get(
            user=instance.user,
            shop=instance.shop,
            role=MembershipRole.BARBER
        ).delete()
    except Membership.DoesNotExist:
        pass


# ============================================================
# 3) Membership -> BarberProfile (somente para BARBER)
#    - espelha is_active -> profile.ativo
#    - se Membership BARBER for criada e não houver BarberProfile, pode criar (opcional)
# ============================================================

@receiver(post_save, sender=Membership)
def sync_profile_from_membership(sender, instance: Membership, created: bool, **kwargs):
    """
    Sincroniza mudanças vindas da Membership (apenas para BARBER):
      - espelha membership.is_active -> profile.ativo
      - (opcional) cria BarberProfile se membership BARBER foi criada sem profile.
    """
    if instance.role != MembershipRole.BARBER:
        # Não sincronizamos OWNER/MANAGER com BarberProfile
        return

    user = instance.user
    shop = instance.shop

    try:
        profile = BarberProfile.objects.get(user=user, shop=shop)
    except BarberProfile.DoesNotExist:
        profile = None

    # Se membership BARBER foi criada sem profile, podemos criar um automaticamente (opcional).
    # Comportamento padrão: cria um profile “básico”.
    if created and profile is None:
        def _do_create_profile():
            BarberProfile.objects.create(
                user=user,
                shop=shop,
                public_slug=f"{user.pk}-{shop.pk}",  # ajuste se tiver outra regra
                ativo=instance.is_active,
            )
        transaction.on_commit(_do_create_profile)
        return

    # Espelha is_active -> ativo
    if profile is not None:
        _update_instance_fields(profile, ativo=instance.is_active)

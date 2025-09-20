# barbearias/signals.py
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.conf import settings

from .models import BarberProfile, Membership, MembershipRole


@receiver(post_save, sender=BarberProfile)
def create_membership_for_barber(sender, instance, created, **kwargs):
    """
    Sempre que um BarberProfile for criado, garante que exista um Membership correspondente
    com role=BARBER.
    """
    if created:
        Membership.objects.get_or_create(
            user=instance.user,
            shop=instance.shop,
            defaults={
                "role": MembershipRole.BARBER,
                "is_active": instance.ativo,
            },
        )


@receiver(post_save, sender=BarberProfile)
def sync_membership_status(sender, instance, created, **kwargs):
    """
    Sincroniza is_active do Membership com o BarberProfile.
    """
    try:
        membership = Membership.objects.get(user=instance.user, shop=instance.shop)
        if membership.role == MembershipRole.BARBER and membership.is_active != instance.ativo:
            membership.is_active = instance.ativo
            membership.save(update_fields=["is_active"])
    except Membership.DoesNotExist:
        # Se não existir, não faz nada (ou poderia recriar)
        pass


@receiver(pre_delete, sender=BarberProfile)
def delete_membership_when_barberprofile_deleted(sender, instance, **kwargs):
    """
    Remove o Membership associado quando o BarberProfile for excluído.
    """
    try:
        membership = Membership.objects.get(user=instance.user, shop=instance.shop, role=MembershipRole.BARBER)
        membership.delete()
    except Membership.DoesNotExist:
        pass

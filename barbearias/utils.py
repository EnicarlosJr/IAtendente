# barbearias/utils.py
from .models import Membership

def get_default_shop_for(user):
    # pega a primeira associação ativa
    return (
        Membership.objects.select_related("shop")
        .filter(user=user, is_active=True)
        .order_by("-role")  # OWNER > MANAGER > BARBER
        .values_list("shop_id", flat=True)
        .first()
    )

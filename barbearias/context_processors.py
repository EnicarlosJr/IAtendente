from .models import BarberShop
from .utils import get_default_shop_for


def shop_context(request):
    """Adiciona `shop` e `shop_slug` no contexto global dos templates."""
    if not request.user.is_authenticated:
        return {"shop": None, "shop_slug": None}

    shop_id = request.session.get("shop_id")

    shop = None
    if shop_id:
        try:
            shop = BarberShop.objects.get(id=shop_id)
        except BarberShop.DoesNotExist:
            request.session.pop("shop_id", None)

    if not shop:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
                request.session["shop_id"] = sid
            except BarberShop.DoesNotExist:
                pass

    return {
        "shop": shop,
        "shop_slug": shop.slug if shop else None,
    }

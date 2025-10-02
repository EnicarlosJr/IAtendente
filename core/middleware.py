# core/middleware.py
from django.utils.deprecation import MiddlewareMixin
from barbearias.models import BarberShop
from core.permissions import role_for

class ShopContextMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # se a view já injetou shop por resolver o slug, não mexe
        if getattr(request, "shop", None):
            request.membership_role = role_for(request.user, request.shop)
            return

        # tenta ?shop=<slug> para /painel/
        slug = (request.GET.get("shop") or "").strip()
        if slug:
            try:
                request.shop = BarberShop.objects.get(slug=slug)
            except BarberShop.DoesNotExist:
                request.shop = None
        else:
            # fallback “primeira barbearia do usuário”
            if request.user.is_authenticated:
                request.shop = (request.user.memberships
                                           .filter(is_active=True)
                                           .select_related("shop")
                                           .values_list("shop", flat=False)
                                           .first())
                if request.shop and not hasattr(request.shop, "slug"):
                    # quando vier como dict/tuple, reconsulta
                    from django.shortcuts import get_object_or_404
                    request.shop = get_object_or_404(BarberShop, pk=request.shop)
            else:
                request.shop = None

        request.membership_role = role_for(request.user, request.shop)

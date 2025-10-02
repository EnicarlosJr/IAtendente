# core/access.py
from __future__ import annotations
from functools import wraps
from typing import Callable, Optional
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.contrib import messages                      # ✅ CORRETO
from django.contrib.auth.views import redirect_to_login
from barbearias.models import BarberShop, Membership, MembershipRole

def _wants_json(request: HttpRequest) -> bool:
    xrw = (request.headers.get("X-Requested-With") or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    return xrw == "xmlhttprequest" or "application/json" in accept

def get_membership(user, shop) -> Optional[Membership]:
    if not (user and user.is_authenticated and shop):
        return None
    return Membership.objects.filter(user=user, shop=shop, is_active=True).first()

def get_shop_for_user(request: HttpRequest, shop_slug: str) -> BarberShop:
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    mem = get_membership(request.user, shop)
    if not mem:
        raise Http404("Barbearia não encontrada.")
    request.shop = shop
    request.membership = mem
    return shop

def is_manager(request: HttpRequest) -> bool:
    mem = getattr(request, "membership", None)
    return bool(mem and mem.role in (MembershipRole.OWNER, MembershipRole.MANAGER))

def require_shop_member(view: Callable) -> Callable:
    """Confere login + associação à barbearia do shop_slug; injeta request.shop."""
    @wraps(view)
    def _wrapped(request: HttpRequest, shop_slug: str, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        shop = get_object_or_404(BarberShop, slug=shop_slug)
        # checa associação
        if not Membership.objects.filter(shop=shop, user=request.user, is_active=True).exists():
            if _wants_json(request):
                return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
            messages.error(request, "Sem acesso a esta barbearia.")
            return redirect("painel:dashboard")
        request.shop = shop
        return view(request, shop_slug, *args, **kwargs)
    return _wrapped

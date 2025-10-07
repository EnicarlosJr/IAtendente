# barbearias/views.py
from __future__ import annotations
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.http import HttpResponseBadRequest
from django.conf import settings
from django.contrib.auth import get_user_model

from barbearias.forms_public import PublicRequestForm
from core.access import require_shop_member

from .models import BarberShop, Membership, MembershipRole
from .utils import get_default_shop_for
from .permissions import get_shop_from_request

from .forms import ShopSignupForm   # 👈 garanta esses imports
from servicos.models import Servico

User = get_user_model()

@require_shop_member
@login_required
@csrf_protect
def shop_signup(request):
    if request.method == "POST":
        form = ShopSignupForm(request.POST)
        if form.is_valid():
            shop = BarberShop.objects.create(
                owner=request.user,
                nome=form.cleaned_data["shop_name"],
            )
            Membership.objects.create(user=request.user, shop=shop, role=MembershipRole.OWNER, is_active=True)
            request.session["shop_id"] = shop.id
            return redirect("painel:dashboard")
    else:
        form = ShopSignupForm()
    return render(request, "barbearias/shop_signup.html", {"form": form})

@require_shop_member
@login_required
def switch_shop(request, slug):
    shop = get_object_or_404(BarberShop, slug=slug)
    if not Membership.objects.filter(user=request.user, shop=shop, is_active=True).exists():
        return HttpResponseBadRequest("Sem acesso a esta barbearia.")
    request.session["shop_id"] = shop.id
    return redirect("painel:dashboard")

# Página pública para agendamentos
def public_booking(request, barber_username):
    barber = get_object_or_404(User, username=barber_username)
    member = Membership.objects.filter(user=barber, is_active=True).select_related("shop").first()
    if not member:
        return HttpResponseBadRequest("Barbeiro sem barbearia ativa.")

    qs = Servico.objects.filter(ativo=True)
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=member.shop)

    if request.method == "POST":
        form = PublicRequestForm(request.POST)
        if form.is_valid():
            return HttpResponseBadRequest("Envie via fetch para o endpoint de intake.")
    else:
        form = PublicRequestForm()

    return render(request, "barbearias/public_booking.html", {
        "barber": barber,
        "shop": member.shop,
        "servicos": qs.order_by("nome"),
        "form": form,
        "intake_url": "/api/solicitacoes/intake/",
        "api_key": getattr(settings, "INBOUND_API_KEY", ""),
    })

# barbearias/views.py
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_protect
from django.http import HttpResponseBadRequest, JsonResponse
from django.conf import settings

from .forms import ShopSignupForm, PublicRequestForm
from .models import BarberShop, Membership, MembershipRole
from .utils import get_default_shop_for

from servicos.models import Servico
from django.contrib.auth import get_user_model
User = get_user_model()

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
            Membership.objects.create(user=request.user, shop=shop, role=MembershipRole.OWNER)
            request.session["shop_id"] = shop.id
            return redirect("painel:dashboard")
    else:
        form = ShopSignupForm()
    return render(request, "barbearias/shop_signup.html", {"form": form})

@login_required
def switch_shop(request, slug):
    shop = get_object_or_404(BarberShop, slug=slug)
    # verifica se o usuário pertence
    if not Membership.objects.filter(user=request.user, shop=shop, is_active=True).exists():
        return HttpResponseBadRequest("Sem acesso a esta barbearia.")
    request.session["shop_id"] = shop.id
    return redirect("painel:dashboard")

def public_booking(request, barber_username):
    """
    Página pública do barbeiro: lista serviços ativos da barbearia do barbeiro
    e envia POST para a sua intake (/api/solicitacoes/intake/).
    """
    barber = get_object_or_404(User, username=barber_username)
    member = Membership.objects.filter(user=barber, is_active=True).select_related("shop").first()
    if not member:
        return HttpResponseBadRequest("Barbeiro sem barbearia ativa.")

    # serviços da barbearia (assumindo Servico tem FK shop nullable; se não tiver, remova o filtro)
    qs = Servico.objects.filter(ativo=True)
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=member.shop)

    if request.method == "POST":
        form = PublicRequestForm(request.POST)
        if form.is_valid():
            # Envia direto para sua view intake interna (sem API externa)
            from solicitacoes.views import IntakeSolicitacaoView  # sua API interna DRF
            data = form.cleaned_data
            # Inclui id_externo opcional (slug+timestamp)
            data["id_externo"] = data.get("id_externo") or f"{barber.username}-{request.META.get('REMOTE_ADDR','')}"
            # força o nome exato do serviço escolhido no select
            # (o form já manda 'servico' como string)
            drf_view = IntakeSolicitacaoView.as_view()
            # Repassa request fake? Simples: chame via API HTTP? Para evitar requests, vamos montar um POST interno:
            # Melhor: poste para o endpoint via fetch no template. Aqui só renderizamos a página.
            return HttpResponseBadRequest("Use o formulário da página (JS) para enviar.")
        # se inválido, cai no render com erros
    else:
        form = PublicRequestForm()

    return render(request, "barbearias/public_booking.html", {
        "barber": barber,
        "shop": member.shop,
        "servicos": qs.order_by("nome"),
        "form": form,
        "intake_url": "/api/solicitacoes/intake/",
        "api_key": getattr(settings, "INBOUND_API_KEY", ""),  # opcional
    })

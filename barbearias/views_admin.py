from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.functional import cached_property

from .models import BarberShop, Membership, MembershipRole
from .forms import InviteMemberForm, UpdateMemberForm
from .utils import get_default_shop_for  # você já usa isso no painel

User = get_user_model()

def _ensure_shop(request):
    shop_id = request.session.get("shop_id")
    if shop_id:
        try:
            return BarberShop.objects.get(id=shop_id)
        except BarberShop.DoesNotExist:
            pass
    sid = get_default_shop_for(request.user)
    if sid:
        request.session["shop_id"] = sid
        return BarberShop.objects.get(id=sid)
    return None

def _user_can_manage(shop, user):
    if not (user and user.is_authenticated and shop):
        return False
    mem = Membership.objects.filter(shop=shop, user=user, is_active=True).first()
    return bool(mem and mem.role in (MembershipRole.OWNER, MembershipRole.MANAGER))

@login_required
def usuarios(request):
    """Lista e convida membros da barbearia atual."""
    shop = _ensure_shop(request)
    if not shop:
        messages.info(request, "Associe-se a uma barbearia para continuar.")
        return redirect("painel:dashboard")  # ou outra rota de onboarding

    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão para gerenciar usuários nesta barbearia.")
        return redirect("painel:dashboard")

    membros = (Membership.objects
               .select_related("user")
               .filter(shop=shop)
               .order_by("-is_active", "role", "user__username"))

    # contador de pendências para o sidebar (opcional)
    try:
        from solicitacoes.models import Solicitacao
        pend = Solicitacao.objects.filter(status="PENDENTE").count()
    except Exception:
        pend = 0

    ctx = {
        "title": "Usuários da barbearia",
        "shop": shop,
        "membros": membros,
        "invite_form": InviteMemberForm(),
        "solicitacoes_pendentes_count": pend,
    }
    return render(request, "barbearias/usuarios.html", ctx)

@login_required
def usuarios_convidar(request):
    shop = _ensure_shop(request)
    if not shop:
        return redirect("painel:dashboard")
    if request.method != "POST":
        return redirect("barbearias:usuarios")
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão.")
        return redirect("barbearias:usuarios")

    form = InviteMemberForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Verifique os dados do convite.")
        return redirect("barbearias:usuarios")

    email = form.cleaned_data["email"].strip().lower()
    role = form.cleaned_data["role"]

    user, _ = User.objects.get_or_create(
        email=email,
        defaults={"username": email, "is_active": True}
    )

    mem, created = Membership.objects.get_or_create(
        user=user, shop=shop, defaults={"role": role, "is_active": True}
    )
    if not created:
        mem.role = role
        mem.is_active = True
        mem.save(update_fields=["role", "is_active"])

    messages.success(request, f"{email} agora é {dict(MembershipRole.choices).get(role, role)}.")
    # TODO (opcional): enviar e-mail de convite / definição de senha
    return redirect("barbearias:usuarios")

@login_required
def usuarios_atualizar(request, mem_id: int):
    shop = _ensure_shop(request)
    if not shop:
        return redirect("painel:dashboard")
    if request.method != "POST":
        return redirect("barbearias:usuarios")
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão.")
        return redirect("barbearias:usuarios")

    mem = get_object_or_404(Membership, id=mem_id, shop=shop)
    form = UpdateMemberForm(request.POST, instance=mem)
    if form.is_valid():
        form.save()
        messages.success(request, "Membro atualizado.")
    else:
        messages.error(request, "Não foi possível atualizar este membro.")
    return redirect("barbearias:usuarios")

@login_required
def usuarios_remover(request, mem_id: int):
    shop = _ensure_shop(request)
    if not shop:
        return redirect("painel:dashboard")
    if request.method != "POST":
        return redirect("barbearias:usuarios")
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão.")
        return redirect("barbearias:usuarios")

    mem = get_object_or_404(Membership, id=mem_id, shop=shop)
    mem.is_active = False
    mem.save(update_fields=["is_active"])
    messages.success(request, "Membro desativado.")
    return redirect("barbearias:usuarios")

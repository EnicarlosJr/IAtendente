# barbearias/views_admin.py
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Count
from django.contrib.auth import get_user_model

from core.access import require_shop_member

from .models import BarberShop, Membership, MembershipRole
from .forms import AddMemberForm, UpdateMemberForm
from django.utils import timezone

User = get_user_model()

def _user_can_manage(shop, user):
    if not (user and user.is_authenticated and shop):
        return False
    mem = Membership.objects.filter(shop=shop, user=user, is_active=True).first()
    return bool(mem and mem.role in (MembershipRole.OWNER, MembershipRole.MANAGER))

@require_shop_member
@login_required
def usuarios(request, shop_slug):
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão para gerenciar usuários nesta barbearia.")
        return redirect("painel:dashboard")

    membros = (Membership.objects
               .select_related("user")
               .filter(shop=shop)
               .order_by("-is_active", "role", "user__username"))

    mem = Membership.objects.filter(shop=shop, user=request.user, is_active=True).first()
    is_manager = bool(mem and mem.role in (MembershipRole.OWNER, MembershipRole.MANAGER))

    ctx = {
        "title": "Usuários da barbearia",
        "shop": shop,
        "membros": membros,
        "role_choices": MembershipRole.choices,
        "is_manager": is_manager,
        "add_form": AddMemberForm(acting_user=request.user, shop=shop),
    }
    return render(request, "barbearias/usuarios.html", ctx)

@require_shop_member
@login_required
def usuarios_adicionar(request, shop_slug):
    """Adiciona diretamente um usuário: cria o User se não existir e vincula Membership ativo."""
    if request.method != "POST":
        return redirect("barbearias:usuarios", shop_slug=shop_slug)

    shop = get_object_or_404(BarberShop, slug=shop_slug)
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão.")
        return redirect("barbearias:usuarios", shop_slug=shop_slug)

    form = AddMemberForm(request.POST, acting_user=request.user, shop=shop)
    if not form.is_valid():
        # agrega erros numa mensagem simples
        errs = " | ".join(f"{f or 'form'}: {e}" for f, es in form.errors.items() for e in es)
        messages.error(request, errs or "Verifique os dados.")
        return redirect("barbearias:usuarios", shop_slug=shop_slug)

    name = form.cleaned_data.get("name") or ""
    email = form.cleaned_data["email"]
    role  = form.cleaned_data["role"]
    password = form.cleaned_data.get("password") or ""

    # cria (ou pega) o usuário
    user, created_user = User.objects.get_or_create(
        email=email,
        defaults={"username": email, "first_name": name[:150], "is_active": True},
    )
    # se o user já existe e não tem nome, atualiza o first_name (sem mexer nos que já tem)
    if not created_user and name and not getattr(user, "first_name", ""):
        user.first_name = name[:150]
        user.save(update_fields=["first_name"])

    # senha só se for novo usuário e você informou password
    if created_user and password:
        user.set_password(password)
        user.save(update_fields=["password"])

    # vincula membership ativo (ou reativa/atualiza role)
    mem, created_mem = Membership.objects.get_or_create(
        user=user, shop=shop, defaults={"role": role, "is_active": True}
    )
    if not created_mem:
        mem.role = role
        mem.is_active = True
        mem.save(update_fields=["role", "is_active"])

    if created_user:
        if password:
            messages.success(request, f"{email} criado e adicionado como {role}.")
        else:
            messages.success(request, f"{email} criado sem senha definida e adicionado como {role}.")
    else:
        messages.success(request, f"{email} adicionado/reativado como {role}.")

    return redirect("barbearias:usuarios", shop_slug=shop_slug)

@require_shop_member
@login_required
def usuarios_atualizar(request, shop_slug, mem_id: int):
    if request.method != "POST":
        return redirect("barbearias:usuarios", shop_slug=shop_slug)
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão.")
        return redirect("barbearias:usuarios", shop_slug=shop_slug)

    mem = get_object_or_404(Membership, id=mem_id, shop=shop)
    form = UpdateMemberForm(request.POST, instance=mem)
    if form.is_valid():
        # OWNER não pode ser alterado para evitar travas indevidas
        if mem.role == MembershipRole.OWNER and form.cleaned_data.get("role") != MembershipRole.OWNER:
            messages.error(request, "Não é possível alterar o papel do OWNER.")
        else:
            form.save()
            messages.success(request, "Membro atualizado.")
    else:
        errs = " | ".join(f"{f or 'form'}: {e}" for f, es in form.errors.items() for e in es)
        messages.error(request, errs or "Não foi possível atualizar este membro.")
    return redirect("barbearias:usuarios", shop_slug=shop_slug)

@require_shop_member
@login_required
def usuarios_remover(request, shop_slug, mem_id: int):
    if request.method != "POST":
        return redirect("barbearias:usuarios", shop_slug=shop_slug)
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão.")
        return redirect("barbearias:usuarios", shop_slug=shop_slug)

    mem = get_object_or_404(Membership, id=mem_id, shop=shop)
    if mem.role == MembershipRole.OWNER:
        messages.error(request, "Não é possível remover o OWNER da barbearia.")
        return redirect("barbearias:usuarios", shop_slug=shop_slug)
    if mem.user_id == request.user.id:
        messages.error(request, "Você não pode remover a si mesmo.")
        return redirect("barbearias:usuarios", shop_slug=shop_slug)

    mem.is_active = False
    mem.save(update_fields=["is_active"])
    messages.success(request, f"{mem.user.email} removido da barbearia.")
    return redirect("barbearias:usuarios", shop_slug=shop_slug)

@require_shop_member
@login_required
def fluxo(request, shop_slug):
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    if not _user_can_manage(shop, request.user):
        messages.error(request, "Sem permissão para acessar o fluxo desta barbearia.")
        return redirect("painel:dashboard")

    try:
        from .models import AccessEvent
        qs = (AccessEvent.objects
              .filter(shop=shop)
              .select_related("user")
              .order_by("-created_at"))
        events = list(qs[:300])
        stats = qs.values("kind").annotate(total=Count("id")).order_by("kind")
    except Exception:
        events, stats = [], []
        messages.info(request, "O modelo AccessEvent ainda não está disponível.")

    return render(request, "barbearias/fluxo.html", {
        "title": "Fluxo de pessoas",
        "shop": shop,
        "events": events,
        "stats": stats,
        "now": timezone.now(),
    })

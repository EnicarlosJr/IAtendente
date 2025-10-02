# barbearias/views_public.py
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .models import BarberShop
from servicos.models import Servico
from solicitacoes.models import Solicitacao, SolicitacaoStatus

# ——— Import opcional (não quebra se ainda não existir) ———
try:
    from .models import BarberProfile  # type: ignore
except Exception:  # pragma: no cover
    BarberProfile = None  # type: ignore


# ===================== Helpers =====================

def _normalize_phone(raw: str) -> str:
    """Mantém só dígitos; útil para deduplicação/mensagens mais consistentes."""
    return "".join(ch for ch in (raw or "") if ch.isdigit())

def _safe_int(s: str | None) -> Optional[int]:
    try:
        return int((s or "").strip())
    except Exception:
        return None

def _parse_inicio_aware(inicio_str: str | None):
    """
    Converte 'YYYY-MM-DDTHH:MM' para datetime *aware* na timezone atual.
    Retorna None se vazio/inválido.
    """
    if not inicio_str:
        return None
    dt = parse_datetime(inicio_str.strip())
    if not dt:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

def _set_if_field(obj, field_name, value):
    """Define obj.<field_name>=value apenas se o campo existir no model."""
    if hasattr(obj, field_name):
        setattr(obj, field_name, value)

def _servicos_da_loja(shop: BarberShop):
    """
    Lista serviços ativos. Se seu model de Servico tiver FK 'shop', filtra por ela.
    """
    qs = Servico.objects.filter(ativo=True).order_by("nome")
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=shop)
    return qs

def _servico_by_id_for_shop(servico_id: int | None, shop: BarberShop) -> Optional[Servico]:
    if not servico_id:
        return None
    qs = Servico.objects.filter(id=servico_id, ativo=True)
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=shop)
    return qs.first()


@transaction.atomic
def _criar_solicitacao(request, shop: BarberShop, barber_obj=None) -> Solicitacao | None:
    """
    Cria uma Solicitação a partir do POST público.
    - Tolerante a esquemas: só seta campos que existirem na sua Solicitacao (barbearia, barbeiro, etc.)
    - Usa snapshots do serviço (nome, preço, duração) se existirem no model.
    """
    nome = (request.POST.get("nome") or "").strip()
    telefone = _normalize_phone(request.POST.get("telefone") or "")
    servico_id = _safe_int(request.POST.get("servico_id"))
    inicio_str = (request.POST.get("inicio") or "").strip()
    observacoes = (request.POST.get("observacoes") or "").strip()

    if not telefone or not servico_id:
        messages.error(request, "Informe telefone e serviço.")
        return None

    # Serviço válido e (se houver FK) pertencente à loja
    srv = _servico_by_id_for_shop(servico_id, shop)
    if not srv:
        messages.error(request, "Serviço inválido ou inativo.")
        return None

    # Início (opcional)
    dt = _parse_inicio_aware(inicio_str)

    # Monta o objeto (sem salvar ainda, para setar campos condicionalmente)
    s = Solicitacao(
        telefone=telefone,
        nome=nome or telefone,
        servico=srv,  # FK real (se existir)
        inicio=dt,
        observacoes=observacoes or "",
        status=SolicitacaoStatus.PENDENTE,
    )

    # Snapshots e campos opcionais (só se existirem)
    _set_if_field(s, "servico_nome", getattr(srv, "nome", "") or "")
    _set_if_field(s, "duracao_min_cotada", getattr(srv, "duracao_min", None))
    _set_if_field(s, "preco_cotado", getattr(srv, "preco", None))
    _set_if_field(s, "barbearia", shop)  # se existir FK para a barbearia

    if barber_obj:
        # se existir BarberProfile, normalmente ele referencia um usuário em barber_obj.user
        barbeiro_user = getattr(barber_obj, "user", None) or barber_obj
        _set_if_field(s, "barbeiro", barbeiro_user)

    # (Opcional) Anti-duplicação ingênua: evita 2 submits idênticos em 2 min
    if hasattr(Solicitacao, "criado_em"):
        dois_min_antes = timezone.now() - timezone.timedelta(minutes=2)
        dup = (Solicitacao.objects
               .filter(telefone=telefone, status=SolicitacaoStatus.PENDENTE)
               .filter(criado_em__gte=dois_min_antes))
        if dt:
            dup = dup.filter(inicio=dt)
        if dup.exists():
            messages.info(request, "Já recebemos sua solicitação recente. Aguarde confirmação.")
            return dup.order_by("-id").first()

    # Salva com possíveis normalizações do model (signals/overrides)
    s.save()
    return s


# ===================== Views públicas =====================

@require_http_methods(["GET", "POST"])
def intake_shop(request, shop_slug):
    """
    Página pública da barbearia (sem login) para o cliente enviar solicitação.
    URL: /pub/<shop_slug>/
    """
    # Se seu BarberShop tiver campo 'ativo', mantenha; senão, remova o filtro 'ativo=True'.
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True) if hasattr(BarberShop, "ativo") \
           else get_object_or_404(BarberShop, slug=shop_slug)

    if request.method == "POST":
        s = _criar_solicitacao(request, shop, barber_obj=None)
        if s:
            messages.success(request, "Solicitação enviada! Em breve entraremos em contato.")
            # redireciona para evitar reenvio em refresh (PRG pattern)
            return redirect("public:intake_shop", shop.slug)

    return render(request, "public/intake_form.html", {
        "shop": shop,
        "barber": None,
        "servicos": _servicos_da_loja(shop),
        "now": timezone.now(),
    })


@require_http_methods(["GET", "POST"])
def intake_barber(request, shop_slug, barber_slug):
    """
    Página pública de um barbeiro específico (sem login) para o cliente enviar solicitação.
    URL: /pub/<shop_slug>/<barber_slug>/
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True) if hasattr(BarberShop, "ativo") \
           else get_object_or_404(BarberShop, slug=shop_slug)

    if BarberProfile is None:
        messages.error(request, "Perfil de barbeiro ainda não configurado.")
        return redirect("public:intake_shop", shop.slug)

    barber = get_object_or_404(BarberProfile, shop=shop, public_slug=barber_slug, ativo=True)

    if request.method == "POST":
        s = _criar_solicitacao(request, shop, barber_obj=barber)
        if s:
            messages.success(request, "Solicitação enviada para o barbeiro! Aguarde confirmação.")
            return redirect("public:intake_barber", shop.slug, barber.public_slug)

    return render(request, "public/intake_form.html", {
        "shop": shop,
        "barber": barber,
        "servicos": _servicos_da_loja(shop),
        "now": timezone.now(),
    })

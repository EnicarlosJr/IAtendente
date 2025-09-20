# barbearias/views_public.py
from __future__ import annotations

from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils.dateparse import parse_datetime

from servicos.models import Servico
from solicitacoes.models import Solicitacao, SolicitacaoStatus
from .models import BarberShop

# ——— Import opcional (não quebra se ainda não existir) ———
try:
    from .models import BarberProfile
except Exception:  # pragma: no cover
    BarberProfile = None  # type: ignore


# ============== Helpers ==============

def _servicos_da_loja(shop: BarberShop):
    """
    Se no futuro você adicionar FK 'shop' em Servico, filtre por shop=shop.
    Por enquanto, listamos apenas serviços ativos, ordenados por nome.
    """
    return Servico.objects.filter(ativo=True).order_by("nome")


def _parse_inicio_aware(inicio_str: str | None):
    """
    Converte 'YYYY-MM-DDTHH:MM' em datetime aware (timezone atual). Retorna None se vazio/inválido.
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


def _criar_solicitacao(request, shop: BarberShop, barber_obj=None) -> Solicitacao | None:
    """
    Cria uma Solicitação a partir do POST público.
    - Tolerante a esquemas: só seta campos que existirem na sua Solicitacao (barbearia, barbeiro, etc.)
    """
    nome = (request.POST.get("nome") or "").strip()
    telefone = (request.POST.get("telefone") or "").strip()
    servico_id = (request.POST.get("servico_id") or "").strip()
    inicio_str = (request.POST.get("inicio") or "").strip()
    observacoes = (request.POST.get("observacoes") or "").strip()

    if not telefone or not servico_id:
        messages.error(request, "Informe telefone e serviço.")
        return None

    # Serviço (ativo)
    try:
        srv = Servico.objects.get(pk=int(servico_id), ativo=True)
    except Exception:
        messages.error(request, "Serviço inválido ou inativo.")
        return None

    # Início (opcional)
    dt = _parse_inicio_aware(inicio_str)

    # Monta o objeto (sem salvar ainda, para setar campos condicionalmente)
    s = Solicitacao(
        telefone=telefone,
        nome=nome or telefone,
        servico=srv,                    # FK real
        servico_nome=getattr(srv, "nome", "") or "",  # snapshot (seu model tem)
        duracao_min_cotada=getattr(srv, "duracao_min", None),
        preco_cotado=getattr(srv, "preco", None),
        inicio=dt,
        observacoes=observacoes or "",
        status=SolicitacaoStatus.PENDENTE,
    )

    # Campos opcionais: só define se existirem no model
    _set_if_field(s, "barbearia", shop)  # FK para BarberShop, se você tiver
    if barber_obj:
        # se existir BarberProfile, normalmente ele referencia um usuário em barber_obj.user
        barbeiro_user = getattr(barber_obj, "user", None) or barber_obj
        _set_if_field(s, "barbeiro", barbeiro_user)

    # Salva com normalização do model (preenche fim se tiver inicio, etc.)
    s.save()
    return s


# ============== Views públicas ==============

@require_http_methods(["GET", "POST"])
def intake_shop(request, shop_slug):
    """
    Página pública da barbearia (sem login) para o cliente enviar solicitação.
    URL sugerida: /pub/<shop_slug>/
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True)

    if request.method == "POST":
        s = _criar_solicitacao(request, shop, barber_obj=None)
        if s:
            messages.success(request, "Solicitação enviada! Em breve entraremos em contato.")
            # redireciona para evitar reenvio em refresh
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
    URL sugerida: /pub/<shop_slug>/<barber_slug>/
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True)

    if BarberProfile is None:
        # Se ainda não existe BarberProfile no seu projeto, tratamos com uma mensagem amigável:
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

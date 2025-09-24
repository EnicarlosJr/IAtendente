from datetime import timedelta
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from barbearias.models import BarberShop
from .models import Cliente, HistoricoItem
from .forms import ClienteForm, HistoricoItemForm


# -------- Helpers --------
def _now_tz():
    return timezone.localtime(timezone.now(), timezone.get_current_timezone())


def _inactive_cutoff(days=30):
    return _now_tz() - timedelta(days=days)


def _get_shop_or_404(shop_slug):
    """Resolve a barbearia pelo slug vindo da URL"""
    return get_object_or_404(BarberShop, slug=shop_slug)


# -------- Listagem --------
def clientes_list(request, shop_slug):
    shop = _get_shop_or_404(shop_slug)
    qs = Cliente.objects.filter(shop=shop).order_by("nome")

    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "").strip()
    inativos_30d = request.GET.get("inativos_30d") == "1"

    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))
    if status_:
        qs = qs.filter(recorrencia_status=status_)
    if inativos_30d:
        cutoff = _inactive_cutoff(30)
        qs = qs.filter(Q(ultimo_corte__lt=cutoff) | Q(ultimo_corte__isnull=True))

    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page"))

    ctx = {
        "title": "Clientes",
        "shop": shop,  # 👈 garante que o template saiba qual barbearia está ativa
        "clientes": page,
        "page_obj": page,
        "filters": {"q": q, "status": status_, "inativos_30d": inativos_30d},
    }
    return render(request, "clientes/clientes.html", ctx)


# -------- Criar/Editar --------
@transaction.atomic
def cliente_new(request, shop_slug):
    shop = _get_shop_or_404(shop_slug)
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.shop = shop  # 👈 vincula o cliente à barbearia
            c.save()
            messages.success(request, "Cliente criado.")
            return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)
    else:
        form = ClienteForm()
    return render(
        request,
        "clientes/cliente_form.html",
        {"form": form, "title": "Novo cliente", "shop": shop},
    )


@transaction.atomic
def cliente_edit(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)
    if request.method == "POST":
        form = ClienteForm(request.POST, instance=c)
        if form.is_valid():
            form.save()
            messages.success(request, "Dados do cliente atualizados.")
            return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)
    else:
        form = ClienteForm(instance=c)
    return render(
        request,
        "clientes/cliente_form.html",
        {"form": form, "title": f"Editar · {c.nome}", "shop": shop},
    )


# -------- Detalhe + adicionar histórico --------
def cliente_detail(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)
    hist = c.historico.filter(shop=shop).order_by("-data")[:20]
    form_hist = HistoricoItemForm()

    prox_retorno_sugerido = None
    if c.ultimo_corte:
        prox_retorno_sugerido = c.ultimo_corte + timedelta(days=30)

    ctx = {
        "title": c.nome,
        "shop": shop,
        "cliente": c,
        "historico": hist,
        "form_hist": form_hist,
        "prox_retorno_sugerido": prox_retorno_sugerido,
    }
    return render(request, "clientes/cliente_detalhe.html", ctx)


@require_POST
@transaction.atomic
def cliente_add_historico(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)
    form = HistoricoItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.cliente = c
        item.shop = shop  # 👈 histórico também vinculado à barbearia
        item.save()

        # Atualiza status do cliente
        if not item.faltou:
            if c.ultimo_corte is None or item.data > c.ultimo_corte:
                c.ultimo_corte = item.data
            if c.recorrencia_status != Cliente.RecorrenciaStatus.ATIVO:
                c.recorrencia_status = Cliente.RecorrenciaStatus.ATIVO
        c.save(update_fields=["ultimo_corte", "recorrencia_status", "updated_at"])
        messages.success(request, "Histórico adicionado.")
    else:
        messages.error(request, "Verifique os dados do histórico.")
    return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)


# -------- Ação rápida: registrar corte hoje --------
@require_POST
@transaction.atomic
def cliente_corte_hoje(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)
    servico = (request.POST.get("servico") or "Corte").strip()
    now = _now_tz()
    HistoricoItem.objects.create(
        cliente=c,
        shop=shop,  # 👈 histórico sempre amarrado à barbearia
        data=now,
        servico=servico,
        faltou=False,
    )
    c.ultimo_corte = now
    c.recorrencia_status = Cliente.RecorrenciaStatus.ATIVO
    c.save(update_fields=["ultimo_corte", "recorrencia_status", "updated_at"])
    messages.success(request, "Corte de hoje registrado.")
    return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)

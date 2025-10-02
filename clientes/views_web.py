from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.access import require_shop_member
from barbearias.models import BarberShop
from .models import Cliente, HistoricoItem
from .forms import ClienteForm, HistoricoItemForm

#-------- Helpers --------
def _now_tz():
    return timezone.localtime(timezone.now(), timezone.get_current_timezone())

def _inactive_cutoff(days=None):
    days = days or getattr(settings, "CLIENTE_INATIVO_DIAS", 60)
    return _now_tz() - timedelta(days=days)

def _get_shop_or_404(shop_slug):
    return get_object_or_404(BarberShop, slug=shop_slug)


# -------- Listagem --------
@require_shop_member
def clientes_list(request, shop_slug):
    shop = _get_shop_or_404(shop_slug)

    qs = Cliente.objects.filter(shop=shop).order_by("nome")

    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "").strip()  # "ATIVO" | "INATIVO" | ""
    inativos_flag = request.GET.get("inativos") == "1"
    dias_param = request.GET.get("dias")

    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))

    if status_ in (Cliente.RecorrenciaStatus.ATIVO, Cliente.RecorrenciaStatus.INATIVO):
        qs = qs.filter(recorrencia_status=status_)

    if inativos_flag:
        try:
            dias = int(dias_param) if dias_param else None
        except ValueError:
            dias = None
        cutoff = _inactive_cutoff(dias)
        qs = qs.filter(Q(ultimo_corte__lt=cutoff) | Q(ultimo_corte__isnull=True))

    page = Paginator(qs, 20).get_page(request.GET.get("page"))

    ctx = {
        "title": "Clientes",
        "shop": shop,
        "clientes": page,
        "page_obj": page,
        "filters": {
            "q": q,
            "status": status_,
            "inativos": inativos_flag,
            "dias": dias_param or "",
        },
    }
    return render(request, "clientes/clientes.html", ctx)



# -------- Criar/Editar --------
@require_shop_member
@transaction.atomic
def cliente_new(request, shop_slug):
    shop = _get_shop_or_404(shop_slug)
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            c = form.save(commit=False)
            c.shop = shop
            c.save()
            c.refresh_recorrencia(save=True)  # garante status inicial coerente
            messages.success(request, "Cliente criado.")
            return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)
    else:
        form = ClienteForm()
    return render(request, "clientes/cliente_form.html", {"form": form, "title": "Novo cliente", "shop": shop})

@require_shop_member
@transaction.atomic
def cliente_edit(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)
    if request.method == "POST":
        form = ClienteForm(request.POST, instance=c)
        if form.is_valid():
            c = form.save()
            c.refresh_recorrencia(save=True)  # caso altere ultimo_corte manualmente
            messages.success(request, "Dados do cliente atualizados.")
            return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)
    else:
        form = ClienteForm(instance=c)
    return render(request, "clientes/cliente_form.html", {"form": form, "title": f"Editar · {c.nome}", "shop": shop})



# -------- Detalhe + adicionar histórico --------
@require_shop_member
def cliente_detail(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)

    hist = c.historico.filter(shop=shop).order_by("-data")[:20]  # requer HistoricoItem.shop
    form_hist = HistoricoItemForm()

    cutoff = getattr(settings, "CLIENTE_INATIVO_DIAS", 60)
    dias_sem_visita = c.dias_desde_ultimo_corte()
    prox_retorno_sugerido = c.ultimo_corte + timedelta(days=cutoff) if c.ultimo_corte else None

    ctx = {
        "title": c.nome,
        "shop": shop,
        "cliente": c,
        "historico": hist,
        "form_hist": form_hist,
        "prox_retorno_sugerido": prox_retorno_sugerido,
        "dias_sem_visita": dias_sem_visita,
        "cutoff_dias": cutoff,
    }
    return render(request, "clientes/cliente_detalhe.html", ctx)

@require_shop_member
@require_POST
@transaction.atomic
def cliente_add_historico(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)

    form = HistoricoItemForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Verifique os dados do histórico.")
        return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)

    item = form.save(commit=False)
    item.cliente = c
    item.shop = shop  # 👈 agora existe no model
    # opcional: se tiver servico_ref, derive preco_tabela
    if item.servico_ref_id and item.preco_tabela is None:
        item.preco_tabela = getattr(item.servico_ref, "preco", None)
    item.save()

    # atualiza cliente (se não foi falta)
    if not item.faltou:
        c.set_ultimo_corte(item.data, save=True)
    c.refresh_recorrencia(save=True)

    messages.success(request, "Histórico adicionado.")
    return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)

# -------- Ação rápida: registrar corte hoje --------
@require_POST
@require_shop_member
@transaction.atomic
def cliente_corte_hoje(request, shop_slug, pk):
    shop = _get_shop_or_404(shop_slug)
    c = get_object_or_404(Cliente, pk=pk, shop=shop)

    servico_label = (request.POST.get("servico") or "Corte").strip()
    now = _now_tz()

    HistoricoItem.objects.create(
        shop=shop,
        cliente=c,
        data=now,
        servico=servico_label,
        faltou=False,
    )

    c.set_ultimo_corte(now, save=True)
    c.refresh_recorrencia(save=True)

    messages.success(request, "Corte de hoje registrado.")
    return redirect("clientes:detalhe", shop_slug=shop.slug, pk=c.pk)

from decimal import Decimal
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from barbearias.models import BarberShop
from .models import Servico
from .forms import ServicoForm


# =========================
# Helpers
# =========================
def _redirect_back(request: HttpRequest, fallback: str, **kwargs):
    nxt = request.GET.get("next") or request.POST.get("next")
    if nxt:
        return redirect(nxt)
    return redirect(fallback, **kwargs)


def _is_ajax(request: HttpRequest) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _get_shop_or_404(shop_slug: str) -> BarberShop:
    return get_object_or_404(BarberShop, slug=shop_slug)


# =========================
# Lista (tabela de preços)
# =========================
def servicos_lista(request: HttpRequest, shop_slug: str) -> HttpResponse:
    shop = _get_shop_or_404(shop_slug)

    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "ativos").strip()   # ativos|inativos|todos
    categoria = (request.GET.get("categoria") or "").strip()
    order = (request.GET.get("order") or "nome").strip()        # nome|preco|duracao

    qs = Servico.objects.filter(shop=shop)

    if q:
        qs = qs.filter(
            Q(nome__icontains=q) |
            Q(descricao__icontains=q) |
            Q(categoria__icontains=q)
        )

    if categoria:
        qs = qs.filter(categoria=categoria)

    if status_ == "ativos":
        qs = qs.filter(ativo=True)
    elif status_ == "inativos":
        qs = qs.filter(ativo=False)

    if order == "duracao":
        qs = qs.order_by("duracao_min", "nome")
    elif order == "preco":
        qs = qs.order_by("preco", "nome")
    else:
        qs = qs.order_by("nome")

    page_obj = Paginator(qs, 20).get_page(request.GET.get("page"))

    ctx = {
        "title": "Tabela de valores",
        "shop": shop,
        "servicos": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": status_, "order": order, "categoria": categoria},
    }
    return render(request, "servicos/servicos_lista.html", ctx)


def inativos(request: HttpRequest, shop_slug: str) -> HttpResponse:
    request.GET = request.GET.copy()
    request.GET["status"] = "inativos"
    return servicos_lista(request, shop_slug)


# =========================
# CRUD
# =========================
def servico_novo(request: HttpRequest, shop_slug: str) -> HttpResponse:
    shop = _get_shop_or_404(shop_slug)

    if request.method == "POST":
        form = ServicoForm(request.POST)
        if form.is_valid():
            s = form.save(commit=False)
            s.shop = shop
            s.save()
            messages.success(request, f"Serviço “{s.nome}” criado.")
            return redirect("servicos:lista", shop_slug=shop.slug)
    else:
        form = ServicoForm()

    return render(request, "servicos/servico_form.html", {"form": form, "title": "Novo serviço", "shop": shop})


def servico_detalhe(request: HttpRequest, shop_slug: str, pk: int) -> HttpResponse:
    shop = _get_shop_or_404(shop_slug)
    s = get_object_or_404(Servico, pk=pk, shop=shop)
    ctx = {"title": f"Serviço · {s.nome}", "servico": s, "shop": shop}
    return render(request, "servicos/servico_detalhe.html", ctx)


def servico_editar(request: HttpRequest, shop_slug: str, pk: int) -> HttpResponse:
    shop = _get_shop_or_404(shop_slug)
    s = get_object_or_404(Servico, pk=pk, shop=shop)

    if request.method == "POST":
        form = ServicoForm(request.POST, instance=s)
        if form.is_valid():
            form.save()
            messages.success(request, "Serviço atualizado.")
            return _redirect_back(request, "servicos:lista", shop_slug=shop.slug)
    else:
        form = ServicoForm(instance=s)

    return render(request, "servicos/servico_form.html", {"form": form, "title": f"Editar · {s.nome}", "shop": shop})


# =========================
# Ativar / Desativar
# =========================
@require_POST
def ativar(request: HttpRequest, shop_slug: str, pk: int):
    shop = _get_shop_or_404(shop_slug)
    s = get_object_or_404(Servico, pk=pk, shop=shop)
    if not s.ativo:
        s.ativo = True
        s.save(update_fields=["ativo"])
    if _is_ajax(request):
        return JsonResponse({"ok": True, "ativo": s.ativo})
    messages.success(request, f"Serviço “{s.nome}” ativado.")
    return _redirect_back(request, "servicos:lista", shop_slug=shop.slug)


@require_POST
def desativar(request: HttpRequest, shop_slug: str, pk: int):
    shop = _get_shop_or_404(shop_slug)
    s = get_object_or_404(Servico, pk=pk, shop=shop)
    if s.ativo:
        s.ativo = False
        s.save(update_fields=["ativo"])
    if _is_ajax(request):
        return JsonResponse({"ok": True, "ativo": s.ativo})
    messages.success(request, f"Serviço “{s.nome}” desativado.")
    return _redirect_back(request, "servicos:lista", shop_slug=shop.slug)


@require_POST
def servicos_toggle_ativo(request: HttpRequest, shop_slug: str, pk: int):
    shop = _get_shop_or_404(shop_slug)
    s = get_object_or_404(Servico, pk=pk, shop=shop)
    s.ativo = not s.ativo
    s.save(update_fields=["ativo"])
    return JsonResponse({"ok": True, "ativo": s.ativo})

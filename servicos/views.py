# servicos/views_web.py
from decimal import Decimal
from typing import Optional

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_POST

from .models import Servico
from .forms import ServicoForm


# =========================
# Helpers
# =========================
def _redirect_back(request: HttpRequest, fallback: str):
    """
    Redireciona para ?next=... se vier; senão, para a rota fallback (nomeada).
    """
    nxt = request.GET.get("next") or request.POST.get("next")
    return redirect(nxt) if nxt else redirect(fallback)


def _is_ajax(request: HttpRequest) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


# =========================
# Lista (tabela de preços)
# =========================
def servicos_lista(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "ativos").strip()   # ativos|inativos|todos
    categoria = (request.GET.get("categoria") or "").strip()
    order = (request.GET.get("order") or "nome").strip()        # nome|preco|duracao

    qs = Servico.objects.all()

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
        "servicos": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": status_, "order": order, "categoria": categoria},
    }
    return render(request, "servicos/servicos_lista.html", ctx)


def inativos(request: HttpRequest) -> HttpResponse:
    request.GET = request.GET.copy()
    request.GET["status"] = "inativos"
    return servicos_lista(request)


# =========================
# CRUD
# =========================
def servico_novo(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ServicoForm(request.POST)
        if form.is_valid():
            s = form.save()
            messages.success(request, f"Serviço “{s.nome}” criado.")
            return redirect("servicos:lista")
    else:
        form = ServicoForm()
    return render(request, "servicos/servico_form.html", {"form": form, "title": "Novo serviço"})


def servico_detalhe(request: HttpRequest, pk: int) -> HttpResponse:
    s = get_object_or_404(Servico, pk=pk)
    # Detalhe somente leitura (linka para editar)
    ctx = {"title": f"Serviço · {s.nome}", "servico": s}
    return render(request, "servicos/servico_detalhe.html", ctx)


def servico_editar(request: HttpRequest, pk: int) -> HttpResponse:
    s = get_object_or_404(Servico, pk=pk)
    if request.method == "POST":
        form = ServicoForm(request.POST, instance=s)
        if form.is_valid():
            form.save()
            messages.success(request, "Serviço atualizado.")
            return _redirect_back(request, "servicos:lista")
    else:
        form = ServicoForm(instance=s)
    return render(request, "servicos/servico_form.html", {"form": form, "title": f"Editar · {s.nome}"})


# =========================
# Ativar / Desativar
# =========================
@require_POST
def ativar(request: HttpRequest, pk: int):
    s = get_object_or_404(Servico, pk=pk)
    if not s.ativo:
        s.ativo = True
        s.save(update_fields=["ativo"])
    if _is_ajax(request):
        return JsonResponse({"ok": True, "ativo": s.ativo})
    messages.success(request, f"Serviço “{s.nome}” ativado.")
    return _redirect_back(request, "servicos:lista")


@require_POST
def desativar(request: HttpRequest, pk: int):
    s = get_object_or_404(Servico, pk=pk)
    if s.ativo:
        s.ativo = False
        s.save(update_fields=["ativo"])
    if _is_ajax(request):
        return JsonResponse({"ok": True, "ativo": s.ativo})
    messages.success(request, f"Serviço “{s.nome}” desativado.")
    return _redirect_back(request, "servicos:lista")

@require_POST
def servicos_toggle_ativo(request, pk: int):
    """
    Alterna o status 'ativo' de um Serviço e retorna JSON.
    Compatível com o template que usa: {% url 'solicitacoes:servicos_toggle_ativo' pk %}
    """
    s = get_object_or_404(Servico, pk=pk)
    s.ativo = not s.ativo
    s.save(update_fields=["ativo"])
    return JsonResponse({"ok": True, "ativo": s.ativo})
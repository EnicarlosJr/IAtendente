# solicitacoes/views_web.py
from datetime import timedelta
from decimal import Decimal

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST


from .models import Solicitacao, SolicitacaoStatus
from servicos.models import Servico  # catálogo oficial

# ----------------- Helpers -----------------
def _label_servico(s: Solicitacao) -> str:
    try:
        nome = getattr(getattr(s, "servico", None), "nome", None)
        return nome or (getattr(s, "servico_nome", None) or "Serviço")
    except Exception:
        return getattr(s, "servico_nome", None) or "Serviço"

def _duracao_min(s: Solicitacao, default=30) -> int:
    try:
        d = getattr(getattr(s, "servico", None), "duracao_min", None)
        return int(d) if d else (int(s.duracao_min_cotada) if s.duracao_min_cotada else default)
    except Exception:
        return default

def _calc_fim(s: Solicitacao):
    if getattr(s, "fim", None):
        return s.fim
    if getattr(s, "inicio", None):
        return s.inicio + timedelta(minutes=_duracao_min(s))
    return None

def _wants_json(request) -> bool:
    xrw = (request.headers.get("x-requested-with") or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    return xrw == "xmlhttprequest" or "application/json" in accept

# Quando 'servico' é FK, usar select_related; senão, segue normal.
def _solicitacao_qs():
    try:
        f = Solicitacao._meta.get_field("servico")
        if getattr(f, "is_relation", False):
            return Solicitacao.objects.select_related("servico")
    except Exception:
        pass
    return Solicitacao.objects.all()

# ----------------- Listagem -----------------
def solicitacoes(request):
    qs = _solicitacao_qs().order_by("-criado_em")

    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "").strip()

    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))
    if status_:
        qs = qs.filter(status=status_)  # PENDENTE / CONFIRMADA / NEGADA / REALIZADA

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    pendentes_count = Solicitacao.objects.filter(status=SolicitacaoStatus.PENDENTE).count()

    ctx = {
        "title": "Solicitações",
        "solicitacoes": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": status_},
        "alertas": {
            "sem_confirmacao": pendentes_count,
            "inativos_30d": 0,  # placeholder
            "solicitacoes_pendentes": pendentes_count,
        },
        "solicitacoes_pendentes_count": pendentes_count,
    }
    return render(request, "painel/solicitacoes.html", ctx)

# ----------------- Detalhe/Editar -----------------
def detalhe(request, pk):
    s = get_object_or_404(Solicitacao, pk=pk)
    servicos = Servico.objects.filter(ativo=True).order_by("nome")
    return render(request, "solicitacoes/detalhe.html", {
        "solicitacao": s,
        "servicos": servicos,
    })

# ----------------- Alterar status rápido -----------------
@require_POST
@csrf_protect
def alterar_status(request, pk: int):
    """
    POST:
      - status=CONFIRMADA & (opcional) inicio=YYYY-MM-DDTHH:MM
      - status=NEGADA
      - status=PENDENTE
    """
    s = get_object_or_404(_solicitacao_qs(), pk=pk)
    novo = (request.POST.get("status") or "").strip()

    if novo not in (SolicitacaoStatus.PENDENTE, SolicitacaoStatus.CONFIRMADA, SolicitacaoStatus.NEGADA):
        messages.error(request, "Status inválido.")
        return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

    if novo == SolicitacaoStatus.CONFIRMADA:
        inicio_str = (request.POST.get("inicio") or "").strip()
        if inicio_str:
            dt = parse_datetime(inicio_str)  # 'YYYY-MM-DDTHH:MM'
            if dt and timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            if dt:
                s.inicio = dt

        dur_min = getattr(getattr(s, "servico", None), "duracao_min", None) or _duracao_min(s)
        if s.inicio and dur_min:
            s.fim = s.inicio + timedelta(minutes=int(dur_min))

    s.status = novo
    s.save()
    messages.success(request, "Status atualizado.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

# ----------------- Confirmar (cria/atualiza Agendamento 1:1) -----------------
@require_POST
@csrf_protect
@transaction.atomic
def confirmar_solicitacao(request, pk: int):
    s = get_object_or_404(_solicitacao_qs(), pk=pk)

    # INÍCIO obrigatório
    inicio_str = (request.POST.get("inicio") or "").strip()
    dt = None
    if inicio_str:
        dt = parse_datetime(inicio_str)
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
    if not dt:
        return JsonResponse({"ok": False, "error": "inicio_obrigatorio"}, status=400)

    # CATÁLOGO (opcional)
    servico_id = (request.POST.get("servico_id") or "").strip()
    if servico_id.isdigit():
        try:
            s.servico = Servico.objects.get(pk=int(servico_id))
            # snapshots úteis (não obrigatórios, mas ajudam na UI/relatórios)
            if not s.servico_nome:
                s.servico_nome = s.servico.nome
            if s.preco_cotado is None:
                s.preco_cotado = s.servico.preco
            if not s.duracao_min_cotada:
                s.duracao_min_cotada = s.servico.duracao_min
        except Servico.DoesNotExist:
            pass

    # PREÇO COTADO (opcional)
    preco_str = (request.POST.get("preco_cotado") or "").strip().replace(",", ".")
    if preco_str:
        try:
            s.preco_cotado = Decimal(preco_str)
        except Exception:
            s.preco_cotado = None

    # CONFIRMA (model cria/atualiza Agendamento com servico_id)
    s.confirmar(dt, cliente=None, barbeiro=None)
    s.save(update_fields=["preco_cotado", "servico", "servico_nome", "duracao_min_cotada", "updated_at"])

    # RESPOSTA
    try:
        preco_value = s.preco_praticado()
    except Exception:
        preco_value = s.preco_cotado

    return JsonResponse(
        {
            "ok": True,
            "id": s.id,
            "status": s.status,
            "inicio": s.inicio.isoformat() if s.inicio else None,
            "fim": s.fim.isoformat() if s.fim else None,
            "servico": s.servico_label,
            "servico_id": s.servico_id,
            "preco_praticado": (str(preco_value) if preco_value is not None else None),
        }
    )

# ----------------- Recusar -----------------
@require_POST
@csrf_protect
@transaction.atomic
def recusar_solicitacao(request, pk: int):
    """
    Recusa a solicitação.
    Aceita opcionalmente: motivo=... (anexado em 'observacoes').
    """
    s = get_object_or_404(Solicitacao.objects.all(), pk=pk)
    motivo = (request.POST.get("motivo") or "").strip()

    # Anexa o motivo nas observações (se houver)
    obs = (s.observacoes or "").strip()
    if motivo:
        obs = (obs + ("\n" if obs else "") + f"[NEGADA] {motivo}").strip()
        s.observacoes = obs

    s.status = SolicitacaoStatus.NEGADA
    s.save(update_fields=["status", "observacoes", "updated_at"])

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": s.id, "status": s.status, "motivo": motivo or None})

    messages.success(request, "Solicitação negada.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

# ----------------- Finalizar & No-show -----------------
def _criar_historico(s: Solicitacao, *, faltou=False):
    """
    Cria HistoricoItem quando o app clientes existir. Atualiza ultimo_corte se não foi falta.
    """
    try:
        from clientes.models import Cliente, HistoricoItem
    except Exception:
        return  # módulo não instalado

    cli = None
    tel = (getattr(s, "telefone", None) or "").strip()
    nome = (getattr(s, "nome", None) or "").strip() or tel or "Cliente"

    if tel:
        cli, _ = Cliente.objects.get_or_create(telefone=tel, defaults={"nome": nome})
    else:
        cli = Cliente.objects.filter(nome=nome).first() or Cliente.objects.create(nome=nome)

    data_ref = _calc_fim(s) or s.inicio or timezone.now()

    HistoricoItem.objects.create(
        cliente=cli,
        data=data_ref,
        servico=_label_servico(s),
        valor=None,       # preencha se quiser registrar faturamento aqui
        faltou=faltou,
    )

    if not faltou:
        cli.ultimo_corte = data_ref
        cli.save(update_fields=["ultimo_corte"])

@require_POST
@csrf_protect
@transaction.atomic
def finalizar_solicitacao(request, pk: int):
    """
    Marca a solicitação como REALIZADA e registra no histórico.
    Regra: só permite finalizar se já começou (inicio <= agora).
    """
    s = get_object_or_404(Solicitacao.objects.all(), pk=pk)

    now = timezone.now()
    if not s.inicio or s.inicio > now:
        messages.error(request, "Ainda não é possível finalizar: horário não iniciado.")
        return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

    if not s.fim:
        s.fim = _calc_fim(s)

    if hasattr(SolicitacaoStatus, "REALIZADA"):
        s.status = SolicitacaoStatus.REALIZADA
    s.save()

    _criar_historico(s, faltou=False)

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": s.id, "status": s.status})

    messages.success(request, "Serviço finalizado e lançado no histórico.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

@require_POST
@csrf_protect
@transaction.atomic
def marcar_no_show(request, pk: int):
    """
    Marca a solicitação como 'no-show' (faltou). Mantém status atual e gera HistoricoItem com faltou=True.
    """
    s = get_object_or_404(Solicitacao.objects.all(), pk=pk)

    _criar_historico(s, faltou=True)

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": s.id, "no_show": True})

    messages.success(request, "Cliente marcado como no-show.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")


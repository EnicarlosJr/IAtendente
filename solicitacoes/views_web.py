# solicitacoes/views_web.py  (trechos principais atualizados)

import logging
from decimal import Decimal

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model

import requests
from core import settings
from barbearias.models import BarberShop, Membership, MembershipRole
from agendamentos.models import Agendamento, StatusAgendamento
from core.access import require_shop_member
from painel.visibility import is_shop_admin, scope_agendamentos_qs, scope_solicitacoes_qs
from servicos.models import Servico
from solicitacoes.helpers import criar_agendamento_from_solicitacao
from solicitacoes.utils import shop_post_view
from .models import Solicitacao, SolicitacaoStatus

logger = logging.getLogger(__name__)

# ===================== Helpers de acesso =====================

def _user_membership(user, shop) -> Membership | None:
    if not (user and user.is_authenticated and shop):
        return None
    return Membership.objects.filter(shop=shop, user=user, is_active=True).first()

def _get_shop_for_user(request, shop_slug) -> BarberShop:
    """
    Recupera a barbearia pelo slug e **só retorna** se o usuário atual
    for membro ativo dessa barbearia. Caso contrário -> 404.
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    mem = _user_membership(request.user, shop)
    if not mem:
        # 404 para não vazar a existência/nomes de barbearias alheias
        raise Http404("Barbearia não encontrada.")
    # opcional: deixar à mão no request
    request.shop = shop
    request.membership = mem
    return shop

def _is_manager(request) -> bool:
    mem = getattr(request, "membership", None)
    return bool(mem and mem.role in (MembershipRole.OWNER, MembershipRole.MANAGER))

def _barber_can_act(request, solicitacao: Solicitacao) -> bool:
    """
    Barbeiro comum só pode agir se:
      - solicitacao.barbeiro == request.user, ou
      - solicitacao não tem barbeiro definido ainda (libera para quem está logado, membro).
    """
    if _is_manager(request):
        return True
    if not request.user.is_authenticated:
        return False
    if solicitacao.barbeiro_id:
        return solicitacao.barbeiro_id == request.user.id
    return True

# ===================== Helpers já existentes =====================

def _wants_json(request) -> bool:
    # retorna JSON se vier AJAX ou se o client pedir application/json
    accept = request.headers.get("Accept", "")
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in accept
        or request.GET.get("format") == "json"
    )

def _solicitacao_qs(shop):
    return (Solicitacao.objects
            .filter(shop=shop)
            .select_related("cliente", "servico"))

def _parse_inicio(inicio_str: str):
    dt = parse_datetime((inicio_str or "").strip())
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

def _agendamento_qs(shop):
    return (Agendamento.objects
            .filter(shop=shop)
            .select_related("cliente", "servico", "barbeiro"))

def _aplicar_snapshots_de_servico(s: Solicitacao, servico: Servico | None):
    if not servico:
        return
    s.servico = servico
    if not s.servico_nome:
        s.servico_nome = servico.nome or ""
    if s.preco_cotado is None and servico.preco is not None:
        s.preco_cotado = servico.preco
    if not s.duracao_min_cotada and getattr(servico, "duracao_min", None):
        s.duracao_min_cotada = servico.duracao_min

@login_required
@require_shop_member
def _criar_agendamento_para_solicitacao(s: Solicitacao, barbeiro=None) -> Agendamento:
    ag = Agendamento.objects.filter(shop=s.shop, solicitacao=s).first()
    if not ag:
        ag = Agendamento(shop=s.shop, solicitacao=s)

    ag.cliente = s.cliente
    ag.cliente_nome = s.nome or (getattr(s.cliente, "nome", None) or (s.telefone or ""))
    ag.barbeiro = barbeiro or s.barbeiro
    ag.servico = s.servico
    ag.servico_nome = s.servico_label
    ag.preco_cobrado = s.preco_praticado()
    ag.inicio = s.inicio
    ag.fim = s.fim
    ag.status = StatusAgendamento.CONFIRMADO
    ag.observacoes = s.observacoes or ""
    ag.save()
    return ag

def _disparar_webhook_confirmacao(s: Solicitacao):
    callback_url = s.callback_url or getattr(settings, "OUTBOUND_CONFIRMATION_WEBHOOK", None)
    if not callback_url:
        logger.info("[Solicitacao] CONFIRMADA sem callback_url (sol=%s)", s.pk)
        return

    telefone = s.telefone or (getattr(s.cliente, "telefone", None))
    payload = {
        "evento": "solicitacao_confirmada",
        "ok": True,
        "timestamp": timezone.now().isoformat(),
        "solicitacao_id": s.pk,
        "id_externo": s.id_externo,
        "status": s.status,
        "inicio": s.inicio.isoformat() if s.inicio else None,
        "fim": s.fim.isoformat() if s.fim else None,
        "servico": s.servico_label,
        "telefone": telefone,
        "nome": s.nome or getattr(getattr(s, "cliente", None), "nome", None),
        "mensagem": "Sua solicitação foi confirmada.",
    }
    headers = {"Content-Type": "application/json", "X-Webhook-Token": getattr(settings, "OUTBOUND_WEBHOOK_TOKEN", "")}

    def _send(url, body, hdrs):
        try:
            resp = requests.post(url, json=body, headers=hdrs, timeout=8)
            resp.raise_for_status()
            logger.info("[Solicitacao] webhook OK (sol=%s)", s.pk)
        except Exception as e:
            logger.exception("[Solicitacao] webhook falhou (sol=%s): %s", s.pk, e)

    transaction.on_commit(lambda: _send(callback_url, payload, headers))

# ===================== Listagem =====================
@require_shop_member
@login_required
def solicitacoes(request, shop_slug):
    shop = _get_shop_for_user(request, shop_slug)
    q = (request.GET.get("q") or "").strip()
    status_raw = request.GET.get("status")
    status_ = (status_raw or "").strip().upper()
    has_status_param = ("status" in request.GET)

    admin = _is_manager(request)

    def paginar(qs):
        return Paginator(qs, 20).get_page(request.GET.get("page"))

    map_ag = {
        "CONFIRMADA": StatusAgendamento.CONFIRMADO,
        "FINALIZADA": getattr(StatusAgendamento, "FINALIZADO", getattr(StatusAgendamento, "REALIZADO", None)),
        "REALIZADA":  getattr(StatusAgendamento, "REALIZADO", None),
        "NO_SHOW":    getattr(StatusAgendamento, "NO_SHOW", StatusAgendamento.CANCELADO),
        "CANCELADA":  getattr(StatusAgendamento, "NO_SHOW", StatusAgendamento.CANCELADO),
    }

    # --- Agendamentos por status ---
    if status_ in map_ag:
        ag_status = map_ag[status_]
        aq = (_agendamento_qs(shop))
        aq = scope_agendamentos_qs(aq, request.user, admin)

        if ag_status is not None:
            aq = aq.filter(status=ag_status)

        if q:
            aq = aq.filter(
                Q(cliente_nome__icontains=q) |
                Q(cliente__nome__icontains=q) |
                Q(servico_nome__icontains=q) |
                Q(servico__nome__icontains=q)
            )

        page_obj = paginar(aq.order_by("-inicio"))
        pendentes_count = scope_solicitacoes_qs(
            Solicitacao.objects.filter(shop=shop, status=SolicitacaoStatus.PENDENTE),
            request.user, admin, incluir_nao_atribuida=True
        ).count()

        return render(request, "painel/solicitacoes.html", {
            "title": "Solicitações",
            "shop": shop,
            "list_kind": "agendamentos",
            "agendamentos": page_obj,
            "page_obj": page_obj,
            "filters": {"q": q, "status": status_},
            "alertas": {
                "sem_confirmacao": pendentes_count,
                "inativos_30d": 0,
                "solicitacoes_pendentes": pendentes_count,
            },
            "solicitacoes_pendentes_count": pendentes_count,
        })

    # --- Solicitações ---
    sq = (_solicitacao_qs(shop).order_by("-criado_em"))
    sq = scope_solicitacoes_qs(sq, request.user, admin, incluir_nao_atribuida=True)

    if q:
        sq = sq.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))

    if has_status_param:
        sq = sq.filter(status=status_) if status_ else sq
        selected_status = status_
    else:
        sq = sq.filter(status=SolicitacaoStatus.PENDENTE)
        selected_status = SolicitacaoStatus.PENDENTE

    page_obj = Paginator(sq, 20).get_page(request.GET.get("page"))
    pendentes_count = scope_solicitacoes_qs(
        Solicitacao.objects.filter(shop=shop, status=SolicitacaoStatus.PENDENTE),
        request.user, admin, incluir_nao_atribuida=True
    ).count()

    return render(request, "painel/solicitacoes.html", {
        "title": "Solicitações",
        "shop": shop,
        "list_kind": "solicitacoes",
        "solicitacoes": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": selected_status},
        "alertas": {
            "sem_confirmacao": pendentes_count,
            "inativos_30d": 0,
            "solicitacoes_pendentes": pendentes_count,
        },
        "solicitacoes_pendentes_count": pendentes_count,
    })

# ===================== Detalhe =====================
@require_shop_member
@login_required
def detalhe(request, shop_slug, pk):
    shop = _get_shop_for_user(request, shop_slug)

    s = _solicitacao_qs(shop).filter(pk=pk).first()
    a = None
    tipo = "solicitacao"

    if not s:
        a = _agendamento_qs(shop).filter(pk=pk).first()
        if not a:
            raise Http404("Nenhuma Solicitação ou Agendamento encontrado para este ID nesta barbearia.")
        tipo = "agendamento"

    servicos = Servico.objects.filter(ativo=True, shop=shop).order_by("nome")

    ctx = {
        "shop": shop,
        "servicos": servicos,
        "tipo": tipo,
        "obj": s or a,
        "solicitacao": s,
        "agendamento": a,
        "now": timezone.now(),
    }
    return render(request, "solicitacoes/detalhe.html", ctx)

# ===================== Ações rápidas =====================

@require_POST
@csrf_protect
@login_required
@transaction.atomic
def alterar_status(request, shop_slug, pk: int):
    shop = _get_shop_for_user(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)
    if not _barber_can_act(request, s):
        return HttpResponseForbidden("Você não tem permissão para alterar esta solicitação.")

    novo = (request.POST.get("status") or "").strip()
    if novo not in (SolicitacaoStatus.PENDENTE, SolicitacaoStatus.NEGADA):
        messages.error(request, "Status inválido.")
        return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

    if novo == SolicitacaoStatus.NEGADA:
        motivo = (request.POST.get("motivo") or "").strip()
        s.negar(motivo=motivo)
        messages.success(request, "Solicitação negada.")
    else:
        s.status = SolicitacaoStatus.PENDENTE
        s.save(update_fields=["status", "updated_at"])
        messages.success(request, "Solicitação reaberta.")

    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

def _resolve_barbeiro_para_agendamento(request, shop: BarberShop, solicitacao: Solicitacao):
    User = get_user_model()
    user = request.user if request.user.is_authenticated else None
    is_admin = _is_manager(request)

    chosen = solicitacao.barbeiro if solicitacao.barbeiro_id else None

    if is_admin:
        barber_param = (request.POST.get("barbeiro") or request.POST.get("barbeiro_id") or "").strip()
        if barber_param.isdigit():
            try:
                candidate = User.objects.get(pk=int(barber_param))
                chosen = candidate
            except User.DoesNotExist:
                pass
    elif user:
        chosen = user

    return chosen

def _next_url_from_request(request, fallback: str) -> str:
    return (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
        or fallback
    )

# ===================== Confirmar / Recusar =====================
@require_shop_member
@login_required
@require_POST
@csrf_protect
@transaction.atomic
def confirmar_solicitacao(request, shop_slug, pk: int):
    shop = _get_shop_for_user(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop).select_for_update(), pk=pk)

    if not _barber_can_act(request, s):
        # HTML normal: volta com msg; JSON: 403
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "forbidden"}, status=403)
        messages.error(request, "Você não tem permissão para confirmar esta solicitação.")
        fb = reverse("agendamentos:agenda_dia", args=[shop.slug])
        return redirect(_next_url_from_request(request, fb))

    # data/hora
    dt = _parse_inicio(request.POST.get("inicio")) or s.inicio
    if not dt:
        if _wants_json(request):
            return JsonResponse(
                {"ok": False, "error": "inicio_obrigatorio",
                 "detail": "Defina a data/hora na solicitação antes de confirmar."},
                status=400
            )
        messages.error(request, "Defina a data/hora na solicitação antes de confirmar.")
        fb = reverse("agendamentos:agenda_dia", args=[shop.slug])
        return redirect(_next_url_from_request(request, fb))

    # snapshots opcionais
    servico_id = (request.POST.get("servico_id") or "").strip()
    if servico_id.isdigit():
        try:
            serv = Servico.objects.get(pk=int(servico_id), shop=shop)
            _aplicar_snapshots_de_servico(s, serv)
        except Servico.DoesNotExist:
            pass

    preco_str = (request.POST.get("preco_cotado") or "").strip().replace(",", ".")
    if preco_str:
        try:
            s.preco_cotado = Decimal(preco_str)
        except Exception:
            s.preco_cotado = None

    callback_override = (request.POST.get("callback_url") or "").strip()
    if callback_override:
        s.callback_url = callback_override

    # 1) confirma a solicitação (mantém sua lógica)
    s.confirmar(dt)

    # 2) cria o agendamento CONFIRMADO (mantém seu helper)
    barbeiro_final = _resolve_barbeiro_para_agendamento(request, shop, s)
    agendamento = criar_agendamento_from_solicitacao(s, barbeiro=barbeiro_final)

    # 3) dispara o webhook (não bloqueie UX caso dê erro)
    _disparar_webhook_confirmacao(s)

    # 4) descarta o vínculo e remove a solicitação (sua lógica original)
    if agendamento.solicitacao_id:
        agendamento.solicitacao = None
        agendamento.save(update_fields=["solicitacao"])
    s.delete()

    # 5) resposta
    if _wants_json(request):
        return JsonResponse({
            "ok": True,
            "agendamento_id": agendamento.id,
            "barbeiro_id": agendamento.barbeiro_id,
            "inicio": agendamento.inicio.isoformat() if agendamento.inicio else None,
            "fim": agendamento.fim.isoformat() if agendamento.fim else None,
            "servico": agendamento.servico_nome,
            "mensagem": "Solicitação confirmada, agendamento criado e solicitação removida."
        })

    # HTML normal: volta para onde estava e já recarrega a agenda
    messages.success(request, "Solicitação confirmada ✅")
    # se conhecemos o dia, fazemos fallback para Agenda do Dia correspondente
    if agendamento.inicio:
        day_url = f"{reverse('agendamentos:agenda_dia', args=[shop.slug])}?dia={agendamento.inicio.date().isoformat()}"
    else:
        day_url = reverse('agendamentos:agenda_dia', args=[shop.slug])

    return redirect(_next_url_from_request(request, day_url))



@require_POST
@csrf_protect
@login_required
@transaction.atomic
def recusar_solicitacao(request, shop_slug, pk: int):
    shop = _get_shop_for_user(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)

    if not _barber_can_act(request, s):
        return HttpResponseForbidden("Você não tem permissão para recusar esta solicitação.")

    motivo = (request.POST.get("motivo") or "").strip()
    s.negar(motivo=motivo)

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": s.id, "status": s.status, "motivo": motivo or None})

    messages.success(request, "Solicitação negada.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

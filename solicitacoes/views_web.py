# solicitacoes/views_web.py

import logging
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
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import requests
from django.contrib.auth import get_user_model
from barbearias.models import BarberShop
from agendamentos.models import Agendamento, StatusAgendamento
from servicos.models import Servico
from core import settings
from .models import Solicitacao, SolicitacaoStatus

logger = logging.getLogger(__name__)


# ----------------- Helpers -----------------
def _get_shop(request, shop_slug):
    return getattr(request, "shop", None) or get_object_or_404(BarberShop, slug=shop_slug)

def _wants_json(request) -> bool:
    xrw = (request.headers.get("x-requested-with") or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    return xrw == "xmlhttprequest" or "application/json" in accept

def _solicitacao_qs(shop):
    return (
        Solicitacao.objects
        .select_related("shop", "cliente", "servico", "barbeiro")
        .filter(shop=shop)
    )

def _parse_inicio(inicio_str: str):
    dt = parse_datetime((inicio_str or "").strip())
    if dt and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

# ----------------- Aplica snapshots de serviço -----------------
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

# ----------------- Cria Agendamento -----------------
def _criar_agendamento_para_solicitacao(s: Solicitacao, barbeiro=None) -> Agendamento:
    cliente_nome = s.nome or (getattr(s.cliente, "nome", None) or (s.telefone or ""))
    ag = Agendamento.objects.create(
        shop=s.shop,
        solicitacao=s,
        cliente=s.cliente,
        cliente_nome=cliente_nome,
        barbeiro=barbeiro or s.barbeiro,  # 👈 força o barbeiro resolvido
        servico=s.servico,
        servico_nome=s.servico_label,
        preco_cobrado=s.preco_praticado(),
        inicio=s.inicio,
        fim=s.fim,  # Agendamento.calcular_fim_pelo_servico cobre quando houver servico
        status=StatusAgendamento.CONFIRMADO,
        observacoes=s.observacoes or "",
    )
    return ag


# ----------------- Webhook de confirmação -----------------
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


# ----------------- Listagem -----------------
def solicitacoes(request, shop_slug):
    shop = _get_shop(request, shop_slug)
    qs = _solicitacao_qs(shop).order_by("-criado_em")

    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "").strip()

    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))
    if status_:
        qs = qs.filter(status=status_)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    pendentes_count = _solicitacao_qs(shop).filter(status=SolicitacaoStatus.PENDENTE).count()

    ctx = {
        "title": "Solicitações",
        "shop": shop,
        "solicitacoes": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": status_},
        "alertas": {
            "sem_confirmacao": pendentes_count,
            "inativos_30d": 0,
            "solicitacoes_pendentes": pendentes_count,
        },
        "solicitacoes_pendentes_count": pendentes_count,
    }
    return render(request, "painel/solicitacoes.html", ctx)


# ----------------- Detalhe/Editar -----------------
def detalhe(request, shop_slug, pk):
    shop = _get_shop(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)
    servicos = Servico.objects.filter(ativo=True, shop=shop).order_by("nome")
    return render(request, "solicitacoes/detalhe.html", {"shop": shop, "solicitacao": s, "servicos": servicos})

# -------- NOVO HELPER: resolve o barbeiro de acordo com o usuário logado --------
def _resolve_barbeiro_para_agendamento(request, shop: BarberShop, solicitacao: Solicitacao):
    """
    Regras:
    - Admin (staff/superuser): pode escolher barbeiro via POST 'barbeiro'/'barbeiro_id'.
    - Barbeiro comum: sempre ele mesmo (request.user).
    - Se nada for possível, cai para o barbeiro já setado na solicitação, se houver.
    """
    User = get_user_model()
    user = request.user if request.user.is_authenticated else None
    is_admin = bool(user and (user.is_staff or user.is_superuser))

    # já vem escolhido na solicitação?
    if solicitacao.barbeiro_id:
        chosen = solicitacao.barbeiro
    else:
        chosen = None

    # Admin pode escolher
    if is_admin:
        barber_param = (request.POST.get("barbeiro") or request.POST.get("barbeiro_id") or "").strip()
        if barber_param.isdigit():
            try:
                candidate = User.objects.get(pk=int(barber_param))
                # (Opcional) se você tiver uma relação de membros da barbearia, valide aqui.
                # Ex.: if not shop.membros.filter(pk=candidate.pk).exists(): raise
                chosen = candidate
            except User.DoesNotExist:
                pass

    # Barbeiro comum → força ser ele mesmo
    if not is_admin and user:
        chosen = user

    return chosen


# ----------------- Alterar status rápido -----------------
@require_POST
@csrf_protect
@transaction.atomic
def alterar_status(request, shop_slug, pk: int):
    shop = _get_shop(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)
    novo = (request.POST.get("status") or "").strip()

    if novo not in (SolicitacaoStatus.PENDENTE, SolicitacaoStatus.CONFIRMADA, SolicitacaoStatus.NEGADA):
        messages.error(request, "Status inválido.")
        return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

    if novo == SolicitacaoStatus.CONFIRMADA:
        dt = _parse_inicio(request.POST.get("inicio"))
        if not dt:
            messages.error(request, "Informe a data/hora de início para confirmar.")
            return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

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

        s.confirmar(dt)
        barbeiro_final = _resolve_barbeiro_para_agendamento(request, shop, s)
        _criar_agendamento_para_solicitacao(s, barbeiro=barbeiro_final)

        messages.success(request, "Solicitação confirmada e agendamento criado.")
        return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

    elif novo == SolicitacaoStatus.NEGADA:
        s.negar()
    else:
        s.status = SolicitacaoStatus.PENDENTE
        s.save(update_fields=["status", "updated_at"])

    messages.success(request, "Status atualizado.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")


# ----------------- Confirmar -> cria Agendamento -----------------
@require_POST
@csrf_protect
@transaction.atomic
def confirmar_solicitacao(request, shop_slug, pk: int):
    """
    Confirma a Solicitação e cria um Agendamento CONFIRMADO.
    - Admin pode escolher o barbeiro (POST 'barbeiro'/'barbeiro_id').
    - Barbeiro comum só pode confirmar para si.
    """
    shop = _get_shop(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)

    # INÍCIO obrigatório
    dt = _parse_inicio(request.POST.get("inicio"))
    if not dt:
        return JsonResponse({"ok": False, "error": "inicio_obrigatorio"}, status=400)

    # (opcionais) atualizar serviço/preço/snapshots
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

    # 1) confirma a solicitação
    s.confirmar(dt)

    # 2) resolve barbeiro conforme regra (admin escolhe; barbeiro comum = self)
    barbeiro_final = _resolve_barbeiro_para_agendamento(request, shop, s)

    # 3) cria o agendamento confirmado
    agendamento = _criar_agendamento_para_solicitacao(s, barbeiro=barbeiro_final)

    # 4) webhook (se configurado)
    _disparar_webhook_confirmacao(s)

    return JsonResponse({
        "ok": True,
        "id": s.id,
        "status": s.status,
        "inicio": s.inicio.isoformat() if s.inicio else None,
        "fim": s.fim.isoformat() if s.fim else None,
        "servico": s.servico_label,
        "servico_id": s.servico_id,
        "agendamento_id": agendamento.id,
        "barbeiro_id": agendamento.barbeiro_id,
        "mensagem": "Solicitação confirmada e agendamento criado.",
    })

# ----------------- Recusar -----------------
@require_POST
@csrf_exempt   # se quiser receber de fora
@transaction.atomic
def recusar_solicitacao(request, shop_slug, pk: int):
    shop = _get_shop(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)
    motivo = (request.POST.get("motivo") or "").strip()

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


# ----------------- Finalizar -----------------
@require_POST
@csrf_protect
@transaction.atomic
def finalizar_solicitacao(request, shop_slug, pk: int):
    """
    Mantido para compatibilidade: marca a solicitação como REALIZADA e lança histórico.
    (O agendamento, se existir, você pode atualizar em outra view do app de agenda.)
    """
    shop = _get_shop(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)
    try:
        s.realizar()
    except ValueError as e:
        if _wants_json(request):
            return JsonResponse({"ok": False, "error": "invalid_state", "detail": str(e)}, status=400)
        messages.error(request, str(e))
        return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": s.id, "status": s.status})

    messages.success(request, "Serviço finalizado e lançado no histórico.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")


# ----------------- No-show -----------------
@require_POST
@csrf_protect
@transaction.atomic
def marcar_no_show(request, shop_slug, pk: int):
    shop = _get_shop(request, shop_slug)
    s = get_object_or_404(_solicitacao_qs(shop), pk=pk)
    s.marcar_no_show()

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": s.id, "no_show": True})

    messages.success(request, "Cliente marcado como no-show.")
    return redirect(request.META.get("HTTP_REFERER") or "solicitacoes:solicitacoes")

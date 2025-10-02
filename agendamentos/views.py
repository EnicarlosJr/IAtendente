# agendamentos/views.py

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.db import transaction
from django.db.models import Q

from barbearias.models import BarberShop
from clientes.models import HistoricoItem
from core.access import require_shop_member, is_manager

from agendamentos.forms import (
    BarbeiroAvailabilityForm,
    BarbeiroTimeOffForm,
    AgendamentoForm,
)
from agendamentos.models import (
    Agendamento,
    StatusAgendamento,
    BarbeiroAvailability as Availability,
    BarbeiroTimeOff as TimeOff,
)

# --- Integração opcional com Solicitações (tolerante à ausência do app)
try:
    from solicitacoes.models import Solicitacao, SolicitacaoStatus
    HAS_SOL = True
except Exception:  # pragma: no cover
    Solicitacao = None
    SolicitacaoStatus = None
    HAS_SOL = False

# --- Integração opcional com Solicitações (tolerante à ausência do app)
try:
    from solicitacoes.models import Solicitacao, SolicitacaoStatus
    HAS_SOL = True
except Exception:
    Solicitacao = None
    SolicitacaoStatus = None
    HAS_SOL = False

# ===================================================
# Helpers gerais
# ===================================================

def _parse_date(s: str, default: date) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return default


def _week_bounds(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())  # segunda
    end = start + timedelta(days=6)          # domingo
    return start, end


def _week_nav(d: date) -> tuple[date, date]:
    start, _ = _week_bounds(d)
    return start - timedelta(days=7), start + timedelta(days=7)


def _day_nav(d: date) -> tuple[date, date]:
    return d - timedelta(days=1), d + timedelta(days=1)


def _day_slots(d: date, start_h: int = 8, end_h: int = 20, step_min: int = 30):
    tz = timezone.get_current_timezone()
    cur = timezone.make_aware(datetime(d.year, d.month, d.day, start_h, 0, 0), tz)
    end = timezone.make_aware(datetime(d.year, d.month, d.day, end_h, 0, 0), tz)
    step = timedelta(minutes=step_min)
    out = []
    while cur < end:
        out.append(cur)
        cur += step
    return out


def _calc_fim(inicio: datetime, servico) -> datetime | None:
    """
    Calcula fim usando campos comuns de duração. Fallback para 30 minutos.
    """
    if not inicio:
        return None
    dur_min = None
    if servico:
        for field in ("duracao_minutos", "duracao", "duracao_estimada", "tempo"):
            val = getattr(servico, field, None)
            if isinstance(val, int) and val > 0:
                dur_min = val
                break
    dur_min = dur_min or 30
    return inicio + timedelta(minutes=dur_min)


def _intervalos_agendamentos(qs, tz):
    """
    [(start_local, end_local, obj Agendamento)]
    - tolera fim=None calculando pela duração do serviço
    """
    out = []
    for a in qs.order_by("inicio"):
        if not a.inicio:
            continue
        ini = timezone.localtime(a.inicio, tz)
        fim_calc = a.fim or _calc_fim(a.inicio, getattr(a, "servico", None))
        if not fim_calc:
            continue
        fim = timezone.localtime(fim_calc, tz)
        out.append((ini, fim, a))
    return out

def _status_is_pendente(status_val) -> bool:
    return str(status_val).upper() in {"PENDENTE", getattr(SolicitacaoStatus, "PENDENTE", "PENDENTE")}

def _can_act_on_solic(user, sol, shop) -> bool:
    """
    Política simples: gerente pode, barbeiro atribuído pode, ou se não houver barbeiro.
    Ajuste se tiver outra regra de permissão.
    """
    try:
        if is_manager  and is_manager.__code__.co_argcount == 1:  # compat se is_manager(request) ou is_manager(user)
            can_mgr = is_manager(user)
        else:
            can_mgr = is_manager(user)  # caso padrão (se sua is_manager espera 'request', adapte)
    except Exception:
        # se a sua is_manager espera request, use: is_manager(request) DENTRO das views (abaixo faço isso também)
        can_mgr = False

    barb = getattr(sol, "barbeiro", None)
    return bool(can_mgr or barb is None or barb == user)

def _inject_actions_for_solic(item_dict, shop_slug, sol_obj, can_act: bool):
    """
    Adiciona campos usados no template para os botões.
    """
    item_dict["kind"] = "solicitacao"
    item_dict["can_act"] = bool(can_act and _status_is_pendente(item_dict.get("status")))
    if item_dict["can_act"]:
        item_dict["confirm_url"] = reverse("solicitacoes:confirmar", args=[shop_slug, sol_obj.id])
        item_dict["deny_url"]    = reverse("solicitacoes:recusar",   args=[shop_slug, sol_obj.id])

def _intervalos_solicitacoes(qs, tz):
    """
    [(start_local, end_local, obj Solicitacao)]
    - tolera fim=None calculando 30min (ou pela duração do serviço se existir)
    """
    out = []
    for s in qs.order_by("inicio"):
        if not s.inicio:
            continue
        ini = timezone.localtime(s.inicio, tz)
        # muitos modelos de solicitação não têm fim; tenta pelo serviço
        fim_calc = getattr(s, "fim", None) or _calc_fim(s.inicio, getattr(s, "servico", None))
        if not fim_calc:
            continue
        fim = timezone.localtime(fim_calc, tz)
        out.append((ini, fim, s))
    return out


def _month_nav(d: date) -> tuple[date, date]:
    prev_month = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return prev_month, next_month


# ===================================================
# Redirect principal
# ===================================================

def agenda_redirect(request, shop_slug):
    return redirect("agendamentos:agenda_semana", shop_slug=shop_slug)


def agenda(request, shop_slug):
    return redirect("agendamentos:agenda", shop_slug=shop_slug)


# ===================================================
# AGENDA — DIA
# ===================================================

@require_shop_member
@login_required
def agenda_dia(request, shop_slug):
    shop = get_object_or_404(BarberShop, slug=shop_slug)

    tz = timezone.get_current_timezone()
    dia_str = (request.GET.get("dia") or request.GET.get("data") or "").strip()
    d = _parse_date(dia_str, timezone.localdate())

    # alvo (barbeiro)
    barbeiro_param = (request.GET.get("barbeiro") or "").strip()
    target_user = None
    if barbeiro_param and barbeiro_param.isdigit():
        User = get_user_model()
        try:
            target_user = User.objects.get(pk=int(barbeiro_param))
        except Exception:
            target_user = None

    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    end = start + timedelta(days=1)

    show_all = is_manager(request) and not target_user and not barbeiro_param

    # Slots do grid
    if show_all:
        slots = [{"start": dt, "end": dt + timedelta(minutes=30),
                  "available": True, "reason": None}
                 for dt in _day_slots(d, 8, 20, 30)]
    else:
        user_for_slots = target_user or request.user
        rule = Availability.objects.filter(barbeiro=user_for_slots, weekday=d.weekday()).first()
        offs_qs = TimeOff.objects.filter(barbeiro=user_for_slots)
        slots = _generate_slots(d, rule, offs_qs) or [
            {"start": dt, "end": dt + timedelta(minutes=30), "available": True, "reason": None}
            for dt in _day_slots(d, 8, 20, 30)
        ]
    slot_step = (slots[1]["start"] - slots[0]["start"]) if len(slots) > 1 else timedelta(minutes=30)

    # --------- Agendamentos ---------
    ag_qs = (
        Agendamento.objects
        .filter(shop=shop)
        .exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
        .filter(inicio__isnull=False, inicio__gte=start, inicio__lt=end)
        .select_related("cliente", "servico")
    )
    if not show_all:
        ag_qs = ag_qs.filter(Q(barbeiro=(target_user or request.user)) | Q(barbeiro__isnull=True))
    ag_intervals = _intervalos_agendamentos(ag_qs, tz)

    # --------- Solicitações ---------
    sol_intervals = []
    if HAS_SOL and SolicitacaoStatus:
        exclude_status = [
            getattr(SolicitacaoStatus, "CANCELADA", "CANCELADA"),
            getattr(SolicitacaoStatus, "NEGADA", "NEGADA"),
        ]
        sol_qs = (
            Solicitacao.objects
            .filter(shop=shop)
            .exclude(status__in=exclude_status)
            .filter(inicio__isnull=False, inicio__gte=start, inicio__lt=end)
            .select_related("cliente", "servico")
        )
        if not show_all:
            sol_qs = sol_qs.filter(Q(barbeiro=(target_user or request.user)) | Q(barbeiro__isnull=True))
        sol_intervals = _intervalos_solicitacoes(sol_qs, tz)

    # Monta linhas do grid
    rows = []
    for slot in slots:
        t = slot["start"]

        ag_matches = [iv for iv in ag_intervals if iv[0] <= t < iv[1]]
        sol_matches = [iv for iv in sol_intervals if iv[0] <= t < iv[1]]

        row = {
            "time": t,
            "item": None,
            "occupied": False,
            "conflicts": max(0, len(ag_matches) + len(sol_matches) - 1),
            "available": slot["available"],
            "reason": slot["reason"],
        }

        def _build_item_from_ag(a_start, a_end, ag):
            return {
                "id": ag.id,
                "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
                "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
                "status": ag.status,
                "inicio": a_start,
                "fim": a_end,
                "is_solicitacao": False,
                "kind": "agendamento",
                "can_act": False,
            }

        def _build_item_from_sol(s_start, s_end, sol):
            status_txt = str(getattr(sol, "status", "PENDENTE")).upper()
            item = {
                "id": sol.id,
                "cliente_nome": getattr(sol, "cliente_nome", None) or (getattr(sol, "cliente", None).nome if getattr(sol, "cliente", None) else getattr(sol, "nome", "—")),
                "servico_nome": getattr(sol, "servico_nome", None) or (getattr(sol, "servico", None).nome if getattr(sol, "servico", None) else "—"),
                "status": status_txt,
                "inicio": s_start,
                "fim": s_end,
                "is_solicitacao": True,
                "kind": "solicitacao",
            }
            # Pode agir? gerente, barbeiro designado ou sem barbeiro, e pendente
            can_act = (is_manager(request) or getattr(sol, "barbeiro", None) in (None, request.user))
            item["can_act"] = bool(can_act and _status_is_pendente(status_txt))
            if item["can_act"]:
                item["confirm_url"] = reverse("solicitacoes:confirmar", args=[shop.slug, sol.id])
                item["deny_url"]    = reverse("solicitacoes:recusar",   args=[shop.slug, sol.id])
            return item

        # prioridade: Agendamento, senão Solicitação
        if ag_matches:
            a_start, a_end, ag = ag_matches[0]
            if a_start <= t < (a_start + slot_step):
                row["item"] = _build_item_from_ag(a_start, a_end, ag)
            else:
                row["occupied"] = True
        elif sol_matches:
            s_start, s_end, sol = sol_matches[0]
            if s_start <= t < (s_start + slot_step):
                row["item"] = _build_item_from_sol(s_start, s_end, sol)
            else:
                row["occupied"] = True

        rows.append(row)

    prev_day, next_day = _day_nav(d)
    return render(request, "agendamentos/agenda_dia.html", {
        "title": "Agenda",
        "view": "dia",
        "date": d,
        "prev_day": prev_day,
        "next_day": next_day,
        "rows": rows,
        "shop": shop,
    })



# ===================================================
# AGENDA — SEMANA
# ===================================================

@require_shop_member
@login_required
def agenda_semana(request, shop_slug):
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    tz = timezone.get_current_timezone()

    hoje = timezone.localdate()
    base = _parse_date(request.GET.get("data", ""), hoje)
    wk_start, _ = _week_bounds(base)
    days = [wk_start + timedelta(days=i) for i in range(7)]
    day_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    days_ctx = [{"date": d, "label": day_labels[i]} for i, d in enumerate(days)]

    # alvo
    barbeiro = None
    barbeiro_param = (request.GET.get("barbeiro") or "").strip()
    if barbeiro_param and barbeiro_param.isdigit():
        User = get_user_model()
        try:
            barbeiro = User.objects.get(pk=int(barbeiro_param))
        except Exception:
            barbeiro = None
    elif not is_manager(request):
        barbeiro = request.user

    # Slots (mapa de horários)
    DEFAULT_START_H, DEFAULT_END_H, DEFAULT_STEP_MIN = 8, 20, 30
    day_slots_map = {d: _day_slots(d, DEFAULT_START_H, DEFAULT_END_H, DEFAULT_STEP_MIN) for d in days}

    slot_step = timedelta(minutes=DEFAULT_STEP_MIN)
    for d in days:
        v = day_slots_map[d]
        if len(v) >= 2:
            slot_step = v[1] - v[0]
            break

    time_keys = sorted({(dt.hour, dt.minute) for d in days for dt in day_slots_map[d]})
    day_slot_keys = {d: {(dt.hour, dt.minute) for dt in day_slots_map.get(d, [])} for d in days}

    # Janela semanal
    week_start_dt = timezone.make_aware(datetime(wk_start.year, wk_start.month, wk_start.day, 0, 0, 0), tz)
    week_end_dt = week_start_dt + timedelta(days=7)

    # --------- Agendamentos ---------
    ag_qs = (
        Agendamento.objects
        .filter(shop=shop)
        .exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
        .filter(inicio__isnull=False, inicio__gte=week_start_dt, inicio__lt=week_end_dt)
        .select_related("cliente", "servico")
    )
    if barbeiro:
        ag_qs = ag_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
    ag_intervals = _intervalos_agendamentos(ag_qs, tz)

    # Index agendamentos por dia
    ag_by_day = {d: [] for d in days}
    for s_start, s_end, ag in ag_intervals:
        key = s_start.date()
        if key in ag_by_day:
            ag_by_day[key].append((s_start, s_end, ag))

    # --------- Solicitações ---------
    sol_by_day = {d: [] for d in days}
    if HAS_SOL and SolicitacaoStatus:
        exclude_status = [
            getattr(SolicitacaoStatus, "CANCELADA", "CANCELADA"),
            getattr(SolicitacaoStatus, "NEGADA", "NEGADA"),
        ]
        sol_qs = (
            Solicitacao.objects
            .filter(shop=shop)
            .exclude(status__in=exclude_status)
            .filter(inicio__isnull=False, inicio__gte=week_start_dt, inicio__lt=week_end_dt)
            .select_related("cliente", "servico")
        )
        if barbeiro:
            sol_qs = sol_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))

        sol_intervals = _intervalos_solicitacoes(sol_qs, tz)
        for s_start, s_end, sol in sol_intervals:
            key = s_start.date()
            if key in sol_by_day:
                sol_by_day[key].append((s_start, s_end, sol))

    # Monta linhas
    rows = []
    for (hh, mm) in time_keys:
        time_label = timezone.make_aware(datetime(wk_start.year, wk_start.month, wk_start.day, hh, mm), tz)
        cells = []
        for d in days:
            slot_dt = timezone.make_aware(datetime(d.year, d.month, d.day, hh, mm), tz)

            ag_matches = [(a, b, obj) for (a, b, obj) in ag_by_day.get(d, []) if a <= slot_dt < b]
            sol_matches = [(a, b, obj) for (a, b, obj) in sol_by_day.get(d, []) if a <= slot_dt < b]

            available, reason = (True, None) if (hh, mm) in day_slot_keys.get(d, set()) else (False, "folga")

            def _cell_item_from_ag(a_start, a_end, ag):
                return {
                    "id": ag.id,
                    "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
                    "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
                    "status": ag.status,
                    "inicio": a_start,
                    "fim": a_end,
                    "is_solicitacao": False,
                    "kind": "agendamento",
                    "can_act": False,
                }

            def _cell_item_from_sol(s_start, s_end, sol):
                status_txt = str(getattr(sol, "status", "PENDENTE")).upper()
                item = {
                    "id": sol.id,
                    "cliente_nome": getattr(sol, "cliente_nome", None) or (getattr(sol, "cliente", None).nome if getattr(sol, "cliente", None) else getattr(sol, "nome", "—")),
                    "servico_nome": getattr(sol, "servico_nome", None) or (getattr(sol, "servico", None).nome if getattr(sol, "servico", None) else "—"),
                    "status": status_txt,
                    "inicio": s_start,
                    "fim": s_end,
                    "is_solicitacao": True,
                    "kind": "solicitacao",
                }
                can_act = (is_manager(request) or getattr(sol, "barbeiro", None) in (None, request.user))
                item["can_act"] = bool(can_act and _status_is_pendente(status_txt))
                if item["can_act"]:
                    item["confirm_url"] = reverse("solicitacoes:confirmar", args=[shop.slug, sol.id])
                    item["deny_url"]    = reverse("solicitacoes:recusar",   args=[shop.slug, sol.id])
                return item

            if ag_matches:
                a_start, a_end, ag = ag_matches[0]
                is_first = (a_start <= slot_dt < (a_start + slot_step))
                if is_first:
                    cells.append({
                        "item": _cell_item_from_ag(a_start, a_end, ag),
                        "occupied": False,
                        "time": slot_dt,
                        "available": available,
                        "reason": reason,
                        "conflicts": max(0, len(ag_matches) + len(sol_matches) - 1),
                    })
                else:
                    cells.append({
                        "item": None, "occupied": True, "time": slot_dt,
                        "available": available, "reason": reason,
                        "conflicts": max(0, len(ag_matches) + len(sol_matches) - 1),
                    })
            elif sol_matches:
                s_start, s_end, sol = sol_matches[0]
                is_first = (s_start <= slot_dt < (s_start + slot_step))
                if is_first:
                    cells.append({
                        "item": _cell_item_from_sol(s_start, s_end, sol),
                        "occupied": False,
                        "time": slot_dt,
                        "available": available,
                        "reason": reason,
                        "conflicts": max(0, len(sol_matches) - 1),
                    })
                else:
                    cells.append({
                        "item": None, "occupied": True, "time": slot_dt,
                        "available": available, "reason": reason,
                        "conflicts": max(0, len(sol_matches) - 1),
                    })
            else:
                cells.append({
                    "item": None, "occupied": False, "time": slot_dt,
                    "available": available, "reason": reason, "conflicts": 0
                })

        rows.append({"time": time_label, "cells": cells})

    prev_week, next_week = _week_nav(base)
    return render(request, "agendamentos/agenda_semana.html", {
        "title": "Agenda — Semana",
        "view": "semana",
        "wk_start": wk_start,
        "wk_end": wk_start + timedelta(days=6),
        "days_ctx": days_ctx,
        "rows": rows,
        "prev_week": prev_week,
        "next_week": next_week,
        "barbeiro": barbeiro,
        "shop": shop,
    })



# ===================================================
# AGENDA — MÊS
# ===================================================
@require_shop_member
@login_required
def agenda_mes(request, shop_slug):
    shop = get_object_or_404(BarberShop, slug=shop_slug)

    hoje = timezone.localdate()
    ref_date = _parse_date(request.GET.get("data", ""), hoje).replace(day=1)

    year, month = ref_date.year, ref_date.month
    first_weekday, num_days = monthrange(year, month)

    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime(year, month, 1, 0, 0, 0), tz)
    end_dt = start_dt + timedelta(days=num_days)

    # alvo
    barbeiro_param = (request.GET.get("barbeiro") or "").strip()
    target_user = None
    if barbeiro_param and barbeiro_param.isdigit():
        User = get_user_model()
        try:
            target_user = User.objects.get(pk=int(barbeiro_param))
        except Exception:
            target_user = None

    # --------- Agendamentos ---------
    ag_qs = (
        Agendamento.objects
        .filter(shop=shop)
        .exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
        .filter(inicio__isnull=False, inicio__gte=start_dt, inicio__lt=end_dt)
        .select_related("cliente", "servico")
    )
    if not is_manager(request) and not target_user:
        ag_qs = ag_qs.filter(Q(barbeiro=request.user) | Q(barbeiro__isnull=True))
    elif target_user:
        ag_qs = ag_qs.filter(Q(barbeiro=target_user) | Q(barbeiro__isnull=True))
    ag_intervals = _intervalos_agendamentos(ag_qs, tz)

    # --------- Solicitações ---------
    sol_items = []
    if HAS_SOL and SolicitacaoStatus:
        exclude_status = [
            getattr(SolicitacaoStatus, "CANCELADA", "CANCELADA"),
            getattr(SolicitacaoStatus, "NEGADA", "NEGADA"),
        ]
        sol_qs = (
            Solicitacao.objects
            .filter(shop=shop)
            .exclude(status__in=exclude_status)
            .filter(inicio__isnull=False, inicio__gte=start_dt, inicio__lt=end_dt)
            .select_related("cliente", "servico")
        )
        if not is_manager(request) and not target_user:
            sol_qs = sol_qs.filter(Q(barbeiro=request.user) | Q(barbeiro__isnull=True))
        elif target_user:
            sol_qs = sol_qs.filter(Q(barbeiro=target_user) | Q(barbeiro__isnull=True))

        sol_intervals = _intervalos_solicitacoes(sol_qs, tz)
        for s_start, s_end, sol in sol_intervals:
            status_txt = str(getattr(sol, "status", "PENDENTE")).upper()
            item = {
                "id": sol.id,
                "inicio": s_start,
                "fim": s_end,
                "cliente_nome": getattr(sol, "cliente_nome", None) or (getattr(sol, "cliente", None).nome if getattr(sol, "cliente", None) else getattr(sol, "nome", "—")),
                "servico_nome": getattr(sol, "servico_nome", None) or (getattr(sol, "servico", None).nome if getattr(sol, "servico", None) else "—"),
                "status": status_txt,
                "is_solicitacao": True,
                "kind": "solicitacao",
            }
            can_act = (is_manager(request) or getattr(sol, "barbeiro", None) in (None, request.user))
            item["can_act"] = bool(can_act and _status_is_pendente(status_txt))
            if item["can_act"]:
                item["confirm_url"] = reverse("solicitacoes:confirmar", args=[shop.slug, sol.id])
                item["deny_url"]    = reverse("solicitacoes:recusar",   args=[shop.slug, sol.id])
            sol_items.append(item)

    # Distribui por dia
    tmp = {ref_date + timedelta(days=i): [] for i in range(num_days)}
    for a_start, a_end, ag in ag_intervals:
        day_key = a_start.date()
        if day_key in tmp:
            tmp[day_key].append({
                "id": ag.id,
                "inicio": a_start,
                "fim": a_end,
                "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
                "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
                "status": ag.status,
                "is_solicitacao": False,
                "kind": "agendamento",
                "can_act": False,
            })
    for item in sol_items:
        day_key = item["inicio"].date()
        if day_key in tmp:
            tmp[day_key].append(item)

    # Ordena
    for k in tmp.keys():
        tmp[k].sort(key=lambda it: it["inicio"])

    por_dia = OrderedDict(sorted(tmp.items(), key=lambda kv: kv[0]))
    blank_cells = list(range(first_weekday))
    dias_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    prev_month = (ref_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (ref_date.replace(day=28) + timedelta(days=4)).replace(day=1)

    return render(request, "agendamentos/agenda_mes.html", {
        "title": "Agenda — Mês",
        "view": "mes",
        "ref_date": ref_date,
        "por_dia": por_dia,
        "blank_cells": blank_cells,
        "dias_semana": dias_semana,
        "prev_month": prev_month,
        "next_month": next_month,
        "shop": shop,
    })


# ===================================================
# MINHA AGENDA (configs do barbeiro)
# ===================================================

@require_shop_member
@login_required
def minha_agenda_config(request, shop_slug):
    """
    Configuração da agenda do barbeiro logado:
    - Regras semanais
    - Folgas
    - Prévia de slots
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    barbeiro = request.user

    AvailabilityFormSet = modelformset_factory(
        Availability,
        form=BarbeiroAvailabilityForm,
        extra=0,
        can_delete=False,
    )

    # Regras existentes (ou cria defaults)
    qs = Availability.objects.filter(barbeiro=barbeiro).order_by("weekday")
    if not qs.exists():
        defaults = []
        for wd in range(7):  # 0=Seg ... 6=Dom
            defaults.append(
                Availability(
                    barbeiro=barbeiro,
                    weekday=wd,
                    start_time="08:00",
                    end_time="18:00",
                    slot_minutes=30,
                    is_active=(wd < 6),  # domingo off
                )
            )
        Availability.objects.bulk_create(defaults)
        qs = Availability.objects.filter(barbeiro=barbeiro).order_by("weekday")

    formset = AvailabilityFormSet(queryset=qs, prefix="rules")
    off_form = BarbeiroTimeOffForm(prefix="off")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        # Salvar REGRAS
        if action == "rules" or "rules-TOTAL_FORMS" in request.POST:
            formset = AvailabilityFormSet(request.POST, queryset=qs, prefix="rules")
            if formset.is_valid():
                instances = formset.save(commit=False)
                for inst in instances:
                    inst.barbeiro = barbeiro
                    if not inst.is_active:
                        inst.lunch_start = None
                        inst.lunch_end = None
                    inst.save()
                messages.success(request, "Regras semanais salvas com sucesso.")
                return redirect("agendamentos:minha_agenda_config", shop_slug=shop_slug)
            else:
                any_error = False
                for idx, f in enumerate(formset.forms):
                    if f.errors:
                        any_error = True
                        messages.error(
                            request,
                            f"Dia #{idx+1}: "
                            + "; ".join([f"{k}: {', '.join(v)}" for k, v in f.errors.items()]),
                        )
                if not any_error:
                    messages.error(request, "Revise os campos das regras semanais.")

        # Salvar FOLGA
        elif action == "off" or "off-start" in request.POST:
            off_form = BarbeiroTimeOffForm(request.POST, prefix="off")
            if off_form.is_valid():
                off = off_form.save(commit=False)
                off.barbeiro = barbeiro
                if off.start and off.end and off.start < off.end:
                    off.save()
                    messages.success(request, "Folga adicionada.")
                    return redirect("agendamentos:minha_agenda_config", shop_slug=shop_slug)
                messages.error(request, "Período de folga inválido.")
            else:
                messages.error(
                    request,
                    "; ".join([f"{k}: {', '.join(v)}" for k, v in off_form.errors.items()])
                    or "Não foi possível salvar a folga. Verifique os campos.",
                )

    # Pré-visualização de slots do dia
    dia_str = (request.GET.get("data") or "").strip()
    try:
        preview_date = date.fromisoformat(dia_str) if dia_str else timezone.localdate()
    except Exception:
        preview_date = timezone.localdate()

    rule = Availability.objects.filter(barbeiro=barbeiro, weekday=preview_date.weekday()).first()
    preview_slots = rule.gerar_slots(preview_date, barbeiro) if rule else []

    offs = TimeOff.objects.filter(barbeiro=barbeiro, end__gte=timezone.now()).order_by("start")[:20]

    return render(
        request,
        "agendamentos/minha_agenda.html",
        {
            "formset": formset,
            "off_form": off_form,
            "offs": offs,
            "preview_date": preview_date,
            "preview_slots": preview_slots,
            "shop": shop,
        },
    )


# ===================================================
# AÇÕES DE AGENDAMENTO
# ===================================================

@require_shop_member
@login_required
@require_POST
@transaction.atomic
def finalizar(request, shop_slug, pk: int):
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    ag = get_object_or_404(Agendamento.objects.select_related("cliente", "servico", "barbeiro"), pk=pk, shop=shop)

    try:
        ag.finalizar()
        ag.save(update_fields=["status", "updated_at", "fim"])
    except ValueError as e:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "invalid_state", "detail": str(e)}, status=400)
        messages.error(request, str(e))
        return redirect(request.META.get("HTTP_REFERER") or "agendamentos:agenda_dia", shop_slug=shop.slug)

    # Histórico do cliente
    if ag.cliente_id:
        cliente = ag.cliente
        data_servico = ag.fim or ag.inicio
        servico_label = ag.servico_nome or (ag.servico.nome if ag.servico_id else "Serviço")
        profissional = (ag.barbeiro.get_full_name() or str(ag.barbeiro)) if ag.barbeiro_id else None

        exists = HistoricoItem.objects.filter(
            shop=shop, cliente=cliente, data=data_servico, servico=servico_label
        ).exists()
        if not exists:
            HistoricoItem.objects.create(
                shop=shop,
                cliente=cliente,
                data=data_servico,
                servico=servico_label,
                servico_ref=ag.servico if ag.servico_id else None,
                valor=ag.preco_cobrado,
                preco_tabela=getattr(ag.servico, "preco", None) if ag.servico_id else None,
                faltou=False,
                profissional=profissional or None,
            )

        if hasattr(cliente, "set_ultimo_corte"):
            cliente.set_ultimo_corte(data_servico, save=True)
        if hasattr(cliente, "refresh_recorrencia"):
            cliente.refresh_recorrencia(save=True)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "id": ag.id, "status": ag.status})

    messages.success(request, "Atendimento finalizado.")
    return redirect(request.META.get("HTTP_REFERER") or "agendamentos:agenda_dia", shop_slug=shop.slug)


@require_shop_member
@login_required
@require_POST
@transaction.atomic
def no_show(request, shop_slug, pk: int):
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    ag = get_object_or_404(Agendamento.objects.select_related("cliente", "servico"), pk=pk, shop=shop)

    try:
        ag.marcar_no_show()
        ag.save(update_fields=["status", "updated_at"])
    except ValueError as e:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "invalid_state", "detail": str(e)}, status=400)
        messages.error(request, str(e))
        return redirect(request.META.get("HTTP_REFERER") or "agendamentos:agenda_dia", shop_slug=shop.slug)

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "id": ag.id, "status": ag.status})

    messages.success(request, "No-show registrado.")
    return redirect(request.META.get("HTTP_REFERER") or "agendamentos:agenda_dia", shop_slug=shop.slug)


#generate slots helper
def _aware_local(dt: datetime, tz):
    if dt is None:
        return None
    return timezone.make_aware(dt, tz) if timezone.is_naive(dt) else dt.astimezone(tz)


def _generate_slots(d: date, rule: Availability | None, timeoffs_qs):
    """
    Slots do dia com flags (available/reason) seguindo 'rule' + folgas.
    """
    tz = timezone.get_current_timezone()
    if not rule or not rule.is_active:
        return []

    step = timedelta(minutes=rule.slot_minutes or 30)
    start_dt = _aware_local(datetime.combine(d, rule.start_time), tz)
    end_dt = _aware_local(datetime.combine(d, rule.end_time), tz)
    lunch_st = _aware_local(datetime.combine(d, rule.lunch_start), tz) if rule.lunch_start else None
    lunch_en = _aware_local(datetime.combine(d, rule.lunch_end), tz) if rule.lunch_end else None

    # janela do dia e folgas no fuso
    day_start = _aware_local(datetime.combine(d, time(0, 0)), tz)
    day_end = day_start + timedelta(days=1)
    offs = [
        (off.start.astimezone(tz), off.end.astimezone(tz))
        for off in timeoffs_qs.filter(start__lt=day_end, end__gt=day_start)
    ]

    slots = []
    cur = start_dt
    while cur < end_dt:
        nxt = min(cur + step, end_dt)
        available, reason = True, None

        # almoço
        if lunch_st and lunch_en and not (nxt <= lunch_st or cur >= lunch_en):
            available, reason = False, "almoco"

        # folga/bloqueio
        if available and offs:
            for off_st, off_en in offs:
                if not (nxt <= off_st or cur >= off_en):
                    available, reason = False, "folga"
                    break

        slots.append({"start": cur, "end": nxt, "available": available, "reason": reason})
        cur = nxt
    return slots


# ---------------------------------------------------
# NOVO AGENDAMENTO (manual, já CONFIRMADO)
# ---------------------------------------------------
@require_shop_member
@login_required
def agendamento_novo(request, shop_slug, solicitacao_id=None):
    """
    Cria um agendamento CONFIRMADO (sempre para o barbeiro logado).
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)

    # parâmetros GET
    dia_param = (request.GET.get("dia") or "").strip()
    cliente_id = (request.GET.get("cliente") or "").strip()
    cliente_nome_param = (request.GET.get("cliente_nome") or "").strip()
    servico_id = (request.GET.get("servico") or "").strip()
    want_debug = request.GET.get("debug") == "1"

    dia = _parse_date(dia_param, timezone.localdate())
    barbeiro = request.user

    # slots disponíveis
    slots_disponiveis = []
    debug_lines = []
    rule = Availability.objects.filter(barbeiro=barbeiro, weekday=dia.weekday()).first()
    if rule:
        slots_disponiveis = [s for s in rule.gerar_slots(dia, barbeiro) if s.get("available")]
        if want_debug:
            offs_count = TimeOff.objects.filter(barbeiro=barbeiro, start__date=dia).count()
            ags_count = Agendamento.objects.filter(shop=shop, barbeiro=barbeiro, inicio__date=dia).count()
            debug_lines += [
                f"Dia: {dia.isoformat()}",
                f"Barbeiro: {barbeiro} (id={barbeiro.pk})",
                f"Regra: slot {rule.slot_minutes} min | {rule.start_time}–{rule.end_time}",
                f"Folgas no dia: {offs_count}",
                f"Agendamentos no dia (shop={shop.slug}): {ags_count}",
                f"Slots livres: {len(slots_disponiveis)}",
            ]
    elif want_debug:
        debug_lines += [
            f"Dia: {dia.isoformat()}",
            f"Barbeiro: {barbeiro} (id={barbeiro.pk})",
            "Regra: nenhuma",
            "Slots livres: 0",
        ]

    debug_info = "\n".join(debug_lines) if want_debug else ""

    # horário selecionado
    sel_inicio = request.POST.get("inicio") or request.GET.get("inicio") or ""

    # montar form
    initial = {
        "status": StatusAgendamento.CONFIRMADO,
        "barbeiro": barbeiro.pk,
    }
    if sel_inicio:
        initial["inicio"] = sel_inicio
    if cliente_id and cliente_id.isdigit():
        initial["cliente"] = int(cliente_id)
    if cliente_nome_param:
        initial["cliente_nome"] = cliente_nome_param
    if servico_id and servico_id.isdigit():
        initial["servico"] = int(servico_id)

    if request.method == "POST":
        form = AgendamentoForm(request.POST, initial=initial)
        if form.is_valid():
            with transaction.atomic():
                ag = form.save(commit=False)
                ag.shop = shop
                ag.barbeiro = barbeiro
                ag.status = StatusAgendamento.CONFIRMADO

                # snapshots
                if ag.servico and not ag.servico_nome:
                    ag.servico_nome = ag.servico.nome
                if ag.cliente_id and not ag.cliente_nome:
                    ag.cliente_nome = ag.cliente.nome or ag.cliente_nome

                # garante fim
                if not ag.fim:
                    ag.calcular_fim_pelo_servico()

                # conflito (global por barbeiro; se quiser por loja, passe shop=shop)
                if ag.inicio and ag.fim and Agendamento.existe_conflito(barbeiro, ag.inicio, ag.fim):
                    form.add_error(None, "Conflito de horário para este barbeiro.")

                if not form.errors:
                    ag.save()
                    messages.success(request, "Atendimento criado com sucesso.")
                    return redirect("agendamentos:agenda_dia", shop_slug=shop.slug)
    else:
        form = AgendamentoForm(initial=initial)

    # preço sugerido
    if not form.is_bound and servico_id and servico_id.isdigit():
        try:
            servico_sel = form.fields["servico"].queryset.get(pk=int(servico_id))
            form.fields["preco_cobrado"].initial = getattr(servico_sel, "preco", None)
        except Exception:
            pass

    # reconstruir URL preservando params úteis
    preserve_params = {}
    if cliente_id:
        preserve_params["cliente"] = cliente_id
    if cliente_nome_param:
        preserve_params["cliente_nome"] = cliente_nome_param
    if servico_id:
        preserve_params["servico"] = servico_id

    ctx = {
        "title": "Novo atendimento",
        "form": form,
        "shop": shop,
        "dia": dia,
        "slots_disponiveis": slots_disponiveis,
        "preserve_params": preserve_params,
        "debug_info": debug_info,
        "sel_inicio": sel_inicio,
    }
    return render(request, "agendamentos/agendamento_form.html", ctx)












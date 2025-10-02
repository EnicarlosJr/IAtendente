from calendar import monthrange
from datetime import date, datetime, time, timedelta
from django.db.models import Q
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.utils import timezone  # <<< use o timezone do Django
from agendamentos.models import Agendamento, StatusAgendamento
from agendamentos.views import _day_nav, _day_slots, _parse_date, _week_bounds, _week_nav
from barbearias.models import BarberShop
from core.access import is_manager, require_shop_member
from django.contrib.auth import get_user_model


# ===================================================
# AGENDA — VISÃO GERAL
# ===================================================


# (caso ainda não tenha no topo do arquivo)
try:
    from solicitacoes.models import Solicitacao, SolicitacaoStatus
    HAS_SOL = True
except Exception:
    HAS_SOL = False
    Solicitacao = None
    SolicitacaoStatus = None

def _safe_duration_minutes(obj) -> int:
    """
    Tenta inferir a duração em minutos a partir do serviço relacionado.
    Fallback: 30 min.
    """
    dur = None
    serv = getattr(obj, "servico", None)
    if serv:
        dur = getattr(serv, "duracao_minutos", None) or getattr(serv, "duracao", None)
        # pode vir em minutos ou timedelta dependendo do seu modelo
        if hasattr(dur, "total_seconds"):
            dur = int(dur.total_seconds() // 60)
    return dur or 30

def _intervalos_agendamentos(qs, tz):
    out = []
    for a in qs.order_by("inicio"):
        if not a.inicio:
            continue
        ini = timezone.localtime(a.inicio, tz)
        fim = a.fim or (a.inicio + timedelta(minutes=_safe_duration_minutes(a)))
        fim = timezone.localtime(fim, tz)
        out.append((ini, fim, a))
    return out

def _intervalos_solicitacoes(qs, tz):
    out = []
    for s in qs.order_by("inicio"):
        if not s.inicio:
            continue
        ini = timezone.localtime(s.inicio, tz)
        # algumas solicitações não têm fim — calcula por duração do serviço
        fim_raw = getattr(s, "fim", None) or (s.inicio + timedelta(minutes=_safe_duration_minutes(s)))
        fim = timezone.localtime(fim_raw, tz)
        out.append((ini, fim, s))
    return out

def _month_nav(d: date) -> tuple[date, date]:
    prev_month = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return prev_month, next_month

@require_shop_member
@login_required
def agenda_visao(request, shop_slug):
    """
    Visão geral: Hoje (linha do tempo), Semana (resumo), Mini-mês.
    Inclui agendamentos e solicitações (pendentes/aceitas), exclui negadas/canceladas.
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)
    tz = timezone.get_current_timezone()

    # --------- Base date (hoje ou ?data=YYYY-MM-DD) ---------
    hoje = timezone.localdate()
    base_date = _parse_date(request.GET.get("data", ""), hoje)

    # --------- Alvo (barbeiro) ---------
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

    # =====================================================================
    # COLUNA 1 — HOJE (timeline)
    # =====================================================================
    day_start = timezone.make_aware(datetime.combine(base_date, time(0, 0)), tz)
    day_end = day_start + timedelta(days=1)
    # grid de horários padrão
    slots_today = _day_slots(base_date, 8, 20, 30)
    slot_step = timedelta(minutes=30)

    # Agendamentos do dia
    ag_qs = (
        Agendamento.objects.filter(shop=shop)
        .exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
        .filter(inicio__isnull=False, inicio__gte=day_start, inicio__lt=day_end)
        .select_related("cliente", "servico")
    )
    if barbeiro:
        ag_qs = ag_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
    ag_int = _intervalos_agendamentos(ag_qs, tz)

    # Solicitações do dia (pendentes/aceitas; fora canceladas/negadas)
    sol_int = []
    if HAS_SOL and SolicitacaoStatus:
        exclude_status = [
            getattr(SolicitacaoStatus, "CANCELADA", "CANCELADA"),
            getattr(SolicitacaoStatus, "NEGADA", "NEGADA"),
        ]
        sol_qs = (
            Solicitacao.objects.filter(shop=shop)
            .exclude(status__in=exclude_status)
            .filter(inicio__isnull=False, inicio__gte=day_start, inicio__lt=day_end)
            .select_related("cliente", "servico")
        )
        if barbeiro:
            sol_qs = sol_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
        sol_int = _intervalos_solicitacoes(sol_qs, tz)

    today_rows = []
    for dt in slots_today:
        ag_matches = [iv for iv in ag_int if iv[0] <= dt < iv[1]]
        sol_matches = [iv for iv in sol_int if iv[0] <= dt < iv[1]]
        item = None

        if ag_matches:
            a_start, a_end, ag = ag_matches[0]
            if a_start <= dt < (a_start + slot_step):
                item = {
                    "id": ag.id,
                    "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
                    "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
                    "status": ag.status,
                    "inicio": a_start,
                    "fim": a_end,
                    "is_solicitacao": False,
                }
        elif sol_matches:
            s_start, s_end, sol = sol_matches[0]
            if s_start <= dt < (s_start + slot_step):
                item = {
                    "id": sol.id,
                    "cliente_nome": getattr(sol, "cliente_nome", None) or (getattr(sol, "cliente", None).nome if getattr(sol, "cliente", None) else getattr(sol, "nome", "—")),
                    "servico_nome": getattr(sol, "servico_nome", None) or (getattr(sol, "servico", None).nome if getattr(sol, "servico", None) else "—"),
                    "status": getattr(sol, "status", "PENDENTE"),
                    "inicio": s_start,
                    "fim": s_end,
                    "is_solicitacao": True,
                }

        today_rows.append({"time": dt, "item": item})

    prev_day, next_day = _day_nav(base_date)

    # =====================================================================
    # COLUNA 2 — SEMANA (resumo compacto)
    # =====================================================================
    wk_start, wk_end = _week_bounds(base_date)
    week_start_dt = timezone.make_aware(datetime.combine(wk_start, time(0, 0)), tz)
    week_end_dt = timezone.make_aware(datetime.combine(wk_end + timedelta(days=1), time(0, 0)), tz)

    ag_w_qs = (
        Agendamento.objects.filter(shop=shop)
        .exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
        .filter(inicio__isnull=False, inicio__gte=week_start_dt, inicio__lt=week_end_dt)
        .select_related("cliente", "servico")
    )
    if barbeiro:
        ag_w_qs = ag_w_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
    ag_w_int = _intervalos_agendamentos(ag_w_qs, tz)

    sol_w_items = []
    if HAS_SOL and SolicitacaoStatus:
        exclude_status = [
            getattr(SolicitacaoStatus, "CANCELADA", "CANCELADA"),
            getattr(SolicitacaoStatus, "NEGADA", "NEGADA"),
        ]
        sol_w_qs = (
            Solicitacao.objects.filter(shop=shop)
            .exclude(status__in=exclude_status)
            .filter(inicio__isnull=False, inicio__gte=week_start_dt, inicio__lt=week_end_dt)
            .select_related("cliente", "servico")
        )
        if barbeiro:
            sol_w_qs = sol_w_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
        for s_start, s_end, sol in _intervalos_solicitacoes(sol_w_qs, tz):
            sol_w_items.append({
                "inicio": s_start,
                "fim": s_end,
                "cliente_nome": getattr(sol, "cliente_nome", None) or (getattr(sol, "cliente", None).nome if getattr(sol, "cliente", None) else getattr(sol, "nome", "—")),
                "servico_nome": getattr(sol, "servico_nome", None) or (getattr(sol, "servico", None).nome if getattr(sol, "servico", None) else "—"),
                "status": getattr(sol, "status", "PENDENTE"),
                "is_solicitacao": True,
            })

    # agrega por dia
    days = [wk_start + timedelta(days=i) for i in range(7)]
    by_day = {d: [] for d in days}
    for a_start, a_end, ag in ag_w_int:
        by_day[a_start.date()].append({
            "inicio": a_start, "fim": a_end,
            "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
            "status": ag.status,
            "is_solicitacao": False,
        })
    for item in sol_w_items:
        by_day[item["inicio"].date()].append(item)

    week_cols = []
    for d in days:
        items = sorted(by_day[d], key=lambda x: x["inicio"])
        total = len(items)
        confirmados = sum(1 for x in items if str(x["status"]).upper() in ("CONFIRMADO", "CONFIRMADA", "FINALIZADO", "REALIZADO"))
        pendentes = sum(1 for x in items if str(x["status"]).upper() == "PENDENTE")
        cancelados = sum(1 for x in items if str(x["status"]).upper() in ("CANCELADO", "NEGADO", "NEGADA"))
        top = items[:3]
        week_cols.append({
            "date": d, "total": total,
            "confirmados": confirmados, "pendentes": pendentes, "cancelados": cancelados,
            "top": top,
        })

    prev_week, next_week = _week_nav(base_date)

    # =====================================================================
    # COLUNA 3 — MINI-MÊS
    # =====================================================================
    ref_date = base_date.replace(day=1)
    year, month = ref_date.year, ref_date.month
    first_weekday, num_days = monthrange(year, month)
    ref_start_dt = timezone.make_aware(datetime(year, month, 1, 0, 0), tz)
    ref_end_dt = ref_start_dt + timedelta(days=num_days)

    ag_m_qs = (
        Agendamento.objects.filter(shop=shop)
        .exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
        .filter(inicio__isnull=False, inicio__gte=ref_start_dt, inicio__lt=ref_end_dt)
        .select_related("cliente", "servico")
    )
    if barbeiro:
        ag_m_qs = ag_m_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
    ag_m_int = _intervalos_agendamentos(ag_m_qs, tz)

    counts_by_day = {ref_date + timedelta(days=i): 0 for i in range(num_days)}
    for a_start, _, _ in ag_m_int:
        key = a_start.date()
        if key in counts_by_day:
            counts_by_day[key] += 1

    if HAS_SOL and SolicitacaoStatus:
        exclude_status = [
            getattr(SolicitacaoStatus, "CANCELADA", "CANCELADA"),
            getattr(SolicitacaoStatus, "NEGADA", "NEGADA"),
        ]
        sol_m_qs = (
            Solicitacao.objects.filter(shop=shop)
            .exclude(status__in=exclude_status)
            .filter(inicio__isnull=False, inicio__gte=ref_start_dt, inicio__lt=ref_end_dt)
        )
        if barbeiro:
            sol_m_qs = sol_m_qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
        for s_start, _, _ in _intervalos_solicitacoes(sol_m_qs, tz):
            key = s_start.date()
            if key in counts_by_day:
                counts_by_day[key] += 1

    month_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    blank_cells = list(range(first_weekday))
    month_days = [{"date": d, "count": counts_by_day[d]} for d in sorted(counts_by_day.keys())]
    prev_month, next_month = _month_nav(ref_date)

    # --------- render ---------
    return render(request, "agendamentos/agenda.html", {
        "title": "Agenda — Visão Geral",
        "shop": shop,
        "base_date": base_date,
        "prev_day": base_date - timedelta(days=1),
        "next_day": base_date + timedelta(days=1),
        "today_rows": today_rows,

        "wk_start": wk_start,
        "wk_end": wk_end,
        "prev_week": wk_start - timedelta(days=7),
        "next_week": wk_start + timedelta(days=7),
        "week_cols": week_cols,

        "ref_date": ref_date,
        "month_labels": month_labels,
        "blank_cells": blank_cells,
        "month_days": month_days,
        "prev_month": prev_month,
        "next_month": next_month,
    })

# views_dashboard.py
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum, Count, F
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

# =========================
# Imports tolerantes
# =========================
from barbearias.models import BarberShop
from barbearias.utils import get_default_shop_for

try:
    from agendamentos.models import (
        Agendamento,
        StatusAgendamento,
        BarberAvailability,   # se tiver
        BarberTimeOff,        # se tiver
    )
except Exception:
    Agendamento = None
    StatusAgendamento = None
    BarberAvailability = None
    BarberTimeOff = None

try:
    from solicitacoes.models import Solicitacao, SolicitacaoStatus
except Exception:
    Solicitacao = None
    SolicitacaoStatus = None

try:
    from clientes.models import Cliente, HistoricoItem
except Exception:
    Cliente = None
    HistoricoItem = None

# =========================
# Flags de disponibilidade
# =========================
HAS_AG = Agendamento is not None
HAS_SOL = Solicitacao is not None and SolicitacaoStatus is not None
HAS_CLIENTE = Cliente is not None
HAS_HIST = HistoricoItem is not None

WORKDAY_START_H = 8
WORKDAY_END_H = 20
DEFAULT_SLOT_MIN = 30

# =========================
# Helpers genéricos
# =========================
def _round_to_slot(dt: datetime, step_min=DEFAULT_SLOT_MIN) -> datetime:
    """Arredonda o datetime para o próximo múltiplo de 'step_min' minutos."""
    dt = _aware(dt)
    m = (dt.minute // step_min) * step_min
    if dt.minute % step_min != 0:
        m += step_min
    base = dt.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=m)
    if base < dt:
        base += timedelta(minutes=step_min)
    return base

def _holes_next(timeline: dict, base_date: date, horizon_hours=3, step_min=DEFAULT_SLOT_MIN) -> list[dict]:
    """
    A partir de agora até +horizon_hours, encontra blocos de slots 'livre' contíguos.
    Retorna no máx. 5 buracos: [{"inicio": dt, "fim": dt, "minutos": int, "slots": int}...]
    """
    now = timezone.localtime(timezone.now(), _tz())
    start = _round_to_slot(now, step_min)
    end = start + timedelta(hours=horizon_hours)

    # Reconstrói a lista real de horários (a timeline tem apenas labels)
    cur = _aware(datetime(base_date.year, base_date.month, base_date.day, start.hour, start.minute))
    end_lim = _aware(datetime(base_date.year, base_date.month, base_date.day, end.hour, end.minute))
    slots_dt = []
    while cur < end_lim:
        slots_dt.append(cur)
        cur += timedelta(minutes=step_min)

    # mapeia labels -> item.kind
    label_to_kind = {}
    for lbl, it in zip(timeline["labels"], timeline["items"]):
        label_to_kind[lbl] = it.get("kind")

    # agrupa contíguos livres
    holes, run_start, run_count = [], None, 0
    for dt in slots_dt:
        lbl = dt.strftime("%H:%M")
        is_free = (label_to_kind.get(lbl) == "livre")
        if is_free:
            if run_start is None:
                run_start = dt
                run_count = 1
            else:
                run_count += 1
        else:
            if run_start is not None:
                holes.append({
                    "inicio": run_start,
                    "fim": run_start + timedelta(minutes=run_count * step_min),
                    "minutos": run_count * step_min,
                    "slots": run_count,
                })
                run_start, run_count = None, 0
    if run_start is not None and run_count > 0:
        holes.append({
            "inicio": run_start,
            "fim": run_start + timedelta(minutes=run_count * step_min),
            "minutos": run_count * step_min,
            "slots": run_count,
        })

    # top 5 por duração desc
    holes.sort(key=lambda h: h["minutos"], reverse=True)
    return holes[:5]

def _tz():
    return timezone.get_current_timezone()

def _aware(dt: datetime):
    tz = _tz()
    return timezone.make_aware(dt, tz) if timezone.is_naive(dt) else dt.astimezone(tz)

def _today_window(d: date):
    start = _aware(datetime(d.year, d.month, d.day, 0, 0, 0))
    return start, start + timedelta(days=1)

def _week_bounds(d: date):
    start = d - timedelta(days=d.weekday())  # segunda
    end = start + timedelta(days=6)          # domingo
    return start, end

def _month_window(d: date):
    first = date(d.year, d.month, 1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    start = _aware(datetime(first.year, first.month, first.day, 0, 0, 0))
    return start, _aware(datetime(nxt.year, nxt.month, nxt.day, 0, 0, 0))

def _parse_date(s: str, default: date) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return default

def _apply_shop_filter(qs, shop):
    if not shop or not qs:
        return qs
    model = qs.model
    try:
        model._meta.get_field("shop")
        return qs.filter(shop=shop)
    except Exception:
        pass
    try:
        model._meta.get_field("barbearia")
        return qs.filter(barbearia=shop)
    except Exception:
        pass
    try:
        model._meta.get_field("barber_shop")
        return qs.filter(barber_shop=shop)
    except Exception:
        pass
    return qs

def _overlap_minutes(a_start, a_end, b_start, b_end) -> int:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    delta = (end - start).total_seconds() / 60
    return int(delta) if delta > 0 else 0

def _safe_duration_minutes(obj) -> int:
    """
    Tenta inferir duração a partir do serviço ligado ao objeto (Agendamento ou Solicitacao).
    Fallback: 30 min.
    """
    dur = None
    serv = getattr(obj, "servico", None) or getattr(obj, "servico_ref", None)
    if serv:
        dur = getattr(serv, "duracao_minutos", None) or getattr(serv, "duracao", None) or getattr(serv, "duracao_min", None)
        if hasattr(dur, "total_seconds"):
            dur = int(dur.total_seconds() // 60)
    return int(dur or DEFAULT_SLOT_MIN)

def _calc_fim(obj, default_min=DEFAULT_SLOT_MIN):
    if getattr(obj, "fim", None):
        return obj.fim
    if getattr(obj, "inicio", None):
        return obj.inicio + timedelta(minutes=_safe_duration_minutes(obj) or default_min)
    return None

def _day_slots(d: date, start_h=WORKDAY_START_H, end_h=WORKDAY_END_H, step_min=DEFAULT_SLOT_MIN):
    tz = _tz()
    cur = _aware(datetime(d.year, d.month, d.day, start_h, 0, 0))
    end = _aware(datetime(d.year, d.month, d.day, end_h, 0, 0))
    step = timedelta(minutes=step_min)
    out = []
    while cur < end:
        out.append(cur)
        cur += step
    return out

def _work_minutes_for_user_on_day(user, d: date, fallback_min: int) -> int:
    """
    Se houver regras de disponibilidade (BarberAvailability/BarberTimeOff), usa-as.
    Senão, fallback para a janela padrão do dia.
    """
    total_min = (WORKDAY_END_H - WORKDAY_START_H) * 60
    if not (user and getattr(user, "is_authenticated", False) and BarberAvailability):
        return fallback_min or total_min

    day_start, day_end = _today_window(d)
    weekday = d.weekday()
    rules = BarberAvailability.objects.filter(barbeiro=user, weekday=weekday, is_active=True)

    tz = _tz()
    win = []
    for r in rules:
        ws = _aware(datetime(d.year, d.month, d.day, r.start_time.hour, r.start_time.minute))
        we = _aware(datetime(d.year, d.month, d.day, r.end_time.hour, r.end_time.minute))
        if we > ws:
            win.append((ws, we))

    # Desconta folgas/bloqueios
    if BarberTimeOff:
        offs = BarberTimeOff.objects.filter(barbeiro=user, start__lt=day_end, end__gt=day_start)
        for i, (ws, we) in enumerate(list(win)):
            for off in offs:
                cut = _overlap_minutes(ws, we, off.start, off.end)
                if cut:
                    # simplificação: subtrai direto do total
                    pass

    # total direto
    total = sum(int((we - ws).total_seconds() / 60) for (ws, we) in win) or total_min
    return max(0, total)

# =========================
# Query helpers (ag/sol)
# =========================
def _ag_qs(shop, start=None, end=None, barbeiro=None):
    if not HAS_AG:
        return None
    qs = _apply_shop_filter(Agendamento.objects.all(), shop).select_related("cliente", "servico")
    if start is not None and end is not None:
        qs = qs.filter(inicio__isnull=False, inicio__gte=start, inicio__lt=end)
    # Exclui cancelado
    if StatusAgendamento is not None:
        qs = qs.exclude(status=getattr(StatusAgendamento, "CANCELADO", None))
    # filtro por barbeiro (ou incluir barbeiro nulo)
    if barbeiro is not None:
        qs = qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
    return qs

def _sol_qs(shop, start=None, end=None, barbeiro=None):
    if not HAS_SOL:
        return None
    qs = _apply_shop_filter(Solicitacao.objects.all(), shop).select_related("cliente", "servico")
    if start is not None and end is not None:
        qs = qs.filter(inicio__isnull=False, inicio__gte=start, inicio__lt=end)

    # Exclui NEGADA/CANCELADA
    excl = []
    for nm in ("NEGADA", "CANCELADA"):
        excl.append(getattr(SolicitacaoStatus, nm, nm))
    qs = qs.exclude(status__in=excl)

    if barbeiro is not None:
        qs = qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
    return qs

def _to_intervals(qs):
    """
    Normaliza em [(ini, fim, obj)] com TZ local e fim calculado se necessário.
    """
    if not qs:
        return []
    tz = _tz()
    out = []
    for obj in qs.order_by("inicio"):
        if not obj.inicio:
            continue
        ini = timezone.localtime(obj.inicio, tz)
        fim = _calc_fim(obj) or obj.inicio
        fim = timezone.localtime(fim, tz)
        out.append((ini, fim, obj))
    return out

# =========================
# Medidas para ECharts
# =========================
def _timeline_for_day(shop, base_date: date, barbeiro=None):
    labels = []
    items = []  # lista paralela a labels; cada posição recebe {kind, title, status, id?}
    slots = _day_slots(base_date, WORKDAY_START_H, WORKDAY_END_H, DEFAULT_SLOT_MIN)
    slot_step = timedelta(minutes=DEFAULT_SLOT_MIN)

    start, end = _today_window(base_date)
    ag = _to_intervals(_ag_qs(shop, start, end, barbeiro))
    sol = _to_intervals(_sol_qs(shop, start, end, barbeiro))

    for dt in slots:
        labels.append(dt.strftime("%H:%M"))
        item = {"kind": "livre", "title": "Livre", "status": "LIVRE", "id": None}
        ag_matches = [iv for iv in ag if iv[0] <= dt < iv[1]]
        sol_matches = [iv for iv in sol if iv[0] <= dt < iv[1]]

        # prioridade para agendamento
        if ag_matches:
            a0, a1, obj = ag_matches[0]
            if a0 <= dt < a0 + slot_step:
                item = {
                    "kind": "agendamento",
                    "title": f"{obj.cliente_nome or getattr(getattr(obj,'cliente',None),'nome','—')} · {obj.servico_nome or getattr(getattr(obj,'servico',None),'nome','—')}",
                    "status": str(getattr(obj, "status", "")),
                    "id": obj.id,
                }
            else:
                item = {"kind": "ocupado", "title": "Em atendimento", "status": "OCUPADO", "id": None}
        elif sol_matches:
            s0, s1, obj = sol_matches[0]
            if s0 <= dt < s0 + slot_step:
                st = str(getattr(obj, "status", "PENDENTE"))
                item = {
                    "kind": "solicitacao",
                    "title": f"{getattr(obj,'cliente_nome',None) or getattr(getattr(obj,'cliente',None),'nome','—')} · {getattr(obj,'servico_nome',None) or getattr(getattr(obj,'servico',None),'nome','—')}",
                    "status": st,
                    "id": obj.id,
                }
            else:
                item = {"kind": "ocupado", "title": "Ocupado", "status": "OCUPADO", "id": None}

        items.append(item)
    return {"labels": labels, "items": items}

def _heatmap_week_occup(shop, base_date: date, barbeiro=None):
    """
    Matriz para heatmap (ECharts): x = horas (08..19), y = dias (seg..dom), data = [[x,y,val],...]
    val = % ocupação no slot (considera agendamentos+solicitações confirmadas/pendentes).
    """
    wk_start, wk_end = _week_bounds(base_date)
    days = [wk_start + timedelta(days=i) for i in range(7)]
    hours = list(range(WORKDAY_START_H, WORKDAY_END_H))  # hora “cheia”

    data = []
    for yi, d in enumerate(days):
        start, end = _today_window(d)
        ag_int = _to_intervals(_ag_qs(shop, start, end, barbeiro))
        sol_int = _to_intervals(_sol_qs(shop, start, end, barbeiro))

        for xi, hh in enumerate(hours):
            slot0 = _aware(datetime(d.year, d.month, d.day, hh, 0, 0))
            slot1 = slot0 + timedelta(hours=1)

            # soma minutos ocupados nesse bloco de 1h
            occ_min = 0
            for a0, a1, _ in ag_int:
                occ_min += _overlap_minutes(a0, a1, slot0, slot1)
            for s0, s1, _ in sol_int:
                occ_min += _overlap_minutes(s0, s1, slot0, slot1)
            pct = min(100, round(occ_min / 60 * 100))
            data.append([xi, yi, pct])

    return {
        "x_labels": [f"{h:02d}h" for h in hours],
        "y_labels": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
        "data": data,  # [[x,y,value],...]
    }

def _funnel_7d(shop, base_date: date, barbeiro=None):
    start = base_date - timedelta(days=6)
    start_dt = _aware(datetime(start.year, start.month, start.day, 0, 0, 0))
    end_dt = _aware(datetime(base_date.year, base_date.month, base_date.day, 23, 59, 59))

    total = confirm = noshow = 0

    # entradas (solicitações criadas no período)
    if HAS_SOL:
        qs = _apply_shop_filter(Solicitacao.objects.all(), shop).filter(criado_em__gte=start_dt, criado_em__lte=end_dt)
        if barbeiro:
            qs = qs.filter(Q(barbeiro=barbeiro) | Q(barbeiro__isnull=True))
        total = qs.count()

        # confirmadas/realizadas
        ok_values = [
            getattr(SolicitacaoStatus, "CONFIRMADA", "CONFIRMADA"),
            getattr(SolicitacaoStatus, "REALIZADA", "REALIZADA"),
            getattr(SolicitacaoStatus, "FINALIZADA", getattr(SolicitacaoStatus, "REALIZADA", "REALIZADA")),
        ]
        confirm = qs.filter(status__in=ok_values).count()

        # no-show (se tiver)
        ns = getattr(SolicitacaoStatus, "NO_SHOW", None)
        if ns is not None:
            noshow = qs.filter(status=ns).count()

    conv_pct = round((confirm / total) * 100) if total else 0
    return {"total": total, "confirmadas": confirm, "noshow": noshow, "conv_pct": conv_pct}

def _revenue_daily_month(shop, base_date: date):
    """
    Faturamento diário do mês (HistoricoItem). Retorna labels, values e média móvel 7d.
    """
    labels, values = [], []
    ma7 = []

    if not HAS_HIST:
        return {"labels": labels, "values": values, "ma7": ma7}

    first = date(base_date.year, base_date.month, 1)
    days = monthrange(base_date.year, base_date.month)[1]
    dlist = [first + timedelta(days=i) for i in range(days)]

    start, end = _month_window(base_date)
    qs = _apply_shop_filter(HistoricoItem.objects.filter(data__gte=start, data__lt=end, faltou=False), shop)

    totals = {d: Decimal("0.00") for d in dlist}
    for row in qs.values("data").annotate(total=Sum("valor")):
        key = row["data"].date()
        if key in totals:
            totals[key] = row["total"] or Decimal("0.00")

    window = deque(maxlen=7)
    for d in dlist:
        labels.append(d.strftime("%d/%m"))
        v = float(totals[d] or 0)
        values.append(v)
        window.append(v)
        ma7.append(round(sum(window) / len(window), 2))
    return {"labels": labels, "values": values, "ma7": ma7}

def _top_services_month(shop, base_date: date, limit=8):
    """
    Top serviços por quantidade no mês. Se não houver HistoricoItem, tenta por Agendamento/Solicitacao confirmados.
    """
    labels, values = [], []
    start, end = _month_window(base_date)

    # HistoricoItem (melhor para faturamento)
    if HAS_HIST:
        qs = _apply_shop_filter(HistoricoItem.objects.filter(data__gte=start, data__lt=end, faltou=False), shop)
        rows = (
            qs.values("servico")
            .annotate(qtd=Count("id"))
            .order_by("-qtd")[:limit]
        )
        for r in rows:
            labels.append(r["servico"] or "Serviço")
            values.append(int(r["qtd"]))
        return {"labels": labels, "values": values}

    # Fallback: Agendamentos/Solicitações confirmadas
    base_labels = defaultdict(int)
    if HAS_AG:
        ag = _apply_shop_filter(
            Agendamento.objects.filter(inicio__gte=start, inicio__lt=end).exclude(
                status=getattr(StatusAgendamento, "CANCELADO", None)
            ),
            shop,
        )
        for a in ag.values("servico_nome").annotate(qtd=Count("id")).order_by("-qtd")[:limit]:
            base_labels[a["servico_nome"] or "Serviço"] += a["qtd"]

    if HAS_SOL:
        ok_values = [
            getattr(SolicitacaoStatus, "CONFIRMADA", "CONFIRMADA"),
            getattr(SolicitacaoStatus, "REALIZADA", "REALIZADA"),
            getattr(SolicitacaoStatus, "FINALIZADA", getattr(SolicitacaoStatus, "REALIZADA", "REALIZADA")),
        ]
        sol = _apply_shop_filter(
            Solicitacao.objects.filter(inicio__gte=start, inicio__lt=end, status__in=ok_values), shop
        )
        for s in sol.values("servico_nome").annotate(qtd=Count("id")).order_by("-qtd")[:limit]:
            base_labels[s["servico_nome"] or "Serviço"] += s["qtd"]

    top = sorted(base_labels.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    for name, qtd in top:
        labels.append(name)
        values.append(int(qtd))
    return {"labels": labels, "values": values}

def _ranking_clientes_month(shop, base_date: date, limit=10):
    rows = []
    if not HAS_HIST:
        return rows
    start, end = _month_window(base_date)
    qs = _apply_shop_filter(HistoricoItem.objects.filter(data__gte=start, data__lt=end, faltou=False), shop)
    for r in (
        qs.values("cliente__nome")
        .annotate(total=Sum("valor"), visitas=Count("id"))
        .order_by("-total")[:limit]
    ):
        rows.append(
            {"nome": r["cliente__nome"] or "(sem nome)", "total": float(r["total"] or 0), "visitas": int(r["visitas"])}
        )
    return rows

def _kpis_basic(shop, base_date: date, user):
    # faturamento/ticket/clientes
    faturamento_mes = Decimal("0.00")
    ticket_medio = Decimal("0.00")
    clientes_novos_mes = 0

    if HAS_HIST:
        start_m, end_m = _month_window(base_date)
        qsm = _apply_shop_filter(HistoricoItem.objects.filter(data__gte=start_m, data__lt=end_m, faltou=False), shop)
        faturamento_mes = qsm.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        atend_mes = qsm.count()
        ticket_medio = (faturamento_mes / atend_mes) if atend_mes else Decimal("0.00")

    if HAS_CLIENTE:
        start_m, end_m = _month_window(base_date)
        clientes_novos_mes = _apply_shop_filter(Cliente.objects.all(), shop).filter(
            created_at__gte=start_m, created_at__lt=end_m
        ).count()

    # ocupação de hoje (min confirmados / janela)
    hoje = timezone.localdate()
    start_d, end_d = _today_window(hoje)
    total_min = _work_minutes_for_user_on_day(user, hoje, (WORKDAY_END_H - WORKDAY_START_H) * 60)

    booked_min = 0
    if HAS_SOL:
        ok_values = [
            getattr(SolicitacaoStatus, "CONFIRMADA", "CONFIRMADA"),
            getattr(SolicitacaoStatus, "REALIZADA", "REALIZADA"),
            getattr(SolicitacaoStatus, "FINALIZADA", getattr(SolicitacaoStatus, "REALIZADA", "REALIZADA")),
        ]
        for s in _apply_shop_filter(
            Solicitacao.objects.filter(status__in=ok_values, inicio__gte=start_d, inicio__lt=end_d), shop
        ):
            s_fim = _calc_fim(s) or s.inicio
            booked_min += _overlap_minutes(s.inicio, s_fim, start_d, end_d)
    utilizacao_hoje = int(round((booked_min / total_min) * 100)) if total_min else 0

    # pendências
    pendentes = 0
    if HAS_SOL:
        pendentes = _apply_shop_filter(Solicitacao.objects.filter(status=SolicitacaoStatus.PENDENTE), shop).count()

    return {
        "faturamento_mes": faturamento_mes,
        "ticket_medio": ticket_medio,
        "clientes_novos_mes": clientes_novos_mes,
        "utilizacao_hoje": utilizacao_hoje,
        "pendencias": pendentes,
    }

def _today_work_window(d: date):
    """Retorna [work_start, work_end] aware para hoje, usando janela padrão."""
    ws = _aware(datetime(d.year, d.month, d.day, WORKDAY_START_H, 0, 0))
    we = _aware(datetime(d.year, d.month, d.day, WORKDAY_END_H, 0, 0))
    return ws, we

def _busy_intervals_for_range(shop, start: datetime, end: datetime, barbeiro=None):
    """Retorna [(ini,fim)] ocupados (agendamentos + solicitações) recortados ao range."""
    def _clip(a0, a1):
        s = max(a0, start)
        e = min(a1, end)
        return (s, e) if e > s else None

    out = []
    for ini, fim, _ in _to_intervals(_ag_qs(shop, start, end, barbeiro)):
        c = _clip(ini, fim);  out.append(c) if c else None
    for ini, fim, _ in _to_intervals(_sol_qs(shop, start, end, barbeiro)):
        c = _clip(ini, fim);  out.append(c) if c else None
    return out

def _merge_intervals(intervals: list[tuple[datetime, datetime]]):
    """Une intervalos [(a,b)] sobrepostos/contíguos."""
    if not intervals:
        return []
    xs = sorted(intervals, key=lambda p: p[0])
    merged = [xs[0]]
    for s, e in xs[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged

def _free_windows_between(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]):
    """Calcula janelas livres no [start,end] subtraindo intervalos ocupados."""
    holes = []
    cur = start
    for s, e in _merge_intervals([iv for iv in busy if iv]):
        if cur < s:
            holes.append((cur, s))
        cur = max(cur, e)
    if cur < end:
        holes.append((cur, end))
    return holes

# =========================
# Views
# =========================
@login_required
def dashboard_operacional(request, shop_slug=None):
    """
    Visão do barbeiro — foco no HOJE:
      - KPIs essenciais (ocupação do dia via _kpis_basic)
      - Timeline do dia (ECharts)
      - Buracos próximos (próx. 3h)
      - Heatmap semanal (ECharts)
      - Pendências (solicitações PENDENTE)
    """
    # resolve shop
    if shop_slug:
        shop = get_object_or_404(BarberShop, slug=shop_slug)
    else:
        sid = get_default_shop_for(request.user)
        shop = BarberShop.objects.filter(id=sid).first() if sid else None
    if not shop:
        return redirect("painel:dashboard")

    base_date = _parse_date((request.GET.get("data") or "").strip(), timezone.localdate())
    barbeiro = request.user  # foco no usuário logado

    # KPIs
    kpis = _kpis_basic(shop, base_date, request.user)

    # Timeline do dia (labels/items)
    timeline = _timeline_for_day(shop, base_date, barbeiro)

    # ---- Buracos nas próximas 3h ----
    tz = _tz()
    now = timezone.localtime(timezone.now(), tz)
    # limita ao dia e à janela de trabalho
    work_s, work_e = _today_work_window(base_date)
    horizon_end = min(work_e, now + timedelta(hours=3))
    horizon_start = max(now, work_s)
    holes = []
    if horizon_end > horizon_start:
        busy = _busy_intervals_for_range(shop, horizon_start, horizon_end, barbeiro)
        for s, e in _free_windows_between(horizon_start, horizon_end, busy):
            dur = int((e - s).total_seconds() // 60)
            holes.append({
                "inicio": s,
                "fim": e,
                "dur_min": dur,
                "label": f"{timezone.localtime(s, tz).strftime('%H:%M')}–{timezone.localtime(e, tz).strftime('%H:%M')} ({dur} min)"
            })

    # Heatmap semanal
    heatmap = _heatmap_week_occup(shop, base_date, barbeiro)

    ctx = {
        "title": "Dashboard — Operacional",
        "shop": shop,
        "shop_slug": shop.slug,
        "base_date": base_date,
        "prev_day": base_date - timedelta(days=1),
        "next_day": base_date + timedelta(days=1),

        # KPIs (usa kpis.utilizacao_hoje)
        "kpis": kpis,

        # Linha do tempo (ECharts)
        "ec_timeline_labels": timeline["labels"],   # ["08:00", ...]
        "ec_timeline_items": timeline["items"],     # [{kind,status,title,id}, ...]

        # Buracos 3h
        "holes": holes or [],  # [{inicio,fim,dur_min,label}, ...]

        # Heatmap semana
        "ec_heatmap_x": heatmap["x_labels"],
        "ec_heatmap_y": heatmap["y_labels"],
        "ec_heatmap_data": heatmap["data"],
    }
    return render(request, "painel/dashboard_op.html", ctx)


@login_required
def dashboard_gerencial(request, shop_slug=None):
    """
    Visão gerencial — foca no MÊS, faturamento diário, top serviços, ranking e heatmap geral.
    """
    # resolve shop
    shop = None
    if shop_slug:
        shop = get_object_or_404(BarberShop, slug=shop_slug)
    else:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
            except BarberShop.DoesNotExist:
                shop = None
    if not shop:
        return redirect("painel:dashboard")

    base_date = _parse_date((request.GET.get("data") or "").strip(), timezone.localdate())
    barbeiro = None  # gerencial = visão agregada (todos)

    # KPIs
    kpis = _kpis_basic(shop, base_date, request.user)

    # ECharts — revenue diário
    rev = _revenue_daily_month(shop, base_date)

    # Top serviços
    top_srv = _top_services_month(shop, base_date, limit=8)

    # Heatmap semanal (padrão: semana da data base)
    heatmap = _heatmap_week_occup(shop, base_date, barbeiro)

    # Ranking clientes
    ranking = _ranking_clientes_month(shop, base_date, limit=10)

    # Funil 7d (agregado)
    funnel = _funnel_7d(shop, base_date, barbeiro)

    # Navegação
    wk_start, wk_end = _week_bounds(base_date)
    first_month_day = base_date.replace(day=1)
    prev_month = (first_month_day - timedelta(days=1)).replace(day=1)
    next_month = (first_month_day.replace(day=28) + timedelta(days=4)).replace(day=1)

    ctx = {
        "title": "Dashboard — Gerencial",
        "shop": shop,
        "shop_slug": shop.slug,
        "base_date": base_date,

        # KPIs
        "kpis": kpis,

        # ECharts data
        "ec_rev_labels": rev["labels"],       # ["01/10","02/10",...]
        "ec_rev_values": rev["values"],       # [120, 0, 340, ...]
        "ec_rev_ma7": rev["ma7"],             # [120, 60, 153, ...]

        "ec_top_srv_labels": top_srv["labels"],   # ["Corte","Barba",...]
        "ec_top_srv_values": top_srv["values"],   # [42, 30, ...]

        "ec_heatmap_x": heatmap["x_labels"],
        "ec_heatmap_y": heatmap["y_labels"],
        "ec_heatmap_data": heatmap["data"],

        "ranking_clientes": ranking,          # [{nome, total, visitas},...]

        "funnel_7d": funnel,

        # Navegação temporal
        "wk_start": wk_start,
        "wk_end": wk_end,
        "prev_week": wk_start - timedelta(days=7),
        "next_week": wk_start + timedelta(days=7),
        "prev_month": prev_month,
        "next_month": next_month,
    }
    return render(request, "painel/dashboard_mgmt.html", ctx)

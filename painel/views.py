# painel/views.py
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate, ExtractHour

# =========================
# Imports de modelos (tolerantes)
# =========================
try:
    from solicitacoes.models import Solicitacao, SolicitacaoStatus
except Exception:
    Solicitacao = None
    SolicitacaoStatus = None

try:
    from clientes.models import Cliente, HistoricoItem  # HistoricoItem opcional
except Exception:
    Cliente = None
    HistoricoItem = None

try:
    from agendamentos.models import Agendamento  # opcional/legado
except Exception:
    Agendamento = None

try:
    from agendamentos.models import BarberAvailability, BarberTimeOff
except Exception:
    BarberAvailability = None
    BarberTimeOff = None


# Flags de disponibilidade
HAS_SOL = Solicitacao is not None
HAS_CLIENTE = Cliente is not None
HAS_AG = Agendamento is not None
HAS_HIST = HistoricoItem is not None

# Janelas padrão (para ocupação)
WORKDAY_START_H = 8
WORKDAY_END_H = 20


# =========================
# Helpers
# =========================
def _today_window(d: date):
    """(start_dt, end_dt) do dia em TZ local, aware, intervalo [start, end)."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    end = start + timedelta(days=1)
    return start, end


def _month_window(d: date):
    """Primeiro dia do mês até o primeiro dia do mês seguinte (aware, [start, end))."""
    tz = timezone.get_current_timezone()
    first = date(d.year, d.month, 1)
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    start = timezone.make_aware(datetime(first.year, first.month, first.day, 0, 0, 0), tz)
    end = timezone.make_aware(datetime(nxt.year, nxt.month, nxt.day, 0, 0, 0), tz)
    return start, end


def _sol_qs():
    """QuerySet seguro: tenta select_related em 'servico' ou 'servico_ref' se forem FK."""
    if not HAS_SOL:
        return None
    qs = Solicitacao.objects.all()
    try:
        f = Solicitacao._meta.get_field("servico")
        if getattr(f, "is_relation", False) and (
            getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)
        ):
            qs = qs.select_related("servico")
    except Exception:
        pass
    # tenta também 'servico_ref' se existir (compatibilidade)
    try:
        f2 = Solicitacao._meta.get_field("servico_ref")
        if getattr(f2, "is_relation", False) and (
            getattr(f2, "many_to_one", False) or getattr(f2, "one_to_one", False)
        ):
            qs = qs.select_related("servico_ref")
    except Exception:
        pass
    return qs


def _calc_fim(s, default_min=30):
    """
    Retorna s.fim; senão, calcula por duração do serviço (servico ou servico_ref);
    senão soma default.
    """
    if getattr(s, "fim", None):
        return s.fim

    dur = None
    # tenta servico (FK)
    try:
        dur = getattr(getattr(s, "servico", None), "duracao_min", None)
    except Exception:
        dur = None
    # tenta servico_ref (FK)
    if not dur:
        try:
            dur = getattr(getattr(s, "servico_ref", None), "duracao_min", None)
        except Exception:
            pass

    return s.inicio + timedelta(minutes=dur or default_min) if s.inicio else None


def _day_bounds_aware(d: date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    end = start + timedelta(days=1)
    return start, end


def _overlap_minutes(a_start, a_end, b_start, b_end) -> int:
    """Minutos de interseção entre [a_start,a_end) e [b_start,b_end). Retorna >=0."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    delta = (end - start).total_seconds() / 60
    return int(delta) if delta > 0 else 0


def _work_minutes_for_user_on_day(user, d: date, fallback_min: int) -> int:
    """
    Soma minutos de janelas ativas de BarberAvailability no dia 'd' para 'user'
    e subtrai BarberTimeOff que cruze o dia. Se modelos não existirem ou user
    não estiver autenticado, usa fallback_min.
    """
    if not (user and getattr(user, "is_authenticated", False) and BarberAvailability):
        return fallback_min

    tz = timezone.get_current_timezone()
    day_start, day_end = _day_bounds_aware(d)

    # regras do dia (weekday)
    weekday = d.weekday()
    rules = BarberAvailability.objects.filter(
        barbeiro=user, weekday=weekday, is_active=True
    ).only("start_time", "end_time")

    if not rules.exists():
        return 0  # sem expediente

    # soma minutos trabalhados (antes de folgas)
    total = 0
    win_list = []
    for r in rules:
        ws = timezone.make_aware(datetime(d.year, d.month, d.day, r.start_time.hour, r.start_time.minute), tz)
        we = timezone.make_aware(datetime(d.year, d.month, d.day, r.end_time.hour, r.end_time.minute), tz)
        if we > ws:
            total += int((we - ws).total_seconds() / 60)
            win_list.append((ws, we))

    if total <= 0:
        return 0

    # subtrai folgas/time-offs que atinjam o dia
    if BarberTimeOff:
        offs = BarberTimeOff.objects.filter(
            barbeiro=user, start__lt=day_end, end__gt=day_start
        ).only("start", "end")
        for off in offs:
            for ws, we in win_list:
                total -= _overlap_minutes(ws, we, off.start, off.end)
                if total <= 0:
                    return 0

    # nunca negativo
    return max(0, total)


# =========================
# DASHBOARD
# =========================
def dashboard(request):
    hoje = timezone.localdate()
    now = timezone.now()
    start_m, end_m = _month_window(hoje)
    start_d, end_d = _today_window(hoje)
    start_30 = now - timedelta(days=30)
    start_90 = now - timedelta(days=90)

    # ---------- KPIs ----------
    faturamento_mes = Decimal("0.00")
    atend_mes = 0
    ticket_medio = Decimal("0.00")
    clientes_novos_mes = 0

    if HAS_HIST:
        qsm = HistoricoItem.objects.filter(data__gte=start_m, data__lt=end_m)
        faturamento_mes = qsm.filter(faltou=False).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        atend_mes = qsm.filter(faltou=False).count()
        ticket_medio = (faturamento_mes / atend_mes) if atend_mes else Decimal("0.00")

    if HAS_CLIENTE:
        clientes_novos_mes = Cliente.objects.filter(created_at__gte=start_m, created_at__lt=end_m).count()

    # ---------- Ocupação do dia ----------
    utilizacao_hoje = 0
    sol_qs = _sol_qs()
    if sol_qs and SolicitacaoStatus is not None:
        # minutos de trabalho (fallback: 08–20)
        fallback_total_min = (WORKDAY_END_H - WORKDAY_START_H) * 60
        total_min = _work_minutes_for_user_on_day(request.user, hoje, fallback_total_min)

        qs_conf = sol_qs.filter(
            status=SolicitacaoStatus.CONFIRMADA, inicio__lt=end_d, inicio__gte=start_d
        )
        # filtra pelo barbeiro logado, se existir FK
        if hasattr(Solicitacao, "barbeiro_id") and getattr(request.user, "is_authenticated", False):
            qs_conf = qs_conf.filter(barbeiro=request.user)

        booked_min = 0
        for s in qs_conf:
            fim = _calc_fim(s) or s.inicio
            booked_min += _overlap_minutes(s.inicio, fim, start_d, end_d)

        utilizacao_hoje = int(round((booked_min / total_min) * 100)) if total_min else 0

    kpis = {
        "faturamento_mes": faturamento_mes,
        "clientes_novos_mes": clientes_novos_mes,
        "utilizacao_hoje": utilizacao_hoje,
        "ticket_medio": ticket_medio,
    }

    # ---------- Gráficos ----------
    chart_fat_labels, chart_fat_values = [], []
    chart_srv_labels, chart_srv_values = [], []
    chart_peak_labels = [f"{h:02d}h" for h in range(24)]
    chart_peak_values = [0] * 24

    if HAS_HIST:
        # Evolução do faturamento (diário no mês)
        fat_dia = (
            HistoricoItem.objects.filter(faltou=False, data__gte=start_m, data__lt=end_m)
            .annotate(dia=TruncDate("data"))
            .values("dia")
            .annotate(total=Sum("valor"))
            .order_by("dia")
        )
        for row in fat_dia:
            chart_fat_labels.append(row["dia"].strftime("%d/%m"))
            chart_fat_values.append(float(row["total"] or 0))

        # Serviços mais executados (mês)
        by_srv = (
            HistoricoItem.objects.filter(faltou=False, data__gte=start_m, data__lt=end_m)
            .values("servico")
            .annotate(qtd=Count("id"))
            .order_by("-qtd")[:8]
        )
        for row in by_srv:
            chart_srv_labels.append(row["servico"] or "—")
            chart_srv_values.append(int(row["qtd"] or 0))

    # Horários de pico (últimos 30d) por solicitações confirmadas
    if sol_qs and SolicitacaoStatus is not None:
        peaks = (
            sol_qs.filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=start_30, inicio__lt=now)
            .annotate(hora=ExtractHour("inicio"))
            .values("hora")
            .annotate(qtd=Count("id"))
            .order_by("hora")
        )
        for row in peaks:
            h = row["hora"]
            if h is not None and 0 <= h <= 23:
                chart_peak_values[h] = int(row["qtd"] or 0)

    # ---------- Relatórios ----------
    ranking_clientes = []
    if HAS_HIST:
        top_cli = (
            HistoricoItem.objects.filter(faltou=False, data__gte=start_m, data__lt=end_m)
            .values("cliente_id", "cliente__nome")
            .annotate(total=Sum("valor"), visitas=Count("id"))
            .order_by("-total")[:10]
        )
        ranking_clientes = [
            {
                "cliente_id": r["cliente_id"],
                "nome": r["cliente__nome"],
                "total": r["total"] or 0,
                "visitas": r["visitas"],
            }
            for r in top_cli
        ]

    # Qualidade (30/90 dias)
    noshow_30 = 0
    noshow_rate_30 = 0
    retencao_30 = 0
    intervalo_medio_dias = None

    if HAS_HIST:
        base_30 = HistoricoItem.objects.filter(data__gte=start_30, data__lt=now)
        tot_30 = base_30.count()
        noshow_30 = base_30.filter(faltou=True).count()
        noshow_rate_30 = int(round((noshow_30 / tot_30) * 100)) if tot_30 else 0

        at_30_ids = set(
            HistoricoItem.objects.filter(faltou=False, data__gte=start_30, data__lt=now)
            .values_list("cliente_id", flat=True)
        )
        prev_count = (
            HistoricoItem.objects.filter(faltou=False, data__lt=start_30, cliente_id__in=at_30_ids)
            .values("cliente_id")
            .distinct()
            .count()
        )
        base_count = len(at_30_ids)
        retencao_30 = int(round((prev_count / base_count) * 100)) if base_count else 0

        eventos = (
            HistoricoItem.objects.filter(faltou=False, data__gte=start_90, data__lt=now)
            .values("cliente_id", "data")
            .order_by("cliente_id", "data")
        )
        last_by_cli, gaps = {}, []
        for ev in eventos:
            cid, dt = ev["cliente_id"], ev["data"]
            if cid in last_by_cli:
                gaps.append((dt - last_by_cli[cid]).days)
            last_by_cli[cid] = dt
        if gaps:
            intervalo_medio_dias = int(round(sum(gaps) / len(gaps)))

    # Próximos horários (operacional)
    proximos = []
    if sol_qs and SolicitacaoStatus is not None:
        qs_up = sol_qs.filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=now)
        if hasattr(Solicitacao, "barbeiro_id") and request.user.is_authenticated:
            qs_up = qs_up.filter(barbeiro=request.user)
        proximos = list(qs_up.order_by("inicio")[:5])

    solicitacoes_pendentes_count = sol_qs.filter(status="PENDENTE").count() if sol_qs else 0

    # ---------- Tendências vs mês anterior ----------
    prev_first_day = (start_m.date().replace(day=1) - timedelta(days=1)).replace(day=1)
    prev_start, prev_end = _month_window(prev_first_day)

    fat_prev = Decimal("0.00")
    at_prev = 0
    ticket_prev = Decimal("0.00")
    clientes_prev = 0

    if HAS_HIST:
        q_prev = HistoricoItem.objects.filter(faltou=False, data__gte=prev_start, data__lt=prev_end)
        fat_prev = q_prev.aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        at_prev = q_prev.count()
        ticket_prev = (fat_prev / at_prev) if at_prev else Decimal("0.00")

    if HAS_CLIENTE:
        clientes_prev = Cliente.objects.filter(created_at__gte=prev_start, created_at__lt=prev_end).count()

    def _pct_delta(cur, prev):
        try:
            if prev and prev != 0:
                return float((Decimal(cur) - Decimal(prev)) / Decimal(prev) * 100)
            return None  # sem base
        except Exception:
            return None

    kpis_delta = {
        "fat_pct": _pct_delta(faturamento_mes, fat_prev),
        "clientes_pct": _pct_delta(clientes_novos_mes, clientes_prev),
        "ticket_pct": _pct_delta(ticket_medio, ticket_prev),
    }

    # ---------- Funil 7d (solicitações) ----------
    seven_days_ago = now - timedelta(days=7)
    funnel = {"total": 0, "confirmadas": 0, "noshow": 0, "conv_pct": 0}

    if sol_qs and SolicitacaoStatus is not None:
        base7 = sol_qs.filter(inicio__gte=seven_days_ago, inicio__lt=now)
        funnel["total"] = base7.count()

        confirmadas_q = base7.filter(status=SolicitacaoStatus.CONFIRMADA)
        # considera REALIZADA como conversão também, se existir na enum
        if hasattr(SolicitacaoStatus, "REALIZADA"):
            confirmadas_q = base7.filter(
                Q(status=SolicitacaoStatus.CONFIRMADA) | Q(status=SolicitacaoStatus.REALIZADA)
            )
        funnel["confirmadas"] = confirmadas_q.count()

    # Agenda hoje (contagem simples para o header, opcional)
    agenda_hoje = []
    if sol_qs and SolicitacaoStatus is not None:
        agenda_hoje = list(
            sol_qs.filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=start_d, inicio__lt=end_d)
            .values_list("id", flat=True)
        )

    # ---------- Contexto ----------
    ctx = {
        "title": "Dashboard",
        "hoje": hoje,
        "now": now,

        "kpis": kpis,
        "kpis_delta": kpis_delta,
        "funnel_7d": funnel,

        "chart_fat_labels": chart_fat_labels,
        "chart_fat_values": chart_fat_values,
        "chart_srv_labels": chart_srv_labels,
        "chart_srv_values": chart_srv_values,
        "chart_peak_labels": chart_peak_labels,
        "chart_peak_values": chart_peak_values,

        "ranking_clientes": ranking_clientes,
        "noshow_30": noshow_30,
        "noshow_rate_30": noshow_rate_30,
        "retencao_30": retencao_30,
        "intervalo_medio_dias": intervalo_medio_dias,

        "proximos": proximos,
        "agenda_hoje": agenda_hoje,
        "solicitacoes_pendentes_count": solicitacoes_pendentes_count,
    }
    return render(request, "painel/dashboard.html", ctx)


# =========================
# AGENDA (atalho simples)
# =========================
def agenda(request):
    hoje = timezone.localdate()
    agendamentos = []
    if HAS_SOL and SolicitacaoStatus is not None:
        start_today, end_today = _today_window(hoje)
        qs = _sol_qs().filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=start_today, inicio__lt=end_today)
        if hasattr(Solicitacao, "barbeiro_id") and request.user.is_authenticated:
            qs = qs.filter(barbeiro=request.user)
        agendamentos = qs.order_by("inicio")
    elif HAS_AG:
        agendamentos = Agendamento.objects.filter(inicio__date=hoje).order_by("inicio")

    ctx = {
        "title": "Agenda",
        "agendamentos": agendamentos,
        "solicitacoes_pendentes_count": (
            Solicitacao.objects.filter(status="PENDENTE").count() if HAS_SOL else 0
        ),
    }
    return render(request, "agendamentos/agenda.html", ctx)


# =========================
# SOLICITAÇÕES (web do painel)
# =========================
def solicitacoes(request):
    if not HAS_SOL:
        ctx = {
            "title": "Solicitações",
            "solicitacoes": [],
            "page_obj": None,
            "filters": {},
            "alertas": {"sem_confirmacao": 0, "inativos_30d": 0, "solicitacoes_pendentes": 0},
            "solicitacoes_pendentes_count": 0,
        }
        return render(request, "painel/solicitacoes.html", ctx)

    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "").strip()

    qs = _sol_qs().order_by("-criado_em")
    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))
    if status_:
        qs = qs.filter(status=status_)

    page_obj = Paginator(qs, 20).get_page(request.GET.get("page"))
    pendentes_count = _sol_qs().filter(status="PENDENTE").count()

    ctx = {
        "title": "Solicitações",
        "solicitacoes": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": status_},
        "alertas": {
            "sem_confirmacao": pendentes_count,
            "inativos_30d": 0,  # placeholder para quando houver regra no app clientes
            "solicitacoes_pendentes": pendentes_count,
        },
        "solicitacoes_pendentes_count": pendentes_count,
    }
    return render(request, "painel/solicitacoes.html", ctx)


# =========================
# CLIENTES
# =========================
def clientes(request):
    lista = Cliente.objects.all().order_by("-created_at") if HAS_CLIENTE else []
    ctx = {
        "title": "Clientes",
        "clientes": lista,
        "solicitacoes_pendentes_count": (
            Solicitacao.objects.filter(status="PENDENTE").count() if HAS_SOL else 0
        ),
    }
    return render(request, "painel/clientes.html", ctx)

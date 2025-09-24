from datetime import date, datetime, timedelta
from decimal import Decimal

from django.shortcuts import render, redirect
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.contrib.auth.decorators import login_required

from barbearias.models import BarberShop
from barbearias.utils import get_default_shop_for

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
def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _apply_shop_filter(qs, shop):
    """Filtra QuerySet pela barbearia informada, se o modelo tiver campo."""
    if not shop or not qs:
        return qs
    model = qs.model
    if _model_has_field(model, "barbearia"):
        return qs.filter(barbearia=shop)
    if _model_has_field(model, "shop"):
        return qs.filter(shop=shop)
    if _model_has_field(model, "barber_shop"):
        return qs.filter(barber_shop=shop)
    return qs


def user_is_manager(user, shop):
    """Retorna True se o usuário for OWNER ou MANAGER da barbearia."""
    return (
        user.is_authenticated
        and shop
        and user.memberships.filter(shop=shop, role__in=["OWNER", "MANAGER"], is_active=True).exists()
    )


def _empty_dashboard_ctx():
    now = timezone.now()
    hoje = timezone.localdate()
    return {
        "title": "Dashboard",
        "hoje": hoje,
        "now": now,
        "is_manager": False,
        "kpis": {
            "faturamento_mes": Decimal("0.00"),
            "clientes_novos_mes": 0,
            "utilizacao_hoje": 0,
            "ticket_medio": Decimal("0.00"),
        },
        "kpis_delta": {"fat_pct": None, "clientes_pct": None, "ticket_pct": None},
        "funnel_7d": {"total": 0, "confirmadas": 0, "noshow": 0, "conv_pct": 0},
        "chart_fat_labels": [],
        "chart_fat_values": [],
        "chart_srv_labels": [],
        "chart_srv_values": [],
        "chart_peak_labels": [f"{h:02d}h" for h in range(24)],
        "chart_peak_values": [0] * 24,
        "ranking_clientes": [],
        "noshow_30": 0,
        "noshow_rate_30": 0,
        "retencao_30": 0,
        "intervalo_medio_dias": None,
        "proximos": [],
        "agenda_hoje": [],
        "solicitacoes_pendentes_count": 0,
        "workday_label": "08h–20h",
    }


# =========================
# Helpers de data e cálculo
# =========================
def _today_window(d: date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    return start, start + timedelta(days=1)


def _month_window(d: date):
    tz = timezone.get_current_timezone()
    first = date(d.year, d.month, 1)
    nxt = date(d.year + (d.month == 12), 1 if d.month == 12 else d.month + 1, 1)
    start = timezone.make_aware(datetime(first.year, first.month, first.day, 0, 0, 0), tz)
    return start, timezone.make_aware(datetime(nxt.year, nxt.month, nxt.day, 0, 0, 0), tz)


def _sol_qs(shop=None):
    if not HAS_SOL:
        return None
    qs = Solicitacao.objects.all()
    for field in ("servico", "servico_ref"):
        try:
            f = Solicitacao._meta.get_field(field)
            if getattr(f, "is_relation", False) and (getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)):
                qs = qs.select_related(field)
        except Exception:
            pass
    return _apply_shop_filter(qs, shop)


def _calc_fim(s, default_min=30):
    if getattr(s, "fim", None):
        return s.fim
    dur = getattr(getattr(s, "servico", None), "duracao_min", None) or getattr(
        getattr(s, "servico_ref", None), "duracao_min", None
    )
    return s.inicio + timedelta(minutes=dur or default_min) if s.inicio else None


def _day_bounds_aware(d: date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    return start, start + timedelta(days=1)


def _overlap_minutes(a_start, a_end, b_start, b_end) -> int:
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    delta = (end - start).total_seconds() / 60
    return int(delta) if delta > 0 else 0


def _work_minutes_for_user_on_day(user, d: date, fallback_min: int) -> int:
    if not (user and getattr(user, "is_authenticated", False) and BarberAvailability):
        return fallback_min

    tz = timezone.get_current_timezone()
    day_start, day_end = _day_bounds_aware(d)
    weekday = d.weekday()
    rules = BarberAvailability.objects.filter(barbeiro=user, weekday=weekday, is_active=True)

    total, win_list = 0, []
    for r in rules:
        ws = timezone.make_aware(datetime(d.year, d.month, d.day, r.start_time.hour, r.start_time.minute), tz)
        we = timezone.make_aware(datetime(d.year, d.month, d.day, r.end_time.hour, r.end_time.minute), tz)
        if we > ws:
            total += int((we - ws).total_seconds() / 60)
            win_list.append((ws, we))

    for off in BarberTimeOff.objects.filter(barbeiro=user, start__lt=day_end, end__gt=day_start):
        for ws, we in win_list:
            total -= _overlap_minutes(ws, we, off.start, off.end)

    return max(0, total or fallback_min)


# =========================
# HOME
# =========================
def home(request):
    return redirect("login" if not request.user.is_authenticated else "painel:dashboard")


# =========================
# DASHBOARD
# =========================
@login_required
def dashboard(request):
    shop = None
    if request.user.is_authenticated:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
            except BarberShop.DoesNotExist:
                shop = None

    if not shop:
        return render(request, "painel/dashboard.html", _empty_dashboard_ctx())

    hoje, now = timezone.localdate(), timezone.now()
    start_m, end_m = _month_window(hoje)
    start_d, end_d = _today_window(hoje)

    is_manager = user_is_manager(request.user, shop)

    faturamento_mes, atend_mes, ticket_medio, clientes_novos_mes = Decimal("0.00"), 0, Decimal("0.00"), 0
    if HAS_HIST:
        qsm = _apply_shop_filter(HistoricoItem.objects.filter(data__gte=start_m, data__lt=end_m), shop)
        faturamento_mes = qsm.filter(faltou=False).aggregate(total=Sum("valor"))["total"] or Decimal("0.00")
        atend_mes = qsm.filter(faltou=False).count()
        ticket_medio = (faturamento_mes / atend_mes) if atend_mes else Decimal("0.00")
    if HAS_CLIENTE:
        clientes_novos_mes = _apply_shop_filter(Cliente.objects.all(), shop).filter(
            created_at__gte=start_m, created_at__lt=end_m
        ).count()

    utilizacao_hoje = 0
    sol_qs = _sol_qs(shop=shop)
    if sol_qs and SolicitacaoStatus:
        total_min = _work_minutes_for_user_on_day(request.user, hoje, (WORKDAY_END_H - WORKDAY_START_H) * 60)
        booked_min = sum(
            _overlap_minutes(s.inicio, _calc_fim(s) or s.inicio, start_d, end_d)
            for s in sol_qs.filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=start_d, inicio__lt=end_d)
        )
        utilizacao_hoje = int(round((booked_min / total_min) * 100)) if total_min else 0

    ctx = _empty_dashboard_ctx()
    ctx.update(
        {
            "is_manager": is_manager,
            "kpis": {
                "faturamento_mes": faturamento_mes,
                "clientes_novos_mes": clientes_novos_mes,
                "utilizacao_hoje": utilizacao_hoje,
                "ticket_medio": ticket_medio,
            },
        }
    )
    return render(request, "painel/dashboard.html", ctx)


# =========================
# AGENDA
# =========================
@login_required
def agenda(request):
    shop = None
    if request.user.is_authenticated:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
            except BarberShop.DoesNotExist:
                shop = None

    hoje = timezone.localdate()
    agendamentos = []
    if shop and HAS_SOL and SolicitacaoStatus:
        start_today, end_today = _today_window(hoje)
        qs = _sol_qs(shop=shop).filter(inicio__gte=start_today, inicio__lt=end_today)
        qs = qs.filter(
            Q(status=SolicitacaoStatus.CONFIRMADA)
            | Q(status=getattr(SolicitacaoStatus, "REALIZADA", None))
        )
        agendamentos = qs.order_by("inicio")
    elif shop and HAS_AG:
        agendamentos = _apply_shop_filter(Agendamento.objects.filter(inicio__date=hoje), shop).order_by("inicio")

    ctx = {
        "title": "Agenda",
        "agendamentos": agendamentos,
        "solicitacoes_pendentes_count": _sol_qs(shop=shop).filter(status="PENDENTE").count() if (shop and HAS_SOL) else 0,
        "is_manager": user_is_manager(request.user, shop),
    }
    return render(request, "agendamentos/agenda.html", ctx)


# =========================
# SOLICITAÇÕES
# =========================
from itertools import chain
from django.core.paginator import Paginator

@login_required
def solicitacoes(request):
    shop = None
    if request.user.is_authenticated:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
            except BarberShop.DoesNotExist:
                shop = None

    # -------------------------
    # 1) Query Solicitações
    # -------------------------
    sol_qs = _sol_qs(shop=shop).order_by("-criado_em") if (shop and HAS_SOL) else Solicitacao.objects.none()

    # -------------------------
    # 2) Query Agendamentos
    # -------------------------
    ag_qs = Agendamento.objects.none()
    if shop and HAS_AG:
        ag_qs = _apply_shop_filter(Agendamento.objects.all(), shop).order_by("-created_at")

    # -------------------------
    # 3) Filtros
    # -------------------------
    q = (request.GET.get("q") or "").strip()
    status_ = (request.GET.get("status") or "").strip()

    if q:
        if HAS_SOL:
            sol_qs = sol_qs.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))
        if HAS_AG:
            ag_qs = ag_qs.filter(Q(cliente_nome__icontains=q) | Q(cliente__telefone__icontains=q))

    if status_:
        if HAS_SOL:
            sol_qs = sol_qs.filter(status=status_)
        if HAS_AG:
            ag_qs = ag_qs.filter(status=status_)

    # -------------------------
    # 4) Unir em uma lista única
    # -------------------------
    combined = sorted(
        chain(sol_qs, ag_qs),
        key=lambda x: getattr(x, "criado_em", None) or getattr(x, "created_at", None),
        reverse=True,
    )

    # paginação
    page_obj = Paginator(combined, 20).get_page(request.GET.get("page"))

    ctx = {
        "title": "Solicitações",
        "solicitacoes": page_obj,
        "page_obj": page_obj,
        "filters": {"q": q, "status": status_},
        "solicitacoes_pendentes_count": _sol_qs(shop=shop).filter(status="PENDENTE").count() if (shop and HAS_SOL) else 0,
        "is_manager": user_is_manager(request.user, shop),
    }
    return render(request, "painel/solicitacoes.html", ctx)


# =========================
# CLIENTES
# =========================
@login_required
def clientes(request):
    shop = None
    if request.user.is_authenticated:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
            except BarberShop.DoesNotExist:
                shop = None

    lista = _apply_shop_filter(Cliente.objects.all(), shop).order_by("-created_at") if (shop and HAS_CLIENTE) else []
    ctx = {
        "title": "Clientes",
        "clientes": lista,
        "solicitacoes_pendentes_count": _sol_qs(shop=shop).filter(status="PENDENTE").count() if shop else 0,
        "is_manager": user_is_manager(request.user, shop),
    }
    return render(request, "painel/clientes.html", ctx)

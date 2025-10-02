# painel/views.py
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

from agendamentos.models import StatusAgendamento
from barbearias.models import BarberShop
from barbearias.utils import get_default_shop_for
from painel.visibility import is_shop_admin, scope_agendamentos_qs, scope_solicitacoes_qs

# =========================
# Imports tolerantes
# =========================
try:
    from solicitacoes.models import Solicitacao, SolicitacaoStatus
except Exception:
    Solicitacao = None
    SolicitacaoStatus = None

try:
    from clientes.models import Cliente  # HistoricoItem não é necessário aqui
except Exception:
    Cliente = None

try:
    from agendamentos.models import Agendamento
except Exception:
    Agendamento = None


# =========================
# Flags de disponibilidade
# =========================
HAS_SOL = Solicitacao is not None
HAS_CLIENTE = Cliente is not None
HAS_AG = Agendamento is not None


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
    if not shop or qs is None:
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


def _today_window(d: date):
    """Retorna janela [start, end) do dia em timezone local."""
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    return start, start + timedelta(days=1)


def _sol_qs(shop=None):
    """Query base de Solicitações com select_related leve (tolerante)."""
    if not HAS_SOL:
        return None
    qs = Solicitacao.objects.all()
    for field in ("servico", "servico_ref", "cliente"):
        try:
            f = Solicitacao._meta.get_field(field)
            if getattr(f, "is_relation", False) and (getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)):
                qs = qs.select_related(field)
        except Exception:
            pass
    return _apply_shop_filter(qs, shop)


# =========================
# HOME
# =========================
def home(request):
    return redirect("login" if not request.user.is_authenticated else "painel:dashboard")


# =========================
# AGENDA (hoje)
# =========================
@login_required
def agenda(request):
    """Lista agendamentos/solicitações confirmadas de HOJE para a barbearia padrão do usuário."""
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
        agendamentos = _apply_shop_filter(
            Agendamento.objects.filter(inicio__date=hoje), shop
        ).order_by("inicio")

    pend_count = 0
    if shop and HAS_SOL and SolicitacaoStatus:
        pend_count = _sol_qs(shop=shop).filter(status=SolicitacaoStatus.PENDENTE).count()

    ctx = {
        "title": "Agenda",
        "agendamentos": agendamentos,
        "shop": shop,
        "shop_slug": shop.slug if shop else "",
        "solicitacoes_pendentes_count": pend_count,
        "is_manager": user_is_manager(request.user, shop),
    }
    return render(request, "agendamentos/agenda.html", ctx)


# =========================
# SOLICITAÇÕES (lista)
# =========================
def _get_shop_from_request(request):
    """
    Tenta pegar a barbearia do request (se middleware setou request.shop),
    ou pelo parâmetro ?shop=<slug>, ou a primeira da base como fallback.
    """
    shop = getattr(request, "shop", None)
    if shop:
        return shop
    slug = (request.GET.get("shop") or "").strip()
    if slug:
        return get_object_or_404(BarberShop, slug=slug)
    return BarberShop.objects.order_by("id").first()


@login_required
def solicitacoes(request):
    """Listagem de solicitações com filtros simples, tolerante a permissões."""
    shop = _get_shop_from_request(request)
    if not shop or not HAS_SOL:
        return render(request, "painel/solicitacoes.html", {
            "title": "Solicitações",
            "shop": shop,
            "shop_slug": shop.slug if shop else "",
            "list_kind": "solicitacoes",
            "solicitacoes": Paginator(Solicitacao.objects.none(), 20).get_page(1) if HAS_SOL else [],
            "page_obj": None,
            "filters": {"q": "", "status": ""},
            "alertas": {"sem_confirmacao": 0, "inativos_30d": 0, "solicitacoes_pendentes": 0},
            "solicitacoes_pendentes_count": 0,
        })

    q = (request.GET.get("q") or "").strip()
    status_raw = request.GET.get("status")
    status_ = (status_raw or "").strip().upper()
    has_status_param = ("status" in request.GET)

    admin = is_shop_admin(request.user)

    def paginar(qs):
        return Paginator(qs, 20).get_page(request.GET.get("page"))

    # mapa de status "de agendamento" para facilitar filtro alternativo
    map_ag = {
        "CONFIRMADA": StatusAgendamento.CONFIRMADO,
        "FINALIZADA": getattr(StatusAgendamento, "FINALIZADO", getattr(StatusAgendamento, "REALIZADO", None)),
        "REALIZADA":  getattr(StatusAgendamento, "REALIZADO", None),
        "NO_SHOW":    getattr(StatusAgendamento, "NO_SHOW", StatusAgendamento.CANCELADO),
        "CANCELADA":  getattr(StatusAgendamento, "NO_SHOW", StatusAgendamento.CANCELADO),
    }

    # === Se o filtro é de status "de agendamento", mudamos a listagem
    if status_ in map_ag and HAS_AG:
        ag_status = map_ag[status_]
        aq = (Agendamento.objects
              .filter(shop=shop)
              .select_related("cliente", "servico", "barbeiro"))
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

        pendentes_count = 0
        if HAS_SOL and SolicitacaoStatus:
            pendentes_qs = scope_solicitacoes_qs(
                Solicitacao.objects.filter(shop=shop, status=SolicitacaoStatus.PENDENTE),
                request.user, admin, incluir_nao_atribuida=True
            )
            pendentes_count = pendentes_qs.count()

        return render(request, "painel/solicitacoes.html", {
            "title": "Solicitações",
            "shop": shop,
            "shop_slug": shop.slug,
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

    # === Caso contrário, listamos Solicitações
    sq = (Solicitacao.objects
          .filter(shop=shop)
          .select_related("cliente", "servico")
          .order_by("-criado_em"))
    sq = scope_solicitacoes_qs(sq, request.user, admin, incluir_nao_atribuida=True)

    if q:
        sq = sq.filter(Q(nome__icontains=q) | Q(telefone__icontains=q))

    if has_status_param:
        if status_:
            sq = sq.filter(status=status_)
        selected_status = status_
    else:
        # padrão: mostrar pendentes
        if SolicitacaoStatus:
            sq = sq.filter(status=SolicitacaoStatus.PENDENTE)
            selected_status = SolicitacaoStatus.PENDENTE
        else:
            selected_status = ""

    page_obj = paginar(sq)

    pendentes_count = 0
    if HAS_SOL and SolicitacaoStatus:
        pendentes_qs = scope_solicitacoes_qs(
            Solicitacao.objects.filter(shop=shop, status=SolicitacaoStatus.PENDENTE),
            request.user, admin, incluir_nao_atribuida=True
        )
        pendentes_count = pendentes_qs.count()

    return render(request, "painel/solicitacoes.html", {
        "title": "Solicitações",
        "shop": shop,
        "shop_slug": shop.slug,
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


# =========================
# CLIENTES
# =========================
@login_required
def clientes(request):
    """Lista de clientes simples, ordenada por criação, da barbearia padrão do usuário."""
    shop = None
    if request.user.is_authenticated:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
            except BarberShop.DoesNotExist:
                shop = None

    lista = _apply_shop_filter(Cliente.objects.all(), shop).order_by("-created_at") if (shop and HAS_CLIENTE) else []
    pend_count = 0
    if shop and HAS_SOL:
        pend_qs = _sol_qs(shop=shop)
        if pend_qs is not None:
            pend_count = pend_qs.filter(status="PENDENTE").count()

    ctx = {
        "title": "Clientes",
        "clientes": lista,
        "shop": shop,
        "shop_slug": shop.slug if shop else "",
        "solicitacoes_pendentes_count": pend_count,
        "is_manager": user_is_manager(request.user, shop),
    }
    return render(request, "painel/clientes.html", ctx)


@login_required
def dashboard(request):
    """
    Redireciona o dashboard padrão para o NOVO dashboard operacional.
    Se o usuário tiver barbearia padrão, usa a rota com <shop_slug>.
    """
    shop_slug = ""
    if request.user.is_authenticated:
        sid = get_default_shop_for(request.user)
        if sid:
            try:
                shop = BarberShop.objects.get(id=sid)
                shop_slug = shop.slug
            except BarberShop.DoesNotExist:
                pass

    if shop_slug:
        return redirect("painel:dashboard_op_slug", shop_slug=shop_slug)
    return redirect("painel:dashboard_op")


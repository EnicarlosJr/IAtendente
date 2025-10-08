# barbearias/views_public_intake.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods

from .models import BarberShop
from servicos.models import Servico
from solicitacoes.models import Solicitacao, SolicitacaoStatus

# ---- imports opcionais (não quebram se não existirem) ----
try:
    from .models import BarberProfile  # perfil público do barbeiro
except Exception:
    BarberProfile = None  # type: ignore

try:
    from clientes.models import Cliente
except Exception:
    Cliente = None  # type: ignore

# Fonte canônica de ocupação
try:
    from agendamentos.models import Agendamento, StatusAgendamento
except Exception:
    Agendamento = None  # type: ignore
    StatusAgendamento = None  # type: ignore

# Regras de disponibilidade e folgas (opcional)
try:
    from agendamentos.models import BarbeiroAvailability as Availability, BarbeiroTimeOff as TimeOff
except Exception:
    Availability = None  # type: ignore
    TimeOff = None  # type: ignore


# ===================== Helpers genéricos =====================

def _normalize_phone(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _safe_int(s: str | None) -> Optional[int]:
    try:
        return int((s or "").strip())
    except Exception:
        return None


def _parse_inicio_aware(inicio_str: str | None):
    if not inicio_str:
        return None
    dt = parse_datetime(inicio_str.strip())
    if not dt:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _set_if_field(obj, field_name, value):
    if hasattr(obj, field_name):
        setattr(obj, field_name, value)


def _servicos_da_loja(shop: BarberShop):
    qs = Servico.objects.filter(ativo=True).order_by("nome")
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=shop)
    return qs


def _servico_by_id_for_shop(servico_id: int | None, shop: BarberShop) -> Optional[Servico]:
    if not servico_id:
        return None
    qs = Servico.objects.filter(id=servico_id, ativo=True)
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=shop)
    return qs.first()


# ===================== Cliente: localizar / criar =====================

def _get_cliente_phone_fields() -> List[str]:
    candidates = ["telefone", "phone", "whatsapp", "celular", "mobile", "phone_number"]
    if not Cliente:
        return []
    return [f for f in candidates if hasattr(Cliente, f)]


def _buscar_cliente_por_telefone(shop: BarberShop, telefone_digits: str):
    if not (Cliente and telefone_digits):
        return None
    qs = Cliente.objects.all()
    if hasattr(Cliente, "shop_id"):
        qs = qs.filter(shop=shop)

    for field in _get_cliente_phone_fields():
        exact = {field: telefone_digits}
        obj = qs.filter(**exact).first()
        if obj:
            return obj
        # regex que ignora máscara (pode não ser suportado por todos os backends)
        try:
            pattern = r"\D*".join(list(telefone_digits))
            obj = qs.filter(**{f"{field}__regex": pattern}).first()
            if obj:
                return obj
        except Exception:
            pass
    return None


def _criar_ou_atualizar_cliente(shop: BarberShop, telefone_digits: str, nome: str | None):
    if not Cliente:
        return None

    cli = _buscar_cliente_por_telefone(shop, telefone_digits)
    if cli:
        try:
            nome_atual = getattr(cli, "nome", "") or getattr(cli, "name", "") or ""
            if (not nome_atual) and (nome or "").strip():
                if hasattr(cli, "nome"):
                    cli.nome = nome.strip()
                    cli.save(update_fields=["nome"])
                elif hasattr(cli, "name"):
                    cli.name = nome.strip()
                    cli.save(update_fields=["name"])
        except Exception:
            pass
        return cli

    # criar novo
    cli = Cliente()
    if hasattr(Cliente, "shop_id"):
        setattr(cli, "shop", shop)

    if hasattr(cli, "nome"):
        cli.nome = (nome or telefone_digits).strip()
    elif hasattr(cli, "name"):
        cli.name = (nome or telefone_digits).strip()

    tel_fields = _get_cliente_phone_fields()
    if tel_fields:
        setattr(cli, tel_fields[0], telefone_digits)

    for f in ["ativo", "is_active", "status"]:
        if hasattr(cli, f):
            try:
                setattr(cli, f, True if f != "status" else "ATIVO")
            except Exception:
                pass

    cli.save()
    return cli


# ===================== Disponibilidade (JSON) =====================

@dataclass
class Intervalo:
    start: datetime
    end: datetime

    def overlaps(self, other: "Intervalo") -> bool:
        return self.start < other.end and other.start < self.end


def _tz():
    return timezone.get_current_timezone()


def _weekday(d: date) -> int:
    return d.weekday()  # 0=Seg .. 6=Dom


# Funcionamento padrão (se não houver Availability)
SHOP_HOURS: dict[int, Tuple[time, time]] = {
    0: (time(9, 0),  time(19, 0)),  # Seg
    1: (time(9, 0),  time(19, 0)),  # Ter
    2: (time(9, 0),  time(19, 0)),  # Qua
    3: (time(9, 0),  time(19, 0)),  # Qui
    4: (time(9, 0),  time(19, 0)),  # Sex
    5: (time(9, 0),  time(17, 0)),  # Sáb
    6: (time(0, 0),  time(0, 0)),   # Dom (fechado)
}


def _window_for_date(shop: BarberShop, d: date, barber_user=None) -> Optional[Tuple[datetime, datetime, int]]:
    """
    Retorna (start_dt, end_dt, step_minutes).
    - Se houver Availability do barbeiro naquele weekday, usa ela (e step = slot_minutes).
    - Senão usa SHOP_HOURS e step de 30 min.
    """
    tz = _tz()

    if barber_user and Availability:
        rule = Availability.objects.filter(barbeiro=barber_user, weekday=_weekday(d), is_active=True).first()
        if rule:
            start = timezone.make_aware(datetime.combine(d, rule.start_time), tz)
            end = timezone.make_aware(datetime.combine(d, rule.end_time), tz)
            step = int(getattr(rule, "slot_minutes", 30) or 30)
            return (start, end, step)

    # fallback: horário padrão da barbearia
    start_t, end_t = SHOP_HOURS.get(_weekday(d), (time(0, 0), time(0, 0)))
    if start_t == end_t:
        return None
    start = timezone.make_aware(datetime.combine(d, start_t), tz)
    end = timezone.make_aware(datetime.combine(d, end_t), tz)
    return (start, end, 30)


def _breaks_for_date(barber_user, d: date) -> List[Intervalo]:
    if not (barber_user and TimeOff):
        return []
    tz = _tz()
    day_start = timezone.make_aware(datetime.combine(d, time.min), tz)
    day_end = day_start + timedelta(days=1)
    offs = TimeOff.objects.filter(barbeiro=barber_user, start__lt=day_end, end__gt=day_start)
    return [Intervalo(start=o.start.astimezone(tz), end=o.end.astimezone(tz)) for o in offs]


def _busy_from_agendamentos(shop: BarberShop, barber_user, d: date) -> List[Intervalo]:
    tz = _tz()
    day_start = timezone.make_aware(datetime.combine(d, time.min), tz)
    day_end = day_start + timedelta(days=1)

    if not Agendamento:
        return []

    qs = Agendamento.objects.filter(inicio__lt=day_end, fim__gt=day_start)
    if hasattr(Agendamento, "shop_id"):
        qs = qs.filter(shop=shop)
    if barber_user is not None and hasattr(Agendamento, "barbeiro_id"):
        qs = qs.filter(barbeiro=barber_user)

    # Exclui cancelados
    if StatusAgendamento and hasattr(StatusAgendamento, "CANCELADO"):
        qs = qs.exclude(status=StatusAgendamento.CANCELADO)

    out: List[Intervalo] = []
    for a in qs:
        ini = a.inicio.astimezone(tz)
        fim = (a.fim or a.inicio).astimezone(tz)
        out.append(Intervalo(ini, fim))
    return out


def _merge(intervals: List[Intervalo]) -> List[Intervalo]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x.start)
    merged = [intervals[0]]
    for it in intervals[1:]:
        last = merged[-1]
        if it.start <= last.end:
            last.end = max(last.end, it.end)
        else:
            merged.append(it)
    return merged


def _duracao_min(servico: Servico) -> int:
    return int(getattr(servico, "duracao_min", 30) or 30)


def _slice_slots(window: Tuple[datetime, datetime, int], breaks: List[Intervalo],
                 busy: List[Intervalo], service_minutes: int) -> List[str]:
    tz = _tz()
    start, end, step_minutes = window
    step = timedelta(minutes=step_minutes or 30)
    dur = timedelta(minutes=service_minutes or 30)
    now = timezone.localtime(timezone.now()).astimezone(tz)

    blocked = _merge(breaks + busy)
    out: List[str] = []
    cur = start
    while cur + dur <= end:
        if cur <= now:
            cur += step
            continue
        slot = Intervalo(cur, cur + dur)
        if not any(slot.overlaps(b) for b in blocked):
            out.append(cur.strftime("%H:%M"))
        cur += step
    return out


@require_GET
def public_slots(request, shop_slug, barber_slug=None):
    """
    JSON de disponibilidade:
      - Dias do mês: ?mode=days&service_id=&year=YYYY&month=MM -> { "days": [1,5,12,...] }
      - Slots do dia: ?service_id=&date=YYYY-MM-DD -> { "slots": ["09:00","09:30", ...] }
    Nunca cria nada: apenas leitura.
    """
    # Shop
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True) if hasattr(BarberShop, "ativo") \
           else get_object_or_404(BarberShop, slug=shop_slug)

    # Barbeiro (opcional)
    barber_user = None
    if barber_slug:
        if BarberProfile is None:
            raise Http404("Barbeiro não disponível.")
        barber = get_object_or_404(BarberProfile, shop=shop, public_slug=barber_slug, ativo=True)
        barber_user = getattr(barber, "user", None) or barber

    # Serviço
    service_id = _safe_int(request.GET.get("service_id"))
    if not service_id:
        return JsonResponse({"error": "service_id requerido"}, status=400)
    servico = _servico_by_id_for_shop(service_id, shop)
    if not servico:
        return JsonResponse({"error": "Serviço inválido ou inativo"}, status=400)

    service_minutes = _duracao_min(servico)

    mode = (request.GET.get("mode") or "").strip().lower()
    if mode == "days":
        year = _safe_int(request.GET.get("year"))
        month = _safe_int(request.GET.get("month"))
        if not year or not month:
            return JsonResponse({"error": "year e month são requeridos"}, status=400)

        from calendar import monthrange
        _, last_day = monthrange(year, month)
        today = timezone.localtime(timezone.now()).date()

        days_out: List[int] = []
        for d in range(1, last_day + 1):
            dt = date(year, month, d)
            if dt < today:
                continue
            window = _window_for_date(shop, dt, barber_user)
            if not window:
                continue
            breaks = _breaks_for_date(barber_user, dt)
            busy = _busy_from_agendamentos(shop, barber_user, dt)
            slots = _slice_slots(window, breaks, busy, service_minutes)
            if slots:
                days_out.append(d)
        return JsonResponse({"days": days_out})

    # Slots do dia
    date_str = (request.GET.get("date") or "").strip()
    if not date_str:
        return JsonResponse({"error": "date requerido (YYYY-MM-DD)"}, status=400)
    try:
        y, m, d = map(int, date_str.split("-"))
        dt = date(y, m, d)
    except Exception:
        return JsonResponse({"error": "date inválido"}, status=400)

    window = _window_for_date(shop, dt, barber_user)
    if not window:
        return JsonResponse({"slots": []})

    breaks = _breaks_for_date(barber_user, dt)
    busy = _busy_from_agendamentos(shop, barber_user, dt)
    slots = _slice_slots(window, breaks, busy, service_minutes)

    return JsonResponse({"slots": slots})


# ===================== Páginas públicas (HTML) =====================

@transaction.atomic
def _criar_solicitacao(request, shop: BarberShop, barber_obj=None) -> Solicitacao | None:
    """
    Cria a Solicitação (somente no submit final).
    - Cria/atualiza Cliente por telefone e vincula.
    - Garante shop e telefone normalizado.
    - Define callback_url se existir no POST ou na barbearia.
    """
    nome = (request.POST.get("nome") or "").strip()
    telefone_digits = _normalize_phone(request.POST.get("telefone") or "")
    servico_id = _safe_int(request.POST.get("servico_id"))
    inicio_str = (request.POST.get("inicio") or "").strip()
    observacoes = (request.POST.get("observacoes") or "").strip()
    callback_url = (request.POST.get("callback_url") or "").strip()

    if not telefone_digits or not servico_id:
        messages.error(request, "Informe telefone e serviço.")
        return None

    srv = _servico_by_id_for_shop(servico_id, shop)
    if not srv:
        messages.error(request, "Serviço inválido ou inativo.")
        return None

    dt = _parse_inicio_aware(inicio_str)

    # Cliente
    cliente_obj = _criar_ou_atualizar_cliente(shop, telefone_digits, nome)

    s = Solicitacao(
        shop=shop,
        telefone=telefone_digits,
        nome=(nome or telefone_digits),
        servico=srv,
        inicio=dt,
        observacoes=observacoes or "",
        status=SolicitacaoStatus.PENDENTE,
    )

    _set_if_field(s, "servico_nome", getattr(srv, "nome", "") or "")
    _set_if_field(s, "duracao_min_cotada", getattr(srv, "duracao_min", None))
    _set_if_field(s, "preco_cotado", getattr(srv, "preco", None))
    _set_if_field(s, "cliente", cliente_obj)

    if barber_obj:
        barbeiro_user = getattr(barber_obj, "user", None) or barber_obj
        _set_if_field(s, "barbeiro", barbeiro_user)

    if not callback_url:
        callback_url = getattr(shop, "default_callback_url", "") or getattr(shop, "webhook_url", "") or ""
    _set_if_field(s, "callback_url", callback_url)

    # Anti-duplicação simples (últimos 2 min)
    if hasattr(Solicitacao, "criado_em"):
        dois_min_antes = timezone.now() - timezone.timedelta(minutes=2)
        dup = (Solicitacao.objects
               .filter(shop=shop, telefone=telefone_digits, status=SolicitacaoStatus.PENDENTE)
               .filter(criado_em__gte=dois_min_antes))
        if dt:
            dup = dup.filter(inicio=dt)
        if dup.exists():
            messages.info(request, "Já recebemos sua solicitação recente. Aguarde confirmação.")
            return dup.order_by("-id").first()

    s.save()
    return s


@require_http_methods(["GET", "POST"])
def intake_shop(request, shop_slug):
    """
    Página pública da barbearia (sem login) para o cliente enviar solicitação.
    URL final: /pub/<shop_slug>/
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True) if hasattr(BarberShop, "ativo") \
           else get_object_or_404(BarberShop, slug=shop_slug)

    if request.method == "POST":
        # só cria se veio do passo 4 (botão final do front)
        if request.POST.get("_submit") == "1":
            s = _criar_solicitacao(request, shop, barber_obj=None)
            if s:
                messages.success(request, "Solicitação enviada! Em breve entraremos em contato.")
                return redirect("public:intake_shop", shop.slug)
        else:
            messages.error(request, "Envio inválido. Tente novamente.")

    return render(request, "public/intake_form.html", {
        "shop": shop,
        "barber": None,
        "servicos": _servicos_da_loja(shop),
        "now": timezone.now(),
    })


@require_http_methods(["GET", "POST"])
def intake_barber(request, shop_slug, barber_slug):
    """
    Página pública de um barbeiro específico (sem login) para o cliente enviar solicitação.
    URL final: /pub/<shop_slug>/<barber_slug>/
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug, ativo=True) if hasattr(BarberShop, "ativo") \
           else get_object_or_404(BarberShop, slug=shop_slug)

    if BarberProfile is None:
        messages.error(request, "Perfil de barbeiro ainda não configurado.")
        return redirect("public:intake_shop", shop.slug)

    barber = get_object_or_404(BarberProfile, shop=shop, public_slug=barber_slug, ativo=True)

    if request.method == "POST":
        if request.POST.get("_submit") == "1":
            s = _criar_solicitacao(request, shop, barber_obj=barber)
            if s:
                messages.success(request, "Solicitação enviada para o barbeiro! Aguarde confirmação.")
                return redirect("public:intake_barber", shop.slug, barber.public_slug)
        else:
            messages.error(request, "Envio inválido. Tente novamente.")

    return render(request, "public/intake_form.html", {
        "shop": shop,
        "barber": barber,
        "servicos": _servicos_da_loja(shop),
        "now": timezone.now(),
    })

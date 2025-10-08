# barbearias/views_public_slots.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple

from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import BarberShop
from servicos.models import Servico

# ---- opcionais (não quebram se ausentes) ----
try:
    from .models import BarberProfile  # perfil público do barbeiro
except Exception:
    BarberProfile = None  # type: ignore

try:
    from agendamentos.models import Agendamento, StatusAgendamento
except Exception:
    Agendamento = None  # type: ignore
    StatusAgendamento = None  # type: ignore

try:
    # Regras semanais e folgas
    from agendamentos.models import BarbeiroAvailability as Availability, BarbeiroTimeOff as TimeOff
except Exception:
    Availability = None  # type: ignore
    TimeOff = None  # type: ignore


# ===================== Helpers =====================

def _safe_int(s: str | None) -> Optional[int]:
    try:
        return int((s or "").strip())
    except Exception:
        return None

def _tz():
    return timezone.get_current_timezone()

def _weekday(d: date) -> int:
    return d.weekday()  # 0=Seg ... 6=Dom

def _servico_for(shop: BarberShop, servico_id: int) -> Optional[Servico]:
    qs = Servico.objects.filter(id=servico_id, ativo=True)
    if hasattr(Servico, "shop_id"):
        qs = qs.filter(shop=shop)
    return qs.first()

def _duracao_min(servico: Servico) -> int:
    return int(getattr(servico, "duracao_min", 30) or 30)

# Funcionamento padrão (fallback quando não há Availability)
SHOP_HOURS: dict[int, Tuple[time, time]] = {
    0: (time(9, 0),  time(19, 0)),  # Seg
    1: (time(9, 0),  time(19, 0)),  # Ter
    2: (time(9, 0),  time(19, 0)),  # Qua
    3: (time(9, 0),  time(19, 0)),  # Qui
    4: (time(9, 0),  time(19, 0)),  # Sex
    5: (time(9, 0),  time(17, 0)),  # Sáb
    6: (time(0, 0),  time(0, 0)),   # Dom (fechado)
}

@dataclass
class Intervalo:
    start: datetime
    end: datetime
    def overlaps(self, other: "Intervalo") -> bool:
        return self.start < other.end and other.start < self.end

def _window_for_date(shop: BarberShop, d: date, barber_user=None) -> Optional[Tuple[datetime, datetime, int]]:
    """
    Retorna (start_dt, end_dt, step_minutes).
    - Se houver Availability ativa do barbeiro no dia da semana, usa (step = slot_minutes).
    - Senão, usa horário padrão (SHOP_HOURS) com step de 30 minutos.
    """
    tz = _tz()
    if barber_user and Availability:
        rule = Availability.objects.filter(barbeiro=barber_user, weekday=_weekday(d), is_active=True).first()
        if rule:
            start = timezone.make_aware(datetime.combine(d, rule.start_time), tz)
            end = timezone.make_aware(datetime.combine(d, rule.end_time), tz)
            step = int(getattr(rule, "slot_minutes", 30) or 30)
            return (start, end, step)

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
    """
    Bloqueia horários por Agendamento (fonte canônica). Ignora CANCELADO.
    """
    if not Agendamento:
        return []
    tz = _tz()
    day_start = timezone.make_aware(datetime.combine(d, time.min), tz)
    day_end = day_start + timedelta(days=1)

    qs = Agendamento.objects.filter(inicio__lt=day_end, fim__gt=day_start)
    if hasattr(Agendamento, "shop_id"):
        qs = qs.filter(shop=shop)
    if barber_user is not None and hasattr(Agendamento, "barbeiro_id"):
        qs = qs.filter(barbeiro=barber_user)
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


# ===================== Endpoint público =====================

@require_GET
def public_slots(request, shop_slug, barber_slug=None):
    """
    Responde disponibilidade em JSON.

    - Dias com vaga (varre o mês):
      GET ?mode=days&service_id=<id>&year=YYYY&month=MM
      -> { "days": [1,5,12,...] }

    - Slots de um dia:
      GET ?service_id=<id>&date=YYYY-MM-DD
      -> { "slots": ["09:00","09:30", ...] }
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
    servico = _servico_for(shop, service_id)
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

    # Slots de um dia
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

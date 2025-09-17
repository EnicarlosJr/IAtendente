# agendamentos/views.py
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

from servicos.forms import AgendamentoForm
from solicitacoes.models import Solicitacao, SolicitacaoStatus
from agendamentos.models import Agendamento, BarberAvailability

# --- imports tolerantes para Availability/TimeOff (nomes novos/antigos) ---
try:
    from agendamentos.models import BarbeiroAvailability as Availability, BarbeiroTimeOff as TimeOff
except Exception:
    from agendamentos.models import BarberAvailability as Availability, BarberTimeOff as TimeOff

# forms (mantém retrocompatibilidade por aliases definidos no arquivo de forms)
try:
    from agendamentos.forms import BarbeiroAvailabilityForm as AvailabilityForm, BarbeiroTimeOffForm as TimeOffForm
except Exception:
    from agendamentos.forms import BarberAvailabilityForm as AvailabilityForm, BarberTimeOffForm as TimeOffForm


# -------------------------------
# Helpers
# -------------------------------
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
    end = timezone.make_aware(datetime(d.year, d.month, d.day, end_h,   0, 0), tz)
    step = timedelta(minutes=step_min)
    out = []
    while cur < end:
        out.append(cur)
        cur += step
    return out


def _sol_qs():
    """select_related('servico') quando for FK; senão plain .all()."""
    try:
        f = Solicitacao._meta.get_field("servico")
        if getattr(f, "is_relation", False) and (getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False)):
            return Solicitacao.objects.select_related("servico")
    except Exception:
        pass
    return Solicitacao.objects.all()


def _generate_slots(d: date, rule: BarberAvailability | None, timeoffs_qs):
    """
    Lista de slots do dia com flags:
      - available: True/False
      - reason: "almoco" | "folga" | None
    """
    tz = timezone.get_current_timezone()
    if not rule or not rule.is_active:
        return []

    def aware(dt: datetime):
        return timezone.make_aware(dt, tz) if timezone.is_naive(dt) else dt.astimezone(tz)

    step = timedelta(minutes=rule.slot_minutes or 30)
    start_dt = aware(datetime.combine(d, rule.start_time))
    end_dt   = aware(datetime.combine(d, rule.end_time))
    lunch_st = aware(datetime.combine(d, rule.lunch_start)) if rule.lunch_start else None
    lunch_en = aware(datetime.combine(d, rule.lunch_end))   if rule.lunch_end else None

    # folgas do dia
    day_start = aware(datetime.combine(d, time(0, 0)))
    day_end   = day_start + timedelta(days=1)
    offs = list(timeoffs_qs.filter(start__lt=day_end, end__gt=day_start))

    slots = []
    cur = start_dt
    while cur < end_dt:
        nxt = min(cur + step, end_dt)
        available, reason = True, None

        # almoço
        if lunch_st and lunch_en and not (nxt <= lunch_st or cur >= lunch_en):
            available, reason = False, "almoco"

        # folga/bloqueio
        if available:
            for off in offs:
                off_st = off.start.astimezone(tz)
                off_en = off.end.astimezone(tz)
                if not (nxt <= off_st or cur >= off_en):
                    available, reason = False, "folga"
                    break

        slots.append({"start": cur, "end": nxt, "available": available, "reason": reason})
        cur = nxt
    return slots


# -------------------------------
# AGENDA redirect
# -------------------------------
def agenda_redirect(request):
    return redirect("agendamentos:agenda_semana")


# -------------------------------
# AGENDA DIA
# -------------------------------
def agenda_dia(request):
    """
    Agenda do dia do barbeiro autenticado.
    Sobrepõe SOLICITAÇÕES CONFIRMADAS aos slots (livre/almoço/folga).
    ?dia=YYYY-MM-DD
    """
    tz = timezone.get_current_timezone()
    dia_str = (request.GET.get("dia") or request.GET.get("data") or "").strip()
    d = _parse_date(dia_str, timezone.localdate())

    # Janela do dia
    start = timezone.make_aware(datetime(d.year, d.month, d.day, 0, 0, 0), tz)
    end = start + timedelta(days=1)

    # Regra do dia + time-offs (barbeiro logado)
    rule = Availability.objects.filter(barbeiro=request.user, weekday=d.weekday()).first()
    offs_qs = TimeOff.objects.filter(barbeiro=request.user)

    # Slots base
    slots = _generate_slots(d, rule, offs_qs)

    # Solicitações confirmadas (margem 2h para pegar cruzamentos)
    query_start = start - timedelta(hours=2)
    confirmadas = (
        _sol_qs()
        .filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=query_start, inicio__lt=end)
        .order_by("inicio")
    )

    DEFAULT_STEP_MIN = (rule.slot_minutes if rule else 30)
    intervals = []
    for s in confirmadas:
        s_start = s.inicio
        dur_min = getattr(getattr(s, "servico", None), "duracao_min", None)
        if s.fim:
            s_end = s.fim
        elif s_start and dur_min:
            s_end = s_start + timedelta(minutes=dur_min)
        else:
            s_end = s_start + timedelta(minutes=DEFAULT_STEP_MIN)
        intervals.append((s_start, s_end, s))

    rows = []
    for slot in slots:
        t = slot["start"]
        overlaps = [iv for iv in intervals if iv[0] <= t < iv[1]]

        row = {
            "time": t,
            "item": None,
            "occupied": False,
            "conflicts": max(0, len(overlaps) - 1),
            "available": slot["available"],
            "reason": slot["reason"],  # None | "almoco" | "folga"
        }

        if overlaps:
            s_start, s_end, s = overlaps[0]
            if t == s_start:
                row["item"] = {
                    "id": s.id,
                    "cliente_nome": s.nome or s.telefone or "—",
                    "servico_nome": getattr(getattr(s, "servico", None), "nome", None)
                                    or getattr(s, "servico", None) or "—",
                    "status": s.status,
                    "inicio": s.inicio,
                    "fim": s_end,
                }
            else:
                row["occupied"] = True

        rows.append(row)

    prev_day, next_day = _day_nav(d)

    ctx = {
        "title": "Agenda",
        "date": d,
        "prev_day": prev_day,
        "next_day": next_day,
        "rows": rows,
    }
    return render(request, "agendamentos/agenda_dia.html", ctx)


# -------------------------------
# AGENDA SEMANA
# -------------------------------
def agenda_semana(request):
    """
    Grade semanal por barbeiro:
      - Linhas = horários unificados
      - Colunas = seg..dom
      - Célula usa disponibilidade (Livre/Almoço/Folga) + solicitações confirmadas
    ?data=YYYY-MM-DD  ?barbeiro=<id>
    """
    tz = timezone.get_current_timezone()
    hoje = timezone.localdate()
    base = _parse_date(request.GET.get("data", ""), hoje)
    wk_start, wk_end = _week_bounds(base)

    # --- resolve barbeiro alvo ---
    barbeiro = None
    barbeiro_param = (request.GET.get("barbeiro") or "").strip()
    if barbeiro_param:
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            barbeiro = User.objects.get(pk=barbeiro_param)
        except Exception:
            barbeiro = None
    elif request.user.is_authenticated:
        barbeiro = request.user

    DEFAULT_START_H, DEFAULT_END_H, DEFAULT_STEP_MIN = 8, 20, 30

    days = [wk_start + timedelta(days=i) for i in range(7)]
    day_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    days_ctx = [{"date": d, "label": day_labels[i]} for i, d in enumerate(days)]

    day_windows_map = {}
    day_slots_map = {}
    used_custom_rules = False

    if barbeiro:
        try:
            from .utils import work_windows_for_day, split_in_slots, subtract_timeoffs
            for d in days:
                windows = work_windows_for_day(barbeiro, d)
                day_windows_map[d] = windows[:]

                base_slots = []
                for ws, we, step in windows:
                    base_slots += split_in_slots(ws, we, step or DEFAULT_STEP_MIN)

                final_slots = subtract_timeoffs(barbeiro, base_slots)
                if not final_slots:
                    final_slots = _day_slots(d, start_h=DEFAULT_START_H, end_h=DEFAULT_END_H, step_min=DEFAULT_STEP_MIN)
                else:
                    used_custom_rules = True
                day_slots_map[d] = final_slots
        except Exception:
            for d in days:
                day_windows_map[d] = [(timezone.make_aware(datetime(d.year, d.month, d.day, DEFAULT_START_H), tz),
                                       timezone.make_aware(datetime(d.year, d.month, d.day, DEFAULT_END_H), tz),
                                       DEFAULT_STEP_MIN)]
                day_slots_map[d] = _day_slots(d, start_h=DEFAULT_START_H, end_h=DEFAULT_END_H, step_min=DEFAULT_STEP_MIN)
    else:
        for d in days:
            day_windows_map[d] = [(timezone.make_aware(datetime(d.year, d.month, d.day, DEFAULT_START_H), tz),
                                   timezone.make_aware(datetime(d.year, d.month, d.day, DEFAULT_END_H), tz),
                                   DEFAULT_STEP_MIN)]
            day_slots_map[d] = _day_slots(d, start_h=DEFAULT_START_H, end_h=DEFAULT_END_H, step_min=DEFAULT_STEP_MIN)

    # HH:MM das linhas
    time_keys = set()
    for d in days:
        for dt_slot in day_slots_map[d]:
            time_keys.add((dt_slot.hour, dt_slot.minute))
        for ws, we, _ in day_windows_map.get(d, []):
            cur = ws
            while cur < we:
                time_keys.add((cur.hour, cur.minute))
                cur += timedelta(minutes=DEFAULT_STEP_MIN)
    time_keys = sorted(time_keys)

    day_slot_keysets = {d: {(dt.hour, dt.minute) for dt in day_slots_map.get(d, [])} for d in days}

    def _in_work_window(d: date, hh: int, mm: int) -> bool:
        dt = timezone.make_aware(datetime(d.year, d.month, d.day, hh, mm), tz)
        for ws, we, _ in day_windows_map.get(d, []):
            if ws <= dt < we:
                return True
        return False

    # solicitações confirmadas da semana (com margem)
    week_start_dt = timezone.make_aware(datetime(wk_start.year, wk_start.month, wk_start.day, 0, 0, 0), tz)
    query_start = week_start_dt - timedelta(hours=6)
    week_end_dt = week_start_dt + timedelta(days=7)

    qs = _sol_qs().filter(status=SolicitacaoStatus.CONFIRMADA, inicio__lt=week_end_dt, inicio__gte=query_start)
    if barbeiro and hasattr(Solicitacao, "barbeiro_id"):
        qs = qs.filter(barbeiro=barbeiro)
    confirmadas = list(qs.order_by("inicio"))

    # indexa por dia
    day_intervals = {d: [] for d in days}
    for s in confirmadas:
        s_start = s.inicio
        dur_min = getattr(getattr(s, "servico", None), "duracao_min", None)
        s_end = s.fim or (s_start + timedelta(minutes=dur_min or DEFAULT_STEP_MIN))

        curr = s_start.date()
        last = s_end.date()
        while curr <= last:
            if curr in day_intervals:
                day_intervals[curr].append((s_start, s_end, s))
            curr += timedelta(days=1)

    rows = []
    for (hh, mm) in time_keys:
        time_label = timezone.make_aware(datetime(wk_start.year, wk_start.month, wk_start.day, hh, mm), tz)
        cells = []
        for d in days:
            slot_dt = timezone.make_aware(datetime(d.year, d.month, d.day, hh, mm), tz)

            matches = [(a, b, s) for (a, b, s) in day_intervals.get(d, []) if a <= slot_dt < b]

            has_slot = (hh, mm) in day_slot_keysets.get(d, set())
            in_window = _in_work_window(d, hh, mm)
            available = has_slot
            reason = None
            if not has_slot:
                reason = "almoco" if in_window else "folga"

            if matches:
                s_start, s_end, s = matches[0]
                if slot_dt == s_start:
                    cells.append({
                        "item": {
                            "id": s.id,
                            "cliente_nome": s.nome or s.telefone or "—",
                            "servico_nome": (getattr(getattr(s, "servico", None), "nome", None)
                                             or getattr(s, "servico", None) or "—"),
                            "inicio": s_start,
                            "fim": s_end,
                            "status": s.status,
                        },
                        "occupied": False,
                        "time": slot_dt,
                        "available": available,
                        "reason": reason,
                        "conflicts": max(0, len(matches) - 1),
                    })
                else:
                    cells.append({
                        "item": None,
                        "occupied": True,
                        "time": slot_dt,
                        "available": available,
                        "reason": reason,
                        "conflicts": max(0, len(matches) - 1),
                    })
            else:
                cells.append({
                    "item": None,
                    "occupied": False,
                    "time": slot_dt,
                    "available": available,
                    "reason": reason,
                    "conflicts": 0,
                })

        rows.append({"time": time_label, "cells": cells})

    prev_week, next_week = _week_nav(base)

    ctx = {
        "title": "Agenda — Semana",
        "wk_start": wk_start,
        "wk_end": wk_end,
        "days_ctx": days_ctx,
        "rows": rows,
        "prev_week": prev_week,
        "next_week": next_week,
        "barbeiro": barbeiro,
        "used_custom_rules": used_custom_rules,
    }
    return render(request, "agendamentos/agenda_semana.html", ctx)


# -------------------------------
# AGENDA MÊS
# -------------------------------
def _month_nav(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    prev_last = first - timedelta(days=1)
    prev = prev_last.replace(day=1)
    next_first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return prev, next_first


def agenda_mes(request):
    """
    Agenda mensal baseada em SOLICITAÇÕES CONFIRMADAS.
    Gera OrderedDict[date -> list[dict]] para o template.
    """
    hoje = timezone.localdate()
    ref_date = _parse_date(request.GET.get("data", ""), hoje).replace(day=1)

    year, month = ref_date.year, ref_date.month
    first_weekday, num_days = monthrange(year, month)

    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime(year, month, 1, 0, 0, 0), tz)
    end_dt = start_dt + timedelta(days=num_days)

    sol = _sol_qs().filter(status=SolicitacaoStatus.CONFIRMADA, inicio__gte=start_dt, inicio__lt=end_dt).order_by("inicio")

    DEFAULT_STEP_MIN = 30
    tmp = {ref_date + timedelta(days=i): [] for i in range(num_days)}

    for s in sol:
        d_local = timezone.localtime(s.inicio, tz).date()
        if d_local not in tmp:
            continue
        s_end = s.fim or (s.inicio + timedelta(minutes=getattr(getattr(s, "servico", None), "duracao_min", None) or DEFAULT_STEP_MIN))
        tmp[d_local].append({
            "id": s.id,
            "inicio": s.inicio,
            "fim": s_end,
            "cliente_nome": s.nome or s.telefone or "—",
            "servico_nome": (getattr(getattr(s, "servico", None), "nome", None) or getattr(s, "servico", None) or "—"),
            "status": s.status,
        })

    por_dia = OrderedDict(sorted(tmp.items(), key=lambda kv: kv[0]))
    blank_cells = list(range(first_weekday))
    dias_semana = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    prev_month, next_month = _month_nav(ref_date)

    ctx = {
        "title": "Agenda — Mês",
        "view": "mes",
        "ref_date": ref_date,
        "por_dia": por_dia,
        "blank_cells": blank_cells,
        "dias_semana": dias_semana,
        "prev_month": prev_month,
        "next_month": next_month,
    }
    return render(request, "agendamentos/agenda_mes.html", ctx)


# -------------------------------
# MINHA AGENDA (barbeiro autenticado)
# -------------------------------
@login_required
def minha_agenda_config(request):
    """
    Tela única: regras semanais + folgas + prévia do dia.
    ?data=YYYY-MM-DD
    """
    AvailabilityFS = modelformset_factory(Availability, form=AvailabilityForm, extra=0, can_delete=False)

    # Bootstrap das 7 linhas (se faltar alguma)
    defaults = {
        0: ("09:00", "19:00"),
        1: ("09:00", "19:00"),
        2: ("09:00", "19:00"),
        3: ("09:00", "19:00"),
        4: ("09:00", "19:00"),
        5: ("09:00", "14:00"),
        6: (None, None),  # domingo off
    }
    existing = {a.weekday: a for a in Availability.objects.filter(barbeiro=request.user)}
    to_create = []
    for wd in range(7):
        if wd not in existing:
            st, en = defaults[wd]
            to_create.append(
                Availability(
                    barbeiro=request.user,
                    weekday=wd,
                    is_active=bool(st and en),
                    start_time=st or "09:00",
                    end_time=en or "17:00",
                    slot_minutes=30,
                )
            )
    if to_create:
        Availability.objects.bulk_create(to_create)

    qs = Availability.objects.filter(barbeiro=request.user).order_by("weekday")

    hoje = timezone.localdate()
    d = _parse_date(request.GET.get("data", ""), hoje)

    if request.method == "POST":
        formset = AvailabilityFS(request.POST, queryset=qs)
        off_form = TimeOffForm(request.POST)

        ok = formset.is_valid()
        if ok:
            instances = formset.save(commit=False)
            for inst in instances:
                inst.barbeiro = request.user
                if not inst.is_active:
                    inst.lunch_start = None
                    inst.lunch_end = None
                inst.save()

        if off_form.is_valid():
            off = off_form.save(commit=False)
            off.barbeiro = request.user
            if off.start and off.end and off.start < off.end:
                off.save()
                messages.success(request, "Folga registrada.")
            else:
                messages.error(request, "Período de folga inválido.")

        if ok:
            messages.success(request, "Regras salvas.")
            return redirect(f"{request.path}?data={d.isoformat()}")

    else:
        formset = AvailabilityFS(queryset=qs)
        off_form = TimeOffForm()

    rule = qs.filter(weekday=d.weekday()).first()
    slots = _generate_slots(d, rule, TimeOff.objects.filter(barbeiro=request.user))

    ctx = {
        "title": "Minha agenda",
        "formset": formset,
        "off_form": off_form,
        "offs": TimeOff.objects.filter(barbeiro=request.user).order_by("-start")[:20],
        "preview_date": d,
        "preview_weekday": d.weekday(),
        "preview_slots": slots,
    }
    return render(request, "agendamentos/minha_agenda.html", ctx)


# ----------------- Criar Agendamento direto (opcional) -----------------
def agendamento_novo(request, solicitacao_id=None):
    """
    Cria um atendimento (Agendamento) direto.
    - Se 'fim' não vier, calcula por servico.duracao_min (fallback 30).
    - Preenche snapshots (servico_nome/cliente_nome).
    - Valida conflito de horário para o barbeiro.
    - Opcionalmente vincula a uma Solicitação existente (solicitacao_id).
    """
    initial = {}
    if request.user.is_authenticated:
        initial["barbeiro"] = request.user

    if request.method == "POST":
        form = AgendamentoForm(request.POST)
        if form.is_valid():
            ag = form.save(commit=False)

            # Preenche snapshots úteis
            if ag.servico and not ag.servico_nome:
                ag.servico_nome = ag.servico.nome
            if ag.cliente_id and not ag.cliente_nome:
                # Usa nome cadastrado; se vazio, mantém o digitado
                ag.cliente_nome = ag.cliente.nome or ag.cliente_nome

            # Define fim se não veio (servico.duracao_min -> fallback 30 min)
            if ag.inicio and not ag.fim:
                dur = getattr(getattr(ag, "servico", None), "duracao_min", None) or 30
                ag.fim = ag.inicio + timedelta(minutes=int(dur))

            # Barbeiro padrão: usuário logado (se não escolhido)
            if not ag.barbeiro_id and request.user.is_authenticated:
                ag.barbeiro = request.user

            # Checagem de conflito
            if ag.barbeiro_id and Agendamento.existe_conflito(ag.barbeiro, ag.inicio, ag.fim):
                form.add_error(None, "Conflito de horário para este barbeiro.")
            else:
                # Vincula a uma Solicitação (opcional)
                if solicitacao_id and not ag.solicitacao_id:
                    try:
                        from solicitacoes.models import Solicitacao
                        ag.solicitacao = get_object_or_404(Solicitacao, pk=solicitacao_id)
                        # se a solicitação tiver cliente/serviço, você pode espelhar aqui se quiser
                    except Exception:
                        pass

                ag.save()
                messages.success(request, "Atendimento criado com sucesso.")
                # redirecione para sua tela preferida
                return redirect("painel:agenda")  # ou "agendamentos:agenda_dia"
    else:
        form = AgendamentoForm(initial=initial)

    ctx = {
        "title": "Novo atendimento",
        "form": form,
    }
    return render(request, "agendamentos/agendamento_form.html", ctx)
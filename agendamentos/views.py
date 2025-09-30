# agendamentos/views.py

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from calendar import monthrange

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

from agendamentos.forms import (
    BarbeiroAvailabilityForm,
    BarbeiroTimeOffForm,
    AgendamentoForm,           # <- form de agendamento no app correto
)
from agendamentos.models import (
    Agendamento,
    StatusAgendamento,
    BarberAvailability,
    BarbeiroAvailability as Availability,
    BarbeiroTimeOff as TimeOff,
)
from barbearias.models import BarberShop

# ---------------------------------------------------
# Helpers
# ---------------------------------------------------
def _parse_date(s: str, default: date) -> date:
    """Aceita 'YYYY-MM-DD' (campo <input type=date>) e retorna date; fallback = default."""
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


def _generate_slots(d: date, rule: Availability | None, timeoffs_qs):
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


# ---------------------------------------------------
# Redirect principal
# ---------------------------------------------------
def agenda_redirect(request, shop_slug):
    return redirect("agendamentos:agenda_semana", shop_slug=shop_slug)


# ---------------------------------------------------
# AGENDA — DIA
# ---------------------------------------------------
@login_required
def agenda_dia(request, shop_slug):
    """
    Agenda do dia do barbeiro autenticado (apenas AGENDAMENTOS confirmados).
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)

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

    # Agendamentos confirmados (margem 2h antes para pegar cruzamentos que estendem do dia anterior)
    query_start = start - timedelta(hours=2)
    agendamentos = (
        Agendamento.objects.filter(
            shop=shop,
            barbeiro=request.user,
            status=StatusAgendamento.CONFIRMADO,
            inicio__gte=query_start,
            inicio__lt=end,
        )
        .select_related("cliente", "servico")
        .order_by("inicio")
    )

    intervals = [(a.inicio, a.fim, a) for a in agendamentos]

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
            "reason": slot["reason"],
        }

        if overlaps:
            a_start, a_end, ag = overlaps[0]
            if t == a_start:
                row["item"] = {
                    "id": ag.id,
                    "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
                    "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
                    "status": ag.status,
                    "inicio": ag.inicio,
                    "fim": ag.fim,
                }
            else:
                row["occupied"] = True

        rows.append(row)

    prev_day, next_day = _day_nav(d)

    ctx = {
        "title": "Agenda",
        "view": "dia",
        "date": d,
        "prev_day": prev_day,
        "next_day": next_day,
        "rows": rows,
        "shop": shop,
    }
    return render(request, "agendamentos/agenda_dia.html", ctx)


# ---------------------------------------------------
# AGENDA — SEMANA
# ---------------------------------------------------
@login_required
def agenda_semana(request, shop_slug):
    """
    Grade semanal por barbeiro (apenas AGENDAMENTOS confirmados).
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)

    tz = timezone.get_current_timezone()
    hoje = timezone.localdate()
    base = _parse_date(request.GET.get("data", ""), hoje)
    wk_start, wk_end = _week_bounds(base)
    barbeiro = request.user

    # resolve barbeiro alvo
    barbeiro = None
    barbeiro_param = (request.GET.get("barbeiro") or "").strip()
    if barbeiro_param:
        User = get_user_model()
        try:
            barbeiro = User.objects.get(pk=barbeiro_param)
        except Exception:
            barbeiro = None
    elif request.user.is_authenticated:
        barbeiro = request.user

    DEFAULT_START_H, DEFAULT_END_H, DEFAULT_STEP_MIN = 8, 20, 30
    days = [wk_start + timedelta(days=i) for i in range(7)]
    day_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    days_ctx = [{"date": d, "label": day_labels[i]} for i, d in enumerate(days)]

    # janelas/slots por dia
    day_windows_map, day_slots_map = {}, {}
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
    time_keys = sorted(time_keys)

    # agendamentos confirmados
    week_start_dt = timezone.make_aware(datetime(wk_start.year, wk_start.month, wk_start.day, 0, 0, 0), tz)
    query_start = week_start_dt - timedelta(hours=6)
    week_end_dt = week_start_dt + timedelta(days=7)

    qs = (Agendamento.objects
        .filter(
            shop=shop,
            status=StatusAgendamento.CONFIRMADO,
            inicio__lt=week_end_dt,
            inicio__gte=query_start,
        )
        .select_related("cliente", "servico")
        .filter(barbeiro=barbeiro))   # <- aqui é filter
    # filtra por barbeiro, se houver
    if barbeiro:
        qs = qs.filter(barbeiro=barbeiro)
    confirmadas = list(qs.order_by("inicio"))

    # indexa por dia
    day_intervals = {d: [] for d in days}
    for ag in confirmadas:
        s_start, s_end = ag.inicio, ag.fim
        curr = s_start.date()
        last = s_end.date()
        while curr <= last:
            if curr in day_intervals:
                day_intervals[curr].append((s_start, s_end, ag))
            curr += timedelta(days=1)

    # monta linhas
    rows = []
    for (hh, mm) in time_keys:
        time_label = timezone.make_aware(datetime(wk_start.year, wk_start.month, wk_start.day, hh, mm), tz)
        cells = []
        for d in days:
            slot_dt = timezone.make_aware(datetime(d.year, d.month, d.day, hh, mm), tz)
            matches = [(a, b, ag) for (a, b, ag) in day_intervals.get(d, []) if a <= slot_dt < b]
            available, reason = True, None
            if not ((hh, mm) in {(dt.hour, dt.minute) for dt in day_slots_map.get(d, [])}):
                available, reason = False, "folga"

            if matches:
                s_start, s_end, ag = matches[0]
                if slot_dt == s_start:
                    cells.append({"item": {
                        "id": ag.id,
                        "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
                        "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
                        "inicio": s_start,
                        "fim": s_end,
                        "status": ag.status,
                    }, "occupied": False, "time": slot_dt, "available": available, "reason": reason,
                        "conflicts": max(0, len(matches) - 1)})
                else:
                    cells.append({"item": None, "occupied": True, "time": slot_dt,
                                  "available": available, "reason": reason, "conflicts": max(0, len(matches) - 1)})
            else:
                cells.append({"item": None, "occupied": False, "time": slot_dt,
                              "available": available, "reason": reason, "conflicts": 0})
        rows.append({"time": time_label, "cells": cells})

    prev_week, next_week = _week_nav(base)

    ctx = {
        "title": "Agenda — Semana",
        "view": "semana",
        "wk_start": wk_start,
        "wk_end": wk_end,
        "days_ctx": days_ctx,
        "rows": rows,
        "prev_week": prev_week,
        "next_week": next_week,
        "barbeiro": barbeiro,
        "used_custom_rules": used_custom_rules,
        "shop": shop,
    }
    return render(request, "agendamentos/agenda_semana.html", ctx)


# ---------------------------------------------------
# AGENDA — MÊS
# ---------------------------------------------------
def _month_nav(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    prev_last = first - timedelta(days=1)
    prev = prev_last.replace(day=1)
    next_first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return prev, next_first


@login_required
def agenda_mes(request, shop_slug):
    """
    Agenda mensal baseada em AGENDAMENTOS confirmados.
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)

    hoje = timezone.localdate()
    ref_date = _parse_date(request.GET.get("data", ""), hoje).replace(day=1)

    year, month = ref_date.year, ref_date.month
    first_weekday, num_days = monthrange(year, month)

    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime(year, month, 1, 0, 0, 0), tz)
    end_dt = start_dt + timedelta(days=num_days)

    ag_qs = (
        Agendamento.objects.filter(
            shop=shop,
            barbeiro=request.user,
            status=StatusAgendamento.CONFIRMADO,
            inicio__gte=start_dt,
            inicio__lt=end_dt,
        )
        .select_related("cliente", "servico")
        .order_by("inicio")
    )

    tmp = {ref_date + timedelta(days=i): [] for i in range(num_days)}
    for ag in ag_qs:
        d_local = timezone.localtime(ag.inicio, tz).date()
        if d_local not in tmp:
            continue
        tmp[d_local].append({
            "id": ag.id,
            "inicio": ag.inicio,
            "fim": ag.fim,
            "cliente_nome": ag.cliente_nome or (ag.cliente.nome if ag.cliente else "—"),
            "servico_nome": ag.servico_nome or (ag.servico.nome if ag.servico else "—"),
            "status": ag.status,
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
        "shop": shop,
    }
    return render(request, "agendamentos/agenda_mes.html", ctx)


# ---------------------------------------------------
# MINHA AGENDA (configs do barbeiro)
# ---------------------------------------------------
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
                    is_active=(wd < 6),  # desativa domingo
                )
            )
        Availability.objects.bulk_create(defaults)
        qs = Availability.objects.filter(barbeiro=barbeiro).order_by("weekday")

    formset = AvailabilityFormSet(queryset=qs, prefix="rules")
    off_form = BarbeiroTimeOffForm(prefix="off")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        # Salvar REGRAS (formset)
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
                            f"Dia #{idx+1}: " + "; ".join(
                                [f"{k}: {', '.join(v)}" for k, v in f.errors.items()]
                            )
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
                    "; ".join([f"{k}: {', '.join(v)}" for k, v in off_form.errors.items()]) or
                    "Não foi possível salvar a folga. Verifique os campos."
                )

    # Pré-visualização de slots do dia
    dia_str = (request.GET.get("data") or "").strip()
    try:
        preview_date = date.fromisoformat(dia_str) if dia_str else timezone.localdate()
    except Exception:
        preview_date = timezone.localdate()

    rule = Availability.objects.filter(
        barbeiro=barbeiro, weekday=preview_date.weekday()
    ).first()
    preview_slots = rule.gerar_slots(preview_date, barbeiro) if rule else []

    offs = TimeOff.objects.filter(
        barbeiro=barbeiro, end__gte=timezone.now()
    ).order_by("start")[:20]

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


# ---------------------------------------------------
# NOVO AGENDAMENTO (manual, já CONFIRMADO)
# ---------------------------------------------------
@login_required
def agendamento_novo(request, shop_slug, solicitacao_id=None):
    """
    Cria um agendamento **confirmado** (independente de Solicitação).
    Sempre restrito ao barbeiro LOGADO e à barbearia (shop_slug) da URL.
    """
    shop = get_object_or_404(BarberShop, slug=shop_slug)

    # --------- parâmetros GET ----------
    dia_param           = (request.GET.get("dia") or "").strip()
    cliente_id          = (request.GET.get("cliente") or "").strip()
    cliente_nome_param  = (request.GET.get("cliente_nome") or "").strip()
    servico_id          = (request.GET.get("servico") or "").strip()
    want_debug          = (request.GET.get("debug") == "1")

    dia = _parse_date(dia_param, timezone.localdate())

    # Barbeiro SEMPRE o usuário logado
    barbeiro = request.user

    # --------- slots disponíveis ----------
    slots_disponiveis = []
    debug_lines = []
    rule = Availability.objects.filter(barbeiro=barbeiro, weekday=dia.weekday()).first()
    if rule:
        # Apenas slots marcados como available
        slots_disponiveis = [s for s in rule.gerar_slots(dia, barbeiro) if s.get("available")]
        if want_debug:
            offs_count = TimeOff.objects.filter(barbeiro=barbeiro, start__date=dia).count()
            ags_count  = Agendamento.objects.filter(shop=shop, barbeiro=barbeiro, inicio__date=dia).count()
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

    # Horário selecionado (pode vir via GET ao clicar em um slot)
    sel_inicio = request.POST.get("inicio") or request.GET.get("inicio") or ""

    # --------- montar form ----------
    initial = {
        "status": StatusAgendamento.CONFIRMADO,
        "barbeiro": barbeiro.pk,        # força barbeiro do logado
    }
    if sel_inicio:
        initial["inicio"] = sel_inicio  # ajuda a pré-popular no form
    if cliente_id and cliente_id.isdigit():
        initial["cliente"] = int(cliente_id)
    if cliente_nome_param:
        initial["cliente_nome"] = cliente_nome_param
    if servico_id and servico_id.isdigit():
        initial["servico"] = int(servico_id)

    if request.method == "POST":
        form = AgendamentoForm(request.POST, initial=initial)
        if form.is_valid():
            ag = form.save(commit=False)
            ag.shop = shop
            ag.barbeiro = barbeiro                         # força barbeiro do logado
            ag.status = StatusAgendamento.CONFIRMADO       # confirmado por definição

            # snapshots
            if ag.servico and not ag.servico_nome:
                ag.servico_nome = ag.servico.nome
            if ag.cliente_id and not ag.cliente_nome:
                ag.cliente_nome = ag.cliente.nome or ag.cliente_nome

            # garante fim
            if not ag.fim:
                ag.calcular_fim_pelo_servico()

            # conflito (para o barbeiro logado)
            if ag.inicio and ag.fim:
                if Agendamento.existe_conflito(barbeiro, ag.inicio, ag.fim):
                    form.add_error(None, "Conflito de horário para este barbeiro.")

            if not form.errors:
                ag.save()
                messages.success(request, "Atendimento criado com sucesso.")
                return redirect("agendamentos:agenda_dia", shop_slug=shop.slug)
    else:
        form = AgendamentoForm(initial=initial)

    # Aplicar preço sugerido se serviço veio por GET
    if not form.is_bound and servico_id and servico_id.isdigit():
        try:
            servico_sel = form.fields["servico"].queryset.get(pk=int(servico_id))
            form.fields["preco_cobrado"].initial = getattr(servico_sel, "preco", None)
        except Exception:
            pass

    # reconstruir URL ao trocar dados (preserva alguns params úteis)
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

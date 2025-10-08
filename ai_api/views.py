# ai_api/views.py
# -*- coding: utf-8 -*-
"""
Endpoints leves para o agente de IA/n8n consultar a agenda pública.

Resumo
------
- TODOS os endpoints retornam JSON (erros 400/404 também em JSON).
- Barbeiro pode ser identificado por: id numérico, public_slug ou user.username.
- Janela padrão: 09:00–19:00. Grade fixa de 30 em 30 minutos.
- Conflitos/slots consideram SOMENTE 'Agendamento' (não usa 'Solicitacao').

Rotas esperadas em core/urls.py:
    path("api/ai/", include(("ai_api.urls", "ai_api"), namespace="ai_api"))

Exemplo de URLs:
    GET /api/ai/barbeiros/?shop=<shop_slug>
    GET /api/ai/servicos/?shop=<shop_slug>
    GET /api/ai/conflito/?shop=<shop_slug>&barbeiro=<id|slug|username>&inicio=YYYY-MM-DD HH:MM
    GET /api/ai/horarios/?shop=<shop_slug>&barbeiro=<id|slug|username>&date=YYYY-MM-DD
"""

from datetime import datetime, timedelta, time, date

from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET

from barbearias.models import BarberShop, BarberProfile
from servicos.models import Servico
from agendamentos.models import Agendamento, StatusAgendamento


# ======================== Utilidades de TZ ========================

def _tz():
    """Retorna a timezone atual do projeto (compatível com settings.TIME_ZONE)."""
    return timezone.get_current_timezone()

def _aware(dt: datetime) -> datetime:
    """Garante que o datetime seja TZ-aware na timezone do projeto."""
    return timezone.make_aware(dt, _tz()) if timezone.is_naive(dt) else dt


# =================== Resolvedor de barbeiro robusto ===================

def _get_barber(shop: BarberShop, ident: str) -> BarberProfile:
    """
    Resolve um barbeiro ativo da loja por:
      - id numérico
      - public_slug (ex.: 'joao')
      - user.username

    Levanta ObjectDoesNotExist se não encontrar.
    """
    qs = BarberProfile.objects.filter(shop=shop, ativo=True)

    # id numérico
    if ident.isdigit():
        bp = qs.filter(id=int(ident)).first()
        if bp:
            return bp

    # public_slug
    bp = qs.filter(public_slug=ident).first()
    if bp:
        return bp

    # username
    bp = qs.filter(user__username=ident).first()
    if bp:
        return bp

    raise ObjectDoesNotExist(f"Barbeiro '{ident}' não encontrado na loja '{shop.slug}'.")


# ====================== Janela/grade simplificadas ======================

STEP_MIN = 30  # grade fixa: 30/30min
WINDOW_START = time(9, 0)   # abre às 09:00
WINDOW_END   = time(19, 0)  # fecha às 19:00

def _day_window(d: date) -> tuple[datetime, datetime]:
    """
    Constrói a janela [inicio, fim] do dia 'd' na timezone local.
    """
    ini = _aware(datetime.combine(d, WINDOW_START))
    fim = _aware(datetime.combine(d, WINDOW_END))
    return ini, fim

# --- AUX ---
def _is_free(barbeiro: BarberProfile, start_dt: datetime, duration: timedelta = timedelta(minutes=STEP_MIN)) -> bool:
    """
    Retorna True se o intervalo [start_dt, start_dt+duration) estiver livre,
    considerando apenas Agendamentos que **ocupam** agenda (exclui CANCELADO).
    OBS: Agendamento.barbeiro -> ForeignKey(User), então usamos barbeiro.user.
    """
    end_dt = start_dt + duration
    barber_user = barbeiro.user  # <- 👈 ajuste crucial

    qs = Agendamento.objects.filter(
        barbeiro=barber_user,
        inicio__lt=end_dt,
        fim__gt=start_dt,
    )
    if hasattr(StatusAgendamento, "CANCELADO"):
        qs = qs.exclude(status=StatusAgendamento.CANCELADO)
    return not qs.exists()


def _nearest_free_slots(barbeiro: BarberProfile, pivot_dt: datetime, n: int = 3) -> list[str]:
    """
    Retorna até 'n' slots livres de 30 min **próximos** ao 'pivot_dt' (mesmo dia):
      1) Prioriza horários no **futuro** (pivot, +30, +60, ...)
      2) Se faltar, completa com **anteriores** (-30, -60, ...)
    Saída no formato ["HH:MM", ...].
    """
    day_ini, day_fim = _day_window(pivot_dt.date())
    dur = timedelta(minutes=STEP_MIN)

    # Alinha o pivot para a grade de 30min (arredonda para baixo)
    minutes = (pivot_dt.minute // STEP_MIN) * STEP_MIN
    pivot = pivot_dt.replace(minute=minutes, second=0, microsecond=0)

    # Sequência crescente (futuros)
    forward = []
    cur = max(pivot, day_ini)
    while cur + dur <= day_fim:
        forward.append(cur)
        cur += timedelta(minutes=STEP_MIN)

    # Sequência decrescente (anteriores)
    backward = []
    cur = min(pivot, day_fim - dur)
    while cur >= day_ini:
        backward.append(cur)
        cur -= timedelta(minutes=STEP_MIN)

    # Mescla resultados
    out: list[datetime] = []
    for dt in forward:
        if len(out) >= n:
            break
        if _is_free(barbeiro, dt, dur):
            out.append(dt)

    if len(out) < n:
        for dt in backward:
            if len(out) >= n:
                break
            if dt in out:  # evita duplicar pivot
                continue
            if _is_free(barbeiro, dt, dur):
                out.append(dt)

    # Converte para HH:MM no TZ local
    return [timezone.localtime(dt).strftime("%H:%M") for dt in out]


# ====================== 1️⃣ Listar Barbeiros ======================

@require_GET
def listar_barbeiros(request):
    """
    GET /api/ai/barbeiros/?shop=<shop_slug>

    Retorna barbeiros ativos da loja:
    {
      "barbeiros": [
        {"id": 3, "nome": "João Silva", "slug": "joao"},
        ...
      ]
    }
    """
    shop_slug = request.GET.get("shop")
    if not shop_slug:
        return JsonResponse({"error": "Parâmetro 'shop' é obrigatório."}, status=400)

    shop = get_object_or_404(BarberShop, slug=shop_slug)

    qs = BarberProfile.objects.filter(shop=shop, ativo=True).values(
        "id", "public_slug", "user__first_name", "user__last_name"
    )
    data = [
        {
            "id": b["id"],
            "nome": f'{b["user__first_name"]} {b["user__last_name"]}'.strip(),
            "slug": b["public_slug"]
        }
        for b in qs
    ]
    return JsonResponse({"barbeiros": data})


# ====================== 2️⃣ Listar Serviços ======================

@require_GET
def listar_servicos(request):
    """
    GET /api/ai/servicos/?shop=<shop_slug>

    Retorna serviços ativos da loja:
    {
      "servicos": [
        {"id": 5, "nome": "Corte", "preco": "40.00"},
        ...
      ]
    }
    """
    shop_slug = request.GET.get("shop")
    if not shop_slug:
        return JsonResponse({"error": "Parâmetro 'shop' é obrigatório."}, status=400)

    shop = get_object_or_404(BarberShop, slug=shop_slug)

    qs = Servico.objects.filter(shop=shop, ativo=True).values("id", "nome", "preco")
    return JsonResponse({"servicos": list(qs)})


# ============== 3️⃣ Check de slot (conflito simplificado) ==============

@require_GET
def verificar_conflito(request):
    """
    GET /api/ai/conflito/?shop=<slug>&barbeiro=<id|slug|username>&inicio=YYYY-MM-DD HH:MM

    Regras:
    - Janela 09:00–19:00; grade 30/30.
    - Só considera Agendamento (exclui CANCELADO).

    Respostas:
    - Livre:
        {"disponivel": true}
    - Ocupado:
        {"disponivel": false, "sugestoes": ["HH:MM", "HH:MM", "HH:MM"]}
      (até 3 horários próximos no mesmo dia, priorizando futuros)
    """
    shop_slug = request.GET.get("shop")
    barbeiro_ident = request.GET.get("barbeiro")
    inicio_str = request.GET.get("inicio")

    if not all([shop_slug, barbeiro_ident, inicio_str]):
        return JsonResponse(
            {"error": "Parâmetros requeridos: shop, barbeiro, inicio (YYYY-MM-DD HH:MM)."},
            status=400
        )

    shop = get_object_or_404(BarberShop, slug=shop_slug)
    try:
        barbeiro = _get_barber(shop, barbeiro_ident)
    except ObjectDoesNotExist as e:
        return JsonResponse({"error": str(e)}, status=404)

    # Parse do datetime (TZ-aware)
    try:
        start = _aware(datetime.strptime(inicio_str, "%Y-%m-%d %H:%M"))
    except Exception:
        return JsonResponse({"error": "inicio inválido. Use 'YYYY-MM-DD HH:MM'."}, status=400)

    # Fora da janela do dia → não sugerimos nada (mantém pacto simples)
    day_ini, day_fim = _day_window(start.date())
    if not (day_ini <= start < day_fim):
        return JsonResponse({"disponivel": False, "sugestoes": []})

    livre = _is_free(barbeiro, start, timedelta(minutes=STEP_MIN))
    if livre:
        return JsonResponse({"disponivel": True})
    else:
        sugestoes = _nearest_free_slots(barbeiro, start, n=3)
        return JsonResponse({"disponivel": False, "sugestoes": sugestoes})


# ============== 4️⃣ Listar horários do dia (livres) ==============

@require_GET
def listar_horarios(request):
    """
    GET /api/ai/horarios/?shop=<slug>&barbeiro=<id|slug|username>&date=YYYY-MM-DD

    Retorna todos os slots livres do dia (grade 30/30; 09:00–19:00):
    {
      "slots_disponiveis": ["09:00","09:30","10:00", ...]
    }
    - Evita horários no passado quando 'date' for hoje.
    """
    shop_slug = request.GET.get("shop")
    barbeiro_ident = request.GET.get("barbeiro")
    date_str = request.GET.get("date")

    if not all([shop_slug, barbeiro_ident, date_str]):
        return JsonResponse(
            {"error": "Parâmetros requeridos: shop, barbeiro, date (YYYY-MM-DD)."},
            status=400
        )

    shop = get_object_or_404(BarberShop, slug=shop_slug)
    try:
        barbeiro = _get_barber(shop, barbeiro_ident)
    except ObjectDoesNotExist as e:
        return JsonResponse({"error": str(e)}, status=404)

    # Data alvo
    try:
        y, m, d = map(int, date_str.split("-"))
        dia = date(y, m, d)
    except Exception:
        return JsonResponse({"error": "date inválido. Use 'YYYY-MM-DD'."}, status=400)

    day_ini, day_fim = _day_window(dia)
    dur = timedelta(minutes=STEP_MIN)
    step = timedelta(minutes=STEP_MIN)

    slots: list[str] = []
    cur = day_ini
    now = timezone.localtime(timezone.now())
    while cur + dur <= day_fim:
        # evita horários no passado quando 'dia' for hoje
        if (dia == now.date() and cur > now and _is_free(barbeiro, cur, dur)) or \
           (dia != now.date() and _is_free(barbeiro, cur, dur)):
            slots.append(cur.strftime("%H:%M"))
        cur += step

    return JsonResponse({"slots_disponiveis": slots})

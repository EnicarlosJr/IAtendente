# agendamentos/utils.py
from datetime import datetime, timedelta, date, time
from django.utils import timezone
from .models import BarberAvailability, BarberTimeOff
from django.utils import timezone

def _aware(dt_naive, tz):
    return timezone.make_aware(dt_naive, tz)

def work_windows_for_day(barber, d: date):
    """
    Retorna lista de janelas [(start_dt, end_dt, slot_minutes)] que o barbeiro
    trabalha no dia 'd', já em timezone local, ignorando dias inativos.
    """
    tz = timezone.get_current_timezone()
    wd = d.weekday()
    rules = BarberAvailability.objects.filter(barber=barber, weekday=wd, is_active=True)
    out = []
    for r in rules:
        start_dt = _aware(datetime(d.year, d.month, d.day, r.start_time.hour, r.start_time.minute), tz)
        end_dt   = _aware(datetime(d.year, d.month, d.day, r.end_time.hour,   r.end_time.minute), tz)
        if start_dt < end_dt:
            out.append((start_dt, end_dt, r.slot_minutes))
    return out

def split_in_slots(start_dt, end_dt, step_min):
    cur, out = start_dt, []
    step = timedelta(minutes=step_min)
    while cur < end_dt:
        out.append(cur)
        cur += step
    return out

def subtract_timeoffs(barber, slots: list[datetime]):
    """
    Remove slots que caem dentro de folgas/exceções do barbeiro.
    """
    if not slots:
        return slots
    tz = timezone.get_current_timezone()
    start, end = min(slots), max(slots) + timedelta(minutes=1)
    offs = BarberTimeOff.objects.filter(barber=barber, start__lt=end, end__gt=start)
    if not offs.exists():
        return slots
    def covered(dt):
        for o in offs:
            if o.start <= dt < o.end:
                return True
        return False
    return [dt for dt in slots if not covered(dt)]



def montar_intervalos(qs, tz):
    """
    Transforma queryset de agendamentos em lista normalizada [(start, end, ag)] no fuso correto.
    """
    return [
        (timezone.localtime(a.inicio, tz), timezone.localtime(a.fim, tz), a)
        for a in qs.order_by("inicio")
    ]
   

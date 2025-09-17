# agendamentos/forms.py
from django import forms

from .models import BarbeiroAvailability, BarbeiroTimeOff


class TimeInput(forms.TimeInput):
    input_type = "time"
    format = "%H:%M"


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"
    format = "%Y-%m-%dT%H:%M"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", self.format)
        super().__init__(*args, **kwargs)


class BarbeiroAvailabilityForm(forms.ModelForm):
    class Meta:
        model = BarbeiroAvailability
        fields = (
            "weekday",
            "is_active",
            "start_time",
            "end_time",
            "slot_minutes",
            "lunch_start",
            "lunch_end",
        )
        widgets = {
            "weekday":      forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "is_active":    forms.CheckboxInput(attrs={"class": "h-4 w-4"}),
            "start_time":   TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "end_time":     TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "slot_minutes": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
                "min": 5, "step": 5, "placeholder": "ex.: 30"
            }),
            "lunch_start":  TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "lunch_end":    TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
        }
        labels = {
            "weekday": "Dia da semana",
            "is_active": "Trabalha neste dia?",
            "start_time": "Início do expediente",
            "end_time": "Fim do expediente",
            "slot_minutes": "Tamanho do slot (min)",
            "lunch_start": "Almoço: início",
            "lunch_end": "Almoço: fim",
        }

    def clean_slot_minutes(self):
        v = self.cleaned_data.get("slot_minutes")
        if v and v <= 0:
            raise forms.ValidationError("O tamanho do slot deve ser positivo.")
        if v and v % 5 != 0:
            raise forms.ValidationError("Use incrementos de 5 minutos (ex.: 15, 20, 30).")
        return v

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("start_time")
        en = cleaned.get("end_time")
        lunch_st = cleaned.get("lunch_start")
        lunch_en = cleaned.get("lunch_end")
        active = cleaned.get("is_active")

        # expediente
        if active:
            if not st or not en:
                raise forms.ValidationError("Defina início e fim do expediente.")
            if st >= en:
                raise forms.ValidationError("Horário inválido: início deve ser antes do fim.")

        # almoço (opcional)
        if lunch_st or lunch_en:
            if not (lunch_st and lunch_en):
                raise forms.ValidationError("Preencha os dois horários do almoço.")
            if lunch_st >= lunch_en:
                raise forms.ValidationError("Almoço inválido: início deve ser antes do fim.")
            if active and st and en and (lunch_st < st or lunch_en > en):
                raise forms.ValidationError("O almoço deve estar dentro do expediente.")
        return cleaned


class BarbeiroTimeOffForm(forms.ModelForm):
    class Meta:
        model = BarbeiroTimeOff
        fields = ("start", "end", "reason")
        widgets = {
            "start":  DateTimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "end":    DateTimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "reason": forms.TextInput(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
                "placeholder": "Ex.: médico, pessoal, férias..."
            }),
        }
        labels = {"start": "Início", "end": "Fim", "reason": "Motivo (opcional)"}

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("start")
        en = cleaned.get("end")
        if st and en and st >= en:
            raise forms.ValidationError("Período inválido: início deve ser antes do fim.")
        return cleaned


# -------------------------
# Aliases de retrocompatibilidade (opcional)
# Permite continuar importando os nomes antigos sem quebrar nada:
# from agendamentos.forms import BarberAvailabilityForm, BarberTimeOffForm
# -------------------------
BarberAvailabilityForm = BarbeiroAvailabilityForm
BarberTimeOffForm = BarbeiroTimeOffForm

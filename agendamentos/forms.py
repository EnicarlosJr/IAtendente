# agendamentos/forms.py
from datetime import date, datetime, timedelta
from django import forms

from .models import Agendamento, BarbeiroAvailability, BarbeiroTimeOff, StatusAgendamento


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
            "weekday": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "is_active": forms.CheckboxInput(attrs={"class": "h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"}),
            "start_time": TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "placeholder": "08:00"}),
            "end_time": TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "placeholder": "18:00"}),
            "slot_minutes": forms.NumberInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "min": 5, "step": 5, "placeholder": "ex.: 30"}),
            "lunch_start": TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "placeholder": "12:00"}),
            "lunch_end": TimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "placeholder": "13:00"}),
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
        help_texts = {"slot_minutes": "Defina o intervalo de cada atendimento."}


class BarbeiroTimeOffForm(forms.ModelForm):
    class Meta:
        model = BarbeiroTimeOff
        fields = ("start", "end", "reason")
        widgets = {
            "start":  DateTimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "end":    DateTimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "reason": forms.TextInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "placeholder": "Ex.: médico, pessoal, férias..."}),
        }
        labels = {"start": "Início", "end": "Fim", "reason": "Motivo (opcional)"}

    def clean(self):
        cleaned = super().clean()
        st, en = cleaned.get("start"), cleaned.get("end")
        if st and en and st >= en:
            raise forms.ValidationError("Período inválido: início deve ser antes do fim.")
        return cleaned


# Aliases p/ retrocompatibilidade
BarberAvailabilityForm = BarbeiroAvailabilityForm
BarberTimeOffForm = BarbeiroTimeOffForm



class AgendamentoForm(forms.ModelForm):
    class Meta:
        model = Agendamento
        fields = (
            "cliente",
            "cliente_nome",
            "barbeiro",
            "servico",
            "inicio",         # fim NÃO vai para o form
            "preco_cobrado",
            "status",
            "observacoes",
        )
        widgets = {
            "cliente": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "cliente_nome": forms.TextInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "barbeiro": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "servico": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "w-full rounded-xl border px-3 py-2"},
                format="%Y-%m-%dT%H:%M",
            ),
            "preco_cobrado": forms.NumberInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "status": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "observacoes": forms.Textarea(attrs={"class": "w-full rounded-xl border px-3 py-2 min-h-[96px]"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # aceitar formatos do <select>/<input> de horário
        self.fields["inicio"].input_formats = [
            "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"
        ]
        # se o usuário não escolher status, não quero erro — aplico default
        self.fields["status"].required = False
        if not self.fields["status"].initial:
            self.fields["status"].initial = StatusAgendamento.PENDENTE

        # sugestão de preço se já houver instância com serviço
        if self.instance and getattr(self.instance, "servico", None) and not self.instance.preco_cobrado:
            self.fields["preco_cobrado"].initial = self.instance.servico.preco

    def clean(self):
        cleaned = super().clean()
        servico = cleaned.get("servico")
        inicio  = cleaned.get("inicio")

        # snapshots
        cliente = cleaned.get("cliente")
        if cliente and not cleaned.get("cliente_nome"):
            cleaned["cliente_nome"] = cliente.nome
        if servico and not cleaned.get("servico_nome"):
            cleaned["servico_nome"] = servico.nome

        # preço sugerido
        if servico and not cleaned.get("preco_cobrado"):
            cleaned["preco_cobrado"] = servico.preco

        # ⚠️ AQUI O PULO DO GATO:
        # Preenche 'fim' diretamente na INSTÂNCIA para passar na validação do ModelForm
        if servico and inicio and not getattr(self.instance, "fim", None):
            dur = getattr(servico, "duracao_min", 30) or 30
            self.instance.fim = inicio + timedelta(minutes=int(dur))

        # Default para status se não vier do POST
        if not cleaned.get("status"):
            cleaned["status"] = StatusAgendamento.PENDENTE
            self.instance.status = StatusAgendamento.PENDENTE

        return cleaned
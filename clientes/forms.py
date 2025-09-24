from django import forms
from django.forms import inlineformset_factory
from .models import Cliente, HistoricoItem
import re

def _norm_tel(s: str) -> str:
    if not s:
        return ""
    # pega só dígitos; se tiver 11 dígitos, formata (31) 98888-7777
    digits = re.sub(r"\D+", "", s)
    return digits


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = [
            "nome", "telefone", "recorrencia_status", "barbeiro_preferido",
            "preferencias", "ultimo_corte", "foto_url", "tags",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={
                "class": "c-input",
                "placeholder": "Ex.: Caio Henrique",
                "autocomplete": "name",
            }),
            "telefone": forms.TextInput(attrs={
                "class": "c-input",
                "inputmode": "tel",
                "autocomplete": "tel",
                "placeholder": "(11) 98888-7777",
            }),
            "recorrencia_status": forms.Select(attrs={
                "class": "c-select",
            }),
            "barbeiro_preferido": forms.TextInput(attrs={
                "class": "c-input",
                "placeholder": "Opcional",
            }),
            "preferencias": forms.Textarea(attrs={
                "class": "c-textarea",
                "placeholder": "Ex.: Degradê #1, acabamento navalha, sem pós com álcool…",
                "rows": 5,
            }),
            "ultimo_corte": forms.DateTimeInput(attrs={
                "class": "c-input",
                "type": "datetime-local",
            }),
            "foto_url": forms.URLInput(attrs={
                "class": "c-input",
                "placeholder": "https://…",
            }),
            # O JSON será controlado pela UI; mantemos oculto.
            "tags": forms.HiddenInput(),
        }


class HistoricoItemForm(forms.ModelForm):
    class Meta:
        model = HistoricoItem
        fields = ["data", "servico", "valor", "faltou"]

HistoricoFormSet = inlineformset_factory(
    Cliente, HistoricoItem, form=HistoricoItemForm,
    fields=["data", "servico", "valor", "faltou"], extra=0, can_delete=True
)

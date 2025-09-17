# servicos/forms.py
from django import forms

from agendamentos.models import Agendamento
from .models import Servico

class ServicoForm(forms.ModelForm):
    class Meta:
        model = Servico
        fields = ["nome", "categoria", "duracao_min", "preco", "descricao", "ativo"]
        labels = {
            "nome": "Nome do serviço",
            "categoria": "Categoria",
            "duracao_min": "Duração (min)",
            "preco": "Preço (R$)",
            "descricao": "Descrição (opcional)",
            "ativo": "Ativo",
        }
        help_texts = {
            "duracao_min": "Em minutos (ex.: 30, 45, 60).",
            "preco": "Valor cobrado em reais. Pode editar quando quiser.",
        }
        widgets = {
            "nome": forms.TextInput(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
                "placeholder": "Ex.: Corte masculino",
                "maxlength": 120,
            }),
            "categoria": forms.Select(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
            }),
            "duracao_min": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
                "min": 5, "max": 480, "step": 5, "inputmode": "numeric",
                "placeholder": "Ex.: 40",
            }),
            "preco": forms.NumberInput(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
                "min": 0, "step": "0.01", "inputmode": "decimal",
                "placeholder": "Ex.: 45,00",
            }),
            "descricao": forms.Textarea(attrs={
                "class": "w-full rounded-xl border px-3 py-2",
                "rows": 3, "placeholder": "Detalhes, observações, versões do serviço…",
            }),
            "ativo": forms.CheckboxInput(attrs={
                "class": "h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500",
            }),
        }

    # validações leves de UX
    def clean_duracao_min(self):
        v = self.cleaned_data.get("duracao_min") or 0
        if v <= 0:
            raise forms.ValidationError("A duração deve ser maior que 0.")
        if v > 480:
            raise forms.ValidationError("Duração máxima permitida é 480 minutos.")
        return v

    def clean_preco(self):
        v = self.cleaned_data.get("preco")
        if v is None:
            return v
        if v < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return v

class AgendamentoForm(forms.ModelForm):
    class Meta:
        model = Agendamento
        fields = (
            "cliente",
            "cliente_nome",
            "barbeiro",
            "servico",
            "preco_cobrado",
            "inicio",
            "fim",
            "status",
            "observacoes",
        )
        widgets = {
            "cliente": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "cliente_nome": forms.TextInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "placeholder": "Nome para o recibo/etiqueta"}),
            "barbeiro": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "servico": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "preco_cobrado": forms.NumberInput(attrs={"class": "w-full rounded-xl border px-3 py-2", "step": "0.01", "min": "0"}),
            "inicio": forms.DateTimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "fim": forms.DateTimeInput(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "status": forms.Select(attrs={"class": "w-full rounded-xl border px-3 py-2"}),
            "observacoes": forms.Textarea(attrs={"class": "w-full rounded-xl border px-3 py-2", "rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        inicio = cleaned.get("inicio")
        fim = cleaned.get("fim")
        servico = cleaned.get("servico")
        barbeiro = cleaned.get("barbeiro")

        # fim poderá ser calculado na view; aqui apenas valida se vier
        if inicio and fim and fim <= inicio:
            raise forms.ValidationError("O horário de fim deve ser depois do início.")

        # valida conflito básico (se ambos vierem)
        if barbeiro and inicio and fim:
            from .models import Agendamento
            if Agendamento.existe_conflito(barbeiro, inicio, fim):
                raise forms.ValidationError("Há conflito de horário para este barbeiro.")

        return cleaned

from __future__ import annotations
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from django import forms

from agendamentos.models import Agendamento
from .models import Servico
from barbearias.models import BarberShop


class ServicoForm(forms.ModelForm):
    """
    Form estilizado (Tailwind) + UX:
      - valida unicidade de 'nome' dentro da barbearia
      - choices de 'categoria' dinâmicos (usa Servico.CATEGORIAS se existir; senão, infere do banco da loja)
      - acessibilidade (autofocus, aria-describedby, placeholders)
      - parsing de preço com vírgula
      - realce visual de erros (borda/outline) sem filtros customizados
    """

    def __init__(self, *args, shop: Optional[BarberShop] = None, **kwargs):
        self.shop: Optional[BarberShop] = shop
        super().__init__(*args, **kwargs)

        # ---------- Categoria dinâmica ----------
        cat_choices: Optional[Iterable] = getattr(Servico, "CATEGORIAS", None)
        if cat_choices is None and self.shop is not None:
            usadas = (
                Servico.objects.filter(shop=self.shop)
                .exclude(categoria__isnull=True)
                .exclude(categoria__exact="")
                .order_by().values_list("categoria", flat=True).distinct()
            )
            cat_choices = [("", "— Selecione —")] + [(c, c) for c in usadas]
        elif cat_choices is not None:
            cat_choices = [("", "— Selecione —")] + list(cat_choices)
        if cat_choices is not None:
            self.fields["categoria"].choices = cat_choices

        # ---------- Acessibilidade / UX ----------
        self.fields["nome"].widget.attrs.update({
            "autofocus": "autofocus",
            "autocomplete": "off",
            "aria-describedby": "nome-help",
            "maxlength": "120",
            "placeholder": "Ex.: Corte masculino",
        })
        self.fields["categoria"].widget.attrs.update({"aria-describedby": "categoria-help"})
        self.fields["duracao_min"].widget.attrs.update({
            "aria-describedby": "duracao_min-help",
            "min": "5", "max": "480", "step": "5", "inputmode": "numeric",
            "placeholder": "Ex.: 40",
        })
        self.fields["preco"].widget.attrs.update({
            "aria-describedby": "preco-help",
            "min": "0", "step": "0.01", "inputmode": "decimal",
            "placeholder": "Ex.: 45,00",
        })
        self.fields["descricao"].widget.attrs.update({
            "aria-describedby": "descricao-help",
            "rows": "3",
            "placeholder": "Detalhes do serviço…",
        })

        # Valor default prático na criação
        if self.instance.pk is None and "ativo" in self.fields:
            self.fields["ativo"].initial = True

        # ---------- Estilo base + realce de erro ----------
        base_input = "w-full rounded-xl border px-3 py-2"
        base_check = "h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        error_ring = "border-rose-300 focus:border-rose-400 focus:ring-rose-300"

        styled = {
            "nome": base_input,
            "categoria": base_input,
            "duracao_min": base_input,
            "preco": base_input,
            "descricao": base_input,
            "ativo": base_check,
        }
        # aplica estilo base
        for name, klass in styled.items():
            if name in self.fields:
                cur = self.fields[name].widget.attrs.get("class", "")
                self.fields[name].widget.attrs["class"] = f"{cur} {klass}".strip()

        # se bound e com erros, realça
        if self.is_bound and self.errors:
            for name in self.fields:
                if name in self.errors:
                    cur = self.fields[name].widget.attrs.get("class", "")
                    self.fields[name].widget.attrs["class"] = f"{cur} {error_ring}".strip()

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
        # Widgets já prontos para receber as classes no __init__
        widgets = {
            "nome": forms.TextInput(),
            "categoria": forms.Select(),
            "duracao_min": forms.NumberInput(),
            "preco": forms.NumberInput(),
            "descricao": forms.Textarea(),
            "ativo": forms.CheckboxInput(),
        }

    # ======= Validações =======
    def clean_nome(self):
        nome = (self.cleaned_data.get("nome") or "").strip()
        if not nome:
            raise forms.ValidationError("Informe o nome do serviço.")
        if self.shop:
            qs = Servico.objects.filter(shop=self.shop, nome__iexact=nome)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Já existe um serviço com esse nome nesta barbearia.")
        return nome

    def clean_duracao_min(self):
        v = self.cleaned_data.get("duracao_min") or 0
        if v <= 0:
            raise forms.ValidationError("A duração deve ser maior que 0.")
        if v > 480:
            raise forms.ValidationError("Duração máxima permitida é 480 minutos.")
        return v

    def clean_preco(self):
        v = self.cleaned_data.get("preco")
        if isinstance(v, str):
            txt = v.strip().replace(",", ".")
            if not txt:
                return None
            try:
                v = Decimal(txt)
            except InvalidOperation:
                raise forms.ValidationError("Preço inválido.")
        if v is not None and v < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return v

    def clean_categoria(self):
        cat = self.cleaned_data.get("categoria")
        if isinstance(cat, str):
            cat = cat.strip()
        return cat

    # ======= Save com shop =======
    def save(self, commit=True, shop: Optional[BarberShop] = None):
        obj: Servico = super().save(commit=False)
        if shop is not None:
            obj.shop = shop
        elif self.shop is not None:
            obj.shop = self.shop
        if commit:
            obj.save()
        return obj




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

from django import forms


class PublicRequestForm(forms.Form):
    """
    Form público simples para montar a solicitação no front (o POST real vai para seu intake).
    Se preferir choices dinâmicas, você pode injetar no __init__.
    """
    nome = forms.CharField(label="Nome", max_length=120, required=False)
    telefone = forms.CharField(label="Telefone", max_length=32)
    servico_id = forms.CharField(label="Serviço", max_length=32)
    inicio = forms.CharField(label="Início (YYYY-MM-DDTHH:MM)", max_length=32, required=False)
    observacoes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_telefone(self):
        tel = (self.cleaned_data.get("telefone") or "").strip()
        if not tel:
            raise forms.ValidationError("Informe um telefone.")
        return tel

    def clean_servico_id(self):
        s = (self.cleaned_data.get("servico_id") or "").strip()
        # Se quiser, valide como inteiro:
        # if not s.isdigit(): raise forms.ValidationError("Serviço inválido.")
        return s
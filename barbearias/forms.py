# barbearias/forms.py
from __future__ import annotations
from django import forms
from .models import Membership, MembershipRole

# -------------------------
# Admin (gestão de membros)
# -------------------------
class InviteMemberForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    role = forms.ChoiceField(choices=MembershipRole.choices, label="Papel")
    name = forms.CharField(label="Nome (opcional)", required=False, max_length=150)

    def __init__(self, *args, **kwargs):
        # contexto opcional (usado nas views_admin)
        self.acting_user = kwargs.pop("acting_user", None)
        self.shop = kwargs.pop("shop", None)
        super().__init__(*args, **kwargs)

class UpdateMemberForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ["role", "is_active"]
        widgets = {
            "role": forms.Select(choices=MembershipRole.choices),
        }
        labels = {
            "role": "Papel",
            "is_active": "Ativo",
        }

    def __init__(self, *args, **kwargs):
        self.acting_user = kwargs.pop("acting_user", None)
        self.shop = kwargs.pop("shop", None)
        super().__init__(*args, **kwargs)

# -------------------------
# Fluxos gerais do app
# -------------------------
class ShopSignupForm(forms.Form):
    shop_name = forms.CharField(
        label="Nome da barbearia",
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Barbearia do João"}),
    )

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
class AddMemberForm(forms.Form):
    name = forms.CharField(label="Nome", max_length=150, required=False)
    email = forms.EmailField(label="E-mail", required=True)
    role = forms.ChoiceField(choices=MembershipRole.choices, label="Papel", required=True)
    password = forms.CharField(
        label="Senha (opcional, apenas p/ novo usuário)",
        widget=forms.PasswordInput,
        required=False,
        min_length=6,
    )

    def __init__(self, *args, acting_user=None, shop=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Se quiser, dá pra restringir choices aqui conforme o acting_user
        # Ex.: MANAGER não consegue criar OWNER — descomente se precisar:
        # if acting_user_role == MembershipRole.MANAGER:
        #     self.fields["role"].choices = [(r, l) for r,l in self.fields["role"].choices if r != "OWNER"]

    def clean_email(self):
        return (self.cleaned_data["email"] or "").strip().lower()

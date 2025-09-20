from django import forms
from .models import Membership, MembershipRole

class InviteMemberForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    role = forms.ChoiceField(choices=MembershipRole.choices, label="Papel")

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
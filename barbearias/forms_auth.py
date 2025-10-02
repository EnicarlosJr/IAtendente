# barbearias/forms_auth.py
from django.contrib.auth.forms import AuthenticationForm

class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        base = "w-full rounded border px-3 py-2"
        self.fields["username"].widget.attrs.update({
            "class": base,
            "placeholder": "Usuário ou e-mail",
            "autocomplete": "username",
        })
        self.fields["password"].widget.attrs.update({
            "class": base,
            "placeholder": "Senha",
            "autocomplete": "current-password",
        })

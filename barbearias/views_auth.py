# barbearias/views_auth.py
from django.contrib.auth import login, logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.views.generic import FormView
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView

from barbearias.forms_auth import LoginForm

from .models import Membership
from .utils import get_default_shop_for





class LoginView(FormView):
    template_name = "barbearias/login.html"
    form_class = LoginForm

    def get_success_url(self):
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return next_url
        return reverse("painel:dashboard")

    def form_valid(self, form):
        user = form.get_user()
        login(self.request, user)
        # define barbearia “ativa” na sessão
        sid = get_default_shop_for(user)
        if not sid:
            # Se não houver, tenta a primeira membership ativa
            mem = Membership.objects.filter(user=user, is_active=True).select_related("shop").first()
            sid = mem.shop_id if mem else None
        if sid:
            self.request.session["shop_id"] = sid
        else:
            # sem shop: painel ainda abre, mas pode pedir para criar/entrar numa barbearia
            messages.info(self.request, "Associe-se a uma barbearia para continuar.")
        return redirect(self.get_success_url())

def logout_view(request):
    if request.method == "POST":
        logout(request)
        messages.success(request, "Você saiu da sua conta.")
        return redirect("barb_auth:login")
    # GET opcional: página de confirmação
    return render(request, "barbearias/logout_confirm.html", {})

class PasswordChangeView_(PasswordChangeView):
    template_name = "barbearias/password_change_form.html"
    success_url = reverse_lazy("barb_auth:password_change_done")

class PasswordChangeDoneView_(PasswordChangeDoneView):
    template_name = "barbearias/password_change_done.html"
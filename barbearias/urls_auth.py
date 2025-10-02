# barbearias/urls_auth.py
from django.urls import path
from . import views_auth as views

urlpatterns = [
    path("login/",  views.LoginView.as_view(),  name="login"),
    path("logout/", views.logout_view,          name="logout"),

    # Troca de senha (próprias do app)
    path("senha/trocar/", views.PasswordChangeView_.as_view(), name="password_change"),
    path("senha/ok/",     views.PasswordChangeDoneView_.as_view(), name="password_change_done"),
]

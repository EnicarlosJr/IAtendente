# barbearias/urls_public.py
from django.urls import path
from . import views_public, views

app_name = "public"

urlpatterns = [
    # Página pública da barbearia para intake
    # /pub/<shop_slug>/
    path("<slug:shop_slug>/", views_public.intake_shop, name="intake_shop"),

    # Página pública de um barbeiro específico da barbearia
    # /pub/<shop_slug>/<barber_slug>/
    path("<slug:shop_slug>/<slug:barber_slug>/", views_public.intake_barber, name="intake_barber"),

    # (Opcional) Página pública por username do barbeiro (sem shop_slug)
    # /pub/barbeiro/<username>/
    path("barbeiro/<str:barber_username>/", views.public_booking, name="public_booking"),
]

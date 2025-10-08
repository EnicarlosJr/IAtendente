from django.urls import path
from . import views_public
from .views_public_slots import public_slots

app_name = "public"

urlpatterns = [
    # Disponibilidade (JSON)
    path("<slug:shop_slug>/slots/", public_slots, name="slots"),
    path("<slug:shop_slug>/<slug:barber_slug>/slots/", public_slots, name="slots_barber"),
    
    # Páginas públicas (sem login)
    path("<slug:shop_slug>/", views_public.intake_shop, name="intake_shop"),
    path("<slug:shop_slug>/<slug:barber_slug>/", views_public.intake_barber, name="intake_barber"),

]

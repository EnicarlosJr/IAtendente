from django.urls import path
from . import views_public  # suas views públicas existentes
from . import views_admin   # novo arquivo acima

app_name = "barbearias"

urlpatterns = [
    # PÚBLICO (que você já tinha/tem)
    path("<slug:shop_slug>/", views_public.intake_shop, name="intake_shop"),
    path("<slug:shop_slug>/<slug:barber_slug>/", views_public.intake_barber, name="intake_barber"),

    # ADMIN (gestão de usuários/membros)
    path("admin/usuarios/", views_admin.usuarios, name="usuarios"),
    path("admin/usuarios/convidar/", views_admin.usuarios_convidar, name="usuarios_convidar"),
    path("admin/usuarios/<int:mem_id>/atualizar/", views_admin.usuarios_atualizar, name="usuarios_atualizar"),
    path("admin/usuarios/<int:mem_id>/remover/", views_admin.usuarios_remover, name="usuarios_remover"),
]

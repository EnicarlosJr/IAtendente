# barbearias/urls.py
from django.urls import path
from . import views, views_admin, views_public_slots  # certifique-se que esses módulos existem

app_name = "barbearias"

urlpatterns = [
    # Gestão de usuários (OWNER/MANAGER)
    path("<slug:shop_slug>/usuarios/", views_admin.usuarios, name="usuarios"),
    path("<slug:shop_slug>/usuarios/<int:mem_id>/atualizar/", views_admin.usuarios_atualizar, name="usuarios_atualizar"),
    path("<slug:shop_slug>/usuarios/<int:mem_id>/remover/", views_admin.usuarios_remover, name="usuarios_remover"),
    path("<slug:shop_slug>/usuarios/adicionar/", views_admin.usuarios_adicionar, name="usuarios_adicionar"),

    # Fluxo de pessoas (OWNER/MANAGER)
    path("<slug:shop_slug>/fluxo/", views_admin.fluxo, name="fluxo"),

]

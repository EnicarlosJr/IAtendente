from django.urls import path
from . import views

urlpatterns = [
    path("barbeiros/", views.listar_barbeiros, name="listar_barbeiros"),
    path("servicos/", views.listar_servicos, name="listar_servicos"),
    path("conflito/", views.verificar_conflito, name="verificar_conflito"),
    path("horarios/", views.listar_horarios, name="listar_horarios"),
]

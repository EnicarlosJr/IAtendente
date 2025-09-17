# servicos/api_urls.py
from django.urls import path
from . import api  # suas views DRF/CBV

app_name = "api_servicos"

urlpatterns = [
    path("", api.ServicoListCreate.as_view(), name="list_create"),
    path("<int:pk>/", api.ServicoRetrieveUpdateDestroy.as_view(), name="retrieve_update_destroy"),
]

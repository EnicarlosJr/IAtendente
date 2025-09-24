from django.shortcuts import get_object_or_404
from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
import barbearias
from .models import BarberShop

# barbearias/middleware.py
from django.utils.deprecation import MiddlewareMixin
from django.urls import resolve
from barbearias.models import BarberShop  # <- importa o MODEL certo

class ShopSlugMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # valor padrão útil para templates / logs
        request.shop = None
        request.shop_slug = None

        try:
            match = resolve(request.path_info)
        except Exception:
            return  # rota ainda não resolvida

        shop_slug = match.kwargs.get("shop_slug")
        request.shop_slug = shop_slug

        if not shop_slug:
            return

        try:
            request.shop = BarberShop.objects.get(slug=shop_slug)
        except BarberShop.DoesNotExist:
            request.shop = None

class BarberShopMiddleware:
    """
    Middleware para disponibilizar o `shop_slug` no request 
    e em contextos sem precisar quebrar se não tiver barbearia.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Só garante que existe a propriedade
        if not hasattr(request, "shop"):
            request.shop = None
        return self.get_response(request)

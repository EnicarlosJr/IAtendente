from django.contrib import admin
from .models import BarberShop, BarberProfile, Membership, MembershipRole


@admin.register(BarberShop)
class BarberShopAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "owner", "created_at")
    search_fields = ("nome", "telefone", "owner__username", "owner__email")
    prepopulated_fields = {"slug": ("nome",)}
    ordering = ("nome",)


@admin.register(BarberProfile)
class BarberProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "shop", "public_slug", "ativo", "criado_em")
    list_filter = ("ativo", "shop")
    search_fields = ("user__username", "user__email", "shop__nome")
    ordering = ("shop", "user__username")
    prepopulated_fields = {"public_slug": ("user",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "shop", "role", "is_active")
    list_filter = ("role", "is_active", "shop")
    search_fields = ("user__username", "user__email", "shop__nome")
    ordering = ("shop", "user__username")
    autocomplete_fields = ("user", "shop")

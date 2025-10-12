from django.contrib import admin
from .models import BarberShop, BarberProfile, Membership, MembershipRole


# admin.py
from django.contrib import admin
from django import forms
from .models import BarberShop

class BarberShopAdminForm(forms.ModelForm):
    class Meta:
        model = BarberShop
        fields = "__all__"
        widgets = {
            "api_key": forms.PasswordInput(render_value=True),  
        }

@admin.register(BarberShop)
class BarberShopAdmin(admin.ModelAdmin):
    form = BarberShopAdminForm
    list_display = ("nome", "slug", "instance", "owner")
    search_fields = ("nome", "slug", "instance", "owner__username")
    list_filter = ("timezone",)
    readonly_fields = ()


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

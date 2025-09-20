from django.conf import settings
from django.db import models
from django.utils.text import slugify


class BarberShop(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_shops",
    )
    nome = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    telefone = models.CharField(max_length=32, blank=True)
    timezone = models.CharField(max_length=64, default="America/Sao_Paulo")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)


class BarberProfile(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="barber_profiles",
    )
    shop = models.ForeignKey(
        BarberShop,
        on_delete=models.CASCADE,
        related_name="barbers",
    )
    public_slug = models.SlugField(max_length=140)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("shop", "public_slug")]
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user} @ {self.shop}"


class MembershipRole(models.TextChoices):
    OWNER = "OWNER", "Dono"
    MANAGER = "MANAGER", "Gerente"
    BARBER = "BARBER", "Barbeiro"


class Membership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    shop = models.ForeignKey(
        BarberShop,
        on_delete=models.CASCADE,
        related_name="members",
    )
    role = models.CharField(
        max_length=16,
        choices=MembershipRole.choices,
        default=MembershipRole.BARBER,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "shop")]

    def __str__(self):
        return f"{self.user} @ {self.shop} ({self.role})"

# servicos/migrations/0002_seed_iniciais.py
from django.db import migrations
from decimal import Decimal

def seed(apps, schema_editor):
    Servico = apps.get_model("servicos", "Servico")
    base = [
        ("Corte masculino",            "corte",  30, Decimal("45.00")),
        ("Corte degradê (fade)",       "corte",  30, Decimal("55.00")),
        ("Barba tradicional",          "barba",  30, Decimal("35.00")),
        ("Barba navalhada",            "barba",  30, Decimal("45.00")),
        ("Combo: corte + barba",       "combo",  30, Decimal("85.00")),
        ("Corte infantil",             "corte",  30, Decimal("40.00")),
        ("Sobrancelha (navalha)",      "add_on", 30, Decimal("20.00")),
        ("Hidratação capilar",         "add_on", 30, Decimal("35.00")),
        ("Pigmentação barba/cabelo",   "add_on", 30, Decimal("60.00")),
        ("Risco / freestyle",          "add_on", 30, Decimal("15.00")),
        ("Camuflagem dos fios",        "quimica",30, Decimal("90.00")),
        ("Platinado (básico)",         "quimica",30, Decimal("180.00")),
    ]
    for nome, cat, dur, preco in base:
        Servico.objects.update_or_create(
            nome=nome,
            defaults={"categoria": cat, "duracao_min": dur, "preco": preco, "ativo": True},
        )

def unseed(apps, schema_editor):
    Servico = apps.get_model("servicos", "Servico")
    nomes = [
        "Corte masculino", "Corte degradê (fade)", "Barba tradicional", "Barba navalhada",
        "Combo: corte + barba", "Corte infantil", "Sobrancelha (navalha)", "Hidratação capilar",
        "Pigmentação barba/cabelo", "Risco / freestyle", "Camuflagem dos fios", "Platinado (básico)",
    ]
    Servico.objects.filter(nome__in=nomes).delete()

class Migration(migrations.Migration):
    dependencies = [
        ("servicos", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]

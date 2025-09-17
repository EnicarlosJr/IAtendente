# solicitacoes/management/commands/finalize_solicitacoes.py
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from solicitacoes.models import Solicitacao, SolicitacaoStatus
from django.db import transaction

class Command(BaseCommand):
    help = "Finaliza automaticamente solicitações confirmadas cujo horário já acabou."

    def add_arguments(self, parser):
        parser.add_argument("--grace-min", type=int, default=5,
                            help="Minutos de tolerância após o fim para finalizar (default: 5).")

    @transaction.atomic
    def handle(self, *args, **opts):
        from solicitacoes.views_web import _calc_fim, _criar_historico  # reutiliza helpers

        now = timezone.now()
        grace = timedelta(minutes=opts["grace_min"])

        qs = Solicitacao.objects.filter(status=SolicitacaoStatus.CONFIRMADA, inicio__isnull=False)
        total = 0
        for s in qs:
            fim = s.fim or _calc_fim(s)
            if fim and (fim + grace) <= now:
                s.fim = fim
                s.status = SolicitacaoStatus.REALIZADA
                s.save(update_fields=["fim", "status"])
                _criar_historico(s, faltou=False)
                total += 1

        self.stdout.write(self.style.SUCCESS(f"Finalizadas automaticamente: {total}"))

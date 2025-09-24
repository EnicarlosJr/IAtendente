# solicitacoes/signals.py
from __future__ import annotations

import logging
import traceback
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Solicitacao, SolicitacaoStatus

log = logging.getLogger(__name__)

# --- util: request atual via threadlocal (ver middleware embaixo) ---
try:
    from core.request_local import get_current_request
except Exception:
    def get_current_request():
        return None


@receiver(pre_save, sender=Solicitacao)
def solicitacao_pre_save(sender, instance: Solicitacao, **kwargs):
    """
    Regras do Plano B:
    - Na criação: força status = PENDENTE.
    - Nunca cria Agendamento via signal.
    - Normaliza 'fim' quando houver 'inicio' sem 'fim'.
    - Loga transições suspeitas (p/ diagnóstico).
    """
    old = None
    if instance.pk:
        try:
            old = sender.objects.only("status", "inicio", "fim").get(pk=instance.pk)
        except sender.DoesNotExist:
            old = None

    # 1) Força PENDENTE na criação
    if instance._state.adding and instance.status != SolicitacaoStatus.PENDENTE:
        log.warning(
            "[signals][pre_save] Forçando PENDENTE na criação (recebido=%s, id_externo=%s)",
            instance.status, instance.id_externo
        )
        instance.status = SolicitacaoStatus.PENDENTE

    # 2) Se veio início e não veio fim, calcula fim (não mexe em status)
    if instance.inicio and not instance.fim:
        try:
            minutos = instance.duracao_minutos()
        except Exception:
            minutos = 30
        instance.fim = instance.inicio + timezone.timedelta(minutes=int(minutos))

    # 3) DETECTORES de transição de status (somente log)
    old_status = getattr(old, "status", None)
    new_status = instance.status

    # qualquer transição é logada em nível INFO
    if old_status != new_status:
        req = get_current_request()
        user = getattr(getattr(req, "user", None), "username", None) if req else None
        path = getattr(req, "path", None) if req else None
        method = getattr(req, "method", None) if req else None
        log.info(
            "[signals][pre_save] Status mudando id=%s %s -> %s por %s via %s %s",
            instance.pk, old_status, new_status, user, method, path
        )

    # transições “suspeitas” (para CONFIRMADA ou REALIZADA) ganham stack trace
    if new_status in (SolicitacaoStatus.CONFIRMADA, SolicitacaoStatus.REALIZADA) and old_status != new_status:
        req = get_current_request()
        user = getattr(getattr(req, "user", None), "username", None) if req else None
        path = getattr(req, "path", None) if req else None
        method = getattr(req, "method", None) if req else None
        log.error(
            "[DETECTOR][pre_save] Transição SUSPEITA (%s) id=%s old=%s -> new=%s "
            "inicio=%s fim=%s by_user=%s via %s %s\nStack:\n%s",
            new_status, instance.pk, old_status, new_status,
            instance.inicio, instance.fim, user, method, path,
            "".join(traceback.format_stack(limit=20)),
        )


@receiver(post_save, sender=Solicitacao)
def solicitacao_post_save(sender, instance: Solicitacao, created: bool, **kwargs):
    """
    Apenas logging/normalização leve. NÃO cria agendamento aqui.
    """
    if created:
        log.info(
            "[signals][post_save] Criada Solicitação id=%s status=%s inicio=%s shop=%s",
            instance.pk, instance.status, instance.inicio, getattr(instance.shop, "slug", None)
        )
        return

    # Loga o estado após salvar (útil para rastrear quem mexeu “por fora”)
    log.debug(
        "[signals][post_save] Persistida Solicitação id=%s status=%s inicio=%s fim=%s",
        instance.pk, instance.status, instance.inicio, instance.fim
    )

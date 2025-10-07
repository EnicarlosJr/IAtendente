# webhooks.py (ou onde você já mantém o de confirmação)
import logging
import requests
from typing import Optional, Mapping
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from solicitacoes.models import Solicitacao

logger = logging.getLogger(__name__)

def _disparar_webhook_evento(
    s: "Solicitacao",
    *,
    evento: str,
    ok: bool,
    mensagem: str,
    extra: Optional[Mapping[str, object]] = None,
    fallback_setting: str = "OUTBOUND_CONFIRMATION_WEBHOOK",
):
    """
    Dispara um webhook genérico após commit de transação.
    Usa s.callback_url se existir; senão, OUTBOUND_CONFIRMATION_WEBHOOK.
    """
    callback_url = s.callback_url or getattr(settings, fallback_setting, None)
    if not callback_url:
        logger.info("[Solicitacao] %s sem callback_url (sol=%s)", evento.upper(), s.pk)
        return

    telefone = s.telefone or getattr(getattr(s, "cliente", None), "telefone", None)

    payload = {
        "evento": evento,
        "ok": ok,
        "timestamp": timezone.now().isoformat(),
        "solicitacao_id": s.pk,
        "id_externo": getattr(s, "id_externo", None),
        "status": getattr(s, "status", None),
        "inicio": s.inicio.isoformat() if getattr(s, "inicio", None) else None,
        "fim": s.fim.isoformat() if getattr(s, "fim", None) else None,
        "servico": getattr(s, "servico_label", None),
        "telefone": telefone,
        "nome": s.nome or getattr(getattr(s, "cliente", None), "nome", None),
        "mensagem": mensagem,
    }
    if extra:
        payload.update(extra)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Token": getattr(settings, "OUTBOUND_WEBHOOK_TOKEN", ""),
    }

    def _send(url, body, hdrs):
        try:
            resp = requests.post(url, json=body, headers=hdrs, timeout=8)
            resp.raise_for_status()
            logger.info("[Solicitacao] webhook %s OK (sol=%s)", evento, s.pk)
        except Exception as e:
            logger.exception("[Solicitacao] webhook %s falhou (sol=%s): %s", evento, s.pk, e)

    transaction.on_commit(lambda: _send(callback_url, payload, headers))

def _disparar_webhook_confirmacao(s: "Solicitacao"):
    """
    Wrapper para quando a solicitação é CONFIRMADA.
    """
    _disparar_webhook_evento(
        s,
        evento="solicitacao_confirmada",
        ok=True,
        mensagem="Sua solicitação foi confirmada.",
    )

def _disparar_webhook_negacao(
    s: "Solicitacao",
    motivo: str | None = None,
    observacao: str | None = None,
):
    """
    Wrapper para quando a solicitação é NEGADA.
    """
    _disparar_webhook_evento(
        s,
        evento="solicitacao_negada",
        ok=False,
        mensagem="Sua solicitação foi negada.",
        extra={
            "motivo": motivo,
            "observacao": observacao,
        },
    )

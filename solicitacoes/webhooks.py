# webhooks.py
import logging
import requests
from typing import Optional, Mapping
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from solicitacoes.models import Solicitacao

logger = logging.getLogger(__name__)

# nomes de headers podem ser customizados via settings
HEADER_INSTANCE = getattr(settings, "OUTBOUND_HEADER_INSTANCE", "X-Instance")
HEADER_API_KEY  = getattr(settings, "OUTBOUND_HEADER_API_KEY",  "X-API-Key")
HEADER_TOKEN    = getattr(settings, "OUTBOUND_HEADER_TOKEN",    "X-Webhook-Token")

DEFAULT_TIMEOUT = getattr(settings, "OUTBOUND_WEBHOOK_TIMEOUT", 8)

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
    Adiciona credenciais por barbearia em headers: X-Instance / X-API-Key (customizáveis).
    """
    callback_url = s.callback_url or getattr(settings, fallback_setting, None)
    if not callback_url:
        logger.info("[Solicitacao] %s sem callback_url (sol=%s)", evento.upper(), s.pk)
        return

    shop = getattr(s, "shop", None)
    shop_slug = getattr(shop, "slug", None)
    shop_instance = getattr(shop, "instance", None)
    shop_api_key = getattr(shop, "api_key", None)

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
        "shop": shop_slug,  # ajuda a identificar qual barbearia gerou o evento
    }
    if extra:
        payload.update(extra)

    headers = {
        "Content-Type": "application/json",
        HEADER_TOKEN: getattr(settings, "OUTBOUND_WEBHOOK_TOKEN", ""),
    }
    # credenciais por barbearia (somente se configuradas)
    if shop_instance:
        headers[HEADER_INSTANCE] = str(shop_instance)
    if shop_api_key:
        headers[HEADER_API_KEY] = str(shop_api_key)

    def _send(url, body, hdrs):
        try:
            resp = requests.post(url, json=body, headers=hdrs, timeout=DEFAULT_TIMEOUT)
            resp.raise_for_status()
            logger.info("[Solicitacao] webhook %s OK (sol=%s, shop=%s)", evento, s.pk, shop_slug)
        except Exception as e:
            # não vazar api_key nos logs
            logger.exception("[Solicitacao] webhook %s falhou (sol=%s, shop=%s): %s", evento, s.pk, shop_slug, e)

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

# solicitacoes/utils.py
import requests

from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db import transaction
from core.access import require_shop_member

def disparar_evento(solicitacao, evento="CONFIRMADA", session_key=None):
    """
    Dispara um POST para o callback_url da solicitação (se existir).
    Inclui a session_key enviada pelo n8n (se disponível).
    """
    if not solicitacao.callback_url:
        return

    payload = {
        "id": solicitacao.id,
        "id_externo": solicitacao.id_externo,
        "status": solicitacao.status,
        "evento": evento,
        "servico": solicitacao.servico_label,
        "inicio": solicitacao.inicio.isoformat() if solicitacao.inicio else None,
        "fim": solicitacao.fim.isoformat() if solicitacao.fim else None,
        "preco": str(solicitacao.preco_praticado()),
        "session_key": session_key,  # 🔹 propaga a mesma session_key do n8n
    }

    try:
        resp = requests.post(solicitacao.callback_url, json=payload, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        # Aqui você pode trocar por logging.warning
        print(f"Falha ao enviar webhook: {e}")



def shop_post_view(view):
    # ordem: require_shop_member -> csrf -> require_POST -> transaction -> login_required (externo)
    # mas como decoradores aplicam de baixo p/ cima, escrevemos:
    wrapped = require_shop_member(view)
    wrapped = csrf_protect(wrapped)
    wrapped = require_POST(wrapped)
    wrapped = transaction.atomic(wrapped)
    wrapped = login_required(wrapped)
    return wrapped
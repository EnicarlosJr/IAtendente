# solicitacoes/utils.py
import requests

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

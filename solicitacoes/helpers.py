# solicitacoes/helpers.py
from agendamentos.models import Agendamento, StatusAgendamento

def criar_agendamento_from_solicitacao(solicitacao, barbeiro=None):
    ag = Agendamento.objects.filter(shop=solicitacao.shop, solicitacao=solicitacao).first()
    if not ag:
        ag = Agendamento(shop=solicitacao.shop, solicitacao=solicitacao)

    ag.cliente = solicitacao.cliente
    ag.cliente_nome = solicitacao.nome or (getattr(solicitacao.cliente, "nome", None) or (solicitacao.telefone or ""))
    ag.barbeiro = barbeiro or solicitacao.barbeiro
    ag.servico = solicitacao.servico
    ag.servico_nome = solicitacao.servico_label
    ag.preco_cobrado = solicitacao.preco_praticado()
    ag.inicio = solicitacao.inicio
    ag.fim = solicitacao.fim
    ag.status = StatusAgendamento.CONFIRMADO
    ag.observacoes = solicitacao.observacoes or ""
    ag.save()
    return ag

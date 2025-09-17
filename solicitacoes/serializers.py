from rest_framework import serializers
from django.utils import timezone

from servicos.models import Servico
from .models import Solicitacao, SolicitacaoStatus


class SolicitacaoIntakeSerializer(serializers.Serializer):
    telefone = serializers.CharField(max_length=20)
    nome = serializers.CharField(max_length=120, required=False, allow_blank=True, allow_null=True)
    # Aqui recebemos o NOME do serviço; a view/serializer resolve para a FK ativa
    servico = serializers.CharField(max_length=120)
    inicio = serializers.DateTimeField(required=False, allow_null=True)
    observacoes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    id_externo = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    callback_url = serializers.URLField(required=False, allow_null=True)

    # guardamos o objeto para usar no create()
    def validate_servico(self, value: str) -> str:
        nome = (value or "").strip()
        svc = Servico.objects.filter(nome__iexact=nome, ativo=True).first()
        if not svc:
            raise serializers.ValidationError("Serviço não encontrado ou inativo.")
        self._servico_obj = svc
        return nome

    def create(self, validated_data):
        telefone     = (validated_data.get("telefone") or "").strip()
        nome         = (validated_data.get("nome") or "") or None
        observacoes  = validated_data.get("observacoes")
        inicio       = validated_data.get("inicio")  # pode ser None
        id_externo   = (validated_data.get("id_externo") or "").strip() or None
        callback_url = validated_data.get("callback_url")
        servico_obj  = getattr(self, "_servico_obj", None)

        defaults = {
            "telefone": telefone,
            "nome": nome or telefone,
            "servico": servico_obj,
            "inicio": inicio,
            "fim": None,  # será calculado na confirmação (regra do model, se houver)
            "observacoes": observacoes,
            "callback_url": callback_url,
            "status": SolicitacaoStatus.PENDENTE,
        }

        if id_externo:
            obj, _ = Solicitacao.objects.update_or_create(id_externo=id_externo, defaults=defaults)
            return obj
        return Solicitacao.objects.create(**defaults)

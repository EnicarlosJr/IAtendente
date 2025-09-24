# solicitacoes/serializers.py
from __future__ import annotations
from rest_framework import serializers
from servicos.models import Servico
from .models import Solicitacao, SolicitacaoStatus


class SolicitacaoIntakeSerializer(serializers.Serializer):
    telefone     = serializers.CharField(max_length=20)
    nome         = serializers.CharField(max_length=120, required=False, allow_blank=True, allow_null=True)
    servico      = serializers.CharField(max_length=120)                 # nome do serviço
    inicio       = serializers.DateTimeField(required=False, allow_null=True)  # horário desejado pelo cliente
    observacoes  = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    id_externo   = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    callback_url = serializers.URLField(required=False, allow_null=True)

    _servico_obj: Servico | None = None

    def validate_servico(self, value: str) -> str:
        nome = (value or "").strip()
        shop = self.context.get("shop")
        qs = Servico.objects.filter(nome__iexact=nome, ativo=True)
        if shop:
            qs = qs.filter(shop=shop)
        svc = qs.first()
        if not svc:
            raise serializers.ValidationError(f"Serviço '{nome}' não encontrado ou inativo.")
        self._servico_obj = svc
        return nome

    def create(self, validated_data):
        """
        Regras:
        - Grava a Solicitação como PENDENTE.
        - 'inicio' (se vier) é armazenado na própria Solicitação (cliente deseja esse horário).
        - NÃO cria Agendamento aqui (só no ato da confirmação pelo painel/admin).
        - Idempotente por (shop, id_externo).
        """
        shop         = self.context["shop"]
        telefone     = (validated_data.get("telefone") or "").strip()
        nome         = (validated_data.get("nome") or "") or None
        observacoes  = (validated_data.get("observacoes") or "") or None
        inicio       = validated_data.get("inicio")      # pode ser None
        id_externo   = (validated_data.get("id_externo") or "").strip() or None
        callback_url = validated_data.get("callback_url")
        servico_obj  = getattr(self, "_servico_obj", None)

        defaults = {
            "shop": shop,
            "telefone": telefone,
            "nome": nome or telefone,
            "servico": servico_obj,
            "inicio": inicio,     # ✅ guarda o horário desejado
            "fim": None,          # fim só será calculado/ajustado na confirmação, se quiser
            "observacoes": observacoes,
            "callback_url": callback_url,
            "status": SolicitacaoStatus.PENDENTE,
        }

        if id_externo:
            obj, created = Solicitacao.objects.update_or_create(
                shop=shop,
                id_externo=id_externo,
                defaults=defaults,
            )
            obj._was_created = created
            return obj

        obj = Solicitacao.objects.create(**defaults)
        obj._was_created = True
        return obj

    def to_representation(self, instance: Solicitacao):
        return {
            "id": instance.id,
            "shop": getattr(instance.shop, "slug", None),
            "status": instance.status,
            "telefone": instance.telefone,
            "nome": instance.nome,
            "servico": instance.servico_label,
            "inicio": instance.inicio.isoformat() if instance.inicio else None,
            "observacoes": instance.observacoes,
            "id_externo": instance.id_externo,
            "criado_em": instance.criado_em.isoformat() if instance.criado_em else None,
        }

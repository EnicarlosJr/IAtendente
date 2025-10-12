# solicitacoes/serializers.py
from __future__ import annotations
from rest_framework import serializers
from servicos.models import Servico
from .models import Solicitacao, SolicitacaoStatus
from core.contacts import find_or_create_cliente, normalize_phone

class SolicitacaoIntakeSerializer(serializers.Serializer):
    telefone     = serializers.CharField(max_length=20)
    nome         = serializers.CharField(max_length=120, required=False, allow_blank=True, allow_null=True)
    servico      = serializers.CharField(max_length=120)                 # nome do serviço
    inicio       = serializers.DateTimeField(required=False, allow_null=True)  # horário desejado
    observacoes  = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    id_externo   = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    callback_url = serializers.URLField(required=False, allow_null=True)

    _servico_obj: Servico | None = None

    def validate_telefone(self, value: str) -> str:
        tel = normalize_phone(value)
        if not tel:
            raise serializers.ValidationError("Telefone inválido ou ausente.")
        return tel

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
        - Cria/atualiza Solicitação PENDENTE.
        - Vincula/resolve Cliente (telefone/nome).
        - Guarda 'inicio' desejado no registro.
        - NÃO cria Agendamento.
        - Idempotente por (shop, id_externo).
        """
        shop         = self.context["shop"]
        telefone     = validated_data.get("telefone")
        nome         = (validated_data.get("nome") or "") or None
        observacoes  = (validated_data.get("observacoes") or "") or None
        inicio       = validated_data.get("inicio")
        id_externo   = (validated_data.get("id_externo") or "").strip() or None
        callback_url = validated_data.get("callback_url")
        servico_obj  = getattr(self, "_servico_obj", None)

        cliente = find_or_create_cliente(shop, nome=nome, telefone=telefone)

        defaults = {
            "shop": shop,
            "cliente": cliente,
            "telefone": telefone,
            "nome": nome or cliente.nome,
            "servico": servico_obj,
            "inicio": inicio,
            "fim": None,
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
        shop = getattr(instance, "shop", None)
        # pega instance/api_key da BarberShop (apenas resposta)
        shop_instance = getattr(shop, "instance", None) if shop else None
        shop_api_key  = getattr(shop, "api_key", None) if shop else None

        return {
            "id": instance.id,
            "shop": getattr(shop, "slug", None),
            "status": instance.status,
            "telefone": instance.telefone,
            "nome": instance.nome,
            "servico": instance.servico_label,
            "inicio": instance.inicio.isoformat() if instance.inicio else None,
            "observacoes": instance.observacoes,
            "id_externo": instance.id_externo,
            "cliente_id": instance.cliente_id,
            "criado_em": instance.criado_em.isoformat() if instance.criado_em else None,

        }

# solicitacoes/api_views.py
from __future__ import annotations

from functools import wraps
import inspect

from django.conf import settings
from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from barbearias.models import BarberShop
from .serializers import SolicitacaoIntakeSerializer


# -------------------------------
# Decorator de autenticação por API Key
# -------------------------------
def require_inbound_api_key(view_func):
    sig = inspect.signature(view_func)

    @wraps(view_func)
    def _wrapped(self, request, *args, **kwargs):
        expected = getattr(settings, "INBOUND_API_KEY", None)
        got = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if expected and got != expected:
            raise PermissionDenied("API key inválida ou ausente.")
        # Sanitize kwargs se a view não aceitar **kwargs
        if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            accepted = {
                name for name, p in sig.parameters.items()
                if p.kind in (p.KEYWORD_ONLY, p.POSITIONAL_OR_KEYWORD)
            }
            kwargs = {k: v for k, v in kwargs.items() if k in accepted}
        return view_func(self, request, *args, **kwargs)

    return _wrapped


# -------------------------------
# Intake de Solicitação (PENDENTE)
# -------------------------------
class SolicitacaoIntakeView(APIView):
    """
    Cria/atualiza uma Solicitação **PENDENTE** para a barbearia informada.
    - NUNCA cria Agendamento aqui.
    - Se 'id_externo' vier, operação é idempotente por (shop, id_externo).
    - 'inicio' vindo do cliente é guardado na própria Solicitação (horário desejado).
    """
    permission_classes = [permissions.AllowAny]

    @require_inbound_api_key
    def post(self, request, shop_slug: str, *args, **kwargs):
        # Resolve a barbearia (via slug da rota ou middleware que populou request.shop)
        shop = getattr(request, "shop", None) or get_object_or_404(BarberShop, slug=shop_slug)

        # Serializa/valida e cria/atualiza a Solicitação como PENDENTE
        ser = SolicitacaoIntakeSerializer(data=request.data, context={"shop": shop})
        ser.is_valid(raise_exception=True)
        obj = ser.save()  # o serializer já garante status=PENDENTE e NENHUM agendamento

        # 201 se criado, 200 se atualizado por id_externo
        http_status = status.HTTP_201_CREATED if getattr(obj, "_was_created", False) else status.HTTP_200_OK

        return Response(
            {
                "ok": True,
                "message": "Solicitação registrada com sucesso." if http_status == 201 else "Solicitação atualizada com sucesso.",
                "shop": shop.slug,
                "created": bool(getattr(obj, "_was_created", False)),
                "solicitacao": ser.to_representation(obj),
            },
            status=http_status,
        )

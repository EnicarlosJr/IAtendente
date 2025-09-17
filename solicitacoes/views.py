from functools import wraps
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status

from solicitacoes.models import Solicitacao
from solicitacoes.serializers import SolicitacaoIntakeSerializer


def require_api_key(view_func):
    @wraps(view_func)
    def _wrapped(self, request, *args, **kwargs):
        expected = getattr(settings, "INBOUND_API_KEY", None)
        got = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if expected and got != expected:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("API key inválida ou ausente.")
        return view_func(self, request, *args, **kwargs)
    return _wrapped


class SolicitacaoIntakeView(APIView):
    permission_classes = [permissions.AllowAny]

    @require_api_key
    def post(self, request):
        ser = SolicitacaoIntakeSerializer(data=request.data)
        if ser.is_valid():
            obj = ser.save()
            return Response({"ok": True, "id": obj.id}, status=status.HTTP_201_CREATED)
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

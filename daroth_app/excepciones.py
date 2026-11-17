from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler

from .services import ReglaDeNegocioError


class Conflicto(APIException):
    """
    HTTP 409: la operación es válida en su forma, pero choca con el estado
    actual del recurso (por ejemplo, borrar un pedido que ya está en camino).
    """
    status_code = status.HTTP_409_CONFLICT
    default_detail = "La operación no es posible en el estado actual del recurso."
    default_code = "conflicto"


def manejar_excepciones(exc, context):
    """
    Manejador de excepciones de DRF (configurado en settings.REST_FRAMEWORK).
    Las violaciones de reglas de negocio lanzadas desde services.py se
    responden como 409 Conflict, sin que cada vista tenga que capturarlas.
    """
    if isinstance(exc, ReglaDeNegocioError):
        exc = Conflicto(str(exc))
    return exception_handler(exc, context)

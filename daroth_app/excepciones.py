from rest_framework import status
from rest_framework.exceptions import APIException


class Conflicto(APIException):
    """
    HTTP 409: la operación es válida en su forma, pero choca con el estado
    actual del recurso (por ejemplo, borrar un pedido que ya está en camino).
    """
    status_code = status.HTTP_409_CONFLICT
    default_detail = "La operación no es posible en el estado actual del recurso."
    default_code = "conflicto"

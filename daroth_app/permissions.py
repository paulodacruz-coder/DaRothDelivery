from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Perfil


def es_administrador(user):
    """Un usuario es administrador si su perfil lo dice o si es superusuario de Django."""
    if not (user and user.is_authenticated):
        return False
    if user.is_superuser:
        return True
    perfil = getattr(user, "perfil", None)
    return perfil is not None and perfil.rol == Perfil.Rol.ADMINISTRADOR


class EsAdministradorOSoloLectura(BasePermission):
    """
    Cualquier usuario autenticado puede consultar; solo un administrador
    puede crear, modificar o borrar. Se usa para el catálogo
    (zonas, productos, repartidores).
    """
    message = "Solo un administrador puede modificar estos datos."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or es_administrador(request.user)

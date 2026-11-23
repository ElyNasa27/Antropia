"""Resolución de zonas horarias con la base IANA real (zoneinfo + tzdata).

En este paquete NO existe ninguna tabla de desfases simulados: para encuentros
reales solo se usa `resolver_zona_real`. La tabla simulada vive únicamente en
tests/zonas_simuladas.py y Coordinacion la rechaza salvo permiso explícito.

En Windows, zoneinfo necesita el paquete tzdata (instalado en .venv). Si falta,
`resolver_zona_real` lanza ZonaNoDisponible y no se propone ninguna hora.
"""
from __future__ import annotations

import unicodedata
from datetime import tzinfo
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones


class ZonaNoDisponible(Exception):
    """La zona horaria no se pudo resolver."""


ResolverZona = Callable[[str], tzinfo]


def resolver_zona_real(nombre: str) -> tzinfo:
    try:
        return ZoneInfo(nombre)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ZonaNoDisponible(
            f"no se pudo resolver la zona horaria {nombre!r} "
            "(en Windows suele indicar que falta el paquete tzdata)"
        ) from exc


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def zona_sin_tildes(nombre: str | None) -> str | None:
    """La zona IANA equivalente a `nombre` quitando solo las tildes, o None.

    Únicamente si el resultado coincide EXACTAMENTE (mayúsculas incluidas) con una
    zona de la base IANA: «America/Bogotá» -> «America/Bogota». No corrige nada
    más (ni espacios, ni mayúsculas, ni ciudades parecidas): si no coincide, la
    zona requiere aclaración.
    """
    if not nombre:
        return None
    candidata = _sin_tildes(nombre.strip())
    if candidata == nombre.strip():
        return None                      # no había tildes que quitar
    try:
        validas = available_timezones()
    except Exception:
        return None
    return candidata if candidata in validas else None


def datos_de_zonas_disponibles() -> bool:
    try:
        ZoneInfo("Europe/Madrid")
        return True
    except Exception:
        return False


def es_resolver_simulado(resolver: ResolverZona) -> bool:
    return getattr(resolver, "es_simulado", False) is True


NOMBRES_LEGIBLES = {
    "Europe/Madrid": "Madrid",
    "America/Mexico_City": "Ciudad de México",
}


def nombre_legible(zona: str) -> str:
    return NOMBRES_LEGIBLES.get(zona, zona.split("/")[-1].replace("_", " "))

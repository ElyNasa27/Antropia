"""Resolución de zonas horarias con la base IANA real (zoneinfo + tzdata).

En este paquete NO existe ninguna tabla de desfases simulados: para encuentros
reales solo se usa `resolver_zona_real`. La tabla simulada vive únicamente en
tests/zonas_simuladas.py y Coordinacion la rechaza salvo permiso explícito.

En Windows, zoneinfo necesita el paquete tzdata (instalado en .venv). Si falta,
`resolver_zona_real` lanza ZonaNoDisponible y no se propone ninguna hora.
"""
from __future__ import annotations

from datetime import tzinfo
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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

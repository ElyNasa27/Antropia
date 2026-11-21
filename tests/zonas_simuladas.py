"""Tabla de zonas SIMULADA. Solo para pruebas con datos ficticios cuando no hay tzdata.

Válida únicamente para estas dos zonas entre el 2026-10-25 y el 2027-03-27:
  Europe/Madrid = UTC+1 (horario de invierno)
  America/Mexico_City = UTC-6 (sin horario de verano desde 2022)
Fuera de ese rango es incorrecta. Nunca debe usarse para encuentros reales:
Coordinacion la rechaza salvo que se pase permitir_zonas_simuladas=True.
"""
from __future__ import annotations

from datetime import timedelta, timezone, tzinfo

from encuentros.zonas import ZonaNoDisponible

ZONAS_FIJAS_PILOTO: dict[str, tzinfo] = {
    "Europe/Madrid": timezone(timedelta(hours=1), "CET"),
    "America/Mexico_City": timezone(timedelta(hours=-6), "CST"),
}


def resolver_zona_simulada(nombre: str) -> tzinfo:
    try:
        return ZONAS_FIJAS_PILOTO[nombre]
    except KeyError as exc:
        raise ZonaNoDisponible(f"la zona {nombre!r} no está en la tabla simulada") from exc


resolver_zona_simulada.es_simulado = True

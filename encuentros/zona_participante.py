"""Zona horaria de cada participante (etapa 5, 2026-11-22).

Fuentes, en este orden:

  1. «Zona horaria seleccionada» (selección del formulario nuevo; nombres IANA).
  2. Si falta: la zona del formato anterior, es decir la antigua columna de texto
     «Zona horaria» (eliminada de Notion el 2026-11-22; solo datos antiguos) o la
     zona escrita dentro de «Disponibilidad + zona horaria».

Reglas (no se adivina nada):
  - Solo se acepta una zona que exista en la base IANA. La validez la comprueba
    A1 con el resolver real (`zonas.resolver_zona_real`); si no existe, el perfil
    queda pendiente de aclaración.
  - Única corrección admitida (ya acordada): quitar tildes cuando el resultado es
    EXACTAMENTE una zona IANA («America/Bogotá» -> «America/Bogota»).
  - Si dos fuentes dan zonas distintas, el perfil queda pendiente de aclaración:
    no se elige una por prioridad.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .zonas import zona_sin_tildes

FALTA = "Zona horaria seleccionada (falta)"
CONTRADICTORIA = "Zona horaria (datos contradictorios entre la selección y el texto anterior; requiere aclaración)"
NO_IANA = "Zona horaria (no existe en la base IANA; requiere aclaración)"

ORIGEN_SELECCION = "Zona horaria seleccionada"
ORIGEN_ANTERIOR = "formato anterior"

AVISO_TILDES = "zona horaria escrita con tildes: se usa su equivalente IANA exacto"


@dataclass(frozen=True)
class ZonaElegida:
    zona: str | None                 # zona que se usará (A1 comprueba que exista en IANA)
    origen: str | None = None
    problema: str | None = None      # motivo sin datos personales; None si no hay problema
    avisos: tuple[str, ...] = field(default_factory=tuple)


def _normalizar(valor) -> tuple[str | None, bool]:
    """(zona sin espacios alrededor, ¿se quitaron tildes?). Solo texto."""
    if not isinstance(valor, str) or not valor.strip():
        return None, False
    z = valor.strip()
    equivalente = zona_sin_tildes(z)
    return (equivalente, True) if equivalente else (z, False)


def elegir_zona(seleccionada, anterior=None, en_texto=None) -> ZonaElegida:
    sel, tildes_sel = _normalizar(seleccionada)
    previas = []
    tildes = tildes_sel
    for v in (anterior, en_texto):
        z, t = _normalizar(v)
        if z is not None:
            previas.append(z)
            tildes = tildes or t
    avisos = (AVISO_TILDES,) if tildes else ()

    if sel is not None:
        if any(z != sel for z in previas):
            return ZonaElegida(None, None, CONTRADICTORIA)
        return ZonaElegida(sel, ORIGEN_SELECCION, None, avisos)
    if previas:
        if len(set(previas)) > 1:
            return ZonaElegida(None, None, CONTRADICTORIA)
        return ZonaElegida(previas[0], ORIGEN_ANTERIOR, None, avisos)
    return ZonaElegida(None, None, FALTA)

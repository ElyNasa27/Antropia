"""Minutos que cada persona ofrece enseñar (etapa 7, 2026-11-22).

«Minutos seleccionados»: «15 minutos» … «120 minutos» u «Otro» (etiquetas
verificadas en Notion: hay una fila con «45 minutos»). Con «Otro», el número se
escribe en «Minutos disponibles». Las respuestas anteriores solo tienen
«Minutos disponibles» y siguen funcionando.

Reglas (no se adivina ni se convierte nada):
  - Etiqueta conocida                    -> sus minutos. Si «Minutos disponibles» trae
                                            OTRO número, se pide aclaración.
  - «Otro»                               -> «Minutos disponibles» (entero positivo);
                                            si falta o no es válido, se pide el dato.
  - Etiqueta desconocida                 -> aclaración (no se usa «Minutos disponibles»).
  - Sin selección                        -> «Minutos disponibles» (formato anterior).
"""
from __future__ import annotations

from dataclasses import dataclass

from .notion_mapa import OPCION_OTRO, minutos_de_opcion

FALTA = "Minutos disponibles"
OTRO_SIN_NUMERO = "Minutos disponibles (eligió «Otro» pero falta un número entero de minutos)"
NO_VALIDO = "Minutos disponibles (debe ser un número entero de minutos mayor que 0)"
CONTRADICTORIOS = "Minutos (la opción elegida y «Minutos disponibles» no coinciden; requiere aclaración)"
OPCION_DESCONOCIDA = "Minutos seleccionados (opción no reconocida; requiere aclaración)"

ORIGEN_SELECCION = "Minutos seleccionados"
ORIGEN_OTRO = "Minutos disponibles («Otro»)"
ORIGEN_ANTERIOR = "Minutos disponibles (formato anterior)"


@dataclass(frozen=True)
class MinutosElegidos:
    minutos: int | None
    origen: str | None = None
    problema: str | None = None


def _entero_positivo(valor) -> int | None | bool:
    """Entero > 0; None si está vacío; False si hay un valor que no sirve."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return False
    if valor <= 0 or not float(valor).is_integer():
        return False
    return int(valor)


def elegir_minutos(seleccionados: str | None, disponibles) -> MinutosElegidos:
    etiqueta = " ".join((seleccionados or "").split())
    numero = _entero_positivo(disponibles)
    if etiqueta:
        if etiqueta.casefold() == OPCION_OTRO.casefold():
            if numero is None:
                return MinutosElegidos(None, None, OTRO_SIN_NUMERO)
            if numero is False:
                return MinutosElegidos(None, None, NO_VALIDO)
            return MinutosElegidos(numero, ORIGEN_OTRO)
        m = minutos_de_opcion(etiqueta)
        if m is None:
            return MinutosElegidos(None, None, OPCION_DESCONOCIDA)
        if numero is False or (numero is not None and numero != m):
            return MinutosElegidos(None, None, CONTRADICTORIOS)
        return MinutosElegidos(m, ORIGEN_SELECCION)
    if numero is None:
        return MinutosElegidos(None, None, FALTA)
    if numero is False:
        return MinutosElegidos(None, None, NO_VALIDO)
    return MinutosElegidos(numero, ORIGEN_ANTERIOR)

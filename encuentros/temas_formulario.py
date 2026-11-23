"""Temas de «Ofrece» y «Quiere aprender» (etapa 4, 2026-11-22).

Formulario nuevo: hasta 7 temas por pregunta, uno por línea.

  - Si el texto tiene varias líneas, se separa SOLO por líneas: cada línea es un
    tema tal como se escribió (las comas o «y» dentro de una línea no la parten).
  - Si es una sola línea (respuestas anteriores), se usa la separación anterior
    (comas, punto y coma, «/», « y », « e »; ver disponibilidad.leer_temas).
  - Líneas vacías y temas repetidos (sin distinguir mayúsculas ni tildes) no cuentan.
  - Más de 7 temas: el perfil queda bloqueado y se pide aclaración. No se descarta
    ningún tema: se devuelven todos, pero no se usan.
  - «Ofrece 2…7» y «Quiere aprender 2…7» no se usan (decisión del 2026-11-22).
"""
from __future__ import annotations

import unicodedata

from .disponibilidad import leer_temas

MAX_TEMAS = 7


def _clave(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(sin.casefold().split())


def problema_demasiados(pregunta: str) -> str:
    return f"{pregunta} (más de {MAX_TEMAS} temas; requiere aclaración)"


def leer_temas_formulario(texto: str | None) -> tuple[list[str], bool]:
    """(temas, hay_demasiados). Con demasiados, los temas se devuelven pero no se usan."""
    if not isinstance(texto, str) or not texto.strip():
        return [], False
    lineas = [ln for ln in texto.splitlines() if ln.strip()]
    if len(lineas) > 1:
        candidatos = [" ".join(ln.split()).strip(" .") for ln in lineas]
    else:
        candidatos = leer_temas(lineas[0])
    temas, vistas = [], set()
    for t in candidatos:
        if t and _clave(t) not in vistas:
            vistas.add(_clave(t))
            temas.append(t)
    return temas, len(temas) > MAX_TEMAS

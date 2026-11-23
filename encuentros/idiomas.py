"""Interpretación de «Idioma» y «Otro idioma» de Participantes (etapas 0 y 3).

«Idioma» era de selección única (un texto) y desde el 2026-11-22 es de selección
múltiple (una lista). Se aceptan ambos formatos. Solo se interpreta lo que no deja
dudas; en cualquier otro caso el perfil queda PENDIENTE (nunca pasa solo):

  - vacío                                              -> falta el idioma
  - uno o varios idiomas                               -> esos idiomas
  - «Otro» con «Otro idioma» legible                   -> se añaden los de «Otro idioma»
  - «Otro» sin «Otro idioma»                           -> pendiente
  - «Otro idioma» que no se puede leer                 -> pendiente
  - «Otro idioma» escrito sin elegir «Otro»            -> pendiente (aclaración)

Dos personas son compatibles si comparten al menos un idioma, comparando sin
distinguir mayúsculas ni tildes («Ingles» = «Inglés»). No se traducen nombres
(«English» no se considera «Inglés»).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

OPCION_OTRO = "otro"
MAX_LARGO_IDIOMA = 40

FALTA = "Idioma"
PENDIENTE_OTRO = "Idioma (eligió «Otro» pero falta «Otro idioma»)"
PENDIENTE_OTRO_ILEGIBLE = "Otro idioma (no se pudo interpretar; requiere aclaración)"
PENDIENTE_OTRO_SIN_OPCION = "Idioma («Otro idioma» escrito sin elegir «Otro»; requiere aclaración)"
PENDIENTE_FORMATO = "Idioma (pendiente: formato no reconocido)"

_SEPARADORES = re.compile(r"[,;/\n]|\s+y\s+|\s+e\s+")
_NOMBRE = re.compile(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*")      # solo letras, espacios, guion o apóstrofo


@dataclass(frozen=True)
class IdiomaInterpretado:
    idiomas: tuple[str, ...]    # vacío si no se puede usar
    problema: str | None        # motivo (sin datos personales), o None

    @property
    def idioma(self) -> str | None:
        """Texto para mostrar («Español, Inglés»), o None si no se puede usar."""
        return ", ".join(self.idiomas) if self.idiomas and not self.problema else None


def _limpio(texto) -> str:
    return " ".join(str(texto).split())


def clave_idioma(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(sin.casefold().split())


def opciones_idioma(valor) -> tuple[str, ...] | None:
    """Lista de opciones sin vacías ni repetidas. None si el formato no se reconoce."""
    if valor is None:
        return ()
    if isinstance(valor, str):
        return (_limpio(valor),) if valor.strip() else ()
    if not isinstance(valor, (list, tuple)):
        return None
    res, vistas = [], set()
    for v in valor:
        n = v.get("name") if isinstance(v, dict) else v
        if not isinstance(n, str):
            return None
        n = _limpio(n)
        if n and clave_idioma(n) not in vistas:
            vistas.add(clave_idioma(n))
            res.append(n)
    return tuple(res)


def leer_otro_idioma(texto: str | None) -> tuple[str, ...] | None:
    """Idiomas escritos en «Otro idioma». () si está vacío; None si no se puede leer."""
    if not isinstance(texto, str) or not texto.strip():
        return ()
    res = []
    for parte in _SEPARADORES.split(texto):
        parte = _limpio(parte).strip(" .")
        if not parte:
            continue
        if len(parte) > MAX_LARGO_IDIOMA or not _NOMBRE.fullmatch(parte):
            return None
        res.append(parte)
    return tuple(res) or None


def interpretar_idioma(valor, otro_idioma: str | None = None) -> IdiomaInterpretado:
    opciones = opciones_idioma(valor)
    if opciones is None:
        return IdiomaInterpretado((), PENDIENTE_FORMATO)
    eligio_otro = any(clave_idioma(o) == OPCION_OTRO for o in opciones)
    idiomas = [o for o in opciones if clave_idioma(o) != OPCION_OTRO]
    otros = leer_otro_idioma(otro_idioma)

    if eligio_otro:
        if otros is None:
            return IdiomaInterpretado((), PENDIENTE_OTRO_ILEGIBLE)
        if not otros:
            return IdiomaInterpretado((), PENDIENTE_OTRO)
        idiomas += list(otros)
    elif otros:                     # texto en «Otro idioma» sin haber elegido «Otro»
        return IdiomaInterpretado((), PENDIENTE_OTRO_SIN_OPCION)
    elif otros is None:
        return IdiomaInterpretado((), PENDIENTE_OTRO_SIN_OPCION)

    unicos, vistas = [], set()
    for i in idiomas:
        if clave_idioma(i) not in vistas:
            vistas.add(clave_idioma(i))
            unicos.append(i)
    if not unicos:
        return IdiomaInterpretado((), FALTA)
    return IdiomaInterpretado(tuple(unicos), None)


def idiomas_comunes(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    """Idiomas de `a` que también están en `b` (sin distinguir mayúsculas ni tildes)."""
    claves_b = {clave_idioma(x) for x in b}
    return tuple(x for x in a if clave_idioma(x) in claves_b)

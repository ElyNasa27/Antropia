"""Lectura del texto libre del formulario de Notion.

«Disponibilidad + zona horaria» es texto libre. El formulario pide el formato
«lunes 18:00–20:00; America/Costa_Rica». Se aceptan también variantes comunes:

    lunes 18:00-20:00; miércoles 19:00 a 21:00
    martes y jueves 18-20
    lunes a viernes de 9:00 a 11:30
    sábado 10:00–12:00, domingo 16:00–18:00; Europe/Madrid

Lo que no se pueda leer NO se adivina: se devuelve como «no reconocido» y, si no
queda ninguna franja, la persona no entra en el emparejamiento.

«Ofrece» y «Quiere aprender» también son texto libre: se separan por comas,
punto y coma, «/», saltos de línea, « y » o « e ». La comparación entre temas
está en `temas.py`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import time

from .modelos import DIAS_SEMANA, Franja


def sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )


_DIAS_SIN_TILDE = [sin_tildes(d) for d in DIAS_SEMANA]
_DIA = r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)s?"
_HORA = r"(\d{1,2})(?:[:.h](\d{2}))?\s*(?:h|hs|hrs)?"
_PATRON = re.compile(
    rf"(?P<dias>{_DIA}(?:\s*(?:,|y|e|a|al|-|–)\s*{_DIA})*)\s*:?\s*(?:de\s+)?"
    rf"{_HORA}\s*(?:-|–|—|a|hasta)\s*{_HORA}"
)
_ZONA = re.compile(r"\b([A-Z][A-Za-z_]+/[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z_]+)?)\b")


@dataclass
class Disponibilidad:
    franjas: list[Franja] = field(default_factory=list)
    zona_en_texto: str | None = None
    no_reconocido: list[str] = field(default_factory=list)


def _dias(texto: str) -> list[str]:
    nombres = re.findall(_DIA, texto)
    nombres = [n.rstrip("s") if n.endswith("s") and n not in ("lunes", "martes", "miercoles", "jueves", "viernes") else n for n in nombres]
    indices = [_DIAS_SIN_TILDE.index(n) for n in nombres]
    # «lunes a viernes» = rango
    if len(indices) == 2 and re.search(rf"{_DIA}\s*(?:a|al|-|–)\s*{_DIA}", texto):
        i, j = indices
        rango = list(range(i, j + 1)) if i <= j else list(range(i, 7)) + list(range(0, j + 1))
        return [DIAS_SEMANA[k] for k in rango]
    return [DIAS_SEMANA[k] for k in dict.fromkeys(indices)]


def _hora(h: str, m: str | None) -> time | None:
    hh, mm = int(h), int(m or 0)
    if hh == 24 and mm == 0:
        return time(23, 59)
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hh, mm)
    return None


def leer_disponibilidad(texto: str | None) -> Disponibilidad:
    res = Disponibilidad()
    if not texto or not texto.strip():
        return res
    zona = _ZONA.search(texto)
    if zona:
        res.zona_en_texto = zona.group(1)
    base = sin_tildes(texto).lower()
    if zona:
        base = base.replace(zona.group(1).lower(), " ")
    usados = []
    for m in _PATRON.finditer(base):
        ini, fin = _hora(m.group(2), m.group(3)), _hora(m.group(4), m.group(5))
        usados.append(m.span())
        if ini is None or fin is None or fin <= ini:
            res.no_reconocido.append(m.group(0).strip())
            continue
        for dia in _dias(m.group("dias")):
            f = Franja(dia, ini, fin)
            if f not in res.franjas:
                res.franjas.append(f)
    resto = base
    for a, b in reversed(usados):
        resto = resto[:a] + " " + resto[b:]
    for trozo in re.split(r"[;\n]", resto):
        trozo = trozo.strip(" ,.-–")
        if re.search(r"\d", trozo):
            res.no_reconocido.append(trozo)
    return res


def leer_temas(texto: str | None) -> list[str]:
    if not texto:
        return []
    partes = re.split(r"[,;\n/]|\s+y\s+|\s+e\s+", texto)
    temas = []
    for p in partes:
        p = " ".join(p.split()).strip(" .")
        if p and p.lower() not in {t.lower() for t in temas}:
            temas.append(p)
    return temas

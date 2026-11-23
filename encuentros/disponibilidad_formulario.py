"""Disponibilidad de cada participante (etapa 6, 2026-11-22).

Formulario nuevo: «Días disponibles» y, para cada día, «Franjas <Día>» (bloques de
una hora, de «00:00–01:00» a «23:00–24:00», u «Otro»). Con «Otro», la persona
escribe en «Otras franjas <Día>» una o varias franjas con inicio y fin («07:30–08:15»).

Formato anterior: el texto libre «Disponibilidad + zona horaria» (disponibilidad.py).

Reglas (nunca se inventa un horario; ante la duda, aclaración y el perfil no se usa):
  - Si hay datos del formulario nuevo, se usan. Cualquier problema en ellos bloquea
    toda la disponibilidad (no se usa una parte):
      · día marcado sin franjas, o con «Otro» sin texto;
      · franjas de un día que no está marcado;
      · texto en «Otras franjas» sin haber elegido «Otro»;
      · una franja que no tiene el formato exacto HH:MM–HH:MM o termina antes de empezar;
      · un día o una opción que no se reconoce.
  - Si NO hay datos nuevos, se usa el texto anterior; si una parte no se entiende,
    también se pide aclaración (no se usa una lectura parcial).
  - Si hay datos nuevos Y texto anterior con franjas, deben coincidir; si no, aclaración.
  - Los bloques contiguos o solapados del mismo día se unen («18–19» + «19–20» = 18–20):
    es la misma disponibilidad, no un horario nuevo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

from .disponibilidad import leer_disponibilidad, sin_tildes
from .modelos import DIAS_SEMANA, Franja

ORIGEN_NUEVO = "formulario nuevo"
ORIGEN_ANTERIOR = "formato anterior"

FALTA = "Disponibilidad (faltan días y franjas)"
CONTRADICTORIA = "Disponibilidad (el formulario nuevo y el texto anterior no coinciden; requiere aclaración)"
ANTERIOR_AMBIGUA = "Disponibilidad + zona horaria (parte del texto no se entiende; requiere aclaración)"

_HORA = r"(\d{2}):(\d{2})"
_FRANJA = re.compile(rf"^\s*{_HORA}\s*(?:-|–|—|a)\s*{_HORA}\s*$")
_SEPARADOR_FRANJAS = re.compile(r"[;,\n]+")


@dataclass(frozen=True)
class DisponibilidadElegida:
    franjas: tuple[Franja, ...]
    origen: str | None = None
    problemas: tuple[str, ...] = ()        # sin datos personales

    @property
    def problema(self) -> str | None:
        return "; ".join(self.problemas) if self.problemas else None


def _dia(nombre) -> str | None:
    if not isinstance(nombre, str):
        return None
    n = sin_tildes(nombre).strip().lower()
    for d in DIAS_SEMANA:
        if sin_tildes(d) == n:
            return d
    return None


def _hora(h: str, m: str) -> time | None:
    hh, mm = int(h), int(m)
    if hh == 24 and mm == 0:
        return time(23, 59)            # mismo criterio que disponibilidad.py
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return time(hh, mm)
    return None


def franja_de_texto(dia: str, texto: str) -> Franja | None:
    """«HH:MM–HH:MM» exacto -> Franja; cualquier otra cosa -> None."""
    m = _FRANJA.match(texto or "")
    if not m:
        return None
    ini, fin = _hora(m.group(1), m.group(2)), _hora(m.group(3), m.group(4))
    if ini is None or fin is None or fin <= ini:
        return None
    return Franja(dia, ini, fin)


def unir_contiguas(franjas) -> tuple[Franja, ...]:
    orden = sorted(set(franjas), key=lambda f: (DIAS_SEMANA.index(f.dia), f.inicio, f.fin))
    res: list[Franja] = []
    for f in orden:
        if res and res[-1].dia == f.dia and f.inicio <= res[-1].fin:
            if f.fin > res[-1].fin:
                res[-1] = Franja(f.dia, res[-1].inicio, f.fin)
            continue
        res.append(f)
    return tuple(res)


def hay_datos_nuevos(dias, franjas: dict, otras: dict) -> bool:
    return bool(dias) or any(franjas.values()) or any((v or "").strip() for v in otras.values())


def leer_formulario_nuevo(dias, franjas: dict, otras: dict) -> tuple[tuple[Franja, ...], list[str]]:
    """(franjas, problemas). Las claves de `franjas` y `otras` son días de DIAS_SEMANA."""
    problemas: list[str] = []
    marcados = []
    for d in dias or ():
        dia = _dia(d)
        if dia is None:
            problemas.append("Días disponibles (opción no reconocida)")
        elif dia not in marcados:
            marcados.append(dia)
    res: list[Franja] = []
    for dia in DIAS_SEMANA:
        col = dia.capitalize()
        opciones = tuple(franjas.get(dia) or ())
        texto = (otras.get(dia) or "").strip()
        if dia not in marcados:
            if opciones or texto:
                problemas.append(f"Franjas {col} (hay franjas pero el día no está marcado; requiere aclaración)")
            continue
        if not opciones:
            problemas.append(f"Franjas {col} (falta)")
            continue
        eligio_otro = False
        for o in opciones:
            if sin_tildes(str(o)).strip().lower() == "otro":
                eligio_otro = True
                continue
            f = franja_de_texto(dia, str(o))
            if f is None:
                problemas.append(f"Franjas {col} (opción no reconocida)")
            else:
                res.append(f)
        if eligio_otro:
            if not texto:
                problemas.append(f"Otras franjas {col} (eligió «Otro» pero falta el horario)")
            else:
                for trozo in _SEPARADOR_FRANJAS.split(texto):
                    if not trozo.strip():
                        continue
                    f = franja_de_texto(dia, trozo)
                    if f is None:
                        problemas.append(f"Otras franjas {col} (use inicio y fin como 07:30–08:15; requiere aclaración)")
                        break
                    res.append(f)
        elif texto:
            problemas.append(f"Otras franjas {col} (hay texto pero no se eligió «Otro»; requiere aclaración)")
    return unir_contiguas(res), problemas


def elegir_disponibilidad(dias, franjas: dict, otras: dict, texto_anterior: str | None) -> DisponibilidadElegida:
    anterior = leer_disponibilidad(texto_anterior)
    franjas_anteriores = unir_contiguas(anterior.franjas)
    if hay_datos_nuevos(dias, franjas, otras):
        nuevas, problemas = leer_formulario_nuevo(dias, franjas, otras)
        if problemas:
            return DisponibilidadElegida((), None, tuple(problemas))
        if franjas_anteriores and franjas_anteriores != nuevas:
            return DisponibilidadElegida((), None, (CONTRADICTORIA,))
        if anterior.no_reconocido:
            return DisponibilidadElegida((), None, (ANTERIOR_AMBIGUA,))
        return DisponibilidadElegida(nuevas, ORIGEN_NUEVO)
    if anterior.no_reconocido:
        return DisponibilidadElegida((), None, (ANTERIOR_AMBIGUA,))
    if franjas_anteriores:
        return DisponibilidadElegida(franjas_anteriores, ORIGEN_ANTERIOR)
    return DisponibilidadElegida((), None, (FALTA,))

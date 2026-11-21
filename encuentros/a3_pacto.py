"""A3: sugiere un pacto usando solo los datos disponibles.

Tiempo del encuentro: «Minutos por sesión» es lo que cada persona ofrece enseñar.
La duración total es la suma de ambos aportes, y ambas personas deben estar
disponibles durante TODA esa duración (dentro de una misma franja de cada una).

Si falta algo (zona horaria, disponibilidad, minutos o su revisión, aceptación
de lo virtual) o no hay una franja común suficiente, no propone fecha: devuelve
lo que falta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Iterable

from .modelos import DIAS_SEMANA, PerfilEncuentro, PropuestaMatch, VersionPacto
from .zonas import ResolverZona, ZonaNoDisponible

MODALIDAD_SOPORTADA = "videollamada"
DIAS_BUSQUEDA = 14


@dataclass
class ResultadoA3:
    version: VersionPacto | None
    faltantes: list[str] = field(default_factory=list)


def _ventanas_utc(
    p: PerfilEncuentro, zona: tzinfo, desde_utc: datetime, dias: int
) -> list[tuple[datetime, datetime]]:
    """Convierte la disponibilidad semanal local en intervalos UTC concretos."""
    primer_dia_local = desde_utc.astimezone(zona).date()
    ventanas = []
    for i in range(dias + 1):
        fecha = primer_dia_local + timedelta(days=i)
        nombre_dia = DIAS_SEMANA[fecha.weekday()]
        for franja in p.disponibilidad:
            if franja.dia != nombre_dia:
                continue
            ini = datetime.combine(fecha, franja.inicio, tzinfo=zona).astimezone(UTC)
            fin = datetime.combine(fecha, franja.fin, tzinfo=zona).astimezone(UTC)
            ventanas.append((ini, fin))
    return ventanas


def resolver_zonas(
    a: PerfilEncuentro, b: PerfilEncuentro, resolver: ResolverZona
) -> tuple[dict[str, tzinfo], list[str]]:
    zonas: dict[str, tzinfo] = {}
    faltantes: list[str] = []
    for p in (a, b):
        if not p.zona_horaria:
            faltantes.append(f"{p.nombre}: zona horaria")
            continue
        try:
            zonas[p.id] = resolver(p.zona_horaria)
        except ZonaNoDisponible as exc:
            faltantes.append(f"{p.nombre}: {exc}")
    return zonas, faltantes


def faltantes_de_minutos(p: PerfilEncuentro) -> list[str]:
    """Lo que impide usar el aporte de minutos de esta persona."""
    if not isinstance(p.minutos, int) or isinstance(p.minutos, bool) or p.minutos <= 0:
        return [f"{p.nombre}: minutos por sesión"]
    if p.minutos_pendientes_revision:
        return [f"{p.nombre}: minutos por sesión pendientes de revisión humana "
                "(podrían representar la duración total y no el aporte de la persona)"]
    return []


def duracion_total(a: PerfilEncuentro, b: PerfilEncuentro) -> timedelta:
    """Duración del encuentro = suma de los minutos que ofrece enseñar cada persona."""
    return timedelta(minutes=a.minutos + b.minutos)


def disponible_durante(p: PerfilEncuentro, zona: tzinfo, inicio_utc: datetime, fin_utc: datetime) -> bool:
    """True si una sola franja de la persona cubre todo el intervalo [inicio, fin)."""
    ventanas = _ventanas_utc(p, zona, inicio_utc - timedelta(days=1), 2)
    return any(ini <= inicio_utc and fin_utc <= fin for ini, fin in ventanas)


def inicios_comunes(
    a: PerfilEncuentro,
    b: PerfilEncuentro,
    zonas: dict[str, tzinfo],
    desde_utc: datetime,
    duracion: timedelta,
    dias: int = DIAS_BUSQUEDA,
    excluidos: Iterable[datetime] = (),
) -> list[datetime]:
    """Inicios (UTC, ordenados) en los que ambas personas están disponibles
    desde el inicio hasta el final de la duración completa."""
    limite = desde_utc + timedelta(days=dias)
    excluidos = set(excluidos)
    candidatos = set()
    for ia, fa in _ventanas_utc(a, zonas[a.id], desde_utc, dias):
        for ib, fb in _ventanas_utc(b, zonas[b.id], desde_utc, dias):
            ini, fin = max(ia, ib, desde_utc), min(fa, fb)
            if fin - ini >= duracion and ini < limite and ini not in excluidos:
                candidatos.add(ini)
    return sorted(candidatos)


def proponer_pacto(
    match: PropuestaMatch,
    a: PerfilEncuentro,
    b: PerfilEncuentro,
    desde_utc: datetime,
    resolver: ResolverZona,
    numero: int = 1,
    inicios_excluidos: Iterable[datetime] = (),
    dias_busqueda: int = DIAS_BUSQUEDA,
) -> ResultadoA3:
    if desde_utc.tzinfo is None:
        raise ValueError("desde_utc debe incluir zona horaria (UTC)")
    if (a.id, b.id) != (match.participante_a, match.participante_b):
        raise ValueError("Los participantes no corresponden al match")

    zonas, faltantes = resolver_zonas(a, b, resolver)
    for p in (a, b):
        if not p.disponibilidad:
            faltantes.append(f"{p.nombre}: disponibilidad")
        faltantes.extend(faltantes_de_minutos(p))
        if p.acepta_virtual is not True:
            faltantes.append(f"{p.nombre}: no consta que acepte participar por {MODALIDAD_SOPORTADA}")
    if not (match.a_ensena and match.b_ensena):
        faltantes.append("el match no tiene temas recíprocos")
    if faltantes:
        return ResultadoA3(None, faltantes)

    duracion = duracion_total(a, b)
    inicios_excluidos = list(inicios_excluidos)
    candidatos = inicios_comunes(a, b, zonas, desde_utc, duracion, dias_busqueda, inicios_excluidos)
    if not candidatos:
        return ResultadoA3(
            None,
            [
                f"no hay una franja común de {int(duracion.total_seconds() // 60)} min "
                f"en los {dias_busqueda} días desde {desde_utc:%Y-%m-%d} (UTC)"
                + (" sin repetir horarios ya propuestos" if inicios_excluidos else "")
            ],
        )

    version = VersionPacto(
        numero=numero,
        objetivos={a.id: ", ".join(match.a_ensena), b.id: ", ".join(match.b_ensena)},
        modalidad=MODALIDAD_SOPORTADA,
        inicio_utc=candidatos[0],
        minutos={a.id: a.minutos, b.id: b.minutos},
        zonas={a.id: a.zona_horaria, b.id: b.zona_horaria},
    )
    # Defensa adicional: la fecha elegida cubre la duración completa para ambas personas.
    for p in (a, b):
        if not disponible_durante(p, zonas[p.id], version.inicio_utc, version.fin_utc):
            raise AssertionError(f"A3 eligió un horario que no cubre la duración completa de {p.nombre}")
    return ResultadoA3(version)

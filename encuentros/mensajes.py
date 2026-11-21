"""Redacción de mensajes individuales.

Las funciones reciben solo el *nombre* de la otra persona, nunca su ficha,
así que es imposible filtrar su teléfono u otros datos de contacto.
"""
from __future__ import annotations

from .modelos import DIAS_SEMANA, Participante, VersionPacto
from .zonas import ResolverZona, nombre_legible

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def horario_local(version: VersionPacto, participante_id: str, resolver: ResolverZona) -> str:
    zona_nombre = version.zonas[participante_id]
    zona = resolver(zona_nombre)
    ini = version.inicio_utc.astimezone(zona)
    fin = version.fin_utc.astimezone(zona)
    return (
        f"{DIAS_SEMANA[ini.weekday()]} {ini.day} de {MESES[ini.month - 1]} de {ini.year}, "
        f"{ini:%H:%M}–{fin:%H:%M} (hora de {nombre_legible(zona_nombre)})"
    )


def _otra_id(version: VersionPacto, yo: str) -> str:
    return next(pid for pid in version.minutos if pid != yo)


def linea_tiempo(version: VersionPacto, yo: str, nombre_otra: str) -> str:
    """Minutos que enseña cada persona y duración total (suma de ambos aportes)."""
    otra = _otra_id(version, yo)
    return (
        f"• Tiempo: {version.minutos[yo]} min enseñas tú · "
        f"{version.minutos[otra]} min enseña {nombre_otra} · "
        f"duración total: {version.duracion_min} min"
    )


def redactar_invitacion(
    destinatario: Participante, nombre_otra: str, version: VersionPacto, resolver: ResolverZona
) -> str:
    yo = destinatario.id
    otra = _otra_id(version, yo)
    return (
        f"Hola, {destinatario.nombre}.\n"
        f"Te proponemos un encuentro de intercambio con {nombre_otra} "
        f"(propuesta v{version.numero}).\n\n"
        f"• Objetivos: tú compartes {version.objetivos[yo]}; "
        f"{nombre_otra} comparte {version.objetivos[otra]}.\n"
        f"• Modalidad: {version.modalidad}\n"
        f"• Fecha: {horario_local(version, yo, resolver)}\n"
        f"{linea_tiempo(version, yo, nombre_otra)}\n\n"
        "Responde ACEPTO, RECHAZO o CAMBIO (y cuéntanos qué cambiarías).\n"
        "Si aceptas, aceptas también este reparto de minutos y la duración total.\n"
        "El encuentro solo se confirma cuando ambas personas aceptan."
    )


def redactar_confirmacion(
    destinatario: Participante,
    nombre_otra: str,
    version: VersionPacto,
    enlace: str,
    resolver: ResolverZona,
) -> str:
    return (
        f"¡Confirmado, {destinatario.nombre}! Tu encuentro con {nombre_otra} es el "
        f"{horario_local(version, destinatario.id, resolver)}.\n"
        f"{linea_tiempo(version, destinatario.id, nombre_otra)}\n"
        f"Enlace de la videollamada: {enlace}\n"
        "Si necesitas cancelar o cambiar algo, avísanos por este canal."
    )

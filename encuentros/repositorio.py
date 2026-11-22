"""Almacenamiento del piloto: en memoria, con carga desde JSON.

Más adelante, un repositorio de Notion implementaría los mismos métodos.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, time
from pathlib import Path

from .modelos import (
    REVISION_PENDIENTE, EventoBitacora, Franja, Pacto, Participante, PropuestaMatch, Solicitud,
    opciones_multiples,
)


class RepositorioMemoria:
    def __init__(self) -> None:
        self.participantes: dict[str, Participante] = {}
        self.solicitudes: dict[str, Solicitud] = {}
        self.matches: dict[str, PropuestaMatch] = {}
        self.pactos: dict[str, Pacto] = {}
        self.ejecuciones_a2: dict[str, object] = {}   # clave de ejecución -> ResultadoA2
        self.bitacora: list[EventoBitacora] = []

    def participante(self, participante_id: str) -> Participante:
        try:
            return self.participantes[participante_id]
        except KeyError:
            raise KeyError(f"Participante {participante_id!r} no registrado") from None

    def solicitud(self, solicitud_id: str) -> Solicitud:
        try:
            return self.solicitudes[solicitud_id]
        except KeyError:
            raise KeyError(f"Solicitud {solicitud_id!r} no registrada") from None

    def registrar(self, actor: str, accion: str, referencia: str, detalle: str = "") -> None:
        self.bitacora.append(EventoBitacora(datetime.now(UTC), actor, accion, referencia, detalle))


def _franjas(lista: list[dict]) -> list[Franja]:
    return [Franja(f["dia"], time.fromisoformat(f["inicio"]), time.fromisoformat(f["fin"])) for f in lista]


DATOS_DE_CONTACTO_NO_PERMITIDOS = ("telefono", "teléfono", "phone", "celular", "whatsapp")


def participante_desde_dict(d: dict) -> Participante:
    prohibidos = [k for k in d if k.strip().lower() in DATOS_DE_CONTACTO_NO_PERMITIDOS]
    if prohibidos:
        raise ValueError(
            f"Los datos de {d.get('id', '?')!r} incluyen {prohibidos}: el sistema no guarda teléfonos."
        )
    return Participante(
        id=d["id"],
        nombre=d["alias"],
        autoriza_participar=d.get("autoriza_participar") is True,
        aptitud=d.get("aptitud"),
        respaldo_declarado=d.get("respaldo_declarado"),
        revision_respaldo=d.get("revision_respaldo") or REVISION_PENDIENTE,
        idioma=d.get("idioma"),
        tipo_perfil=opciones_multiples(d.get("tipo_perfil")),
    )


def solicitud_desde_dict(d: dict) -> Solicitud:
    return Solicitud(
        id=d["id"],
        participante_id=d["participante_id"],
        tema_ofrece=list(d.get("tema_ofrece", [])),
        tema_busca=list(d.get("tema_busca", [])),
        idioma=d.get("idioma"),
        modalidad=d.get("modalidad"),
        minutos_por_sesion=d.get("minutos_por_sesion"),
        zona_horaria=d.get("zona_horaria"),
        disponibilidad=_franjas(d.get("disponibilidad", [])),
        estado=d.get("estado"),
        acepta_virtual=d.get("acepta_virtual"),
        objetivo_concreto=d.get("objetivo_concreto"),
        version_entrada=d.get("version_entrada"),
        # Solo `false` explícito o ausencia (datos ficticios creados con la regla actual)
        # se toman como aporte revisado; cualquier otro valor exige revisión humana.
        minutos_requieren_revision=d.get("minutos_requieren_revision", False) is not False,
    )


def cargar_datos_json(ruta: str | Path) -> tuple[list[Participante], list[Solicitud]]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return (
        [participante_desde_dict(d) for d in datos["participantes"]],
        [solicitud_desde_dict(d) for d in datos["solicitudes"]],
    )

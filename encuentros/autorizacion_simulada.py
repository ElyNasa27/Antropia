"""AUTORIZACIÓN SIMULADA — NO ES AUTENTICACIÓN.

Este módulo solo sirve para probar, con personas FICTICIAS, qué rol puede hacer
cada paso humano del piloto. Limitaciones que hay que tener presentes:

  - No verifica identidades reales: nadie inicia sesión ni demuestra quién es.
    Cualquiera que ejecute el código puede «actuar como» cualquier persona del
    directorio con `actuar_como(...)`, y cualquiera que edite los archivos puede
    cambiar personas y roles.
  - Los roles son etiquetas simuladas, no permisos de ningún sistema real.
  - La bitácora del piloto es una lista en memoria que se puede modificar: sirve
    para seguir el flujo, no como prueba de quién hizo qué.

Lo que sí garantiza (dentro del propio programa):
  - Un nombre escrito (texto) ya no basta para aprobar o confirmar: hace falta un
    `ActorSimulado` emitido por el directorio que usa la coordinación.
  - La persona debe estar activa y tener un rol que permita la acción.
  - Los agentes (A2, A3) no pueden figurar como personas.

La autenticación real se diseñará aparte (p. ej. con usuarios verificados de Notion).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .modelos import OperacionNoPermitida

AVISO = "simulado: no verifica identidades reales"
AGENTES = frozenset({"A2", "A3"})


class Rol(str, Enum):
    REVISORA = "revisora"
    COORDINADORA = "coordinadora"
    REGISTRO_RESPUESTAS = "registro_respuestas"


class Accion(Enum):
    REVISAR_RESPALDO = "revisar el respaldo declarado"
    REVISAR_MINUTOS = "revisar los minutos por sesión"
    APROBAR_PROPUESTA = "aprobar una propuesta"
    RECHAZAR_PROPUESTA = "rechazar una propuesta"
    REVISAR_PACTO = "revisar el pacto"
    REGISTRAR_RESPUESTA = "registrar una respuesta"
    REVISAR_RESPUESTA = "revisar una respuesta"
    CONFIRMAR_PACTO = "confirmar el pacto"
    APROBAR_BORRADOR = "aprobar un borrador de mensaje"


# Qué roles (simulados) permiten cada acción.
PERMISOS: dict[Accion, frozenset[Rol]] = {
    Accion.REVISAR_RESPALDO: frozenset({Rol.REVISORA}),
    Accion.REVISAR_MINUTOS: frozenset({Rol.REVISORA}),
    Accion.APROBAR_PROPUESTA: frozenset({Rol.REVISORA}),
    Accion.RECHAZAR_PROPUESTA: frozenset({Rol.REVISORA}),
    Accion.REVISAR_PACTO: frozenset({Rol.COORDINADORA}),
    Accion.REGISTRAR_RESPUESTA: frozenset({Rol.COORDINADORA, Rol.REGISTRO_RESPUESTAS}),
    Accion.REVISAR_RESPUESTA: frozenset({Rol.COORDINADORA}),
    Accion.CONFIRMAR_PACTO: frozenset({Rol.COORDINADORA}),
    Accion.APROBAR_BORRADOR: frozenset({Rol.COORDINADORA}),
}


@dataclass(frozen=True)
class PersonaSimulada:
    """Persona FICTICIA del directorio simulado."""

    id: str
    nombre: str
    roles: frozenset[Rol]
    activa: bool = True


@dataclass(frozen=True, eq=False)
class ActorSimulado:
    """«Actuar como» una persona del directorio. No demuestra quién es nadie."""

    persona_id: str
    _directorio: "DirectorioSimulado" = field(repr=False, compare=False)


@dataclass(frozen=True)
class ActorAutorizado:
    """Resultado de una comprobación de permisos (simulada) que se superó."""

    id: str
    nombre: str
    rol: Rol

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre} [{self.id}] · rol «{self.rol.value}» ({AVISO})"


def _es_agente(texto: str) -> bool:
    return texto.strip().upper() in AGENTES


class DirectorioSimulado:
    """Personas ficticias y sus roles simulados. Se fija al crearlo (no se edita)."""

    def __init__(self, personas: list[PersonaSimulada]) -> None:
        self._personas: dict[str, PersonaSimulada] = {}
        for p in personas:
            if not p.id.strip() or not p.nombre.strip():
                raise ValueError("Cada persona simulada necesita id y nombre.")
            if _es_agente(p.id) or _es_agente(p.nombre):
                raise ValueError(f"Un agente no puede figurar como persona: {p.id!r}.")
            if p.id in self._personas:
                raise ValueError(f"Persona simulada repetida: {p.id!r}.")
            if not all(isinstance(r, Rol) for r in p.roles):
                raise ValueError(f"Rol no válido para {p.id!r}.")
            self._personas[p.id] = p

    def personas(self) -> list[PersonaSimulada]:
        return list(self._personas.values())

    def actuar_como(self, persona_id: str) -> ActorSimulado:
        """Simula actuar como una persona del directorio. NO es un inicio de sesión."""
        if persona_id not in self._personas:
            raise OperacionNoPermitida(f"{persona_id!r} no está en el directorio simulado.")
        return ActorSimulado(persona_id, self)

    def autorizar(self, actor: object, accion: Accion) -> ActorAutorizado:
        if not isinstance(actor, ActorSimulado):
            raise OperacionNoPermitida(
                f"Para {accion.value} hace falta un actor del directorio simulado; "
                "un nombre escrito no basta. (Simulación: no verifica identidades reales.)"
            )
        if actor._directorio is not self:
            raise OperacionNoPermitida("El actor pertenece a otro directorio simulado.")
        persona = self._personas.get(actor.persona_id)
        if persona is None:
            raise OperacionNoPermitida(f"{actor.persona_id!r} no está en el directorio simulado.")
        if not persona.activa:
            raise OperacionNoPermitida(f"{persona.nombre} está inactiva en el directorio simulado.")
        permitidos = persona.roles & PERMISOS[accion]
        if not permitidos:
            roles = ", ".join(sorted(r.value for r in persona.roles)) or "ninguno"
            raise OperacionNoPermitida(
                f"{persona.nombre} no tiene un rol que permita {accion.value} "
                f"(roles simulados: {roles})."
            )
        rol = sorted(permitidos, key=lambda r: r.value)[0]
        return ActorAutorizado(persona.id, persona.nombre, rol)


def cargar_directorio_json(ruta: str | Path) -> DirectorioSimulado:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return DirectorioSimulado([
        PersonaSimulada(
            id=d["id"],
            nombre=d["nombre"],
            roles=frozenset(Rol(r) for r in d.get("roles", [])),
            activa=d.get("activa", True) is True,
        )
        for d in datos["personas"]
    ])

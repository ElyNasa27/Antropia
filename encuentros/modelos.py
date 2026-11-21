"""Modelos de datos, alineados con las bases de Notion del piloto (solo lectura).

Participante  ~ base «Participantes»
Solicitud     ~ base «Solicitudes»
PropuestaMatch~ base «Propuestas»
Pacto         ~ base «Pactos»
Ver encuentros/notion_mapa.py para la correspondencia exacta de columnas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum

DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

# Valores de la columna «Revisión humana del respaldo» (Participantes)
REVISION_PENDIENTE = "Pendiente"
REVISION_APROBADA = "Aprobada"
REVISION_NO_REQUERIDA = "No requerida"
REVISIONES_RESPALDO = (REVISION_PENDIENTE, REVISION_APROBADA, REVISION_NO_REQUERIDA)


class OperacionNoPermitida(Exception):
    """Se intentó una acción que las reglas del piloto no permiten."""


@dataclass(frozen=True)
class Franja:
    """Franja semanal de disponibilidad, en la hora local de la persona."""

    dia: str
    inicio: time
    fin: time

    def __post_init__(self) -> None:
        if self.dia not in DIAS_SEMANA:
            raise ValueError(f"Día no válido: {self.dia!r}")
        if self.fin <= self.inicio:
            raise ValueError("La franja debe terminar después de empezar")


@dataclass
class Participante:
    id: str
    nombre: str                                   # «Alias»
    autoriza_participar: bool = False             # «Autorización para participar»
    aptitud: str | None = None                    # «Aptitud»: se requiere "Apto"
    respaldo_declarado: str | None = None         # «Respaldo declarado» (lo declara la persona)
    revision_respaldo: str = REVISION_PENDIENTE   # «Revisión humana del respaldo»
    respaldo_revisado_por: str | None = None      # quién decidió (no hay columna en Notion)
    idioma: str | None = None                     # «Idioma» (informativo; se usa el de la solicitud)
    tipo_perfil: str | None = None                # «Tipo de perfil»
    # Privado: nunca se copia a mensajes, bitácora ni a la otra persona.
    telefono: str | None = field(default=None, repr=False)


@dataclass
class Solicitud:
    id: str
    participante_id: str                          # «Participante» (relación)
    tema_ofrece: list[str]                        # «Tema que ofrece»
    tema_busca: list[str]                         # «Tema que busca»
    idioma: str | None                            # «Idioma»
    modalidad: str | None                         # «Modalidad»: Virtual / Presencial / Mixta
    # «Minutos por sesión»: minutos que ESTA persona ofrece enseñar (su aporte).
    # La duración del encuentro es la suma de los aportes de ambas personas.
    minutos_por_sesion: int | None
    zona_horaria: str | None                      # de «Franja y zona horaria» (zona IANA)
    disponibilidad: list[Franja]                  # de «Franja y zona horaria» (estructurada)
    estado: str | None = None                     # «Estado»: se requiere "Lista"
    acepta_virtual: bool | None = None            # aclaración explícita si la modalidad es Mixta
    objetivo_concreto: str | None = None          # «Objetivo concreto»
    version_entrada: str | None = None            # «Versión de entrada»
    # True si no consta que «Minutos por sesión» signifique el aporte de la persona
    # (p. ej. valores antiguos de Notion que podrían ser la duración total).
    # Nunca se convierte automáticamente: una persona debe revisarlo.
    minutos_requieren_revision: bool = False
    minutos_revisados_por: str | None = None      # sin columna en Notion (ver notion_mapa)


@dataclass(frozen=True)
class PerfilEncuentro:
    """Vista combinada participante + solicitud que usan A2 y A3 para el horario."""

    id: str
    nombre: str
    zona_horaria: str | None
    disponibilidad: list[Franja]
    minutos: int | None                           # aporte: minutos que esta persona enseña
    acepta_virtual: bool | None
    minutos_pendientes_revision: bool = False


def aportes_distintos(minutos: dict[str, int]) -> bool:
    """True si las dos personas ofrecen enseñar una cantidad distinta de minutos."""
    return len(set(minutos.values())) > 1


class DecisionHumana(Enum):
    """«Decisión humana» en Propuestas."""
    PENDIENTE = "Pendiente"
    APROBADA = "Aprobada"
    RECHAZADA = "Rechazada"


class EstadoPacto(Enum):
    FALTA_INFORMACION = "falta información"
    BORRADOR = "borrador (pendiente de revisión humana)"
    INVITACIONES_PREPARADAS = "invitaciones preparadas (esperando respuestas)"
    CAMBIOS_SOLICITADOS = "cambios solicitados"
    RESPUESTAS_POR_REVISAR = "ambas aceptaciones registradas (pendientes de revisión humana)"
    LISTO_PARA_CONFIRMAR = "listo para confirmar"
    CONFIRMADO = "confirmado"
    CERRADO_SIN_PACTO = "cerrado sin pacto"


class TipoRespuesta(Enum):
    PENDIENTE = "pendiente"
    ACEPTA = "acepta"
    RECHAZA = "rechaza"
    CAMBIOS = "solicita cambios"


@dataclass
class PropuestaMatch:
    id: str
    solicitud_origen: str                         # «Solicitud origen»
    solicitud_candidata: str                      # sin columna en Notion (ver notion_mapa)
    participante_a: str                           # «Participante A»
    participante_b: str                           # «Participante B»
    a_ensena: list[str]                           # «Coincidencia A→B»
    b_ensena: list[str]                           # «Coincidencia B→A»
    motivo: str                                   # «Motivo»
    evidencia: dict = field(default_factory=dict) # evidencia de A2 para revisión humana
    clave_ejecucion: str = ""                     # «Clave de ejecución»
    decision: DecisionHumana = DecisionHumana.PENDIENTE
    decidido_por: str | None = None               # id de la persona SIMULADA que decidió
    evidencia_revisada: bool = False
    aportes_distintos_revisados: bool = False      # solo se exige si los aportes difieren
    propuesto_por: str = "A2"

    @property
    def activa(self) -> bool:
        return self.decision is not DecisionHumana.RECHAZADA

    @property
    def requiere_revision_de_aportes(self) -> bool:
        return bool(self.evidencia.get("aportes_distintos"))

    @property
    def es_valida(self) -> bool:
        """Válida solo si una persona la aprobó tras revisar la evidencia
        (y, si los aportes de minutos difieren, también ese reparto)."""
        return (
            self.decision is DecisionHumana.APROBADA
            and self.evidencia_revisada
            and bool(self.evidencia)
            and bool(self.decidido_por)
            and (self.aportes_distintos_revisados or not self.requiere_revision_de_aportes)
        )


@dataclass(frozen=True)
class VersionPacto:
    numero: int
    objetivos: dict[str, str]     # participante_id -> lo que esa persona enseña
    modalidad: str
    inicio_utc: datetime
    minutos: dict[str, int]       # participante_id -> minutos que enseña (su aporte)
    zonas: dict[str, str]         # participante_id -> zona IANA
    propuesto_por: str = "A3"

    @property
    def duracion_min(self) -> int:
        """Duración total del encuentro: suma de los aportes de ambas personas."""
        return sum(self.minutos.values())

    @property
    def duracion(self) -> timedelta:
        return timedelta(minutes=self.duracion_min)

    @property
    def aportes_distintos(self) -> bool:
        return aportes_distintos(self.minutos)

    @property
    def fin_utc(self) -> datetime:
        return self.inicio_utc + self.duracion


@dataclass
class Respuesta:
    tipo: TipoRespuesta
    version: int                      # versión del pacto a la que responde la persona
    registrado_por: str | None = None # id de la persona SIMULADA que la registró
    origen: str | None = None         # p. ej. "simulación" en el piloto
    comentario: str | None = None
    # Revisión humana (simulada) de la respuesta, ligada a una versión concreta.
    revisada_por: str | None = None
    version_revisada: int | None = None


@dataclass
class Pacto:
    id: str
    match_id: str
    participantes: tuple[str, str]
    clave_ejecucion: str = ""
    versiones: list[VersionPacto] = field(default_factory=list)
    estado: EstadoPacto = EstadoPacto.BORRADOR
    respuestas: dict[str, Respuesta] = field(default_factory=dict)
    faltantes: list[str] = field(default_factory=list)
    revisado_por: str | None = None               # id de persona SIMULADA
    enlace_videollamada: str | None = None
    confirmado_por: str | None = None             # id de persona SIMULADA

    @property
    def version_actual(self) -> VersionPacto | None:
        return self.versiones[-1] if self.versiones else None


@dataclass
class Mensaje:
    id: str
    pacto_id: str
    destinatario_id: str
    tipo: str                         # "invitación" | "confirmación"
    version: int
    texto: str
    estado: str = "pendiente de revisión"
    revisado_por: str | None = None


@dataclass(frozen=True)
class EventoBitacora:
    """Entrada de la bitácora del piloto. La bitácora es una lista en memoria y se
    puede modificar: registra el flujo, pero NO es una prueba inalterable."""

    momento_utc: datetime
    actor: str
    accion: str
    referencia: str
    detalle: str = ""

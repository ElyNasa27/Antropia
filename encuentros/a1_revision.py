"""A1: revisa una respuesta del formulario y prepara un INFORME LOCAL para la
persona revisora.

A1 no decide nada y no escribe en ningún sitio:
  - No escribe ni sugiere en Notion (ni «Faltantes», ni «Aptitud», ni «Estado»).
  - No marca a nadie como Apto ni una solicitud como Lista.
  - No aprueba ni rechaza el respaldo declarado: eso es una revisión humana.
  - No inventa, completa ni corrige datos: solo describe lo que hay y lo que falta.
  - No muestra el correo (solo si está indicado y si su formato parece válido).

La persona revisora lee el informe y es quien decide y escribe en Notion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .formulario import RespuestaFormulario
from .notion_mapa import COLUMNAS_FORMULARIO, OPCIONES
from .zonas import ResolverZona, ZonaNoDisponible, datos_de_zonas_disponibles, resolver_zona_real

# Preguntas obligatorias del formulario (campo -> columna de Notion).
OBLIGATORIOS = (
    "alias", "tipo_perfil", "ofrece", "quiere_aprender", "objetivo_concreto", "idioma",
    "modalidad", "dias_y_franjas", "zona_horaria", "minutos_que_ensena",
)
SELECCIONES = {
    "tipo_perfil": "Participantes.Tipo de perfil",
    "idioma": "Participantes.Idioma",
    "modalidad": "Participantes.Modalidad",
    "acepta_videollamada": "Participantes.Acepta videollamada",
}
FORMATO_IANA = re.compile(r"^[A-Za-z]+(?:/[A-Za-z0-9_+\-]+)+$")
FORMATO_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

AVISO_FINAL = "A1 no ha cambiado nada en Notion ni ha tomado ninguna decisión."


@dataclass
class InformeA1:
    referencia: str
    alias: str
    autoriza_participar: bool
    faltantes: list[str] = field(default_factory=list)      # columnas obligatorias vacías
    observaciones: list[str] = field(default_factory=list)  # datos presentes que la revisora debe mirar
    respaldo: str = ""
    correo: str = ""
    avisos: list[str] = field(default_factory=list)

    @property
    def datos_completos(self) -> bool:
        return not self.faltantes

    def texto(self) -> str:
        lineas = [
            f"Informe A1 · {self.alias} · solo para la persona revisora",
            f"Referencia: {self.referencia}",
            f"Autorización para participar: {'sí' if self.autoriza_participar else 'NO (no puede continuar)'}",
            f"Datos completos: {'sí' if self.datos_completos else 'no'}",
        ]
        lineas += [f"  - Falta: {f}" for f in self.faltantes]
        if self.observaciones:
            lineas.append("Observaciones:")
            lineas += [f"  - {o}" for o in self.observaciones]
        lineas.append(f"Respaldo declarado: {self.respaldo}")
        lineas.append(f"Correo para el aviso de match: {self.correo}")
        lineas += [f"Aviso: {a}" for a in self.avisos]
        lineas.append(AVISO_FINAL)
        return "\n".join(lineas)


def _vacio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def revisar(r: RespuestaFormulario, resolver: ResolverZona = resolver_zona_real) -> InformeA1:
    inf = InformeA1(
        referencia=r.referencia,
        alias=(r.alias or "").strip() or "(sin alias)",
        autoriza_participar=r.autoriza_participar is True,
    )

    for campo in OBLIGATORIOS:
        if _vacio(getattr(r, campo)):
            inf.faltantes.append(COLUMNAS_FORMULARIO[campo])

    for campo, opciones in SELECCIONES.items():
        valor = getattr(r, campo)
        if not _vacio(valor) and valor not in OPCIONES[opciones]:
            inf.observaciones.append(
                f"{COLUMNAS_FORMULARIO[campo]}: valor no reconocido {valor!r} "
                f"(opciones: {', '.join(OPCIONES[opciones])})"
            )

    # Modalidad: el piloto solo coordina por videollamada.
    if r.modalidad == "Mixta":
        if _vacio(r.acepta_videollamada) or r.acepta_videollamada == "No aplica":
            inf.faltantes.append(f"{COLUMNAS_FORMULARIO['acepta_videollamada']} (la modalidad es Mixta)")
        elif r.acepta_videollamada == "No":
            inf.observaciones.append("Modalidad Mixta, pero no acepta videollamada: el piloto solo coordina videollamadas")
    elif r.modalidad == "Presencial":
        inf.observaciones.append("Modalidad Presencial: el piloto solo coordina videollamadas")

    # Zona horaria: formato IANA y que exista.
    if not _vacio(r.zona_horaria):
        zona = r.zona_horaria.strip()
        if not FORMATO_IANA.match(zona):
            inf.observaciones.append(f"Zona horaria {zona!r} no tiene el formato Continente/Ciudad")
        elif not datos_de_zonas_disponibles():
            inf.avisos.append("no se pudo verificar la zona horaria: faltan los datos IANA (tzdata)")
        else:
            try:
                resolver(zona)
            except ZonaNoDisponible:
                inf.observaciones.append(f"Zona horaria {zona!r} no existe en la base IANA")

    # Minutos que enseña: número entero positivo.
    m = r.minutos_que_ensena
    if not _vacio(m):
        if isinstance(m, bool) or not isinstance(m, (int, float)):
            inf.observaciones.append(f"Minutos que enseña por encuentro: valor no numérico {m!r}")
        elif m <= 0:
            inf.observaciones.append(f"Minutos que enseña por encuentro: debe ser mayor que 0 (es {m})")
        elif m != int(m):
            inf.observaciones.append(f"Minutos que enseña por encuentro: no es un número entero ({m})")

    # Disponibilidad: hoy es texto libre; A1 no la interpreta.
    if not _vacio(r.dias_y_franjas):
        inf.observaciones.append(
            "Días y franjas en texto libre: una persona debe pasarlos a formato estructurado "
            "antes de crear la solicitud (A1 no los interpreta)"
        )

    inf.respaldo = (
        "sí; pendiente de revisión humana (A1 no lo aprueba)"
        if not _vacio(r.respaldo_declarado)
        else "no declarado (la persona revisora decide)"
    )

    if _vacio(r.correo):
        inf.correo = "no indicado (no recibirá el aviso de match por correo)"
    elif FORMATO_CORREO.match(r.correo.strip()):
        inf.correo = "indicado (no se muestra aquí)"
    else:
        inf.correo = "indicado, pero el formato no parece válido (no se muestra aquí)"

    if r.columnas_ignoradas:
        inf.avisos.append(
            "se ignoraron columnas internas o desconocidas: " + ", ".join(r.columnas_ignoradas)
        )
    return inf

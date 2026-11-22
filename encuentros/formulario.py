"""Respuestas del formulario «Antropia: comparte lo que sabes, aprende lo que sueñas».

El formulario es una vista nativa de Notion sobre la base Participantes: cada
respuesta crea una fila con las columnas de `notion_mapa.COLUMNAS_FORMULARIO`.
Este módulo representa esa fila tal como llega, SIN interpretarla:

  - No incluye campos internos (Aptitud, Revisión humana del respaldo, Faltantes,
    ID): si vienen en los datos, se ignoran y se avisa.
  - «Tipo de perfil» es de selección múltiple: se guarda como tupla de opciones.
  - Rechaza cualquier dato de contacto que no sea el correo (p. ej. teléfono).
  - El correo es privado: no aparece en `repr`, ni en informes, ni en mensajes.

Hoy los datos se cargan desde JSON ficticio. La lectura desde Notion es una
etapa posterior (no hay ninguna llamada a la API aquí).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .notion_mapa import CAMPOS_INTERNOS_PARTICIPANTES, COLUMNAS_FORMULARIO
from .modelos import opciones_multiples
from .repositorio import DATOS_DE_CONTACTO_NO_PERMITIDOS

COLUMNA_A_CAMPO = {columna: campo for campo, columna in COLUMNAS_FORMULARIO.items()}


@dataclass(frozen=True)
class RespuestaFormulario:
    """Una respuesta del formulario, con los nombres de las columnas de Notion."""

    alias: str | None = None
    tipo_perfil: tuple[str, ...] = ()           # selección múltiple
    ofrece: str | None = None
    quiere_aprender: str | None = None
    objetivo_concreto: str | None = None
    idioma: str | None = None
    modalidad: str | None = None
    acepta_videollamada: str | None = None      # «Sí» / «No» / «No aplica»
    dias_y_franjas: str | None = None           # columna «Disponibilidad + zona horaria»
    zona_horaria: str | None = None
    minutos_que_ensena: float | int | None = None
    respaldo_declarado: str | None = None
    autoriza_participar: bool | None = None
    correo: str | None = field(default=None, repr=False)   # privado
    referencia: str = ""                        # p. ej. URL de la fila; solo para la revisora
    columnas_ignoradas: tuple[str, ...] = ()    # internas o desconocidas que venían en los datos


def respuesta_desde_columnas(fila: dict, referencia: str = "") -> RespuestaFormulario:
    """Crea una respuesta a partir de {columna de Notion: valor}."""
    contacto = [k for k in fila if k.strip().lower() in DATOS_DE_CONTACTO_NO_PERMITIDOS]
    if contacto:
        raise ValueError(f"La respuesta incluye {contacto}: el sistema no guarda teléfonos.")
    valores, ignoradas = {}, []
    for columna, valor in fila.items():
        if columna.startswith("_"):
            continue                            # notas del archivo ficticio
        campo = COLUMNA_A_CAMPO.get(columna)
        if campo is None or columna in CAMPOS_INTERNOS_PARTICIPANTES:
            ignoradas.append(columna)
            continue
        valores[campo] = opciones_multiples(valor) if campo == "tipo_perfil" else valor
    return RespuestaFormulario(**valores, referencia=referencia, columnas_ignoradas=tuple(ignoradas))


def cargar_respuestas_json(ruta: str | Path) -> list[RespuestaFormulario]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    return [
        respuesta_desde_columnas(fila, referencia=fila.get("_referencia", f"fila-{i}"))
        for i, fila in enumerate(datos["respuestas"], start=1)
    ]

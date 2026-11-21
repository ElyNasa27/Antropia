"""Correspondencia entre el código y las columnas REALES de Notion (leídas en solo
lectura el 2026-11-21). No contiene ninguna llamada a la API de Notion.

Sirve para la futura integración: el repositorio de Notion usará estos nombres
sin renombrar nada en Notion.
"""
from __future__ import annotations

from .modelos import EstadoPacto

COLUMNAS_PARTICIPANTES = {
    "id": "ID",
    "nombre": "Alias",
    "autoriza_participar": "Autorización para participar",
    "aptitud": "Aptitud",
    "respaldo_declarado": "Respaldo declarado",
    "revision_respaldo": "Revisión humana del respaldo",
    "idioma": "Idioma",
    "tipo_perfil": "Tipo de perfil",
    # También existen y aún no se usan: «Modalidad», «Minutos disponibles», «Ofrece»,
    # «Quiere aprender», «Disponibilidad + zona horaria», «Faltantes».
}

COLUMNAS_SOLICITUDES = {
    "id": "ID",
    "titulo": "Solicitud",
    "participante_id": "Participante",
    "tema_ofrece": "Tema que ofrece",
    "tema_busca": "Tema que busca",
    "idioma": "Idioma",
    "modalidad": "Modalidad",
    "minutos_por_sesion": "Minutos por sesión",               # = minutos que la persona enseña (ver abajo)
    "zona_horaria+disponibilidad": "Franja y zona horaria",   # texto libre en Notion
    "objetivo_concreto": "Objetivo concreto",
    "estado": "Estado",
    "faltantes": "Faltantes",
    "version_entrada": "Versión de entrada",
}

COLUMNAS_PROPUESTAS = {
    "id": "ID",
    "solicitud_origen": "Solicitud origen",
    "participante_a": "Participante A",
    "participante_b": "Participante B",
    "a_ensena": "Coincidencia A→B",
    "b_ensena": "Coincidencia B→A",
    "evidencia.horario_comun_utc": "Horario común",
    "evidencia.duracion_propuesta_min": "Duración propuesta",
    "motivo": "Motivo",
    "resultado": "Resultado",
    "datos_pendientes": "Datos pendientes",
    "decision": "Decisión humana",
    "clave_ejecucion": "Clave de ejecución",
}

COLUMNAS_PACTOS = {
    "id": "ID",
    "match_id": "Propuesta",
    "objetivo_a": "Objetivo A",
    "objetivo_b": "Objetivo B",
    "minutos_a": "Minutos A",     # minutos que enseña A
    "minutos_b": "Minutos B",     # minutos que enseña B; duración total = A + B
    "modalidad": "Modalidad",
    "inicio_utc": "Fecha",
    "zona_horaria": "Zona horaria",
    "respuesta_a": "Evidencia aceptación A",
    "respuesta_b": "Evidencia aceptación B",
    "confirmado_por": "Cierre humano",
    "faltantes": "Datos pendientes",
    "estado": "Estado",
    "clave_ejecucion": "Clave de ejecución",
    # «Sesiones» existe; el piloto asume 1 sesión.
}

# Opciones reales de las listas de selección.
OPCIONES = {
    "Participantes.Aptitud": ("Pendiente", "Apto", "Incompleto", "Sin autorización"),
    "Participantes.Revisión humana del respaldo": ("Pendiente", "Aprobada", "No requerida"),
    "Solicitudes.Estado": ("Nueva", "Incompleta", "Lista", "Procesada", "Sin coincidencia", "Bloqueada"),
    "Solicitudes.Modalidad": ("Virtual", "Presencial", "Mixta"),
    "Solicitudes.Idioma": ("Español", "Inglés", "Portugués"),
    "Propuestas.Resultado": ("Propuesta", "Sin coincidencia", "Bloqueada"),
    "Propuestas.Decisión humana": ("Pendiente", "Aprobada", "Rechazada"),
    "Pactos.Estado": ("Borrador", "Pendiente de aceptación", "Confirmado", "En curso", "Completado", "Cancelado"),
    "Pactos.Modalidad": ("Virtual", "Presencial", "Mixta"),
}

# Estados locales del pacto -> «Estado» de Pactos.
ESTADO_PACTO_A_NOTION = {
    EstadoPacto.FALTA_INFORMACION: "Borrador",           # + «Datos pendientes»
    EstadoPacto.BORRADOR: "Borrador",
    EstadoPacto.INVITACIONES_PREPARADAS: "Pendiente de aceptación",
    EstadoPacto.CAMBIOS_SOLICITADOS: "Borrador",         # A3 debe preparar otra versión
    EstadoPacto.RESPUESTAS_POR_REVISAR: "Pendiente de aceptación",  # falta revisar las aceptaciones
    EstadoPacto.LISTO_PARA_CONFIRMAR: "Pendiente de aceptación",  # falta el cierre humano
    EstadoPacto.CONFIRMADO: "Confirmado",
    EstadoPacto.CERRADO_SIN_PACTO: "Cancelado",
}

# Interpretación acordada de «Minutos por sesión» (Solicitudes): minutos que esa
# persona ofrece enseñar. La duración del encuentro es la suma de ambos aportes.
#
# Valores YA existentes en Notion: algunos podrían representar la duración total.
# La futura integración debe cargarlos con `minutos_requieren_revision=True` y
# NUNCA convertirlos (ni dividir ni copiar): una persona escribe el aporte con
# Coordinacion.revisar_minutos_por_sesion(). Hasta entonces, A2 y A3 los bloquean.
INTERPRETACION_MINUTOS = "aporte por persona"
MINUTOS_EXISTENTES_EN_NOTION_REQUIEREN_REVISION = True

# Datos que el flujo necesita y que hoy NO tienen columna en Notion.
# No se ha creado nada: son cambios a decidir por una persona.
SIN_COLUMNA_EN_NOTION = (
    "Pactos: revisión humana de cada aceptación y versión revisada",
    "Personas que revisan: hoy son un directorio SIMULADO; en Notion harían falta usuarios verificados",
    "Solicitudes: marca de que «Minutos por sesión» fue revisado como aporte (y quién lo revisó)",
    "Propuestas: revisión humana de aportes de minutos distintos",
    "Pactos: duración total (podría ser una fórmula «Minutos A» + «Minutos B»)",
    "Pactos: enlace de la videollamada (lo agrega una persona al confirmar)",
    "Pactos: versión del pacto (las aceptaciones van ligadas a una versión)",
    "Pactos: zona horaria de cada participante («Zona horaria» es una sola)",
    "Propuestas: solicitud candidata (solo existe «Solicitud origen»)",
    "Solicitudes: aclaración de si acepta lo virtual cuando la modalidad es «Mixta»",
    "Solicitudes: disponibilidad estructurada («Franja y zona horaria» es texto libre)",
    "Participantes: quién hizo la revisión humana del respaldo",
)

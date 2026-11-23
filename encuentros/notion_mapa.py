"""Correspondencia entre el código y las columnas REALES de Notion (leídas en solo
lectura el 2026-11-21). No contiene ninguna llamada a la API de Notion.

Sirve para la futura integración: el repositorio de Notion usará estos nombres
sin renombrar nada en Notion.
"""
from __future__ import annotations

from .modelos import DIAS_SEMANA, EstadoPacto

COLUMNAS_PARTICIPANTES = {
    "id": "ID consecutivo",                  # «ID» se eliminó el 2026-11-22
    "nombre": "Alias",
    "autoriza_participar": "Autorización para participar",
    "aptitud": "Aptitud",
    "respaldo_declarado": "Respaldo declarado",
    "revision_respaldo": "Revisión humana del respaldo",
    "idioma": "Idioma",
    "tipo_perfil": "Tipo de perfil",              # selección múltiple (ver SELECCION_MULTIPLE)
    # El resto de columnas se usan en el formulario (ver COLUMNAS_FORMULARIO).
}

# Columnas reales de Participantes, releídas en solo lectura el 2026-11-21.
# «Minutos que enseña por encuentro» ya NO existe: el formulario pregunta los
# minutos de enseñanza en «Minutos disponibles». «Tipo de perfil» es de
# selección múltiple.
COLUMNAS_REALES_PARTICIPANTES = frozenset({
    "Alias", "Tipo de perfil", "Ofrece", "Quiere aprender", "Objetivo concreto", "Idioma",
    "Modalidad", "Acepta videollamada", "Disponibilidad + zona horaria", "Zona horaria",
    "Minutos disponibles", "Respaldo declarado",
    "Autorización para participar", "Correo electrónico",
    "Aptitud", "Revisión humana del respaldo", "Faltantes", "ID",
})

# ---------------------------------------------------------------------------
# Formulario nuevo (esquema releído en solo lectura el 2026-11-22).
# Etapa 1: estas columnas solo se LEEN (automatico.Persona); todavía no cambian
# la elegibilidad ni los horarios. Las columnas anteriores se conservan.
# ---------------------------------------------------------------------------
COLUMNA_OTRO_IDIOMA = "Otro idioma"                       # texto; se usa si «Idioma» incluye «Otro»
COLUMNA_ZONA_SELECCIONADA = "Zona horaria seleccionada"   # selección (nombres IANA)
COLUMNA_DIAS_DISPONIBLES = "Días disponibles"             # selección múltiple
COLUMNA_MINUTOS_SELECCIONADOS = "Minutos seleccionados"   # 15…120 u «Otro» (-> «Minutos disponibles»)
# día (como en modelos.DIAS_SEMANA) -> columna
COLUMNAS_FRANJAS = {d: f"Franjas {d.capitalize()}" for d in DIAS_SEMANA}           # selección múltiple
COLUMNAS_OTRAS_FRANJAS = {d: f"Otras franjas {d.capitalize()}" for d in DIAS_SEMANA}  # texto («Otro»)
# Existen en Notion pero NO se usan (decisión del 2026-11-22): mientras estén
# vacías se ignoran; si tienen datos solo se avisa, sin mostrarlos ni borrarlos.
COLUMNAS_TEMAS_ADICIONALES = tuple(
    f"{base} {n}" for base in ("Ofrece", "Quiere aprender") for n in range(2, 8)
)
COLUMNAS_NUEVAS_PARTICIPANTES = frozenset({
    COLUMNA_OTRO_IDIOMA, COLUMNA_ZONA_SELECCIONADA, COLUMNA_DIAS_DISPONIBLES,
    COLUMNA_MINUTOS_SELECCIONADOS, *COLUMNAS_FRANJAS.values(), *COLUMNAS_OTRAS_FRANJAS.values(),
    *COLUMNAS_TEMAS_ADICIONALES,
})
COLUMNA_ID_CONSECUTIVO = "ID consecutivo"                 # numeración automática de Notion
# Eliminadas de Notion el 2026-11-22 (el usuario copió antes el único valor de
# «Zona horaria» a «Zona horaria seleccionada»). El ciclo automático ya no las lee;
# siguen en COLUMNAS_FORMULARIO solo por la ruta manual con JSON ficticio.
COLUMNAS_ELIMINADAS_PARTICIPANTES = frozenset({"ID", "Acepta videollamada", "Zona horaria"})
COLUMNAS_REALES_PARTICIPANTES = (
    (COLUMNAS_REALES_PARTICIPANTES | COLUMNAS_NUEVAS_PARTICIPANTES | {COLUMNA_ID_CONSECUTIVO})
    - COLUMNAS_ELIMINADAS_PARTICIPANTES
)

OPCION_OTRO = "Otro"
# Opciones del formulario nuevo, según la descripción del 2026-11-22.
OPCIONES_FRANJA = tuple(f"{h:02d}:00–{h + 1:02d}:00" for h in range(24)) + (OPCION_OTRO,)
# «Minutos seleccionados»: el formulario muestra etiquetas como «15 minutos».
# PENDIENTE DE VERIFICAR en el esquema: la lista de opciones no se pudo leer (la
# respuesta completa del esquema supera el tamaño permitido y las opciones no
# aparecen en las consultas agregadas mientras ninguna fila las use). Se toman
# las etiquetas del formulario; en la etapa 7 se confirmará con un recuento de
# los valores usados y, si difieren, se ajusta solo este mapa.
MINUTOS_POR_OPCION = {f"{m} minutos": m for m in (15, 30, 45, 60, 90, 120)}
OPCIONES_MINUTOS = (*MINUTOS_POR_OPCION, OPCION_OTRO)


def minutos_de_opcion(etiqueta: str | None) -> int | None:
    """Minutos de una etiqueta exacta («30 minutos» -> 30). «Otro», vacía o
    desconocida -> None (no se adivina: «Otro» se lee en «Minutos disponibles»).
    Aún no se usa en las reglas (etapa 7)."""
    return MINUTOS_POR_OPCION.get(" ".join((etiqueta or "").split()))

# Preguntas del formulario «Antropia: comparte lo que sabes, aprende lo que sueñas»
# -> columna de Participantes (campo de encuentros.formulario.RespuestaFormulario).
COLUMNAS_FORMULARIO = {
    "alias": "Alias",
    "tipo_perfil": "Tipo de perfil",
    "ofrece": "Ofrece",
    "quiere_aprender": "Quiere aprender",
    "objetivo_concreto": "Objetivo concreto",
    "idioma": "Idioma",
    "modalidad": "Modalidad",
    "acepta_videollamada": "Acepta videollamada",
    "dias_y_franjas": "Disponibilidad + zona horaria",   # se usa para días y franjas
    "zona_horaria": "Zona horaria",
    "minutos_que_ensena": "Minutos disponibles",         # minutos que la persona enseña
    "respaldo_declarado": "Respaldo declarado",
    "autoriza_participar": "Autorización para participar",
    "correo": "Correo electrónico",                       # privado
}

# Campos internos: nunca forman parte del formulario ni los escribe quien responde.
CAMPOS_INTERNOS_PARTICIPANTES = frozenset({
    "Aptitud", "Revisión humana del respaldo", "Faltantes", "ID", "ID consecutivo",
})

# Columnas de selección múltiple: su valor es una lista de opciones.
SELECCION_MULTIPLE = frozenset({"Participantes.Tipo de perfil"})

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
    "Participantes.Tipo de perfil": ("Titulado", "Empírico", "Tutor", "Mentor", "Emprendedor", "Público general"),
    "Participantes.Idioma": ("Español", "Inglés", "Portugués"),
    "Participantes.Modalidad": ("Virtual", "Presencial", "Mixta"),
    "Participantes.Acepta videollamada": ("Sí", "No", "No aplica"),
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
    "Solicitudes: aclaración de si acepta lo virtual cuando la modalidad es «Mixta» "
    "(en Participantes ya existe «Acepta videollamada»)",
    "Solicitudes: disponibilidad estructurada («Franja y zona horaria» es texto libre)",
    "Participantes: quién hizo la revisión humana del respaldo",
)

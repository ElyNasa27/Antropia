"""A2: propone candidatos para cada solicitud. No aprueba nada.

Requisitos de la PERSONA (base Participantes):
  - «Autorización para participar» marcada (True explícito).
  - «Aptitud» = Apto.
  - Respaldo declarado resuelto por una persona (ver estado_respaldo).
Requisito de la SOLICITUD (base Solicitudes): «Estado» = Lista.

Criterios del PAR (solicitud origen A ↔ solicitud candidata B):
  - Reciprocidad: A ofrece algo que B busca Y B ofrece algo que A busca, las dos
    con claridad. Cada dirección se analiza por separado con un analizador de
    temas (temas_semantica.py): por defecto, solo las reglas locales de temas.py
    (igual, sinónimo o tema definido); opcionalmente, además, un análisis por
    significado («semántico») para lo que las reglas no resuelven. Si alguna
    dirección «requiere aclaración», el par queda «Bloqueada»: no se propone.
    Si alguna dirección «no cubre», es «sin reciprocidad».
  - Al menos un idioma en común (o el mismo idioma, en el formato anterior).
  - Dos filas con el mismo alias (sin distinguir mayúsculas, tildes ni espacios)
    podrían ser la misma persona con correos distintos: ESE PAR queda «Bloqueada»
    hasta que se aclare. Cada perfil puede seguir emparejándose con otras personas.
  - Modalidad compatible con videollamada (Virtual, o Mixta con aceptación
    explícita de lo virtual; si no consta, se pide aclaración).
  - Horario común real (UTC) durante TODA la duración del encuentro, que es la
    suma de los minutos que ofrece enseñar cada persona («Minutos por sesión»).
  - Si los aportes de minutos son distintos, la propuesta se permite pero queda
    marcada («aportes_distintos») y una persona debe revisarlos al aprobarla.
  - Minutos sin revisar (p. ej. valores antiguos que podrían ser la duración
    total) bloquean el par: no se convierten automáticamente.

Resultado por par, como en la columna «Resultado» de Propuestas:
  "Propuesta" | "Sin coincidencia" | "Bloqueada" (faltan datos o aclaraciones).

Límite: cada solicitud participa como máximo en MAX_CANDIDATOS_POR_SOLICITUD
propuestas activas (como origen o como candidata). Las propuestas rechazadas
no cuentan.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable

from .idiomas import idiomas_comunes
from .a3_pacto import (
    DIAS_BUSQUEDA, MODALIDAD_SOPORTADA, duracion_total, faltantes_de_minutos,
    inicios_comunes, resolver_zonas,
)
from .modelos import (
    APTITUD_AUTOMATICA, RESPALDO_SIN_VERIFICAR_NO_USADO, REVISION_APROBADA,
    REVISION_NO_REQUERIDA, PerfilEncuentro, Participante, PropuestaMatch, Solicitud,
    aportes_distintos,
)
from .temas import FUERZA, REQUIERE_ACLARACION, coincidencias
from .temas_semantica import ANALIZADOR_REGLAS, NO_CUBRE, REQUIERE, AnalizadorTemas
from .zonas import ResolverZona

MAX_CANDIDATOS_POR_SOLICITUD = 3
APTITUD_REQUERIDA = "apto"
ESTADO_SOLICITUD_REQUERIDO = "lista"

PROPUESTA, SIN_COINCIDENCIA, BLOQUEADA = "Propuesta", "Sin coincidencia", "Bloqueada"


POSIBLE_MISMA_PERSONA = (
    "posible misma persona (mismo alias en dos filas); requiere aclaración; no se propone este par"
)


def mismo_alias(pa: Participante, pb: Participante) -> bool:
    a, b = _normalizar(pa.nombre or ""), _normalizar(pb.nombre or "")
    return bool(a) and a == b


def _normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios simples («Inglés» = «ingles»)."""
    sin = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(sin.lower().split())


# «Apto» escrito por una persona o «Apto (automático)» calculado por el ciclo automático.
APTITUDES_VALIDAS = frozenset({APTITUD_REQUERIDA, _normalizar(APTITUD_AUTOMATICA)})


# --- Requisitos de la persona -------------------------------------------------

def estado_respaldo(p: Participante) -> tuple[bool, str | None]:
    """(puede_continuar, motivo_si_no). Nunca aprueba automáticamente.

    - "Aprobada": continúa solo si hay respaldo declarado y consta quién lo revisó.
    - "No requerida": continúa solo si NO hay ninguna afirmación de respaldo;
      si la hay, es una contradicción y se pide revisión humana.
    - "Pendiente" (o cualquier otro valor): no continúa.
    """
    tiene_respaldo = bool(p.respaldo_declarado and p.respaldo_declarado.strip())
    if p.revision_respaldo == RESPALDO_SIN_VERIFICAR_NO_USADO:
        # Solo lo asigna el ciclo automático, y solo tras descartar el respaldo del modelo.
        if tiene_respaldo:
            return False, "respaldo sin verificar presente en el modelo; requiere revisión humana"
        return True, None
    if p.revision_respaldo == REVISION_APROBADA:
        if not tiene_respaldo:
            return False, "contradicción: respaldo «Aprobada» sin respaldo declarado; requiere revisión humana"
        if not p.respaldo_revisado_por:
            return False, "respaldo «Aprobada» sin persona revisora registrada; requiere revisión humana"
        return True, None
    if p.revision_respaldo == REVISION_NO_REQUERIDA:
        if tiene_respaldo:
            return False, ("contradicción: hay respaldo declarado pero la revisión figura como "
                           "«No requerida»; requiere revisión humana")
        return True, None
    return False, "respaldo declarado pendiente de revisión humana"


def motivos_participante_no_elegible(p: Participante) -> list[str]:
    motivos = []
    if p.autoriza_participar is not True:
        motivos.append("sin autorización para participar")
    if _normalizar(p.aptitud or "") not in APTITUDES_VALIDAS:
        motivos.append(f"aptitud no Apto (aptitud: {p.aptitud or 'sin valor'})")
    ok, motivo = estado_respaldo(p)
    if not ok:
        motivos.append(motivo)
    return motivos


def motivos_solicitud_no_lista(s: Solicitud) -> list[str]:
    if _normalizar(s.estado or "") != ESTADO_SOLICITUD_REQUERIDO:
        return [f"solicitud no Lista (estado: {s.estado or 'sin estado'})"]
    return []


# --- Criterios del par ----------------------------------------------------------

def temas_en_comun(ofrece: Iterable[str], busca: Iterable[str]) -> list[str]:
    """Etiquetas de los temas ofrecidos que coinciden con lo buscado (ver temas.py)."""
    return [c.etiqueta for c in coincidencias(ofrece, busca)]


def acepta_virtual(s: Solicitud) -> bool | None:
    """True / False, o None si no está claro (Mixta sin aclaración, o sin modalidad)."""
    modalidad = _normalizar(s.modalidad or "")
    if modalidad == "virtual":
        return True
    if modalidad == "presencial":
        return False
    if modalidad == "mixta":
        return s.acepta_virtual if isinstance(s.acepta_virtual, bool) else None
    return None


def perfil(p: Participante, s: Solicitud) -> PerfilEncuentro:
    return PerfilEncuentro(
        id=p.id, nombre=p.nombre, zona_horaria=s.zona_horaria,
        disponibilidad=list(s.disponibilidad), minutos=s.minutos_por_sesion,
        acepta_virtual=acepta_virtual(s),
        minutos_pendientes_revision=s.minutos_requieren_revision is not False,
    )


@dataclass
class EvaluacionPar:
    resultado: str
    evidencia: dict | None = None
    motivos: list[str] = field(default_factory=list)          # sin coincidencia
    datos_pendientes: list[str] = field(default_factory=list)  # bloqueada
    primer_inicio: datetime | None = None
    aclaraciones_temas: list[str] = field(default_factory=list)  # parte de datos_pendientes

    @property
    def requiere_aclaracion_de_temas(self) -> bool:
        return bool(self.aclaraciones_temas)


def evaluar_par(
    pa: Participante, sa: Solicitud, pb: Participante, sb: Solicitud,
    desde_utc: datetime, resolver: ResolverZona, dias: int = DIAS_BUSQUEDA,
    analizador: AnalizadorTemas | None = None,
) -> EvaluacionPar:
    incompatibles: list[str] = []
    pendientes: list[str] = []

    if mismo_alias(pa, pb):
        pendientes.append(POSIBLE_MISMA_PERSONA)

    # Cada dirección por separado: lo que A ofrece frente a lo que B busca, y al revés.
    analizador = analizador or ANALIZADOR_REGLAS
    ra = analizador.analizar(sa.tema_ofrece, sb.tema_busca)
    rb = analizador.analizar(sb.tema_ofrece, sa.tema_busca)
    ca, cb = list(ra.coincidencias), list(rb.coincidencias)
    a_ensena, b_ensena = [c.etiqueta for c in ca], [c.etiqueta for c in cb]
    aclaraciones: list[str] = []
    if NO_CUBRE in (ra.estado, rb.estado):
        incompatibles.append("sin reciprocidad")      # una dirección no cubre lo buscado
    else:
        for quien, otra, r in ((pa, pb, ra), (pb, pa, rb)):
            if r.estado == REQUIERE:                  # sin conclusión clara en esta dirección
                aclaraciones += [
                    f"{REQUIERE_ACLARACION} de temas: {quien.nombre} ofrece «{x.ofrece}» y "
                    f"{otra.nombre} busca «{x.busca}» ({x.motivo})" for x in r.aclaraciones
                ]
        pendientes.extend(aclaraciones)

    comunes: tuple[str, ...] = ()
    if not sa.idioma or not sb.idioma:
        for p, s in ((pa, sa), (pb, sb)):
            if not s.idioma:
                pendientes.append(f"{p.nombre}: idioma de la solicitud")
    elif sa.idiomas and sb.idiomas:
        comunes = idiomas_comunes(sa.idiomas, sb.idiomas)
        if not comunes:
            incompatibles.append(f"sin idioma común ({sa.idioma} / {sb.idioma})")
    elif _normalizar(sa.idioma) != _normalizar(sb.idioma):
        incompatibles.append(f"sin idioma común ({sa.idioma} / {sb.idioma})")
    else:
        comunes = (sa.idioma,)

    for p, s in ((pa, sa), (pb, sb)):
        v = acepta_virtual(s)
        if v is False:
            incompatibles.append(f"{p.nombre}: modalidad {s.modalidad} no compatible con {MODALIDAD_SOPORTADA}")
        elif v is None:
            if _normalizar(s.modalidad or "") == "mixta":
                pendientes.append(f"{p.nombre}: modalidad Mixta; requiere aclaración de si acepta participar por {MODALIDAD_SOPORTADA}")
            else:
                pendientes.append(f"{p.nombre}: modalidad")

    a, b = perfil(pa, sa), perfil(pb, sb)
    zonas, faltan_zona = resolver_zonas(a, b, resolver)
    faltan = list(faltan_zona)
    for x in (a, b):
        if not x.disponibilidad:
            faltan.append(f"{x.nombre}: disponibilidad")
        faltan.extend(faltantes_de_minutos(x))
    inicios: list[datetime] = []
    duracion = None
    if faltan:
        pendientes.extend(faltan)
    else:
        duracion = duracion_total(a, b)
        inicios = inicios_comunes(a, b, zonas, desde_utc, duracion, dias)
        if not inicios:
            incompatibles.append(
                f"sin horario común de {int(duracion.total_seconds() // 60)} min "
                f"en los {dias} días desde {desde_utc:%Y-%m-%d} (UTC)"
            )

    if incompatibles:
        return EvaluacionPar(SIN_COINCIDENCIA, motivos=incompatibles, datos_pendientes=pendientes)
    if pendientes:
        return EvaluacionPar(BLOQUEADA, datos_pendientes=pendientes, aclaraciones_temas=aclaraciones)
    minutos = {pa.id: a.minutos, pb.id: b.minutos}
    return EvaluacionPar(
        PROPUESTA,
        evidencia={
            "coincidencia_a_b": a_ensena,
            "coincidencia_b_a": b_ensena,
            # Tipo de cada coincidencia (igual, sinónimo, tema definido) y la más indirecta.
            "tipos_coincidencia": sorted({c.tipo for c in ca + cb}, key=FUERZA.get),
            "fuerza_temas": max(min(FUERZA[c.tipo] for c in ca), min(FUERZA[c.tipo] for c in cb)),
            # Cómo se decidió cada dirección («reglas» o «semántico») y por qué. Es una
            # comparación de temas: no verifica conocimientos, niveles ni respaldos.
            "analisis_temas": {
                "a_b": {"origen": ra.origen, "motivo": ra.motivo},
                "b_a": {"origen": rb.origen, "motivo": rb.motivo},
            },
            "idioma": ", ".join(comunes) or sa.idioma,
            "idiomas_comunes": list(comunes),
            "modalidad": MODALIDAD_SOPORTADA,
            "horario_comun_utc": inicios[0].isoformat(),
            "horarios_comunes_encontrados": len(inicios),
            # Tiempo: aporte de cada persona y duración total (= suma de aportes).
            "minutos_por_persona": minutos,
            "duracion_propuesta_min": int(duracion.total_seconds() // 60),
            "aportes_distintos": aportes_distintos(minutos),   # exige revisión humana
            # Estado de la OTRA revisión (respaldo de cada persona), solo como referencia.
            "revision_respaldo": {pa.id: pa.revision_respaldo, pb.id: pb.revision_respaldo},
            "buscado_desde_utc": desde_utc.isoformat(),
            "dias_busqueda": dias,
        },
        primer_inicio=inicios[0],
    )


# --- Ejecución de A2 --------------------------------------------------------------

@dataclass
class ResumenSolicitud:
    resultado: str = SIN_COINCIDENCIA
    propuestas: list[str] = field(default_factory=list)
    sin_coincidencia: dict[str, list[str]] = field(default_factory=dict)
    bloqueadas: dict[str, list[str]] = field(default_factory=dict)
    omitidas_por_limite: list[str] = field(default_factory=list)
    ya_propuestas: list[str] = field(default_factory=list)


@dataclass
class ResultadoA2:
    clave_ejecucion: str
    propuestas: list[PropuestaMatch] = field(default_factory=list)
    por_solicitud: dict[str, ResumenSolicitud] = field(default_factory=dict)
    excluidas: dict[str, list[str]] = field(default_factory=dict)   # solicitud_id -> motivos


def ejecutar_a2(
    participantes: dict[str, Participante],
    solicitudes: list[Solicitud],
    propuestas_existentes: list[PropuestaMatch],
    desde_utc: datetime,
    resolver: ResolverZona,
    generar_id: Callable[[], str],
    clave_ejecucion: str,
    dias: int = DIAS_BUSQUEDA,
    maximo: int = MAX_CANDIDATOS_POR_SOLICITUD,
    analizador: AnalizadorTemas | None = None,
) -> ResultadoA2:
    res = ResultadoA2(clave_ejecucion)

    elegibles: list[Solicitud] = []
    for s in sorted(solicitudes, key=lambda x: x.id):
        p = participantes[s.participante_id]
        motivos = motivos_participante_no_elegible(p) + motivos_solicitud_no_lista(s)
        if motivos:
            res.excluidas[s.id] = motivos   # no se usa en ningún cálculo
        else:
            elegibles.append(s)

    uso = Counter()
    pares_existentes: dict[frozenset[str], str] = {}
    for m in propuestas_existentes:
        pares_existentes[frozenset((m.participante_a, m.participante_b))] = m.id
        if m.activa:
            uso[m.solicitud_origen] += 1
            uso[m.solicitud_candidata] += 1

    for sa in elegibles:
        pa = participantes[sa.participante_id]
        resumen = res.por_solicitud.setdefault(sa.id, ResumenSolicitud())
        validas: list[tuple[int, datetime, str, Solicitud, EvaluacionPar]] = []
        for sb in elegibles:
            if sb.participante_id == sa.participante_id:
                continue
            par = frozenset((sa.participante_id, sb.participante_id))
            if par in pares_existentes:
                resumen.ya_propuestas.append(sb.id)
                continue
            pb = participantes[sb.participante_id]
            ev = evaluar_par(pa, sa, pb, sb, desde_utc, resolver, dias, analizador)
            if ev.resultado == PROPUESTA:
                validas.append((ev.evidencia["fuerza_temas"], ev.primer_inicio, sb.id, sb, ev))
            elif ev.resultado == BLOQUEADA:
                resumen.bloqueadas[sb.id] = ev.datos_pendientes
            else:
                resumen.sin_coincidencia[sb.id] = ev.motivos

        # Primero las coincidencias de temas más fuertes; luego el horario más próximo.
        for _, _, _, sb, ev in sorted(validas, key=lambda t: (t[0], t[1], t[2])):
            if uso[sa.id] >= maximo or uso[sb.id] >= maximo:
                resumen.omitidas_por_limite.append(sb.id)
                continue
            pb = participantes[sb.participante_id]
            e = ev.evidencia
            m = PropuestaMatch(
                id=generar_id(),
                solicitud_origen=sa.id,
                solicitud_candidata=sb.id,
                participante_a=pa.id,
                participante_b=pb.id,
                a_ensena=e["coincidencia_a_b"],
                b_ensena=e["coincidencia_b_a"],
                motivo=(
                    f"{pa.nombre} ofrece {', '.join(e['coincidencia_a_b'])}, que {pb.nombre} busca; "
                    f"{pb.nombre} ofrece {', '.join(e['coincidencia_b_a'])}, que {pa.nombre} busca. "
                    f"Idioma: {e['idioma']}. Modalidad: {e['modalidad']}. "
                    f"Tiempo: {pa.nombre} enseña {e['minutos_por_persona'][pa.id]} min, "
                    f"{pb.nombre} enseña {e['minutos_por_persona'][pb.id]} min "
                    f"(duración total {e['duracion_propuesta_min']} min)"
                    + ("; aportes distintos: requieren revisión humana" if e["aportes_distintos"] else "")
                    + f". Horarios comunes encontrados: {e['horarios_comunes_encontrados']}."
                ),
                evidencia=e,
                clave_ejecucion=clave_ejecucion,
            )
            res.propuestas.append(m)
            resumen.propuestas.append(m.id)
            pares_existentes[frozenset((pa.id, pb.id))] = m.id
            uso[sa.id] += 1
            uso[sb.id] += 1

    for resumen in res.por_solicitud.values():
        if resumen.propuestas or resumen.ya_propuestas:
            resumen.resultado = PROPUESTA
        elif resumen.bloqueadas or resumen.omitidas_por_limite:
            resumen.resultado = BLOQUEADA
        else:
            resumen.resultado = SIN_COINCIDENCIA
    return res

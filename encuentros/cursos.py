"""Base «Cursos»: SIMULACIÓN de los vínculos con Participantes (2026-11-22).

Este módulo solo CALCULA qué haría una sincronización; no escribe nada. No existe
todavía ninguna función que modifique Cursos: el usuario quiere revisar el
resultado antes (decisión del 2026-11-22).

Reglas acordadas:
  - Temas leídos igual que en el ciclo (temas_formulario): uno por línea; una sola
    línea, con la separación anterior. Como máximo 7; si hay más,
    ese campo no se toca y se pide aclaración (no se descarta ningún tema).
  - Se vinculan perfiles con correo válido y único, aunque tengan otros datos
    pendientes. Sin autorización para participar no se vincula, y sus vínculos
    actuales se propondrían para quitar.
  - Correos distintos NO garantizan personas distintas: filas con el mismo alias y
    correos distintos se señalan para revisión. Nunca se unen registros.
  - Los temas que se queden sin personas se conservan (solo se informa).
  - Temas parecidos («Soporte computadoras» / «Soporte computadores») no se fusionan:
    solo coinciden si son iguales sin distinguir mayúsculas, tildes ni espacios.
  - Si un perfil con correo duplicado o no válido ya estaba vinculado, ese vínculo
    se mantiene (no se añade ni se quita) hasta que se aclare.
  - Nunca se propone quitar un vínculo por una lectura incompleta o por falta de
    acceso: que una fila no aparezca al consultar Participantes NO prueba que se haya
    eliminado (la integración podría no verla). Solo se propone quitar el vínculo a
    una fila cuya página Notion confirma en la papelera; el resto se mantiene y se avisa.
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from .automatico import Persona, clave_correo, marcar_correos_duplicados, problema_de_correo
from .temas_formulario import MAX_TEMAS, leer_temas_formulario
OFRECEN = "Personas que ofrecen"
QUIEREN = "Personas que quieren aprender"
CAMPO_DE_PERSONA = {OFRECEN: "ofrece", QUIEREN: "quiere_aprender"}
PREGUNTA = {OFRECEN: "Ofrece", QUIEREN: "Quiere aprender"}

AÑADIR, QUITAR = "añadir", "quitar"
MOTIVO_NUEVO = "indica este tema en el formulario"
MOTIVO_YA_NO_INDICA = "ya no indica este tema"
MOTIVO_FILA_NO_EXISTE = "la fila está en la papelera de Notion (eliminada)"
MOTIVO_SIN_AUTORIZACION = "sin autorización para participar"


@dataclass(frozen=True)
class TemaExistente:
    id: str                         # id de la página en Cursos (sin guiones)
    titulo: str                     # «Tema»
    ofrecen: frozenset[str]         # ids de páginas de Participantes (sin guiones)
    quieren: frozenset[str]
    lectura_incompleta: bool = False   # Notion indicó más vínculos de los leídos


@dataclass(frozen=True)
class Cambio:
    accion: str                     # AÑADIR / QUITAR
    tema: str                       # título del tema
    tema_id: str | None             # None si el tema se crearía
    campo: str                      # OFRECEN / QUIEREN
    persona: str                    # referencia a la fila (nunca alias ni correo)
    motivo: str


@dataclass
class PlanCursos:
    cambios: list[Cambio] = field(default_factory=list)
    temas_nuevos: list[str] = field(default_factory=list)      # se crearían
    sin_personas: list[str] = field(default_factory=list)      # quedarían vacíos; se conservan
    vinculables: int = 0
    no_vinculables: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)            # sin datos personales

    def de(self, accion: str) -> list[Cambio]:
        return [c for c in self.cambios if c.accion == accion]


def clave_tema(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return " ".join(sin.casefold().split()).strip(" .,;:")


def temas_de_campo(texto: str | None) -> tuple[list[str], str | None]:
    """Temas de un campo con la MISMA lectura que el ciclo (temas_formulario):
    uno por línea; una sola línea, con la separación anterior. (temas, problema)."""
    temas, demasiados = leer_temas_formulario(texto)
    if demasiados:
        return temas, f"más de {MAX_TEMAS} temas: requiere aclaración"
    return temas, None


def referencia(p: Persona | None, pid: str) -> str:
    if p is not None and p.id_consecutivo is not None:
        return f"fila #{p.id_consecutivo}"
    return f"fila …{pid[-6:]}"


def _clave_alias(alias: str | None) -> str:
    return clave_tema(alias or "")


def planificar(personas: list[Persona], temas: list[TemaExistente],
               eliminadas_confirmadas: frozenset[str] = frozenset()) -> PlanCursos:
    """`eliminadas_confirmadas`: ids de filas que Notion devolvió como eliminadas
    (en la papelera). Una fila que solo «no aparece» no se trata como eliminada."""
    plan = PlanCursos()
    marcar_correos_duplicados(personas)            # entre TODAS las filas leídas
    por_id = {p.id: p for p in personas}

    # 1. Qué perfiles se pueden vincular y qué campos se evalúan.
    vinculables: dict[str, Persona] = {}
    sin_autorizacion: set[str] = set()
    campos_evaluados: dict[str, set[str]] = defaultdict(set)     # pid -> {OFRECEN, QUIEREN}
    deseado: dict[str, dict[str, set[str]]] = defaultdict(lambda: {OFRECEN: set(), QUIEREN: set()})
    titulo_de: dict[str, str] = {}
    demasiados = 0

    for p in personas:
        if p.autoriza is not True:
            sin_autorizacion.add(p.id)
            plan.no_vinculables[MOTIVO_SIN_AUTORIZACION] = plan.no_vinculables.get(MOTIVO_SIN_AUTORIZACION, 0) + 1
            continue
        problema = problema_de_correo(p)
        if problema:
            plan.no_vinculables[problema] = plan.no_vinculables.get(problema, 0) + 1
            continue
        vinculables[p.id] = p
        for campo, atributo in CAMPO_DE_PERSONA.items():
            lista, problema_temas = temas_de_campo(getattr(p, atributo))
            if problema_temas:
                demasiados += 1
                continue
            campos_evaluados[p.id].add(campo)
            for t in lista:
                k = clave_tema(t)
                titulo_de.setdefault(k, t)
                deseado[k][campo].add(p.id)
    plan.vinculables = len(vinculables)
    if demasiados:
        plan.avisos.append(f"{demasiados} campo(s) con más de {MAX_TEMAS} temas: no se tocan; requieren aclaración")

    # 2. Posible misma persona con correos distintos (no se unen; solo se avisa).
    correos_por_alias: dict[str, set[str]] = defaultdict(set)
    for p in personas:
        if _clave_alias(p.alias) and clave_correo(p.correo):
            correos_por_alias[_clave_alias(p.alias)].add(clave_correo(p.correo))
    grupos = sum(1 for c in correos_por_alias.values() if len(c) > 1)
    if grupos:
        plan.avisos.append(
            f"{grupos} alias repetido(s) con correos distintos: podrían ser la misma persona; "
            "se tratan como filas separadas y no se unen; revisar")

    # 3. Temas existentes: duplicados exactos (misma clave) -> ambiguos, no se tocan.
    por_clave: dict[str, list[TemaExistente]] = defaultdict(list)
    for t in temas:
        por_clave[clave_tema(t.titulo)].append(t)
    ambiguos = {k for k, ts in por_clave.items() if len(ts) > 1}
    if ambiguos:
        plan.avisos.append(f"{len(ambiguos)} tema(s) repetidos en Cursos con el mismo texto: no se tocan; revisar")

    if not personas:
        plan.avisos.append("no se leyó ninguna fila de Participantes: no se propone quitar vínculos")
    no_encontradas: set[str] = set()
    incompletos = 0

    for k, ts in por_clave.items():
        if k in ambiguos:
            continue
        t = ts[0]
        if t.lectura_incompleta:
            incompletos += 1
        quedan_total = 0
        for campo, actuales in ((OFRECEN, t.ofrecen), (QUIEREN, t.quieren)):
            quiere = deseado.get(k, {OFRECEN: set(), QUIEREN: set()})[campo]
            for pid in sorted(quiere - actuales):
                plan.cambios.append(Cambio(AÑADIR, t.titulo, t.id, campo, referencia(por_id[pid], pid), MOTIVO_NUEVO))
            quedan = set(actuales) | quiere
            for pid in sorted(actuales - quiere):
                motivo = None
                if pid not in por_id:
                    if pid in eliminadas_confirmadas and personas:
                        motivo = MOTIVO_FILA_NO_EXISTE
                    else:
                        no_encontradas.add(pid)
                elif pid in sin_autorizacion:
                    motivo = MOTIVO_SIN_AUTORIZACION
                elif pid in vinculables and campo in campos_evaluados[pid]:
                    motivo = MOTIVO_YA_NO_INDICA
                if motivo and not t.lectura_incompleta:
                    plan.cambios.append(Cambio(QUITAR, t.titulo, t.id, campo, referencia(por_id.get(pid), pid), motivo))
                    quedan.discard(pid)
            quedan_total += len(quedan)
        if quedan_total == 0:
            plan.sin_personas.append(t.titulo)

    if incompletos:
        plan.avisos.append(f"{incompletos} tema(s) con vínculos que Notion no devolvió completos: "
                           "no se propone quitar ninguno de sus vínculos")
    if no_encontradas:
        plan.avisos.append(
            f"{len(no_encontradas)} fila(s) vinculada(s) que no aparecen al leer Participantes y "
            "cuya eliminación no está confirmada (podría faltar acceso): sus vínculos se mantienen")

    # 4. Temas que no existen en Cursos: se crearían con sus vínculos.
    for k in sorted(set(deseado) - set(por_clave), key=lambda x: titulo_de[x]):
        titulo = titulo_de[k]
        plan.temas_nuevos.append(titulo)
        for campo in (OFRECEN, QUIEREN):
            for pid in sorted(deseado[k][campo]):
                plan.cambios.append(Cambio(AÑADIR, titulo, None, campo, referencia(por_id[pid], pid), MOTIVO_NUEVO))
    return plan


def informe(plan: PlanCursos) -> list[str]:
    """Texto para revisar el plan. Muestra temas y referencias de fila, nunca alias ni correos."""
    lineas = [
        "SIMULACIÓN de Cursos: no se ha modificado nada.",
        f"Perfiles vinculables: {plan.vinculables} · no vinculables: "
        + (", ".join(f"{m}: {n}" for m, n in sorted(plan.no_vinculables.items())) or "ninguno"),
        f"Vínculos que se añadirían: {len(plan.de(AÑADIR))} · que se quitarían: {len(plan.de(QUITAR))} · "
        f"temas nuevos: {len(plan.temas_nuevos)} · temas que quedarían sin personas (se conservan): "
        f"{len(plan.sin_personas)}",
    ]
    for c in plan.cambios:
        donde = "tema nuevo" if c.tema_id is None else "tema existente"
        lineas.append(f"  {c.accion.upper():7} «{c.tema}» ({donde}) · {c.campo} · {c.persona} · {c.motivo}")
    for t in plan.sin_personas:
        lineas.append(f"  SIN PERSONAS «{t}»: se conserva")
    for a in plan.avisos:
        lineas.append(f"Aviso: {a}")
    return lineas

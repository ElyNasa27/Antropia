"""Base aparte «Matches por cursos [PRUEBA]»: lectura, plan y escritura GUARDADA.

Decisión del 2026-11-22: los matches por cursos van en una base APARTE, que el ciclo
automático no lee. Así no pueden disparar correos ni interferir con las propuestas
de A2. Esta base no es una propuesta de encuentro: solo registra coincidencias.

  - Nunca se borra nada. Un par que deja de coincidir pasa a «Ya no coincide».
  - Cada par tiene una «Clave» estable (ids de las dos filas, ordenados): volver a
    ejecutar no duplica filas.
  - El cliente de escritura (`ClienteSoloMatchesCursos`) solo puede crear páginas en
    ESTA base y actualizar páginas que leyó de ESTA base. Cualquier otra escritura
    (Participantes, Cursos, Matches del ciclo, etc.) se rechaza.
  - El título no lleva alias: «fila #N ↔ fila #M». Las relaciones enlazan las filas.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .match_cursos import RECIPROCO, UNA_DIRECCION, ParCursos, ResultadoCursos
from .notion_api import DS_MATCHES, ClienteNotion, EscrituraNoPermitida, _id, _valor

# Base creada con aprobación del usuario el 2026-11-22 dentro de «Piloto - Intercambio
# de Conocimiento». Las relaciones son de un solo sentido: Participantes no cambió.
VARIABLE_DS = "ANTROPIA_DS_MATCHES_CURSOS"
DS_MATCHES_CURSOS = "420edf5c-24dd-81b0-aaaa-000b6e1f0e2b"

COL_TITULO = "Match"
COL_A, COL_B = "Participante A", "Participante B"
COL_TIPO = "Tipo"
COL_A_ENSENA, COL_B_ENSENA = "A enseña", "B enseña"
COL_CLAVE = "Clave"
COL_ESTADO = "Estado"
COL_NOTAS = "Notas del sistema"
# Columnas del correo de cada lado (PENDIENTES de crear en Notion):
#   «Correo a X»   VISTA (selección): puede IMPEDIR un envío, nunca autorizarlo. Una
#                  persona puede poner «Enviado» a mano (p. ej. tras un envío manual) y
#                  el agente ya no lo enviará.
#   «Id correo X»  VISTA (texto): Message-ID del último intento.
#   «Registro X»   REGISTRO de envíos (texto, lo escribe SOLO el programa; no editar).
COLUMNAS_CORREO = {
    "A": {"estado": "Correo a A", "id": "Id correo A", "registro": "Registro A"},
    "B": {"estado": "Correo a B", "id": "Id correo B", "registro": "Registro B"},
}
TIPOS_COLUMNAS_CORREO = {"estado": "select", "id": "rich_text", "registro": "rich_text"}

VIGENTE, YA_NO_COINCIDE = "Vigente", "Ya no coincide"
TIPO_A_NOTION = {RECIPROCO: "Recíproco", UNA_DIRECCION: "En una dirección"}

CREAR, ACTUALIZAR, MARCAR = "crear", "actualizar", "marcar «Ya no coincide»"
ADOPTAR = "adoptar fila puesta a mano"


def ds_matches_cursos() -> str:
    return os.environ.get(VARIABLE_DS, "").strip() or DS_MATCHES_CURSOS


def clave_par(a: str, b: str) -> str:
    x, y = sorted((_id(a), _id(b)))
    return f"cursos:{x}:{y}"


# Filas puestas por una PERSONA en la base (sin «Clave», o adoptadas con este prefijo).
# Decisión del usuario del 2026-11-23: se usan como fuente de quién hizo match y con qué
# cursos. El agente las adopta (les pone «Clave» y «Estado»), nunca las marca «Ya no
# coincide» y no crea otra fila para el mismo par.
PREFIJO_MANUAL = "manual:"


def clave_manual(a: str, b: str) -> str:
    x, y = sorted((_id(a), _id(b)))
    return f"{PREFIJO_MANUAL}{x}:{y}"


def es_manual(clave: str | None) -> bool:
    return not clave or clave.startswith(PREFIJO_MANUAL)


@dataclass(frozen=True)
class FilaMatchCursos:
    id: str
    clave: str
    estado: str | None
    tipo: str | None
    a: str | None
    b: str | None
    a_ensena: str
    b_ensena: str
    # Lo que muestra Notion de cada lado: (estado, «Id correo»).
    vista_a: tuple = (None, "")
    vista_b: tuple = (None, "")

    def vista(self, lado: str) -> tuple:
        return self.vista_a if lado == "A" else self.vista_b


@dataclass(frozen=True)
class Accion:
    tipo: str                    # CREAR / ACTUALIZAR / MARCAR
    clave: str
    pagina: str | None           # None al crear
    propiedades: dict


@dataclass
class PlanEscritura:
    acciones: list[Accion] = field(default_factory=list)
    sin_cambios: int = 0
    avisos: list[str] = field(default_factory=list)

    def cuantas(self, tipo: str) -> int:
        return sum(1 for a in self.acciones if a.tipo == tipo)


def _texto(lista) -> str:
    return " | ".join(c.curso for c in lista)


def _rt(t: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": t[:2000]}}] if t else []}


def propiedades(par: ParCursos) -> dict:
    flecha = "↔" if par.tipo == RECIPROCO else "→"
    return {
        COL_TITULO: {"title": [{"type": "text", "text": {"content": f"{par.ref_a} {flecha} {par.ref_b}"}}]},
        COL_A: {"relation": [{"id": par.a}]},
        COL_B: {"relation": [{"id": par.b}]},
        COL_TIPO: {"select": {"name": TIPO_A_NOTION[par.tipo]}},
        COL_A_ENSENA: _rt(_texto(par.a_ensena)),
        COL_B_ENSENA: _rt(_texto(par.b_ensena)),
        COL_CLAVE: _rt(clave_par(par.a, par.b)),
        COL_ESTADO: {"select": {"name": VIGENTE}},
        COL_NOTAS: _rt("Coincidencia de cursos calculada por match_cursos.py. No es una propuesta "
                       "de encuentro ni envía correos."),
    }


def _vista_de(g, lado: str) -> tuple:
    c = COLUMNAS_CORREO[lado]
    return (g(c["estado"]) or None, g(c["id"]) or "")


def fila_de_pagina(pg: dict) -> FilaMatchCursos:
    p = pg["properties"]
    g = lambda n: _valor(p.get(n))  # noqa: E731
    a, b = g(COL_A) or [], g(COL_B) or []
    return FilaMatchCursos(
        id=_id(pg["id"]), clave=g(COL_CLAVE) or "", estado=g(COL_ESTADO), tipo=g(COL_TIPO),
        # Una relación con más de una persona no es un par: se deja sin A/B (no se usa).
        a=_id(a[0]) if len(a) == 1 else None, b=_id(b[0]) if len(b) == 1 else None,
        a_ensena=g(COL_A_ENSENA) or "", b_ensena=g(COL_B_ENSENA) or "",
        vista_a=_vista_de(g, "A"), vista_b=_vista_de(g, "B"),
    )


def leer_filas(cliente, ds: str) -> list[FilaMatchCursos]:
    return [fila_de_pagina(pg) for pg in cliente.consultar(ds)]


def planificar_escritura(resultado: ResultadoCursos, filas: list[FilaMatchCursos]) -> PlanEscritura:
    plan = PlanEscritura()
    por_clave: dict[str, list[FilaMatchCursos]] = {}
    for f in filas:
        if f.clave:
            por_clave.setdefault(f.clave, []).append(f)
    repetidas = {k for k, v in por_clave.items() if len(v) > 1}
    if repetidas:
        plan.avisos.append(f"{len(repetidas)} clave(s) repetidas en la base: no se tocan; revisar")

    # Filas puestas por una persona: se adoptan (Clave «manual:…» + Estado Vigente si no
    # tiene). Si no tienen exactamente una persona en A y otra en B, no se tocan.
    pares_manuales: set[frozenset] = set()
    incompletas = 0
    for f in filas:
        if not es_manual(f.clave):
            continue
        if not (f.a and f.b) or f.a == f.b:
            incompletas += 1
            continue
        pares_manuales.add(frozenset((f.a, f.b)))
        if not f.clave:
            props = {COL_CLAVE: _rt(clave_manual(f.a, f.b))}
            if not f.estado:
                props[COL_ESTADO] = {"select": {"name": VIGENTE}}
            plan.acciones.append(Accion(ADOPTAR, clave_manual(f.a, f.b), f.id, props))
    if incompletas:
        plan.avisos.append(f"{incompletas} fila(s) puestas a mano sin una persona en A y otra distinta "
                           "en B: no se tocan ni se usan")

    vigentes = set()
    duplicadas_manual = 0
    for par in resultado.reciprocos + resultado.una_direccion:
        k = clave_par(par.a, par.b)
        vigentes.add(k)
        if k in repetidas:
            continue
        if frozenset((_id(par.a), _id(par.b))) in pares_manuales and k not in por_clave:
            duplicadas_manual += 1          # ya está como fila puesta a mano: no se duplica
            continue
        props = propiedades(par)
        existente = (por_clave.get(k) or [None])[0]
        if existente is None:
            plan.acciones.append(Accion(CREAR, k, None, props))
            continue
        igual = (existente.estado == VIGENTE and existente.tipo == TIPO_A_NOTION[par.tipo]
                 and (existente.a, existente.b) == (_id(par.a), _id(par.b))
                 and existente.a_ensena == _texto(par.a_ensena) and existente.b_ensena == _texto(par.b_ensena))
        if igual:
            plan.sin_cambios += 1
        else:
            plan.acciones.append(Accion(ACTUALIZAR, k, existente.id, props))

    if duplicadas_manual:
        plan.avisos.append(f"{duplicadas_manual} par(es) calculados ya están como fila puesta a mano: "
                           "no se crea otra fila")

    # Pares que ya no coinciden: se marcan, nunca se borran. Si no se leyó ningún
    # perfil, no se marca nada (podría ser una lectura fallida o sin acceso). Las filas
    # puestas a mano NUNCA se marcan: solo una persona puede cambiarlas.
    if resultado.perfiles == 0:
        if filas:
            plan.avisos.append("no se leyó ninguna fila de Participantes: no se marca nada")
        return plan
    for k, fs in por_clave.items():
        if k in vigentes or k in repetidas or es_manual(k):
            continue
        f = fs[0]
        if f.estado != YA_NO_COINCIDE:
            plan.acciones.append(Accion(MARCAR, k, f.id, {COL_ESTADO: {"select": {"name": YA_NO_COINCIDE}}}))
    return plan


class ClienteSoloMatchesCursos:
    """Puede CONSULTAR cualquier base, pero solo escribe en la base de matches por
    cursos: crear allí y actualizar páginas leídas de allí. Nada más."""

    def __init__(self, real: ClienteNotion, ds: str) -> None:
        if not ds or _id(ds) == _id(DS_MATCHES):
            raise ValueError("La base de matches por cursos debe ser distinta de «Matches [PRUEBA]».")
        self._real, self._ds = real, _id(ds)
        self._paginas_propias: set[str] = set()

    def __repr__(self) -> str:
        return "ClienteSoloMatchesCursos(token oculto)"

    def consultar(self, data_source_id: str, filtro: dict | None = None) -> list[dict]:
        paginas = self._real.consultar(data_source_id, filtro)
        if _id(data_source_id) == self._ds:
            self._paginas_propias.update(_id(p["id"]) for p in paginas)
        return paginas

    def crear(self, data_source_id: str, props: dict) -> dict:
        if _id(data_source_id) != self._ds:
            raise EscrituraNoPermitida("solo se puede crear en «Matches por cursos [PRUEBA]»")
        pg = self._real.crear(data_source_id, props)
        self._paginas_propias.add(_id(pg["id"]))
        return pg

    def actualizar(self, page_id: str, props: dict) -> dict:
        if _id(page_id) not in self._paginas_propias:
            raise EscrituraNoPermitida("solo se pueden actualizar páginas de «Matches por cursos [PRUEBA]»")
        return self._real.actualizar(page_id, props)

    def leer_fuente(self, data_source_id: str) -> dict:
        """GET del esquema de una base (solo lectura)."""
        return self._real.pedir("GET", f"/data_sources/{data_source_id}")

    def leer_pagina(self, page_id: str) -> dict:
        """GET de una página (solo lectura), p. ej. la plantilla del correo."""
        return self._real.pedir("GET", f"/pages/{page_id}")

    def pedir(self, *a, **k):
        raise EscrituraNoPermitida("petición no permitida")


def aplicar(plan: PlanEscritura, cliente: ClienteSoloMatchesCursos, ds: str) -> int:
    hechas = 0
    for a in plan.acciones:
        if a.tipo == CREAR:
            cliente.crear(ds, a.propiedades)
        else:
            cliente.actualizar(a.pagina, a.propiedades)
        hechas += 1
    return hechas


def recuentos_plan(plan: PlanEscritura, escrito: bool) -> list[str]:
    verbo = "Escritas" if escrito else "Se escribirían (ENSAYO: no se ha escrito nada)"
    lineas = [f"{verbo} en «Matches por cursos [PRUEBA]»: crear {plan.cuantas(CREAR)} · "
              f"actualizar {plan.cuantas(ACTUALIZAR)} · marcar «Ya no coincide» {plan.cuantas(MARCAR)} · "
              f"adoptar filas puestas a mano {plan.cuantas(ADOPTAR)} · sin cambios {plan.sin_cambios}"]
    return lineas + [f"Aviso: {a}" for a in plan.avisos]


# ---------------------------------------------------------------------------
# Correos de coincidencias de cursos (conectado a envio_exclusivo; NO activado)
# ---------------------------------------------------------------------------
# - Qué correo falta y si se puede enviar lo decide el REGISTRO de envíos (crear solo si
#   no existe; nada se modifica). Ver encuentros/envio_exclusivo.py.
# - La vista de Notion solo puede IMPEDIR un primer envío (si no coincide con el
#   registro), nunca autorizarlo, y no interviene en los reenvíos.
# - Antes de reservar y justo antes de enviar se RELEEN las dos fichas de Participantes:
#   autorización vigente de las dos personas, correo de quien recibe igual, válido y no
#   repetido, y cursos que siguen coincidiendo igual. Si algo cambió, no se envía.
# - El envío automático solo hace el primer intento. Los reenvíos son decisiones humanas
#   con el «Id correo» COMPLETO Y EXACTO del último intento.
#
# REGISTRO EN NOTION (decisión del usuario del 2026-11-23: sin registro externo y sin la
# verificación de atomicidad). El registro de cada correo vive en la columna «Registro X»
# de su fila. Notion NO tiene escrituras condicionales: «crear solo si no existe» se hace
# leyendo, escribiendo y releyendo, y NO es atómico. La protección contra envíos dobles
# depende entonces de que SOLO HAYA UNA EJECUCIÓN A LA VEZ: el envío solo se permite desde
# GitHub Actions, con `concurrency` (una ejecución en curso como máximo) y sin ejecutar el
# envío desde ningún otro sitio. Riesgo aceptado por el usuario.
import json
from datetime import UTC, datetime

from . import envio_exclusivo as ee
from .automatico import clave_correo, problema_de_correo
from .notion_api import DS_PARTICIPANTES, persona_desde_pagina
from .reserva_envios import base_correo, huella


def id_correo(clave: str, lado: str, intento: int) -> str:
    """Message-ID DISTINTO para A y B y para cada intento. Sin datos personales. Sirve para
    localizar el mensaje (p. ej. en «Enviados»); NO garantiza que se descarten duplicados."""
    return f"<antropia-cursos.{huella(clave, lado)}.{lado.lower()}.{intento}@antropia.invalid>"


MAX_REGISTRO = 2000          # caracteres de un texto de Notion: si no cabe, no se arriesga


class RegistroNotion:
    """Registro de envíos (interfaz de envio_exclusivo.Registro) guardado en la columna
    «Registro X» de cada fila de «Matches por cursos [PRUEBA]», como JSON.

    Cada operación RELEE la página (nunca usa una copia vieja). `crear` lee, añade la
    entrada si no existe, escribe y vuelve a leer: True solo si la relectura muestra la
    entrada propia. NO ES ATÓMICO: ver el comentario de la sección. Cualquier duda -> None
    o una excepción, y el llamante no envía."""

    def __init__(self, cliente, filas: list[FilaMatchCursos]) -> None:
        self.c = cliente
        self._donde: dict[str, tuple[str, str]] = {}
        for f in filas:
            if f.clave:
                for lado in ("A", "B"):
                    self._donde[base_correo(f.clave, lado)] = (f.id, lado)

    def _ubicar(self, nombre: str) -> tuple[str, str, str]:
        base, entrada = nombre.rsplit("/", 1)
        pagina, lado = self._donde[base]            # KeyError: no es un correo de esta base
        return pagina, COLUMNAS_CORREO[lado]["registro"], entrada

    def _entradas(self, pagina: str, columna: str) -> dict:
        pg = self.c.leer_pagina(pagina)
        texto = _valor((pg.get("properties") or {}).get(columna)) or ""
        if not texto.strip():
            return {}
        datos = json.loads(texto)
        if not isinstance(datos, dict) or not all(isinstance(v, str) for v in datos.values()):
            raise ValueError("el registro de la fila no tiene el formato esperado")
        return datos

    def leer(self, nombre: str) -> str | None:
        pagina, columna, entrada = self._ubicar(nombre)
        return self._entradas(pagina, columna).get(entrada)

    def crear(self, nombre: str, contenido: str) -> bool | None:
        try:
            pagina, columna, entrada = self._ubicar(nombre)
            datos = self._entradas(pagina, columna)
        except Exception:
            return None
        if entrada in datos:
            return False
        datos[entrada] = contenido
        texto = json.dumps(datos, sort_keys=True, ensure_ascii=False)
        if len(texto) > MAX_REGISTRO:
            return None
        try:
            self.c.actualizar(pagina, {columna: _rt(texto)})
            return True if self._entradas(pagina, columna).get(entrada) == contenido else None
        except Exception:
            return None


@dataclass(frozen=True)
class EnvioPendiente:
    fila: FilaMatchCursos
    par: ParCursos
    lado: str                    # "A" o "B"
    manual: bool = False         # fila puesta a mano por una persona


@dataclass
class ResumenEnvios:
    enviados: int = 0
    no_enviados: dict[str, int] = field(default_factory=dict)    # motivo -> cuántos


FALTAN_COLUMNAS = ("la base no tiene las columnas del correo («Correo a A/B», «Id correo A/B», "
                   "«Registro A/B»): no se envía nada")


def tiene_columnas_de_correo(cliente, ds: str) -> bool:
    """Comprueba en el ESQUEMA de la base las seis columnas, sus tipos y las opciones."""
    props = (cliente.leer_fuente(ds) or {}).get("properties") or {}
    for lado in ("A", "B"):
        for clave, nombre in COLUMNAS_CORREO[lado].items():
            p = props.get(nombre) or {}
            if p.get("type") != TIPOS_COLUMNAS_CORREO[clave]:
                return False
            if clave == "estado":
                opciones = {o.get("name") for o in (p.get("select") or {}).get("options", [])}
                if not {ee.PENDIENTE, ee.EN_CURSO, ee.ESTADO_ENVIADO, ee.POR_REVISAR} <= opciones:
                    return False
    return True


def filas_tras_el_plan(filas: list[FilaMatchCursos], plan: PlanEscritura,
                       resultado: ResultadoCursos) -> list[FilaMatchCursos]:
    """Cómo quedaría la base tras aplicar el plan (para simular sin escribir)."""
    por_clave = {clave_par(p.a, p.b): p for p in resultado.reciprocos + resultado.una_direccion}
    res = {f.clave: f for f in filas if f.clave}
    por_pagina = {f.id: f for f in filas}
    for a in plan.acciones:
        f = res.get(a.clave)
        if a.tipo == ADOPTAR:
            f = por_pagina[a.pagina]
            res[a.clave] = FilaMatchCursos(f.id, a.clave, f.estado or VIGENTE, f.tipo, f.a, f.b, f.a_ensena,
                                           f.b_ensena, f.vista_a, f.vista_b)
        elif a.tipo == CREAR:
            p = por_clave[a.clave]
            res[a.clave] = FilaMatchCursos(f"(nueva) {a.clave}", a.clave, VIGENTE, TIPO_A_NOTION[p.tipo],
                                           _id(p.a), _id(p.b), _texto(p.a_ensena), _texto(p.b_ensena))
        elif a.tipo == MARCAR:
            res[a.clave] = FilaMatchCursos(f.id, f.clave, YA_NO_COINCIDE, f.tipo, f.a, f.b, f.a_ensena,
                                           f.b_ensena, f.vista_a, f.vista_b)
        else:
            p = por_clave[a.clave]
            res[a.clave] = FilaMatchCursos(f.id, f.clave, VIGENTE, TIPO_A_NOTION[p.tipo], _id(p.a), _id(p.b),
                                           _texto(p.a_ensena), _texto(p.b_ensena), f.vista_a, f.vista_b)
    return list(res.values())


NOTION_A_TIPO = {v: k for k, v in TIPO_A_NOTION.items()}


def _cursos_de_texto(texto: str) -> tuple:
    from .match_cursos import Coincidencia
    return tuple(Coincidencia(c, c) for c in (" ".join(x.split()) for x in (texto or "").split("|")) if c)


def par_de_fila_manual(f: FilaMatchCursos) -> tuple[ParCursos | None, str | None]:
    """El par de una fila puesta por una persona, tal como está escrita. (par, problema)."""
    if not (f.a and f.b) or f.a == f.b:
        return None, "la fila no tiene una persona en A y otra distinta en B"
    tipo = NOTION_A_TIPO.get(f.tipo or "")
    if tipo is None:
        return None, "«Tipo» no es «Recíproco» ni «En una dirección»"
    a_ens, b_ens = _cursos_de_texto(f.a_ensena), _cursos_de_texto(f.b_ensena)
    if not a_ens:
        return None, "falta «A enseña»"
    if tipo == RECIPROCO and not b_ens:
        return None, "es recíproco pero falta «B enseña»"
    if tipo == UNA_DIRECCION and b_ens:
        return None, "es en una dirección pero «B enseña» tiene texto"
    return ParCursos(tipo, f.a, f.b, f"fila …{f.a[-6:]}", f"fila …{f.b[-6:]}", a_ens, b_ens), None


def _vigentes(resultado: ResultadoCursos, filas: list[FilaMatchCursos]):
    """(fila, par, manual) de los pares a los que se puede escribir: los calculados que
    siguen vigentes y las filas puestas a mano (ya adoptadas) en estado «Vigente»."""
    pares = {clave_par(p.a, p.b): p for p in resultado.reciprocos + resultado.una_direccion}
    for f in filas:
        if f.estado != VIGENTE:
            continue
        if f.clave.startswith(PREFIJO_MANUAL):
            par, problema = par_de_fila_manual(f)
            if par is not None and f.clave == clave_manual(f.a, f.b):
                yield f, par, True
            continue
        p = pares.get(f.clave)
        if p is not None and (f.a, f.b) == (_id(p.a), _id(p.b)):
            yield f, p, False


def avisos_filas_manuales(filas: list[FilaMatchCursos]) -> list[str]:
    """Filas puestas a mano que no se pueden usar (sin datos personales)."""
    motivos: dict[str, int] = {}
    for f in filas:
        if f.clave.startswith(PREFIJO_MANUAL) and f.estado == VIGENTE:
            _, problema = par_de_fila_manual(f)
            if problema:
                motivos[problema] = motivos.get(problema, 0) + 1
    return [f"{n} fila(s) puestas a mano no se usan: {m}" for m, n in sorted(motivos.items())]


def planificar_envios(resultado: ResultadoCursos, filas: list[FilaMatchCursos], registro,
                      estado_ejecucion) -> list[EnvioPendiente]:
    """Lados que el REGISTRO da como «Pendiente» (nunca intentados), de pares vigentes."""
    pendientes = []
    for f, p, manual in _vigentes(resultado, filas):
        for lado in ("A", "B"):
            if ee.estado_de(registro, base_correo(f.clave, lado), estado_ejecucion).estado == ee.PENDIENTE:
                pendientes.append(EnvioPendiente(f, p, lado, manual))
    return pendientes


def comprobacion_vigente(e: EnvioPendiente, leidas: dict, cliente):
    """Se ejecuta antes de reservar y justo antes de enviar: relee las dos fichas (solo
    lectura) y devuelve el motivo para NO enviar, o None si todo sigue igual.

    Fila puesta a mano: en vez de recalcular los cursos (los decidió una persona), relee
    la fila y exige que siga «Vigente» y sin cambios, y que los alias sean distintos."""
    from . import a2_match
    from .match_cursos import emparejar_por_cursos
    yo_id, otra_id = (e.par.a, e.par.b) if e.lado == "A" else (e.par.b, e.par.a)

    def comprobar() -> str | None:
        yo = persona_desde_pagina(cliente.leer_pagina(yo_id))
        otra = persona_desde_pagina(cliente.leer_pagina(otra_id))
        if yo.autoriza is not True or otra.autoriza is not True:
            return "sin autorización para participar (comprobado antes de enviar)"
        if problema_de_correo(yo):
            return "el correo de quien recibe falta o no es válido (comprobado antes de enviar)"
        if clave_correo(yo.correo) != clave_correo(leidas[_id(yo_id)].correo):
            return "el correo de quien recibe cambió desde la lectura"
        iguales = cliente.consultar(DS_PARTICIPANTES, {
            "property": "Correo electrónico", "email": {"equals": (yo.correo or "").strip()}})
        if len(iguales) > 1:
            return "el correo de quien recibe está repetido (comprobado antes de enviar)"
        if e.manual:
            n_yo, n_otra = a2_match._normalizar(yo.alias or ""), a2_match._normalizar(otra.alias or "")
            if n_yo and n_yo == n_otra:
                return "posible misma persona (mismo alias en las dos filas)"
            ahora = fila_de_pagina(cliente.leer_pagina(e.fila.id))
            if (ahora.estado, ahora.clave, ahora.tipo, ahora.a, ahora.b, ahora.a_ensena, ahora.b_ensena) != \
                    (VIGENTE, e.fila.clave, e.fila.tipo, e.fila.a, e.fila.b, e.fila.a_ensena, e.fila.b_ensena):
                return "la fila puesta a mano cambió o ya no está «Vigente»"
            return None
        actual = emparejar_por_cursos([yo, otra])
        pares = actual.reciprocos + actual.una_direccion
        if len(pares) != 1 or clave_par(pares[0].a, pares[0].b) != e.fila.clave or \
                (pares[0].tipo, pares[0].a, pares[0].a_ensena, pares[0].b_ensena) != \
                (e.par.tipo, e.par.a, e.par.a_ensena, e.par.b_ensena):
            return "los cursos ya no coinciden como en la lectura"
        return None
    return comprobar


def _enviar_fn(e: EnvioPendiente, personas: dict, servicio, instrucciones: str):
    from .correo import CorreoMatch
    from .correo_cursos import redactar
    yo_id, otra_id = (e.par.a, e.par.b) if e.lado == "A" else (e.par.b, e.par.a)
    yo, otra = personas[_id(yo_id)], personas[_id(otra_id)]
    asunto, cuerpo = redactar(e.par, e.lado, yo, otra, instrucciones)

    def enviar(n: int) -> None:
        servicio.enviar(CorreoMatch(e.fila.clave, yo.id, yo.correo.strip(), asunto, cuerpo,
                                    message_id=id_correo(e.fila.clave, e.lado, n)))
    return enviar


def _contar(r: ResumenEnvios, motivo: str) -> None:
    r.no_enviados[motivo] = r.no_enviados.get(motivo, 0) + 1


def enviar_correos(pendientes: list[EnvioPendiente], personas: dict, cliente, servicio, registro,
                   ejecucion: "ee.Ejecucion", instrucciones: str,
                   ahora=lambda: datetime.now(UTC)) -> ResumenEnvios:
    """Primer intento de cada lado pendiente, con reserva exclusiva. Nunca repite."""
    r = ResumenEnvios()
    for e in pendientes:
        informe = ee.enviar_automatico(
            registro, base_correo(e.fila.clave, e.lado), ejecucion, ahora().isoformat(timespec="seconds"),
            _enviar_fn(e, personas, servicio, instrucciones),
            comprobar=comprobacion_vigente(e, personas, cliente),
            estado_en_notion=e.fila.vista(e.lado)[0])
        if informe.enviado:
            r.enviados += 1
        else:
            _contar(r, informe.motivo)
    return r


def reenviar(id_mensaje, resultado: ResultadoCursos, filas: list[FilaMatchCursos], personas: dict,
             cliente, servicio, registro, ejecucion: "ee.Ejecucion", instrucciones: str, estado_ejecucion,
             ahora=lambda: datetime.now(UTC)) -> "ee.Informe":
    """Reenvío por DECISIÓN HUMANA. `id_mensaje` tiene que ser EXACTAMENTE el «Id correo»
    del ÚLTIMO intento según el registro (no se recorta ni se completa). El par tiene que
    seguir vigente en esta lectura. Notion no interviene."""
    if isinstance(id_mensaje, str):
        for f, p, manual in _vigentes(resultado, filas):
            for lado in ("A", "B"):
                base = base_correo(f.clave, lado)
                ultimo = ee.estado_de(registro, base, estado_ejecucion).intento
                if ultimo and id_mensaje == id_correo(f.clave, lado, ultimo):
                    e = EnvioPendiente(f, p, lado, manual)
                    return ee.reenviar_por_decision_humana(
                        registro, base, ejecucion, ahora().isoformat(timespec="seconds"),
                        _enviar_fn(e, personas, servicio, instrucciones), estado_ejecucion,
                        id_mensaje, lambda n, c=f.clave, l=lado: id_correo(c, l, n),
                        comprobar=comprobacion_vigente(e, personas, cliente))
    return ee.Informe(False, "el identificador no es el completo y exacto del último intento "
                             "de ningún correo vigente")


def actualizar_vistas(resultado: ResultadoCursos, filas: list[FilaMatchCursos], cliente, registro,
                      estado_ejecucion) -> int:
    """Escribe en Notion la VISTA calculada desde el registro (solo si cambió)."""
    hechas = 0
    for f, _, _ in _vigentes(resultado, filas):
        props = {}
        for lado in ("A", "B"):
            est = ee.estado_de(registro, base_correo(f.clave, lado), estado_ejecucion)
            if est.estado == ee.PENDIENTE and f.vista(lado)[0] not in (None, "", ee.PENDIENTE):
                continue        # p. ej. «Enviado» puesto a mano tras un envío manual: se respeta
            esperado = (est.estado, id_correo(f.clave, lado, est.intento) if est.intento else "")
            if f.vista(lado) != esperado:
                col = COLUMNAS_CORREO[lado]
                props[col["estado"]] = {"select": {"name": esperado[0]}}
                props[col["id"]] = _rt(esperado[1])
        if props:
            cliente.actualizar(f.id, props)
            hechas += 1
    return hechas

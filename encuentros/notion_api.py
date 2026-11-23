"""Conexión con la API de Notion (biblioteca estándar) y almacén del ciclo automático.

El token de la integración se lee de la variable de entorno NOTION_TOKEN (en
GitHub Actions, un secreto del repositorio). Nunca se escribe en el código.
La integración debe estar conectada a la página «Piloto - Intercambio de
Conocimiento» para poder leer y escribir sus bases.

Bases que usa (ids de data source, no son secretos):
  - Participantes                 (solo lectura)
  - Matches [PRUEBA]              (lectura y escritura)
  - Respuestas al match [PRUEBA]  (lectura y escritura)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Callable

from .automatico import ESPERANDO, PENDIENTE, FilaMatch, FilaRespuesta, Persona
from .notion_mapa import (
    COLUMNA_DIAS_DISPONIBLES, COLUMNA_ID_CONSECUTIVO, COLUMNA_MINUTOS_SELECCIONADOS, COLUMNA_OTRO_IDIOMA,
    COLUMNA_ZONA_SELECCIONADA, COLUMNAS_FRANJAS, COLUMNAS_OTRAS_FRANJAS, COLUMNAS_TEMAS_ADICIONALES,
)

API = "https://api.notion.com/v1"
VERSION_API = "2025-09-03"

DS_PARTICIPANTES = os.environ.get("ANTROPIA_DS_PARTICIPANTES", "90dedf5c-24dd-836d-9814-87532a3f9afd")
DS_MATCHES = os.environ.get("ANTROPIA_DS_MATCHES", "41fedf5c-24dd-819d-a540-000b01a12b25")
DS_RESPUESTAS = os.environ.get("ANTROPIA_DS_RESPUESTAS", "41fedf5c-24dd-812f-a0c1-000b110affc1")
DS_CURSOS = os.environ.get("ANTROPIA_DS_CURSOS", "66cedf5c-24dd-8211-adeb-87d102b1a5e1")


class ErrorNotion(Exception):
    pass


class ClienteNotion:
    def __init__(self, token: str, abrir: Callable = urllib.request.urlopen,
                 esperar: Callable[[float], None] = time.sleep) -> None:
        if not token:
            raise ValueError("Falta NOTION_TOKEN.")
        self._token, self._abrir, self._esperar = token, abrir, esperar

    def __repr__(self) -> str:
        return "ClienteNotion(token oculto)"

    def pedir(self, metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        for intento in range(5):
            req = urllib.request.Request(API + ruta, data=datos, method=metodo, headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": VERSION_API,
                "Content-Type": "application/json",
            })
            try:
                with self._abrir(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and intento < 4:
                    self._esperar(float(e.headers.get("Retry-After") or 2 ** intento))
                    continue
                detalle = e.read().decode(errors="replace")[:300]
                raise ErrorNotion(f"{metodo} {ruta}: HTTP {e.code} {detalle}") from None
        raise ErrorNotion(f"{metodo} {ruta}: demasiados reintentos")

    def consultar(self, data_source_id: str, filtro: dict | None = None) -> list[dict]:
        paginas, cursor = [], None
        while True:
            cuerpo = {"page_size": 100}
            if filtro:
                cuerpo["filter"] = filtro
            if cursor:
                cuerpo["start_cursor"] = cursor
            r = self.pedir("POST", f"/data_sources/{data_source_id}/query", cuerpo)
            paginas += r.get("results", [])
            if not r.get("has_more"):
                return paginas
            cursor = r.get("next_cursor")

    def crear(self, data_source_id: str, propiedades: dict) -> dict:
        return self.pedir("POST", "/pages", {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": propiedades,
        })

    def actualizar(self, page_id: str, propiedades: dict) -> dict:
        return self.pedir("PATCH", f"/pages/{page_id}", {"properties": propiedades})


# ---------------------------------------------------------------------------
# Lectura y escritura de propiedades
# ---------------------------------------------------------------------------
def _texto(prop: dict | None) -> str | None:
    if not prop:
        return None
    partes = prop.get(prop.get("type"), [])
    if not isinstance(partes, list):
        return None
    t = "".join(x.get("plain_text", "") for x in partes).strip()
    return t or None


def _valor(prop: dict | None):
    if not prop:
        return None
    tipo = prop.get("type")
    v = prop.get(tipo)
    if tipo in ("title", "rich_text"):
        return _texto(prop)
    if tipo in ("select", "status"):
        return v.get("name") if v else None
    if tipo == "multi_select":                     # p. ej. «Tipo de perfil»
        return [x.get("name") for x in v or [] if x.get("name")]
    if tipo == "date":
        return datetime.fromisoformat(v["start"].replace("Z", "+00:00")) if v and v.get("start") else None
    if tipo == "relation":
        return [x["id"] for x in v or []]
    return v      # checkbox, number, email, url


def _rt(texto: str | None) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": (texto or "")[:2000]}}] if texto else []}


def _sel(nombre: str | None) -> dict:
    return {"select": {"name": nombre} if nombre else None}


def _tupla(v) -> tuple[str, ...]:
    """Selección múltiple como tupla; acepta también una sola opción."""
    if v is None:
        return ()
    return tuple(v) if isinstance(v, list) else (v,)


def _texto_de(v) -> str | None:
    """Una selección como texto («30», «Otro»); si llegara un número, también."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() or None


def _numero_consecutivo(prop: dict | None) -> int | None:
    """«ID consecutivo» (tipo unique_id de Notion) -> número, o None."""
    v = (prop or {}).get("unique_id") if (prop or {}).get("type") == "unique_id" else None
    n = (v or {}).get("number")
    return n if isinstance(n, int) and not isinstance(n, bool) else None


def _id(x: str) -> str:
    return x.replace("-", "")


# ---------------------------------------------------------------------------
# Almacén
# ---------------------------------------------------------------------------
def persona_desde_pagina(pg: dict) -> Persona:
    """Una página de Participantes como Persona (también para releer UNA ficha)."""
    p = pg["properties"]
    g = lambda n: _valor(p.get(n))  # noqa: E731
    return Persona(
        id=_id(pg["id"]), alias=g("Alias") or "(sin alias)", correo=g("Correo electrónico"),
        autoriza=g("Autorización para participar") is True, aptitud=g("Aptitud"),
        respaldo=g("Respaldo declarado"), revision_respaldo=g("Revisión humana del respaldo"),
        # «Acepta videollamada» y «Zona horaria» se eliminaron de Notion el 2026-11-22.
        idioma=g("Idioma"), modalidad=g("Modalidad"),
        ofrece=g("Ofrece"), quiere_aprender=g("Quiere aprender"),
        disponibilidad=g("Disponibilidad + zona horaria"),
        # El formulario pregunta los minutos de ENSEÑANZA en «Minutos disponibles».
        minutos=g("Minutos disponibles"),
        tipo_perfil=tuple(g("Tipo de perfil") or ()),   # selección múltiple
        # Formulario nuevo: solo lectura (todavía no se usa en las reglas).
        otro_idioma=g(COLUMNA_OTRO_IDIOMA),
        objetivo_concreto=g("Objetivo concreto"),
        zona_horaria_seleccionada=g(COLUMNA_ZONA_SELECCIONADA),
        id_consecutivo=_numero_consecutivo(p.get(COLUMNA_ID_CONSECUTIVO)),
        dias_disponibles=_tupla(g(COLUMNA_DIAS_DISPONIBLES)),
        franjas={d: v for d, c in COLUMNAS_FRANJAS.items() if (v := _tupla(g(c)))},
        otras_franjas={d: v for d, c in COLUMNAS_OTRAS_FRANJAS.items() if (v := g(c))},
        minutos_seleccionados=_texto_de(g(COLUMNA_MINUTOS_SELECCIONADOS)),
        temas_adicionales_con_datos=tuple(c for c in COLUMNAS_TEMAS_ADICIONALES if g(c)),
    )


class AlmacenNotion:
    def __init__(self, cliente: ClienteNotion) -> None:
        self.c = cliente

    def personas(self) -> list[Persona]:
        return [persona_desde_pagina(pg) for pg in self.c.consultar(DS_PARTICIPANTES)]

    def matches(self) -> list[FilaMatch]:
        res = []
        for pg in self.c.consultar(DS_MATCHES):
            p = pg["properties"]
            g = lambda n: _valor(p.get(n))  # noqa: E731
            a, b = g("Participante A") or [], g("Participante B") or []
            if not a or not b:
                continue
            alias = (g("Match") or "?↔?").split("↔")
            res.append(FilaMatch(
                id=_id(pg["id"]), a=_id(a[0]), b=_id(b[0]),
                alias_a=alias[0].strip(), alias_b=alias[-1].strip(),
                a_ensena=[t.strip() for t in (g("A enseña") or "").split("|") if t.strip()],
                b_ensena=[t.strip() for t in (g("B enseña") or "").split("|") if t.strip()],
                inicio_utc=g("Inicio propuesto"),
                minutos_a=int(g("Minutos A") or 0), minutos_b=int(g("Minutos B") or 0),
                version=int(g("Versión del horario") or 1),
                respuesta_a=g("Respuesta A") or PENDIENTE, respuesta_b=g("Respuesta B") or PENDIENTE,
                estado=g("Estado") or ESPERANDO, enlace=g("Enlace Jitsi"),
                huella_a=g("Huella código A") or "", huella_b=g("Huella código B") or "",
                aviso_a=g("Aviso enviado a A") is True, aviso_b=g("Aviso enviado a B") is True,
                confirmacion_a=g("Confirmación enviada a A") is True,
                confirmacion_b=g("Confirmación enviada a B") is True,
                clave=g("Clave A2") or "", notas=g("Notas del sistema") or "",
            ))
        return res

    def respuestas_pendientes(self) -> list[FilaRespuesta]:
        filtro = {"or": [
            {"property": "Procesada", "select": {"is_empty": True}},
            {"property": "Procesada", "select": {"equals": PENDIENTE}},
        ]}
        res = []
        for pg in self.c.consultar(DS_RESPUESTAS, filtro):
            p = pg["properties"]
            res.append(FilaRespuesta(
                id=_id(pg["id"]), codigo=_valor(p.get("Código")) or "",
                respuesta=_valor(p.get("Respuesta")), procesada=_valor(p.get("Procesada")),
            ))
        return res

    @staticmethod
    def _propiedades_match(f: FilaMatch) -> dict:
        return {
            "Match": {"title": [{"type": "text", "text": {"content": f"{f.alias_a} ↔ {f.alias_b}"}}]},
            "Participante A": {"relation": [{"id": f.a}]},
            "Participante B": {"relation": [{"id": f.b}]},
            "A enseña": _rt(" | ".join(f.a_ensena)),
            "B enseña": _rt(" | ".join(f.b_ensena)),
            "Inicio propuesto": {"date": {"start": f.inicio_utc.isoformat()} if f.inicio_utc else None},
            "Minutos A": {"number": f.minutos_a},
            "Minutos B": {"number": f.minutos_b},
            "Duración total (min)": {"number": f.minutos_a + f.minutos_b},
            "Versión del horario": {"number": f.version},
            "Respuesta A": _sel(f.respuesta_a),
            "Respuesta B": _sel(f.respuesta_b),
            "Estado": _sel(f.estado),
            "Enlace Jitsi": {"url": f.enlace},
            "Huella código A": _rt(f.huella_a),
            "Huella código B": _rt(f.huella_b),
            "Aviso enviado a A": {"checkbox": f.aviso_a},
            "Aviso enviado a B": {"checkbox": f.aviso_b},
            "Confirmación enviada a A": {"checkbox": f.confirmacion_a},
            "Confirmación enviada a B": {"checkbox": f.confirmacion_b},
            "Clave A2": _rt(f.clave),
            "Notas del sistema": _rt(f.notas),
        }

    def crear_match(self, f: FilaMatch) -> str:
        return _id(self.c.crear(DS_MATCHES, self._propiedades_match(f))["id"])

    def guardar_match(self, f: FilaMatch) -> None:
        self.c.actualizar(f.id, self._propiedades_match(f))

    def marcar_respuesta(self, respuesta_id: str, estado: str, match_id: str | None) -> None:
        props = {"Procesada": _sel(estado)}
        if match_id:
            props["Match"] = {"relation": [{"id": match_id}]}
        self.c.actualizar(respuesta_id, props)


class AlmacenSoloLectura:
    """Lee de Notion pero no escribe nada: para la ejecución de simulación."""

    def __init__(self, real: AlmacenNotion) -> None:
        self.real = real
        self.escrituras: list[str] = []
        self._n = 0

    def personas(self):
        return self.real.personas()

    def matches(self):
        return self.real.matches()

    def respuestas_pendientes(self):
        return self.real.respuestas_pendientes()

    def crear_match(self, f):
        self._n += 1
        self.escrituras.append("crear match")
        return f"simulado-{self._n}"

    def guardar_match(self, f):
        self.escrituras.append(f"guardar {f.id[-6:]}")

    def marcar_respuesta(self, rid, estado, mid):
        self.escrituras.append(f"respuesta {rid[-6:]}: {estado}")


# ---------------------------------------------------------------------------
# Cursos: SOLO LECTURA (simulación del 2026-11-22; no hay escritura de Cursos)
# ---------------------------------------------------------------------------
class EscrituraNoPermitida(Exception):
    """Se intentó escribir con un cliente de solo lectura."""


class ClienteSoloLectura:
    """Envuelve ClienteNotion y solo deja CONSULTAR bases. Cualquier otra petición falla."""

    def __init__(self, real: ClienteNotion) -> None:
        self._real = real

    def __repr__(self) -> str:
        return "ClienteSoloLectura(token oculto)"

    def consultar(self, data_source_id: str, filtro: dict | None = None) -> list[dict]:
        return self._real.consultar(data_source_id, filtro)

    def leer_fuente(self, data_source_id: str) -> dict:
        """GET del esquema de una base (solo lectura)."""
        return self._real.pedir("GET", f"/data_sources/{data_source_id}")

    def leer_pagina(self, page_id: str) -> dict:
        """GET de una página (solo lectura)."""
        return self._real.pedir("GET", f"/pages/{page_id}")

    def esta_en_la_papelera(self, page_id: str) -> bool | None:
        """True solo si Notion devuelve la página y dice que está en la papelera.
        False si existe y no lo está. None si no se puede saber (p. ej. sin acceso)."""
        try:
            pg = self._real.pedir("GET", f"/pages/{page_id}")
        except ErrorNotion:
            return None
        if pg.get("in_trash") is True or pg.get("archived") is True:
            return True
        if pg.get("object") == "page":
            return False
        return None

    def pedir(self, *a, **k):
        raise EscrituraNoPermitida("cliente de solo lectura")

    crear = actualizar = pedir


def leer_cursos(cliente) -> list:
    """Temas de Cursos con sus vínculos (ids sin guiones)."""
    from .cursos import OFRECEN, QUIEREN, TemaExistente
    res = []
    for pg in cliente.consultar(DS_CURSOS):
        p = pg["properties"]
        rel = lambda n: p.get(n) or {}  # noqa: E731
        res.append(TemaExistente(
            id=_id(pg["id"]), titulo=_valor(p.get("Tema")) or "",
            ofrecen=frozenset(_id(x) for x in _valor(rel(OFRECEN)) or []),
            quieren=frozenset(_id(x) for x in _valor(rel(QUIEREN)) or []),
            lectura_incompleta=bool(rel(OFRECEN).get("has_more") or rel(QUIEREN).get("has_more")),
        ))
    return res

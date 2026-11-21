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

API = "https://api.notion.com/v1"
VERSION_API = "2025-09-03"

DS_PARTICIPANTES = os.environ.get("ANTROPIA_DS_PARTICIPANTES", "90dedf5c-24dd-836d-9814-87532a3f9afd")
DS_MATCHES = os.environ.get("ANTROPIA_DS_MATCHES", "41fedf5c-24dd-819d-a540-000b01a12b25")
DS_RESPUESTAS = os.environ.get("ANTROPIA_DS_RESPUESTAS", "41fedf5c-24dd-812f-a0c1-000b110affc1")


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
    if tipo == "date":
        return datetime.fromisoformat(v["start"].replace("Z", "+00:00")) if v and v.get("start") else None
    if tipo == "relation":
        return [x["id"] for x in v or []]
    return v      # checkbox, number, email, url


def _rt(texto: str | None) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": (texto or "")[:2000]}}] if texto else []}


def _sel(nombre: str | None) -> dict:
    return {"select": {"name": nombre} if nombre else None}


def _id(x: str) -> str:
    return x.replace("-", "")


# ---------------------------------------------------------------------------
# Almacén
# ---------------------------------------------------------------------------
class AlmacenNotion:
    def __init__(self, cliente: ClienteNotion) -> None:
        self.c = cliente

    def personas(self) -> list[Persona]:
        res = []
        for pg in self.c.consultar(DS_PARTICIPANTES):
            p = pg["properties"]
            g = lambda n: _valor(p.get(n))  # noqa: E731
            res.append(Persona(
                id=_id(pg["id"]), alias=g("Alias") or "(sin alias)", correo=g("Correo electrónico"),
                autoriza=g("Autorización para participar") is True, aptitud=g("Aptitud"),
                respaldo=g("Respaldo declarado"), revision_respaldo=g("Revisión humana del respaldo"),
                idioma=g("Idioma"), modalidad=g("Modalidad"), acepta_videollamada=g("Acepta videollamada"),
                ofrece=g("Ofrece"), quiere_aprender=g("Quiere aprender"),
                disponibilidad=g("Disponibilidad + zona horaria"), zona_horaria=g("Zona horaria"),
                # El formulario pregunta los minutos de ENSEÑANZA en «Minutos disponibles».
                minutos=g("Minutos disponibles"),
            ))
        return res

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

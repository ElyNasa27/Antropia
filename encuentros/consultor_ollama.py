"""Consultor del análisis de temas por significado con Ollama LOCAL (qwen3:1.7b).

Sustituye al consultor de la API de Anthropic (consultor_claude.py, que queda sin
usar). El modelo corre en esta computadora: la consulta va a Ollama en
127.0.0.1 y NO sale a internet. Solo se aceptan direcciones locales
(127.0.0.1, localhost, ::1) y el cliente HTTP no usa proxies.

Estado: DESACTIVADO por defecto. Para usarlo hacen falta las dos cosas a la vez:
  1. ANTROPIA_ANALISIS_SEMANTICO=si en el entorno;
  2. llamar expresamente a crear_consultor_real() (lo hace ciclo_automatico.py
     solo con esa variable).

Qué recibe el modelo (ver crear_peticion): las instrucciones fijas y los TEXTOS
de «Ofrece» y «Quiere aprender» de UNA dirección. Ni nombres, ni correos, ni ids,
ni respaldos, ni horarios. Sí llegaría lo que una persona haya escrito dentro de
esos textos.

Protecciones contra un modelo pequeño demasiado seguro de sí mismo:
  - salida forzada a un esquema JSON (formato estructurado de Ollama);
  - el modelo razona antes de responder (think) y debe contestar dos preguntas
    («mismo_tema» y «alcance_incluido») además del veredicto;
  - si el veredicto no concuerda con esas respuestas, el resultado es
    «requiere aclaración» (solo hay «cubre» si ambas son «si»);
  - si Ollama no responde, la respuesta queda cortada o no es JSON, se lanza
    ConsultaFallida y temas_semantica.AnalizadorSemantico pide aclaración.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .temas_semantica import CUBRE, INSTRUCCIONES, NO_CUBRE, REQUIERE

MODELO = "qwen3:1.7b"
URL_POR_DEFECTO = "http://127.0.0.1:11434"
HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1"})
TIEMPO_MAXIMO = 180          # segundos por consulta (con razonamiento tarda ~20-40 s)
MAX_CONSULTAS_POR_CICLO = 20
VARIABLE_ACTIVACION = "ANTROPIA_ANALISIS_SEMANTICO"
VALOR_ACTIVO = "si"
SI, NO, NO_SE_SABE = "si", "no", "no_se_sabe"

INSTRUCCIONES_OLLAMA = INSTRUCCIONES.replace(
    "Responde solo con JSON: {",
    "Antes del veredicto, contesta dos preguntas, cada una con \"si\", \"no\" o \"no_se_sabe\":\n"
    "- «mismo_tema»: ¿tratan del mismo tema concreto?\n"
    "- «alcance_incluido»: ¿todo lo que se quiere aprender (herramientas, nivel y alcance) "
    "está dentro de lo ofrecido?\n"
    "Responde solo con JSON: {\"mismo_tema\": \"si\" | \"no\" | \"no_se_sabe\", "
    "\"alcance_incluido\": \"si\" | \"no\" | \"no_se_sabe\", ",
)
assert INSTRUCCIONES_OLLAMA != INSTRUCCIONES, "no se pudieron ampliar las instrucciones"

_RESPUESTA_3 = {"type": "string", "enum": [SI, NO, NO_SE_SABE]}
ESQUEMA = {
    "type": "object",
    "properties": {
        "mismo_tema": _RESPUESTA_3,
        "alcance_incluido": _RESPUESTA_3,
        "veredicto": {"type": "string", "enum": [CUBRE, NO_CUBRE, REQUIERE]},
        "coincidencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ofrece": {"type": "string"}, "busca": {"type": "string"}},
                "required": ["ofrece", "busca"],
            },
        },
        "motivo": {"type": "string"},
    },
    "required": ["mismo_tema", "alcance_incluido", "veredicto", "coincidencias", "motivo"],
}


class ConsultaFallida(Exception):
    """La consulta no dio un veredicto utilizable (sin conexión, cortada, JSON inválido, límite)."""


def validar_url_local(url: str) -> str:
    """Solo http a esta misma computadora. Cualquier otra dirección es un error."""
    partes = urlsplit(url)
    if partes.scheme != "http" or partes.hostname not in HOSTS_LOCALES:
        raise ValueError(f"La URL de Ollama debe ser local (http://127.0.0.1:11434); se recibió «{url}».")
    if partes.username or partes.password or partes.path not in ("", "/") or partes.query:
        raise ValueError("La URL de Ollama solo puede tener esquema, host y puerto.")
    return url.rstrip("/")


def crear_peticion(consulta: dict, modelo: str = MODELO) -> dict:
    """El cuerpo EXACTO que se envía a /api/chat. No hace ninguna llamada."""
    datos = {"ofrece": list(consulta["ofrece"]), "quiere_aprender": list(consulta["quiere_aprender"])}
    return {
        "model": modelo,
        "stream": False,
        "think": True,                       # con razonamiento distingue mejor los casos ambiguos
        "format": ESQUEMA,
        "keep_alive": "10m",
        "options": {"temperature": 0, "seed": 1, "num_ctx": 8192, "num_predict": 4096},
        "messages": [
            {"role": "system", "content": INSTRUCCIONES_OLLAMA},
            {"role": "user", "content": json.dumps(datos, ensure_ascii=False)},
        ],
    }


def interpretar(resp: dict) -> dict:
    """Comprueba que el veredicto concuerde con las dos preguntas. Si no: aclaración."""
    tema, alcance, veredicto = resp.get("mismo_tema"), resp.get("alcance_incluido"), resp.get("veredicto")
    if tema == SI and alcance == SI:
        esperado = CUBRE
    elif tema == NO:
        esperado = NO_CUBRE
    else:
        esperado = REQUIERE
    if veredicto == esperado:
        return resp
    return {"veredicto": REQUIERE, "coincidencias": [],
            "motivo": f"respuesta no clara del modelo (veredicto «{veredicto}» con "
                      f"mismo_tema={tema}, alcance_incluido={alcance})"}


# Envía JSON (o nada, para GET) y devuelve el JSON de la respuesta.
Transporte = Callable[[str, dict | None, float], dict]


def transporte_http(url: str, cuerpo: dict | None, tiempo: float) -> dict:
    validar_url_local(url.split("/api/")[0])
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # sin proxies
    with abridor.open(req, timeout=tiempo) as r:
        return json.load(r)


class ConsultorOllama:
    """Consultor para AnalizadorSemantico. En las pruebas, el transporte es simulado."""

    def __init__(self, transporte: Transporte, url: str = URL_POR_DEFECTO, modelo: str = MODELO,
                 max_consultas: int | None = MAX_CONSULTAS_POR_CICLO) -> None:
        if transporte is None:
            raise ValueError("Hace falta un transporte explícito; no se crea ninguno por defecto.")
        self.transporte, self.url, self.modelo = transporte, validar_url_local(url), modelo
        self.max_consultas = max_consultas
        self.enviadas = 0

    def disponible(self) -> tuple[bool, str]:
        """¿Responde Ollama y tiene el modelo instalado? No envía ningún tema."""
        try:
            r = self.transporte(f"{self.url}/api/tags", None, 10)
        except (OSError, ValueError) as e:
            return False, f"Ollama no responde en {self.url} ({type(e).__name__})"
        nombres = {m.get("name") for m in r.get("models", []) if isinstance(m, dict)}
        if self.modelo not in nombres:
            return False, f"el modelo {self.modelo} no está instalado (ollama pull {self.modelo})"
        return True, "ok"

    def __call__(self, consulta: dict) -> dict:
        if self.max_consultas is not None and self.enviadas >= self.max_consultas:
            raise ConsultaFallida("límite de consultas de este ciclo")
        self.enviadas += 1
        try:
            r = self.transporte(f"{self.url}/api/chat", crear_peticion(consulta, self.modelo), TIEMPO_MAXIMO)
        except (OSError, ValueError) as e:           # incluye URLError y tiempo agotado
            raise ConsultaFallida(f"Ollama no respondió ({type(e).__name__})") from e
        if not isinstance(r, dict) or r.get("error"):
            raise ConsultaFallida("Ollama devolvió un error")
        if r.get("done_reason") == "length":
            raise ConsultaFallida("respuesta cortada")
        texto = (r.get("message") or {}).get("content")
        if not isinstance(texto, str) or not texto.strip():
            raise ConsultaFallida("respuesta sin texto")
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError as e:
            raise ConsultaFallida("respuesta que no es JSON") from e
        if not isinstance(datos, dict):
            raise ConsultaFallida("respuesta que no es un objeto JSON")
        return interpretar(datos)


class ConsultorConMemoria:
    """Recuerda entre ciclos las respuestas VÁLIDAS del modelo, en un archivo local.

    Así, cada 30 minutos solo se consultan las direcciones nuevas. El archivo no
    guarda textos: la clave es una huella SHA-256 (modelo + instrucciones + temas)
    y las coincidencias se guardan como posiciones en las listas. Los fallos no
    se guardan: se reintentan en el ciclo siguiente.
    """

    def __init__(self, consultor: ConsultorOllama, ruta: Path) -> None:
        self.consultor, self.ruta = consultor, Path(ruta)
        self.recordadas = self.nuevas = 0
        try:
            self._datos = json.loads(self.ruta.read_text("utf-8"))
        except (OSError, ValueError):
            self._datos = {}

    def _clave(self, consulta: dict) -> str:
        base = [self.consultor.modelo, INSTRUCCIONES_OLLAMA, consulta["ofrece"], consulta["quiere_aprender"]]
        return hashlib.sha256(json.dumps(base, ensure_ascii=False).encode("utf-8")).hexdigest()

    def __call__(self, consulta: dict) -> dict:
        ofrece, busca = list(consulta["ofrece"]), list(consulta["quiere_aprender"])
        guardada = self._datos.get(self._clave(consulta))
        if isinstance(guardada, dict):
            try:
                citas = [{"ofrece": ofrece[i], "busca": busca[j]} for i, j in guardada["citas"]]
                self.recordadas += 1
                return {"veredicto": guardada["veredicto"], "coincidencias": citas,
                        "motivo": guardada.get("motivo", "") + " (respuesta recordada)"}
            except (KeyError, IndexError, TypeError, ValueError):
                pass                                     # entrada dañada: se vuelve a consultar
        resp = self.consultor(consulta)
        self.nuevas += 1
        citas = []
        for c in resp.get("coincidencias") or []:
            o, b = (c.get("ofrece"), c.get("busca")) if isinstance(c, dict) else (None, None)
            if o not in ofrece or b not in busca:
                return resp                  # cita inventada: no se recuerda; la validación pide aclaración
            citas.append([ofrece.index(o), busca.index(b)])
        self._datos[self._clave(consulta)] = {"veredicto": resp.get("veredicto"), "citas": citas,
                                              "motivo": str(resp.get("motivo", ""))[:300]}
        self._guardar()
        return resp

    def _guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.ruta.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._datos, f, ensure_ascii=False)
        os.replace(tmp, self.ruta)


def crear_consultor_real() -> ConsultorOllama:
    """Solo con ANTROPIA_ANALISIS_SEMANTICO=si. URL opcional: ANTROPIA_OLLAMA_URL (local)."""
    if os.environ.get(VARIABLE_ACTIVACION, "") != VALOR_ACTIVO:
        raise RuntimeError(f"Análisis semántico desactivado: {VARIABLE_ACTIVACION} no es «{VALOR_ACTIVO}».")
    url = os.environ.get("ANTROPIA_OLLAMA_URL", "").strip() or URL_POR_DEFECTO
    maximo = int(os.environ.get("ANTROPIA_OLLAMA_MAX_CONSULTAS", "") or MAX_CONSULTAS_POR_CICLO)
    return ConsultorOllama(transporte_http, url=url, max_consultas=maximo)

"""Apoyo del envío exclusivo (encuentros/envio_exclusivo.py).

  - `huella` / `base_correo`: nombre estable y sin datos personales de cada correo
    (un lado de un par) en el registro de envíos.
  - `ConsultaEjecucionesGitHub`: estado de una ejecución de GitHub Actions (id y
    reintento). Es la PRUEBA POSITIVA de que un intento terminó; sin ella, un intento sin
    cierre cuenta como activo.

Decisión del usuario del 2026-11-23: el registro de envíos NO usa un repositorio externo;
vive en la propia base «Matches por cursos [PRUEBA]» (ver match_cursos_notion.RegistroNotion).

En las pruebas solo se usa con respuestas HTTP simuladas: nunca se conecta a GitHub.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Callable

API = "https://api.github.com"
PREFIJO = "antropia-correos"


def huella(clave: str, lado: str) -> str:
    """32 caracteres hexadecimales derivados de la clave del par y del lado. Sin datos personales."""
    return hashlib.sha256(f"{clave}|{lado}".encode()).hexdigest()[:32]


def base_correo(clave: str, lado: str) -> str:
    return f"{PREFIJO}/{huella(clave, lado)}-{lado.lower()}"


class ConsultaEjecucionesGitHub:
    """`consulta(id, reintento)` -> el «status» de ese reintento de la ejecución, o None.

    Solo lectura. Necesita, en el workflow, `permissions: actions: read`."""

    def __init__(self, repo: str, token: str, abrir: Callable = urllib.request.urlopen) -> None:
        if not (repo and token) or repo.count("/") != 1:
            raise ValueError("Repositorio o token de GitHub no válidos.")
        self._repo, self._token, self._abrir = repo, token, abrir

    def __repr__(self) -> str:
        return "ConsultaEjecucionesGitHub(token oculto)"

    def __call__(self, ejecucion: str, reintento: str) -> str | None:
        if not (str(ejecucion).isdigit() and str(reintento).isdigit()):
            return None
        req = urllib.request.Request(
            f"{API}/repos/{self._repo}/actions/runs/{ejecucion}/attempts/{reintento}", method="GET",
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with self._abrir(req, timeout=30) as r:
                return (json.loads(r.read().decode() or "{}") or {}).get("status")
        except (urllib.error.URLError, OSError, ValueError):
            return None

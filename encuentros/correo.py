"""Correo automático de aviso de match.

Decisión del 2026-11-21: en cuanto A2 detecta que dos personas son compatibles
(resultado «Propuesta»), el sistema redacta y ENVÍA automáticamente un aviso a
cada una, al «Correo electrónico» que dejaron en el formulario de Notion.
No hay aprobación manual de este correo.

Privacidad:
  - Las direcciones viven solo en `AgendaCorreos` (privada): no aparecen en
    `repr`, en la bitácora, en los mensajes ni en el correo de la otra persona.
  - El aviso incluye solo el nombre (Alias) de la otra persona y los temas.

Envío:
  - `EnvioSimulado`: para pruebas y demo; no sale nada de la máquina.
  - `EnvioGmailSMTP`: Gmail por SMTP (smtp.gmail.com:587, STARTTLS) con una
    «contraseña de aplicación». Usuario y contraseña se leen de variables de
    entorno; nunca se escriben en el código, en Git ni en la memoria.
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

from .modelos import Participante, PropuestaMatch

VAR_USUARIO = "ANTROPIA_SMTP_USUARIO"
VAR_CLAVE = "ANTROPIA_SMTP_CLAVE"            # contraseña de aplicación de Google
VAR_REMITENTE_NOMBRE = "ANTROPIA_SMTP_NOMBRE"

ASUNTO_MATCH = "Antropia: encontramos a alguien para intercambiar conocimiento"

_CORREO_VALIDO = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
_PATRON_CORREO = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+")


class ErrorEnvio(Exception):
    """El servicio de correo no pudo enviar el mensaje."""


def correo_valido(direccion: str | None) -> bool:
    return bool(direccion) and len(direccion) <= 254 and bool(_CORREO_VALIDO.match(direccion.strip()))


def contiene_correo(texto: str) -> bool:
    return bool(_PATRON_CORREO.search(texto))


def _una_linea(texto: str) -> str:
    """Quita saltos de línea (evita inyectar cabeceras o alterar el formato)."""
    return " ".join((texto or "").split())


def _lista(temas: list[str]) -> str:
    temas = [_una_linea(t) for t in temas if t and t.strip()]
    # «Excel avanzado → Excel básico» (coincidencia no exacta, ver temas.py)
    temas = [t.replace(" → ", " (para «", 1) + "»)" if " → " in t else t for t in temas]
    if not temas:
        return "—"
    return temas[0] if len(temas) == 1 else ", ".join(temas[:-1]) + " y " + temas[-1]


# ---------------------------------------------------------------------------
# Agenda privada de correos
# ---------------------------------------------------------------------------
class AgendaCorreos:
    """Correos de las personas, por id de participante. Privada."""

    def __init__(self, correos: dict[str, str | None] | None = None) -> None:
        self._correos: dict[str, str] = {}
        for pid, direccion in (correos or {}).items():
            if direccion:
                self.guardar(pid, direccion)

    def guardar(self, participante_id: str, direccion: str) -> None:
        direccion = (direccion or "").strip()
        if not correo_valido(direccion):
            raise ValueError(f"El correo de {participante_id} no es válido.")
        self._correos[participante_id] = direccion

    def correo_de(self, participante_id: str) -> str | None:
        return self._correos.get(participante_id)

    def __repr__(self) -> str:   # nunca mostrar direcciones
        return f"AgendaCorreos({len(self._correos)} correos, ocultos)"


# ---------------------------------------------------------------------------
# Redacción
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CorreoMatch:
    match_id: str
    destinatario_id: str
    para: str = field(repr=False)            # privado
    asunto: str = ASUNTO_MATCH
    cuerpo: str = ""
    # (nombre de archivo, tipo MIME «principal/secundario», contenido)
    adjuntos: tuple[tuple[str, str, bytes], ...] = ()


def redactar_aviso_match(nombre: str, nombre_otra: str, ensenas: list[str], aprendes: list[str]) -> str:
    """Solo aviso: nombre de la otra persona y temas. Sin datos de contacto."""
    nombre, nombre_otra = _una_linea(nombre), _una_linea(nombre_otra)
    return (
        f"Hola, {nombre}:\n\n"
        "¡Buenas noticias! En Antropia encontramos a una persona compatible contigo "
        "para intercambiar conocimiento.\n\n"
        f"• Persona: {nombre_otra}\n"
        f"• Tú compartes: {_lista(ensenas)}\n"
        f"• {nombre_otra} comparte: {_lista(aprendes)}\n\n"
        "Pronto te contactaremos para acordar el día y la hora del encuentro.\n"
        "Por tu privacidad, no compartimos tus datos de contacto con la otra persona.\n\n"
        "Comparte lo que sabes, aprende lo que sueñas.\n"
        "— Comunidad Antropia"
    )


# ---------------------------------------------------------------------------
# Servicios de envío
# ---------------------------------------------------------------------------
class ServicioEnvio(Protocol):
    def enviar(self, correo: CorreoMatch) -> None: ...


class EnvioSimulado:
    """No envía nada: guarda los correos en una lista. Para pruebas y demo."""

    def __init__(self, fallar_para: set[str] | None = None) -> None:
        self.enviados: list[CorreoMatch] = []
        self.fallar_para = set(fallar_para or ())   # ids de participante que fallan

    def enviar(self, correo: CorreoMatch) -> None:
        if correo.destinatario_id in self.fallar_para:
            raise ErrorEnvio("fallo simulado del servidor de correo")
        self.enviados.append(correo)


class EnvioGmailSMTP:
    """Envío real por Gmail SMTP. Credenciales SOLO desde variables de entorno."""

    SERVIDOR = "smtp.gmail.com"
    PUERTO = 587

    def __init__(self, entorno: dict[str, str] | None = None, timeout: float = 30) -> None:
        entorno = os.environ if entorno is None else entorno
        self._usuario = (entorno.get(VAR_USUARIO) or "").strip()
        self._clave = (entorno.get(VAR_CLAVE) or "").replace(" ", "")
        self._nombre = _una_linea(entorno.get(VAR_REMITENTE_NOMBRE) or "Comunidad Antropia")
        faltan = [v for v, x in ((VAR_USUARIO, self._usuario), (VAR_CLAVE, self._clave)) if not x]
        if faltan:
            raise ValueError("Faltan variables de entorno para el correo: " + ", ".join(faltan))
        if not correo_valido(self._usuario):
            raise ValueError(f"{VAR_USUARIO} no es un correo válido.")
        self.timeout = timeout

    def __repr__(self) -> str:
        return "EnvioGmailSMTP(credenciales ocultas)"

    def construir(self, correo: CorreoMatch) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = formataddr((self._nombre, self._usuario))
        msg["To"] = correo.para
        msg["Subject"] = _una_linea(correo.asunto)
        msg.set_content(correo.cuerpo)
        for nombre, tipo, contenido in correo.adjuntos:
            principal, secundario = tipo.split("/", 1)
            msg.add_attachment(contenido, maintype=principal, subtype=secundario, filename=nombre)
        return msg

    def enviar(self, correo: CorreoMatch) -> None:
        try:
            with smtplib.SMTP(self.SERVIDOR, self.PUERTO, timeout=self.timeout) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self._usuario, self._clave)
                smtp.send_message(self.construir(correo))
        except (smtplib.SMTPException, OSError) as e:
            # Sin direcciones ni credenciales en el mensaje de error.
            raise ErrorEnvio(f"{type(e).__name__}") from None


# ---------------------------------------------------------------------------
# Notificador automático
# ---------------------------------------------------------------------------
ENVIADO = "enviado"
FALLIDO = "fallido"
SIN_CORREO = "sin correo"


@dataclass
class ResultadoAviso:
    match_id: str
    estado_por_persona: dict[str, str] = field(default_factory=dict)

    @property
    def completo(self) -> bool:
        return bool(self.estado_por_persona) and all(
            e == ENVIADO for e in self.estado_por_persona.values()
        )


class NotificadorMatch:
    """Envía automáticamente el aviso de match a las dos personas.

    - Si alguna de las dos no tiene correo, no se envía a ninguna (ninguna
      recibe un aviso que la otra no recibe).
    - Nunca se envía dos veces el mismo aviso (match + persona).
    - Si el envío falla, queda pendiente y `notificar` se puede repetir: solo se
      envía a quien aún no lo recibió.
    """

    def __init__(self, agenda: AgendaCorreos, servicio: ServicioEnvio) -> None:
        self.agenda = agenda
        self.servicio = servicio
        self._enviados: set[tuple[str, str]] = set()

    def ya_enviado(self, match_id: str, participante_id: str) -> bool:
        return (match_id, participante_id) in self._enviados

    def notificar(self, match: PropuestaMatch, a: Participante, b: Participante) -> ResultadoAviso:
        res = ResultadoAviso(match.id)
        pares = ((a, b.nombre, match.a_ensena, match.b_ensena),
                 (b, a.nombre, match.b_ensena, match.a_ensena))
        sin_correo = [p.id for p, *_ in pares if not self.agenda.correo_de(p.id)]
        if sin_correo:
            for p, *_ in pares:
                res.estado_por_persona[p.id] = (
                    ENVIADO if self.ya_enviado(match.id, p.id) else SIN_CORREO
                )
            return res
        for p, nombre_otra, ensenas, aprendes in pares:
            if self.ya_enviado(match.id, p.id):
                res.estado_por_persona[p.id] = ENVIADO
                continue
            correo = CorreoMatch(
                match_id=match.id, destinatario_id=p.id, para=self.agenda.correo_de(p.id),
                cuerpo=redactar_aviso_match(p.nombre, nombre_otra, ensenas, aprendes),
            )
            try:
                self.servicio.enviar(correo)
            except ErrorEnvio:
                res.estado_por_persona[p.id] = FALLIDO
                continue
            self._enviados.add((match.id, p.id))
            res.estado_por_persona[p.id] = ENVIADO
        return res

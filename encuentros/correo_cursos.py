"""Correos de coincidencias SOLO de cursos (preparado el 2026-11-22; NO activado).

Sigue la plantilla de Notion «Plantilla de correo · Propuesta de intercambio»
(página PLANTILLA_PAGINA). El texto está aquí, revisado frente a esa versión; antes
de enviar, el programa comprueba que la plantilla de Notion no haya cambiado desde
la versión revisada (PLANTILLA_EDITADA). Si cambió, no se envía nada hasta revisarla.

Reglas del contenido:
  - Es una POSIBILIDAD, no un encuentro confirmado.
  - No se afirma que idioma, horario o duración sean compatibles: no se han comprobado.
  - Recíproco: cada persona recibe «Lo que podrías aprender» y «Lo que podrías compartir».
    En una dirección: quien enseña recibe solo «Lo que podrías compartir» y quien
    aprende recibe solo «Lo que podrías aprender», con una frase que lo explica.
  - De la otra persona se comparte solo su alias y los cursos que coinciden (como en el
    aviso aprobado el 2026-11-21). Su objetivo, experiencia, respaldo y minutos NO se
    comparten: Participantes no tiene ninguna columna de autorización para compartirlos.
    La sección de experiencia dice «No se ha compartido información sobre experiencia o
    respaldo», como indica la plantilla. Nunca se presenta un respaldo como verificado.
  - Los datos propios de quien recibe (su objetivo y sus minutos) sí pueden aparecer.
  - Nunca se incluye el correo de nadie.
"""
from __future__ import annotations

from dataclasses import dataclass

from .automatico import Persona
from .match_cursos import RECIPROCO, ParCursos
from .minutos_formulario import elegir_minutos

PLANTILLA_PAGINA = "936edf5c-24dd-8373-b2a0-8126737cc355"
PLANTILLA_EDITADA = "2026-11-22T22:18"          # última edición revisada (al minuto, UTC)

SIN_RESPALDO = "No se ha compartido información sobre experiencia o respaldo."
NO_COMPROBADO = ("Solo hemos comparado los cursos. El idioma, el horario y la duración del "
                 "encuentro todavía no se han comprobado ni acordado.")

APRENDE, ENSENA = "aprende", "enseña"


def _una_linea(texto: str | None) -> str:
    return " ".join((texto or "").split())


def _lista(cursos) -> str:
    cs = [_una_linea(c) for c in cursos if _una_linea(c)]
    if not cs:
        return "—"
    return cs[0] if len(cs) == 1 else ", ".join(cs[:-1]) + " y " + cs[-1]


@dataclass(frozen=True)
class CorreoCursos:
    clave: str                 # clave del par (Matches por cursos)
    lado: str                  # "A" o "B"
    destinatario_id: str
    asunto: str
    cuerpo: str


def roles(par: ParCursos, lado: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(cursos que esta persona enseña, cursos que aprende) en el par."""
    a = tuple(c.curso for c in par.a_ensena)
    b = tuple(c.curso for c in par.b_ensena)
    return (a, b) if lado == "A" else (b, a)


def redactar(par: ParCursos, lado: str, yo: Persona, otra: Persona, instrucciones: str) -> tuple[str, str]:
    nombre, nombre_otra = _una_linea(yo.alias), _una_linea(otra.alias)
    ensena, aprende = roles(par, lado)
    asunto = f"{nombre}, tienes una posible oportunidad de intercambio en Antropia"

    partes = [
        f"Hola, {nombre}:",
        f"Encontramos una posible oportunidad de intercambio de conocimientos con {nombre_otra}.",
    ]
    if par.tipo != RECIPROCO:
        partes.append(
            f"Por ahora la coincidencia es en una sola dirección: {nombre_otra} podría enseñarte algo "
            "que quieres aprender." if aprende else
            f"Por ahora la coincidencia es en una sola dirección: podrías enseñar a {nombre_otra} algo "
            "que quiere aprender.")
    if aprende:
        objetivo = _una_linea(yo.objetivo_concreto)      # objetivo PROPIO: no es de la otra persona
        bloque = ["Lo que podrías aprender",
                  f"Curso o tema que ofrece {nombre_otra}: {_lista(aprende)}."]
        if objetivo:
            bloque.append(f"Tu objetivo al aprenderlo: {objetivo}.")
        bloque.append(f"Experiencia o respaldo de {nombre_otra}: {SIN_RESPALDO}")
        partes.append("\n".join(bloque))
    if ensena:
        partes.append("\n".join(["Lo que podrías compartir", f"Curso o tema que ofreces: {_lista(ensena)}."]))
    minutos = elegir_minutos(yo.minutos_seleccionados, yo.minutos).minutos if ensena else None
    tiempo = ["Tiempo para el intercambio"]
    if minutos:
        tiempo.append(f"- Tu tiempo de enseñanza disponible: {minutos} minutos.")
    tiempo.append(NO_COMPROBADO)
    partes.append("\n".join(tiempo))
    partes.append("\n".join(["¿Te interesa?", _una_linea(instrucciones)]))
    partes.append("Esta es una propuesta: el encuentro solo se confirma cuando ambas personas aceptan.")
    partes.append("¡Gracias por compartir lo que sabes y seguir aprendiendo!\n\nEquipo de Antropia")
    return asunto, "\n\n".join(partes)


def plantilla_sin_cambios(ultima_edicion: str | None) -> bool:
    """True si la última edición de la página (ISO, UTC) es la revisada, al minuto."""
    return bool(ultima_edicion) and ultima_edicion[:16] == PLANTILLA_EDITADA

"""Análisis de temas por dirección, con reglas locales o por significado (A2).

Cada DIRECCIÓN del intercambio se analiza por separado: lo que una persona
ofrece frente a lo que la OTRA quiere aprender. El resultado es uno de:

  cubre                 al menos un tema ofrecido cubre un tema buscado
  no_cubre              no tratan del mismo tema
  requiere aclaración   están relacionados, pero no se puede concluir

Dos analizadores:

  AnalizadorReglas      (por defecto) solo las reglas locales y conservadoras de
                        temas.py. Sin red ni servicios externos.

  AnalizadorSemantico   primero aplica las reglas; si dan una coincidencia clara,
                        no consulta nada. Si no, pregunta a un «consultor» que
                        juzga por el significado. El consultor se inyecta desde
                        fuera: este módulo NO se conecta a ningún servicio. En las
                        pruebas es una función con respuestas ficticias.

Lo que recibe el consultor (ver construir_consulta): las instrucciones y los
TEXTOS de los temas de esa dirección. Nada más: ni nombres, ni correos, ni ids,
ni respaldos, ni horarios.

La respuesta del consultor se valida con rigor y, ante cualquier duda, el
resultado es «requiere aclaración» (nunca una coincidencia):
  - veredicto desconocido o respuesta mal formada;
  - «cubre» sin citar temas, o citando un texto que nadie escribió;
  - el consultor no responde o falla: también «requiere aclaración» (sin
    guardarlo, para reintentar después). Nunca se toma un fallo por «no cubre».
El análisis solo compara temas: no verifica conocimientos, niveles ni
respaldos, y su resultado nunca se presenta como verificación.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .temas import SEMANTICO, Aclaracion, Coincidencia, comparar

CUBRE, NO_CUBRE, REQUIERE = "cubre", "no_cubre", "requiere_aclaracion"
ORIGEN_REGLAS, ORIGEN_SEMANTICO = "reglas", "semántico"
MAX_MOTIVO = 300

INSTRUCCIONES = (
    "Recibes dos listas de textos escritos por participantes de un intercambio de "
    "conocimientos: «ofrece» (lo que una persona dice que puede enseñar) y "
    "«quiere_aprender» (lo que OTRA persona quiere aprender). Decide, por el significado, "
    "si al menos un tema ofrecido cubre al menos un tema que se quiere aprender.\n"
    "Reglas:\n"
    "1. Básate solo en los textos. No supongas conocimientos, niveles ni experiencia "
    "que no estén escritos.\n"
    "2. «cubre»: lo buscado queda claramente dentro de lo ofrecido (mismo tema, con un "
    "nivel y un alcance compatibles).\n"
    "3. «requiere_aclaracion»: están relacionados, pero el nivel o el alcance no "
    "permiten concluir, o algún texto es ambiguo.\n"
    "4. «no_cubre»: no tratan del mismo tema. Compartir solo una categoría amplia "
    "(p. ej. «cocina italiana» y «cocina mexicana») no basta.\n"
    "5. No juzgues si la persona está capacitada ni sus credenciales.\n"
    "Responde solo con JSON: {\"veredicto\": \"cubre\" | \"no_cubre\" | "
    "\"requiere_aclaracion\", \"coincidencias\": [{\"ofrece\": <texto exacto de la "
    "lista>, \"busca\": <texto exacto de la lista>}], \"motivo\": <una frase breve>}. "
    "En «coincidencias» copia los textos tal cual; déjala vacía si no es «cubre»."
)


@dataclass(frozen=True)
class Direccion:
    """Resultado de UNA dirección (lo que X ofrece frente a lo que Y busca)."""
    estado: str                                   # CUBRE / NO_CUBRE / REQUIERE
    coincidencias: tuple[Coincidencia, ...] = ()
    aclaraciones: tuple[Aclaracion, ...] = ()
    origen: str = ORIGEN_REGLAS
    motivo: str = ""


class AnalizadorTemas(Protocol):
    def analizar(self, ofrece: Sequence[str], busca: Sequence[str]) -> Direccion: ...


def por_reglas(ofrece: Sequence[str], busca: Sequence[str]) -> Direccion:
    r = comparar(ofrece, busca)
    if r.cubre:
        return Direccion(CUBRE, tuple(r.coincidencias))
    if r.requiere_aclaracion:
        return Direccion(REQUIERE, aclaraciones=tuple(r.aclaraciones),
                         motivo="; ".join(a.motivo for a in r.aclaraciones))
    return Direccion(NO_CUBRE)


class AnalizadorReglas:
    """Comportamiento anterior: solo reglas locales (temas.py)."""

    def analizar(self, ofrece: Sequence[str], busca: Sequence[str]) -> Direccion:
        return por_reglas(ofrece, busca)


ANALIZADOR_REGLAS = AnalizadorReglas()

# Recibe la consulta (solo textos de temas) y devuelve el veredicto como dict.
Consultor = Callable[[dict], dict]


def construir_consulta(ofrece: Sequence[str], busca: Sequence[str]) -> dict:
    """Exactamente lo que recibiría el consultor. Solo textos de temas."""
    return {"instrucciones": INSTRUCCIONES, "ofrece": list(ofrece), "quiere_aprender": list(busca)}


def _aclarar(ofrece: Sequence[str], busca: Sequence[str], motivo: str) -> Direccion:
    a = Aclaracion("; ".join(ofrece), "; ".join(busca), motivo)
    return Direccion(REQUIERE, aclaraciones=(a,), origen=ORIGEN_SEMANTICO, motivo=motivo)


def validar_respuesta(resp: object, ofrece: Sequence[str], busca: Sequence[str]) -> Direccion:
    """Convierte la respuesta del consultor en una Direccion. Ante la duda: aclaración."""
    if not isinstance(resp, dict):
        return _aclarar(ofrece, busca, "análisis semántico: respuesta no válida")
    veredicto = resp.get("veredicto")
    motivo = resp.get("motivo")
    motivo = " ".join(motivo.split())[:MAX_MOTIVO] if isinstance(motivo, str) else ""
    motivo = motivo or "sin motivo indicado"
    if veredicto == NO_CUBRE:
        return Direccion(NO_CUBRE, origen=ORIGEN_SEMANTICO, motivo=motivo)
    if veredicto == REQUIERE:
        return _aclarar(ofrece, busca, f"análisis semántico: {motivo}")
    if veredicto != CUBRE:
        return _aclarar(ofrece, busca, "análisis semántico: veredicto no válido")
    citas = resp.get("coincidencias")
    if not isinstance(citas, list) or not citas:
        return _aclarar(ofrece, busca, "análisis semántico: «cubre» sin citar los temas")
    coincidencias = []
    for c in citas:
        o = c.get("ofrece") if isinstance(c, dict) else None
        b = c.get("busca") if isinstance(c, dict) else None
        if o not in ofrece or b not in busca:      # solo textos que alguien escribió
            return _aclarar(ofrece, busca, "análisis semántico: cita un tema que no figura en los datos")
        coincidencias.append(Coincidencia(o, b, SEMANTICO))
    unicas = tuple(dict.fromkeys(coincidencias))
    return Direccion(CUBRE, unicas, origen=ORIGEN_SEMANTICO, motivo=motivo)


class AnalizadorSemantico:
    """Reglas primero; el consultor solo para las direcciones que las reglas no resuelven."""

    def __init__(self, consultor: Consultor) -> None:
        self.consultor = consultor
        self.consultas = 0
        self.fallos = 0
        self._cache: dict[tuple[tuple[str, ...], tuple[str, ...]], Direccion] = {}

    def analizar(self, ofrece: Sequence[str], busca: Sequence[str]) -> Direccion:
        base = por_reglas(ofrece, busca)
        if base.estado == CUBRE or not ofrece or not busca:
            return base
        clave = (tuple(ofrece), tuple(busca))
        if clave in self._cache:
            return self._cache[clave]
        self.consultas += 1
        try:
            resp = self.consultor(construir_consulta(ofrece, busca))
        except Exception:                    # sin respuesta: aclaración, sin guardar en caché
            self.fallos += 1
            motivo = "análisis semántico: el modelo no respondió"
            return _aclarar(ofrece, busca, f"{motivo}; {base.motivo}" if base.motivo else motivo)
        res = validar_respuesta(resp, ofrece, busca)
        self._cache[clave] = res
        return res

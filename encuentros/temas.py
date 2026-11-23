"""Comparación CONSERVADORA de temas escritos en texto libre («Ofrece» / «Quiere aprender»).

Funciona solo en local: sin internet, sin servicios externos y sin dependencias.
NO entiende el lenguaje: aplica reglas y listas de palabras escritas a mano y
solo reconoce como equivalentes las expresiones que esas listas definen.

Resultado de comparar UN tema ofrecido con UN tema buscado:

  Compatibles (cuentan para el match):
    igual          mismas palabras de contenido, sin contar mayúsculas, tildes,
                   plurales, relleno ni palabras de formato como «clases de»
                   («Clases de inglés» / «ingles»)
    sinónimo       mismas ideas con palabras de un mismo grupo de SINONIMOS
                   («inglés» / «English», «fotos con el móvil» / «fotografía con celular»)
    tema definido  las dos frases describen el mismo tema de TEMAS_DEFINIDOS
                   («crear tablas en Excel para controlar gastos» /
                    «aprender a organizar gastos usando Excel»)

  «requiere aclaración» (NO cuenta para el match):
    - mismo tema, pero el nivel no consta en las dos frases o no es el mismo
      («Excel» / «Excel avanzado», «inglés avanzado» / «inglés básico»);
    - una frase es más general o más concreta que la otra
      («Excel» / «Excel para controlar gastos»);
    - comparten una palabra concreta pero dicen cosas distintas
      («Excel para contabilidad» / «Excel para finanzas»);
    - parece una errata («fotografia» / «fotogarfía»): no se corrige sola.

  Sin coincidencia:
    - no comparten ninguna palabra de contenido;
    - solo comparten una palabra amplia o de categoría (AMPLIAS):
      «cocina italiana» / «cocina mexicana»; la misma categoría no basta;
    - quien enseña declara un nivel MENOR que el buscado.

Para ampliar lo que se reconoce se editan SINONIMOS (palabras sueltas con el
mismo significado) y TEMAS_DEFINIDOS (temas compuestos y las palabras aceptadas
para decirlos). Cada entrada debe ser una equivalencia clara, nunca una
relación de categoría.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable

IGUAL, SINONIMO, TEMA_DEFINIDO = "igual", "sinónimo", "tema definido"
REQUIERE_ACLARACION = "requiere aclaración"
# «semántico» solo lo produce el análisis por significado (temas_semantica.py),
# nunca las reglas de este módulo. Es la coincidencia menos directa.
SEMANTICO = "semántico"
FUERZA = {IGUAL: 0, SINONIMO: 1, TEMA_DEFINIDO: 2, SEMANTICO: 3}   # menor = más directa
SEPARADOR_ETIQUETA = " → "
PARECIDO_ERRATA = 0.85

# Palabras que no aportan tema.
RELLENO = {
    "de", "del", "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "e", "o", "u",
    "a", "al", "en", "con", "para", "por", "mi", "mis", "su", "sus", "tu", "tus", "sobre",
    "lo", "como", "que", "mediante", "desde", "hasta", "entre", "me", "te", "se",
}
# Intención o forma de aprender: no cambian el tema.
INTENCION = {
    "aprender", "aprendo", "aprendiendo", "aprendizaje", "ensenar", "ensenando", "enseno",
    "ensenanza", "quiero", "quisiera", "busco", "ofrezco", "saber", "usar", "usando", "uso",
    "utilizar", "utilizando", "emplear", "empleando", "manejar", "manejo",
}
# Formato de la sesión: no cambia el tema.
GENERICAS = {
    "clase", "curso", "taller", "leccion", "tutoria", "sesion", "nocion", "introduccion",
    "intro", "nivel", "tema", "conocimiento", "idioma", "tecnica", "practica",
}
NIVELES = {
    "basico": 1, "basica": 1, "principiante": 1, "inicial": 1, "elemental": 1,
    "intermedio": 2, "intermedia": 2,
    "avanzado": 3, "avanzada": 3, "experto": 3, "experta": 3,
}
NOMBRE_NIVEL = {1: "básico", 2: "intermedio", 3: "avanzado"}
# Expresiones de varias palabras que se leen como una sola (escritas sin tildes).
FRASES = {
    "desde cero": "principiante",
    "microsoft excel": "excel",
}
# Grupos de palabras con el MISMO significado. El primero de cada grupo es el nombre común.
SINONIMOS: list[tuple[str, ...]] = [
    ("ingles", "english"),
    ("espanol", "castellano", "spanish"),
    ("frances", "french"),
    ("portugues", "portuguese"),
    ("aleman", "german"),
    ("italiano", "italian"),
    ("fotografia", "foto", "photography"),
    ("movil", "celular", "smartphone"),
    ("programacion", "programar"),
    ("cocina", "cocinar"),
    ("reposteria", "pasteleria"),
    ("baile", "bailar", "danza"),
    ("canto", "cantar"),
    ("dibujo", "dibujar"),
    ("pintura", "pintar"),
    ("costura", "coser"),
    ("tejido", "tejer"),
    ("guitarra", "guitar"),
    ("gasto", "gastar", "egreso"),
    ("conversacion", "conversar", "conversacional", "hablar", "hablado", "oral", "speaking"),
]
# Palabras amplias o de categoría: compartir SOLO una de ellas no indica relación.
AMPLIAS = {
    "programacion", "cocina", "fotografia", "musica", "arte", "diseno", "tecnologia",
    "informatica", "computacion", "negocio", "finanza", "deporte", "salud", "ciencia",
    "matematica", "escritura", "lectura", "manualidad", "baile", "canto",
}


@dataclass(frozen=True)
class TemaDefinido:
    """Un tema compuesto y las palabras aceptadas para describirlo.

    Una frase describe este tema si contiene al menos una palabra de cada grupo
    de `requeridas` y TODAS sus demás palabras están en `permitidas`. Si añade
    cualquier otra palabra («personales», «empresa»…), ya no se considera el
    mismo tema y se pide aclaración.
    """
    clave: str
    descripcion: str
    requeridas: tuple[frozenset[str], ...]
    permitidas: frozenset[str] = frozenset()

    def describe(self, palabras: frozenset[str]) -> bool:
        if not all(palabras & g for g in self.requeridas):
            return False
        return palabras <= self.permitidas.union(*self.requeridas)


def _f(*p: str) -> frozenset[str]:
    return frozenset(p)


# Palabras ya normalizadas: sin tildes, en singular y con el nombre común de SINONIMOS.
TEMAS_DEFINIDOS: tuple[TemaDefinido, ...] = (
    TemaDefinido(
        "excel_control_gastos", "Excel para registrar, controlar u organizar gastos",
        requeridas=(_f("excel"), _f("gasto")),
        permitidas=_f("tabla", "planilla", "plantilla", "hoja", "crear", "hacer", "armar",
                      "elaborar", "controlar", "control", "organizar", "organizacion",
                      "registrar", "registro", "administrar", "gestionar", "ordenar",
                      "seguimiento", "llevar"),
    ),
    TemaDefinido(
        "python", "Programación en Python",
        requeridas=(_f("python"),),
        permitidas=_f("programacion"),
    ),
    TemaDefinido(
        "conversacion_ingles", "Conversación en inglés",
        requeridas=(_f("ingles"), _f("conversacion")),
        permitidas=_f("practicar"),
    ),
    TemaDefinido(
        "fotografia_movil", "Fotografía con el teléfono móvil",
        requeridas=(_f("fotografia"), _f("movil")),
        permitidas=_f("telefono", "hacer", "tomar", "sacar"),
    ),
)


# ---------------------------------------------------------------------------
# Análisis de una frase
# ---------------------------------------------------------------------------
def _plano(texto: str) -> str:
    sin = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    plano = re.sub(r"[^a-z0-9+#]+", " ", sin.lower()).strip()
    for frase, palabra in FRASES.items():
        plano = re.sub(rf"\b{frase}\b", palabra, plano)
    return plano


_SIN_PLURAL = ("ingles", "frances", "portugues", "python", "ss")


def _singular(p: str) -> str:
    if p.endswith(_SIN_PLURAL):
        return p
    if len(p) > 4 and p.endswith("es") and p[-3] in "lrndzj":
        return p[:-2]
    if len(p) > 3 and p.endswith("s"):
        return p[:-1]
    return p


_COMUN: dict[str, str] = {}
for _grupo in SINONIMOS:
    for _p in _grupo:
        _COMUN[_p] = _COMUN[_singular(_p)] = _grupo[0]

_VACIAS = RELLENO | INTENCION | GENERICAS
_VACIAS = _VACIAS | {_singular(p) for p in _VACIAS}
_NIVELES = {**NIVELES, **{_singular(k): v for k, v in NIVELES.items()}}


@dataclass(frozen=True)
class Tema:
    texto: str
    escritas: frozenset[str]      # palabras de contenido como se escribieron (en singular)
    palabras: frozenset[str]      # las mismas, con el nombre común de SINONIMOS
    nivel: int | None
    definido: str | None          # clave de TEMAS_DEFINIDOS, si describe exactamente uno


def analizar(texto: str) -> Tema:
    escritas, palabras, nivel = set(), set(), None
    for p in _plano(texto).split():
        s = _singular(p)
        if p in _NIVELES or s in _NIVELES:
            nivel = max(nivel or 0, _NIVELES.get(p) or _NIVELES[s])
        elif p not in _VACIAS and s not in _VACIAS:
            escritas.add(s)
            palabras.add(_COMUN.get(p) or _COMUN.get(s) or s)
    pal = frozenset(palabras)
    definidos = [t.clave for t in TEMAS_DEFINIDOS if pal and t.describe(pal)]
    return Tema(texto, frozenset(escritas), pal, nivel, definidos[0] if len(definidos) == 1 else None)


# ---------------------------------------------------------------------------
# Comparación de un tema ofrecido con un tema buscado
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Resultado:
    tipo: str                 # IGUAL, SINONIMO, TEMA_DEFINIDO o REQUIERE_ACLARACION
    motivo: str = ""

    @property
    def compatible(self) -> bool:
        return self.tipo in FUERZA


def _nivel(n: int | None) -> str:
    return NOMBRE_NIVEL[n] if n else "sin nivel indicado"


def _posible_errata(x: frozenset[str], y: frozenset[str]) -> bool:
    """Mismo número de palabras, cada una casi idéntica a otra, y alguna distinta."""
    if len(x) != len(y) or x == y:
        return False

    def cerca(a: str, b: str) -> bool:
        return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= PARECIDO_ERRATA)

    return all(any(cerca(a, b) for b in y) for a in x) and all(any(cerca(a, b) for a in x) for b in y)


def comparar_tema(ofrece: Tema | str, busca: Tema | str) -> Resultado | None:
    """Compara UN tema ofrecido con UN tema buscado. None = sin coincidencia."""
    o = ofrece if isinstance(ofrece, Tema) else analizar(ofrece)
    b = busca if isinstance(busca, Tema) else analizar(busca)
    if not o.palabras or not b.palabras:
        return None                         # «clases», «idiomas»…: sin tema concreto

    if o.palabras == b.palabras:
        tipo = IGUAL if o.escritas == b.escritas else SINONIMO
    elif o.definido and o.definido == b.definido:
        tipo = TEMA_DEFINIDO
    else:
        tipo = None

    if tipo:
        if o.nivel == b.nivel:
            return Resultado(tipo)
        if o.nivel and b.nivel and o.nivel < b.nivel:
            return None                     # quien enseña declara un nivel menor
        return Resultado(REQUIERE_ACLARACION,
                         f"nivel incierto: ofrece {_nivel(o.nivel)}, busca {_nivel(b.nivel)}")

    comunes = o.palabras & b.palabras
    if comunes:
        if o.palabras < b.palabras:
            return Resultado(REQUIERE_ACLARACION, "alcance incierto: lo ofrecido es más general que lo buscado")
        if b.palabras < o.palabras:
            return Resultado(REQUIERE_ACLARACION, "alcance incierto: lo ofrecido es más concreto que lo buscado")
        if comunes - AMPLIAS:
            return Resultado(REQUIERE_ACLARACION,
                             "alcance incierto: comparten «" + ", ".join(sorted(comunes))
                             + "» pero dicen cosas distintas")
        return None                         # solo comparten una categoría amplia
    if _posible_errata(o.palabras, b.palabras):
        return Resultado(REQUIERE_ACLARACION, "posible errata: las palabras son casi iguales")
    return None


# ---------------------------------------------------------------------------
# Comparación de listas (una dirección: lo que A ofrece frente a lo que B busca)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Coincidencia:
    ofrece: str
    busca: str
    tipo: str

    @property
    def etiqueta(self) -> str:
        """Texto para «A enseña»: el ofrecido, y lo buscado si se escribió distinto."""
        if _plano(self.ofrece) == _plano(self.busca):
            return self.ofrece
        return f"{self.ofrece}{SEPARADOR_ETIQUETA}{self.busca}"


@dataclass(frozen=True)
class Aclaracion:
    ofrece: str
    busca: str
    motivo: str


@dataclass
class ComparacionTemas:
    coincidencias: list[Coincidencia] = field(default_factory=list)
    aclaraciones: list[Aclaracion] = field(default_factory=list)

    @property
    def cubre(self) -> bool:
        """Al menos un tema ofrecido cubre con claridad un tema buscado."""
        return bool(self.coincidencias)

    @property
    def requiere_aclaracion(self) -> bool:
        """No hay coincidencia clara, pero sí temas relacionados que hay que aclarar."""
        return not self.coincidencias and bool(self.aclaraciones)


def comparar(ofrece: Iterable[str], busca: Iterable[str]) -> ComparacionTemas:
    """Para cada tema ofrecido, su coincidencia más directa con lo buscado.

    Las aclaraciones solo se anotan para temas (ofrecidos y buscados) que no
    quedaron cubiertos por ninguna coincidencia clara.
    """
    buscados = [analizar(b) for b in busca]
    res = ComparacionTemas()
    dudas: list[Aclaracion] = []
    for texto in ofrece:
        t = analizar(texto)
        mejor: Coincidencia | None = None
        for b in buscados:
            r = comparar_tema(t, b)
            if r is None:
                continue
            if not r.compatible:
                dudas.append(Aclaracion(texto, b.texto, r.motivo))
            elif mejor is None or FUERZA[r.tipo] < FUERZA[mejor.tipo]:
                mejor = Coincidencia(texto, b.texto, r.tipo)
        if mejor:
            res.coincidencias.append(mejor)
    ofrecidos = {c.ofrece for c in res.coincidencias}
    buscados_ok = {c.busca for c in res.coincidencias}
    res.aclaraciones = [a for a in dudas if a.ofrece not in ofrecidos and a.busca not in buscados_ok]
    return res


def coincidencias(ofrece: Iterable[str], busca: Iterable[str]) -> list[Coincidencia]:
    """Solo las coincidencias claras (compatibles)."""
    return comparar(ofrece, busca).coincidencias

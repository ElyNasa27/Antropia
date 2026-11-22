"""Ciclo automático: formulario de Notion → match → respuestas → Jitsi → confirmación.

Decisiones del 2026-11-21 (todo automático, sin revisiones humanas de match,
pacto, respuestas ni confirmación; las únicas decisiones humanas siguen siendo
«Aptitud» y «Revisión humana del respaldo» en Participantes):

  0. A1 AUTOMÁTICO comprueba los datos de cada persona (temas, idioma, modalidad,
     disponibilidad legible, zona horaria IANA, minutos y correo). Es una
     comprobación automática: no escribe «Aptitud» ni nada en Notion y no
     sustituye a las decisiones humanas de «Aptitud» y del respaldo.
  1. A2 empareja a las personas elegibles de Participantes (temas comparados de
     forma conservadora; si hay que aclarar un tema, NO se crea el match).
  2. Por cada par compatible se crea una fila en «Matches [PRUEBA]» y se envía a
     cada persona un correo con la fecha/hora propuesta (en su zona), los minutos
     y su CÓDIGO PERSONAL para responder en el formulario «Responder a tu match».
  3. Cada respuesta del formulario se aplica al match (se busca por la huella del
     código; el código nunca se guarda).
  4. Si ambas aceptan la MISMA versión y el horario sigue siendo válido, el match
     queda confirmado. La confirmación (con el enlace y un .ics) se envía solo
     cuando hay un enlace real: el que crea el proveedor de salas configurado
     (`Configuracion.nueva_sala`, desactivado por defecto) o el que una persona
     escribe en «Enlace Jitsi». El sistema nunca inventa un enlace.
  5. Si el horario pasó, ya no está libre o choca con otro encuentro confirmado,
     se propone otro horario (con códigos nuevos). Si alguien responde «No me
     interesa», el match se cierra y se avisa a la otra persona.

Este módulo no sabe nada de Notion: trabaja contra un `Almacen` (Notion en
producción, memoria en las pruebas).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable, Protocol

from . import a2_match
from .correo import CorreoMatch, ErrorEnvio, ServicioEnvio, correo_valido
from .disponibilidad import leer_disponibilidad, leer_temas
from .temas import SEPARADOR_ETIQUETA
from .modelos import (
    DIAS_SEMANA, REVISION_APROBADA, Participante, PropuestaMatch, Solicitud,
)
from .temas import REQUIERE_ACLARACION
from .zonas import ResolverZona, ZonaNoDisponible, nombre_legible, resolver_zona_real

# Estados y respuestas, con los mismos textos que las opciones de Notion
ESPERANDO, CONFIRMADO, CERRADO = "Esperando respuestas", "Confirmado", "Cerrado sin encuentro"
PENDIENTE, ACEPTO, NO_INTERESA = "Pendiente", "Acepto", "No me interesa"
APLICADA, CODIGO_NO_VALIDO, YA_RESPONDIDA, CADUCADA, SIN_RESPUESTA = (
    "Aplicada", "Código no válido", "Ya respondida", "Caducada", "Sin respuesta",
)

ANTICIPACION = timedelta(hours=24)   # el primer horario propuesto, al menos 24 h después
MARGEN_CONFIRMAR = timedelta(hours=1)  # si faltan menos de 1 h, se busca otro horario
MAX_VERSIONES = 3                    # después de 3 horarios sin respuesta, se cierra
DIAS_BUSQUEDA = 14

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # sin 0/O ni 1/I
_CODIGO = re.compile(r"([A-Z2-9]{4})[\s\-–]*([A-Z2-9]{4})")


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------
@dataclass
class Persona:
    """Una fila de Participantes, tal como viene de Notion."""
    id: str
    alias: str
    correo: str | None = field(default=None, repr=False)
    autoriza: bool = False
    aptitud: str | None = None
    respaldo: str | None = None
    revision_respaldo: str | None = None
    idioma: str | None = None
    modalidad: str | None = None
    acepta_videollamada: str | None = None
    ofrece: str | None = None
    quiere_aprender: str | None = None
    disponibilidad: str | None = None
    zona_horaria: str | None = None
    minutos: float | None = None


@dataclass
class FilaMatch:
    id: str
    a: str
    b: str
    alias_a: str
    alias_b: str
    a_ensena: list[str]
    b_ensena: list[str]
    inicio_utc: datetime | None
    minutos_a: int
    minutos_b: int
    version: int = 1
    respuesta_a: str = PENDIENTE
    respuesta_b: str = PENDIENTE
    estado: str = ESPERANDO
    enlace: str | None = None
    huella_a: str = ""
    huella_b: str = ""
    aviso_a: bool = False
    aviso_b: bool = False
    confirmacion_a: bool = False
    confirmacion_b: bool = False
    clave: str = ""
    notas: str = ""

    @property
    def duracion(self) -> timedelta:
        return timedelta(minutes=self.minutos_a + self.minutos_b)

    def lado(self, pid: str) -> str:
        return "a" if pid == self.a else "b"


@dataclass
class FilaRespuesta:
    id: str
    codigo: str
    respuesta: str | None
    procesada: str | None = PENDIENTE


class Almacen(Protocol):
    def personas(self) -> list[Persona]: ...
    def matches(self) -> list[FilaMatch]: ...
    def respuestas_pendientes(self) -> list[FilaRespuesta]: ...
    def crear_match(self, fila: FilaMatch) -> str: ...
    def guardar_match(self, fila: FilaMatch) -> None: ...
    def marcar_respuesta(self, respuesta_id: str, estado: str, match_id: str | None) -> None: ...


# ---------------------------------------------------------------------------
# Códigos personales
# ---------------------------------------------------------------------------
def generar_codigo() -> str:
    c = "".join(secrets.choice(_ALFABETO) for _ in range(8))
    return f"{c[:4]}-{c[4:]}"


def normalizar_codigo(texto: str | None) -> str | None:
    m = _CODIGO.search((texto or "").upper())
    return f"{m.group(1)}-{m.group(2)}" if m else None


def huella(codigo: str, clave_secreta: str) -> str:
    """HMAC-SHA256: sin la clave secreta, la huella de Notion no sirve para adivinar el código."""
    return hmac.new(clave_secreta.encode(), codigo.encode(), hashlib.sha256).hexdigest()


SALAS_PRUEBA, SALAS_JITSI = "jitsi-prueba", "jitsi"   # valores de ANTROPIA_SALAS
PREFIJO_JITSI = "https://meet.jit.si/"
PREFIJO_SALA_PRUEBA = "AntropiaPRUEBA"


def nueva_sala_jitsi(prueba: bool = False) -> str:
    """Enlace de una sala de Jitsi Meet con un nombre aleatorio difícil de adivinar.

    El nombre lleva 128 bits aleatorios (32 caracteres hexadecimales de `secrets`).
    La sala no existe hasta que entra la primera persona. Las salas de prueba
    llevan «AntropiaPRUEBA» en el nombre para distinguirlas.
    """
    return PREFIJO_JITSI + (PREFIJO_SALA_PRUEBA if prueba else "Antropia") + secrets.token_hex(16)


def nueva_sala_jitsi_prueba() -> str:
    return nueva_sala_jitsi(prueba=True)


def es_enlace_de_prueba(enlace: str | None) -> bool:
    return bool(enlace) and enlace.startswith(PREFIJO_JITSI + PREFIJO_SALA_PRUEBA)


def proveedor_de_salas(valor: str | None) -> Callable[[], str] | None:
    """Traduce ANTROPIA_SALAS: vacío = sin salas automáticas; «jitsi-prueba»; «jitsi»."""
    v = (valor or "").strip().lower()
    if not v:
        return None
    if v == SALAS_PRUEBA:
        return nueva_sala_jitsi_prueba
    if v == SALAS_JITSI:
        return nueva_sala_jitsi
    raise ValueError(f"ANTROPIA_SALAS no válido: {valor!r} (use «{SALAS_PRUEBA}», «{SALAS_JITSI}» o déjelo vacío)")


def enlace_valido(enlace: str | None) -> bool:
    """Solo enlaces https con dominio. No comprueba que la sala exista."""
    return bool(enlace) and re.fullmatch(r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?", enlace.strip()) is not None


# ---------------------------------------------------------------------------
# Conversión al modelo de A2
# ---------------------------------------------------------------------------
REVISADO_EN_NOTION = "persona en Notion («Revisión humana del respaldo»)"


def a_modelo(p: Persona) -> tuple[Participante, Solicitud, list[str]]:
    """Devuelve (participante, solicitud, avisos). No inventa datos."""
    avisos = []
    disp = leer_disponibilidad(p.disponibilidad)
    if disp.no_reconocido:
        avisos.append("disponibilidad no reconocida: " + "; ".join(disp.no_reconocido))
    zona = (p.zona_horaria or "").strip() or disp.zona_en_texto
    minutos = None
    if isinstance(p.minutos, (int, float)) and p.minutos > 0 and float(p.minutos).is_integer():
        minutos = int(p.minutos)
    acepta = {"sí": True, "si": True, "no": False}.get((p.acepta_videollamada or "").strip().lower())
    revision = p.revision_respaldo or "Pendiente"
    part = Participante(
        id=p.id, nombre=p.alias, autoriza_participar=p.autoriza is True, aptitud=p.aptitud,
        respaldo_declarado=p.respaldo, revision_respaldo=revision,
        respaldo_revisado_por=REVISADO_EN_NOTION if revision == REVISION_APROBADA else None,
        idioma=p.idioma,
    )
    sol = Solicitud(
        id="sol-" + p.id, participante_id=p.id,
        tema_ofrece=leer_temas(p.ofrece), tema_busca=leer_temas(p.quiere_aprender),
        idioma=p.idioma, modalidad=p.modalidad, minutos_por_sesion=minutos,
        zona_horaria=zona, disponibilidad=disp.franjas,
        estado="Lista",                         # automático: no hay base Solicitudes
        acepta_virtual=acepta,
    )
    return part, sol, avisos


def _como_propuesta(f: FilaMatch, ahora: datetime) -> PropuestaMatch:
    """Las filas de Matches, para que A2 no repita pares y respete el límite de 3."""
    terminado = f.estado == CONFIRMADO and f.inicio_utc and f.inicio_utc + f.duracion < ahora
    inactiva = f.estado == CERRADO or terminado
    return PropuestaMatch(
        id=f.id, solicitud_origen="sol-" + f.a, solicitud_candidata="sol-" + f.b,
        participante_a=f.a, participante_b=f.b, a_ensena=f.a_ensena, b_ensena=f.b_ensena,
        motivo="", cerrada_automaticamente=bool(inactiva),
    )


# ---------------------------------------------------------------------------
# A1 automático
# ---------------------------------------------------------------------------
def validar_a1_automatico(p: Persona, resolver: ResolverZona) -> list[str]:
    """Columnas de Participantes que faltan o no se pueden usar. No inventa ni corrige nada.

    Es una comprobación AUTOMÁTICA: no decide la aptitud ni revisa el respaldo.
    """
    part, sol, _ = a_modelo(p)
    problemas = []
    if not sol.tema_ofrece:
        problemas.append("Ofrece")
    if not sol.tema_busca:
        problemas.append("Quiere aprender")
    if not (p.idioma or "").strip():
        problemas.append("Idioma")
    if not (p.modalidad or "").strip():
        problemas.append("Modalidad")
    if not sol.disponibilidad:
        problemas.append("Disponibilidad + zona horaria")
    if not sol.zona_horaria:
        problemas.append("Zona horaria")
    else:
        try:
            resolver(sol.zona_horaria)
        except ZonaNoDisponible:
            problemas.append("Zona horaria (no existe en la base IANA)")
    if sol.minutos_por_sesion is None:
        problemas.append("Minutos disponibles")
    if not correo_valido(p.correo):
        problemas.append("Correo electrónico")
    return problemas


# ---------------------------------------------------------------------------
# Redacción
# ---------------------------------------------------------------------------
def _lista(temas: list[str], pidio: str | None = None) -> str:
    """«Excel avanzado → Excel básico» se muestra como «Excel avanzado (Bruno pidió: «Excel básico»)»."""
    def uno(t: str) -> str:
        if pidio and SEPARADOR_ETIQUETA in t:
            ofrece, busca = t.split(SEPARADOR_ETIQUETA, 1)
            return f"{ofrece} ({pidio}: «{busca}»)"
        return t.replace(SEPARADOR_ETIQUETA, " / ")
    temas = [uno(t) for t in temas]
    return temas[0] if len(temas) == 1 else ", ".join(temas[:-1]) + " y " + temas[-1]


def hora_local(inicio: datetime, duracion: timedelta, zona: str, resolver: ResolverZona) -> str:
    tz = resolver(zona)
    ini, fin = inicio.astimezone(tz), (inicio + duracion).astimezone(tz)
    return (f"{DIAS_SEMANA[ini.weekday()]} {ini.day} de {MESES[ini.month - 1]} de {ini.year}, "
            f"{ini:%H:%M}–{fin:%H:%M} (hora de {nombre_legible(zona)})")


def redactar_propuesta(f: FilaMatch, yo: Persona, zona: str, codigo: str,
                       url_formulario: str, resolver: ResolverZona) -> tuple[str, str]:
    lado = f.lado(yo.id)
    otra = f.alias_b if lado == "a" else f.alias_a
    ensenas, aprendes = (f.a_ensena, f.b_ensena) if lado == "a" else (f.b_ensena, f.a_ensena)
    mis_min, sus_min = (f.minutos_a, f.minutos_b) if lado == "a" else (f.minutos_b, f.minutos_a)
    nuevo = f.version > 1
    asunto = ("Antropia: nuevo horario para tu encuentro" if nuevo
              else "Antropia: encontramos a alguien para intercambiar conocimiento")
    intro = ("Te proponemos un NUEVO horario para tu encuentro con {o}. "
             "El código anterior ya no sirve.\n\n" if nuevo else
             "¡Buenas noticias! Encontramos a una persona compatible contigo para "
             "intercambiar conocimiento.\n\n").format(o=otra)
    cuerpo = (
        f"Hola, {yo.alias}:\n\n{intro}"
        f"• Persona: {otra}\n"
        f"• Tú compartes: {_lista(ensenas, otra + ' pidió')}\n"
        f"• {otra} comparte: {_lista(aprendes, 'tú pediste')}\n"
        f"• Fecha: {hora_local(f.inicio_utc, f.duracion, zona, resolver)}\n"
        f"• Tiempo: {mis_min} min enseñas tú · {sus_min} min enseña {otra} · "
        f"duración total: {mis_min + sus_min} min\n"
        "• Modalidad: videollamada\n\n"
        "Para responder:\n"
        f"  1. Abre el formulario: {url_formulario}\n"
        f"  2. Escribe tu código personal: {codigo}\n"
        "  3. Elige «Acepto» o «No me interesa».\n\n"
        "Tu código es personal: no lo compartas. Si ambas personas aceptan, te "
        "enviaremos el enlace de la videollamada y una invitación para tu calendario.\n"
        "Por tu privacidad, no compartimos tus datos de contacto con la otra persona.\n\n"
        "— Comunidad Antropia"
    )
    return asunto, cuerpo


def redactar_confirmacion(f: FilaMatch, yo: Persona, zona: str, resolver: ResolverZona) -> tuple[str, str]:
    lado = f.lado(yo.id)
    otra = f.alias_b if lado == "a" else f.alias_a
    mis_min, sus_min = (f.minutos_a, f.minutos_b) if lado == "a" else (f.minutos_b, f.minutos_a)
    cuerpo = (
        f"¡Confirmado, {yo.alias}! Las dos personas aceptaron.\n\n"
        f"• Encuentro con: {otra}\n"
        f"• Fecha: {hora_local(f.inicio_utc, f.duracion, zona, resolver)}\n"
        f"• Tiempo: {mis_min} min enseñas tú · {sus_min} min enseña {otra} · "
        f"duración total: {mis_min + sus_min} min\n"
        f"• Enlace de la videollamada: {f.enlace}\n"
        + ("  (Enlace de PRUEBA del piloto: sala temporal de Jitsi Meet.)\n" if es_enlace_de_prueba(f.enlace) else "")
        + "\n"
        "Adjuntamos una invitación (.ics) para añadirlo a tu calendario.\n"
        + ("Nota: Jitsi puede pedir que la primera persona en entrar inicie sesión "
           "(Google, GitHub o Facebook) para abrir la sala.\n" if "meet.jit.si" in (f.enlace or "") else "")
        + "\n— Comunidad Antropia"
    )
    return "Antropia: tu encuentro está confirmado", cuerpo


def redactar_cierre(nombre: str, otra: str) -> tuple[str, str]:
    cuerpo = (
        f"Hola, {nombre}:\n\n"
        f"El encuentro propuesto con {otra} no se realizará. No tienes que hacer nada: "
        "seguiremos buscando otra persona compatible contigo.\n\n— Comunidad Antropia"
    )
    return "Antropia: el encuentro propuesto no se realizará", cuerpo


def ics(f: FilaMatch, ahora: datetime) -> bytes:
    fmt = "%Y%m%dT%H%M%SZ"
    ini = f.inicio_utc.astimezone(UTC)
    texto = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Antropia//Encuentros//ES", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{f.id}-v{f.version}@antropia",
        f"DTSTAMP:{ahora.astimezone(UTC):{fmt}}",
        f"DTSTART:{ini:{fmt}}",
        f"DTEND:{ini + f.duracion:{fmt}}",
        "SUMMARY:" + ("[PRUEBA] " if es_enlace_de_prueba(f.enlace) else "")
        + "Encuentro Antropia (intercambio de conocimiento)",
        f"LOCATION:{f.enlace}",
        f"DESCRIPTION:Videollamada: {f.enlace}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])
    return texto.encode("utf-8")


# ---------------------------------------------------------------------------
# Ciclo
# ---------------------------------------------------------------------------
@dataclass
class Configuracion:
    url_formulario: str
    clave_codigos: str
    resolver: ResolverZona = resolver_zona_real
    generar_codigo: Callable[[], str] = generar_codigo
    # Proveedor de salas. None (por defecto) = el sistema NO crea enlaces: la
    # confirmación espera a que una persona escriba un enlace real en «Enlace Jitsi».
    # nueva_sala_jitsi_prueba = salas de Jitsi marcadas «PRUEBA» (piloto);
    # nueva_sala_jitsi = salas reales. En ambos casos, una sala aleatoria distinta
    # por pareja, creada solo cuando las dos personas aceptaron la misma versión.
    nueva_sala: Callable[[], str] | None = None


@dataclass
class Resumen:
    personas: int = 0
    elegibles: int = 0
    matches_nuevos: int = 0
    respuestas: dict[str, int] = field(default_factory=dict)
    confirmados: int = 0
    reprogramados: int = 0
    cerrados: int = 0
    correos_enviados: int = 0
    errores_envio: int = 0
    a1_con_problemas: int = 0          # personas elegibles que A1 automático dejó fuera
    pares_por_aclarar: int = 0         # temas relacionados pero inciertos: no se propone match
    confirmados_sin_enlace: int = 0    # ambas aceptaron; falta un enlace real para confirmar
    avisos: list[str] = field(default_factory=list)   # sin datos personales


class Ciclo:
    def __init__(self, almacen: Almacen, envio: ServicioEnvio, cfg: Configuracion,
                 ahora: datetime | None = None) -> None:
        self.almacen, self.envio, self.cfg = almacen, envio, cfg
        self.ahora = ahora or datetime.now(UTC)
        self.r = Resumen()

    # -- utilidades ---------------------------------------------------------
    def _enviar(self, f: FilaMatch, p: Persona, asunto: str, cuerpo: str, adjuntos=()) -> bool:
        try:
            self.envio.enviar(CorreoMatch(f.id, p.id, p.correo, asunto, cuerpo, tuple(adjuntos)))
        except ErrorEnvio as e:
            self.r.errores_envio += 1
            self.r.avisos.append(f"{f.id}: falló un envío ({e})")
            return False
        self.r.correos_enviados += 1
        return True

    def _zona(self, p: Persona) -> str | None:
        return (p.zona_horaria or "").strip() or leer_disponibilidad(p.disponibilidad).zona_en_texto

    # -- ejecución ----------------------------------------------------------
    def ejecutar(self) -> Resumen:
        self.personas = {p.id: p for p in self.almacen.personas()}
        self.r.personas = len(self.personas)
        self.filas = self.almacen.matches()
        self._aplicar_respuestas()
        for f in self.filas:
            if f.estado == ESPERANDO:
                self._avanzar(f)
            elif f.estado == CONFIRMADO and not (f.confirmacion_a and f.confirmacion_b):
                self._enviar_confirmaciones(f)
        self._nuevos_matches()
        return self.r

    def _aplicar_respuestas(self) -> None:
        por_huella = {}
        for f in self.filas:
            for lado in ("a", "b"):
                h = getattr(f, f"huella_{lado}")
                if h:
                    por_huella[h] = (f, lado)
        for resp in self.almacen.respuestas_pendientes():
            estado, match_id = self._una_respuesta(resp, por_huella)
            self.r.respuestas[estado] = self.r.respuestas.get(estado, 0) + 1
            self.almacen.marcar_respuesta(resp.id, estado, match_id)

    def _una_respuesta(self, resp: FilaRespuesta, por_huella) -> tuple[str, str | None]:
        codigo = normalizar_codigo(resp.codigo)
        if codigo is None:
            return CODIGO_NO_VALIDO, None
        encontrado = por_huella.get(huella(codigo, self.cfg.clave_codigos))
        if encontrado is None:
            return CODIGO_NO_VALIDO, None
        f, lado = encontrado
        if resp.respuesta not in (ACEPTO, NO_INTERESA):
            return SIN_RESPUESTA, f.id
        if f.estado != ESPERANDO or getattr(f, f"respuesta_{lado}") != PENDIENTE:
            return YA_RESPONDIDA, f.id
        if f.inicio_utc is None or f.inicio_utc <= self.ahora:
            return CADUCADA, f.id
        setattr(f, f"respuesta_{lado}", resp.respuesta)
        self.almacen.guardar_match(f)
        return APLICADA, f.id

    def _avanzar(self, f: FilaMatch) -> None:
        pa, pb = self.personas.get(f.a), self.personas.get(f.b)
        if pa is None or pb is None:
            return self._cerrar(f, "una de las personas ya no está en Participantes", avisar=False)
        if NO_INTERESA in (f.respuesta_a, f.respuesta_b):
            return self._cerrar(f, "una persona respondió «No me interesa»")
        if not (f.aviso_a and f.aviso_b):
            self._enviar_propuestas(f, pa, pb)     # reintento de avisos pendientes
            return
        vence = f.inicio_utc is None or f.inicio_utc - MARGEN_CONFIRMAR <= self.ahora
        if f.respuesta_a == ACEPTO and f.respuesta_b == ACEPTO:
            motivo = self._motivo_no_confirmable(f, pa, pb)
            if motivo is None:
                if not enlace_valido(f.enlace) and self.cfg.nueva_sala is not None:
                    f.enlace = self._sala_unica(f)
                f.estado = CONFIRMADO
                f.notas = (f"confirmado automáticamente el {self.ahora:%Y-%m-%d %H:%M} UTC "
                           f"(ambas aceptaron la versión {f.version})")
                if not enlace_valido(f.enlace):
                    f.notas += "; falta el enlace de la videollamada: escribirlo en «Enlace Jitsi»"
                self.almacen.guardar_match(f)
                self.r.confirmados += 1
                self._enviar_confirmaciones(f)
                return
            return self._reprogramar(f, pa, pb, motivo)
        if vence:
            return self._reprogramar(f, pa, pb, "llegó la hora propuesta sin las dos aceptaciones")

    def _sala_unica(self, f: FilaMatch) -> str | None:
        """Una sala distinta por pareja: nunca reutiliza el enlace de otro match."""
        usados = {g.enlace for g in self.filas if g is not f and g.enlace}
        for _ in range(5):
            enlace = self.cfg.nueva_sala()
            if enlace_valido(enlace) and enlace not in usados:
                return enlace
        self.r.avisos.append(f"{f.id}: no se pudo crear una sala única")
        return None

    def _motivo_no_confirmable(self, f: FilaMatch, pa: Persona, pb: Persona) -> str | None:
        if f.inicio_utc - MARGEN_CONFIRMAR <= self.ahora:
            return "la hora propuesta ya pasó o está demasiado cerca"
        for p in (pa, pb):
            part, _, _ = a_modelo(p)
            if a2_match.motivos_participante_no_elegible(part):
                return f"{p.alias} ya no es elegible"
        fin = f.inicio_utc + f.duracion
        for g in self.filas:
            if g is f or g.estado != CONFIRMADO or g.inicio_utc is None:
                continue
            if {g.a, g.b} & {f.a, f.b} and g.inicio_utc < fin and f.inicio_utc < g.inicio_utc + g.duracion:
                return "choca con otro encuentro confirmado"
        return None

    def _reprogramar(self, f: FilaMatch, pa: Persona, pb: Persona, motivo: str) -> None:
        if f.version >= MAX_VERSIONES:
            return self._cerrar(f, f"{motivo}; se alcanzó el máximo de {MAX_VERSIONES} horarios")
        desde = self.ahora + ANTICIPACION
        for g in self.filas:   # no antes de que terminen sus encuentros confirmados
            if g is not f and g.estado == CONFIRMADO and {g.a, g.b} & {f.a, f.b} and g.inicio_utc:
                desde = max(desde, g.inicio_utc + g.duracion)
        (part_a, sol_a, _), (part_b, sol_b, _) = a_modelo(pa), a_modelo(pb)
        try:
            ev = a2_match.evaluar_par(part_a, sol_a, part_b, sol_b, desde, self.cfg.resolver, DIAS_BUSQUEDA)
        except ZonaNoDisponible:
            ev = None
        if ev is None or ev.resultado != a2_match.PROPUESTA:
            return self._cerrar(f, f"{motivo}; no hay otro horario común")
        f.version += 1
        f.inicio_utc = ev.primer_inicio
        f.minutos_a = ev.evidencia["minutos_por_persona"][f.a]
        f.minutos_b = ev.evidencia["minutos_por_persona"][f.b]
        f.respuesta_a = f.respuesta_b = PENDIENTE
        f.aviso_a = f.aviso_b = False
        f.huella_a = f.huella_b = ""
        f.enlace = None
        f.notas = f"horario v{f.version}: {motivo}"
        self.almacen.guardar_match(f)
        self.r.reprogramados += 1
        self._enviar_propuestas(f, pa, pb)

    def _cerrar(self, f: FilaMatch, motivo: str, avisar: bool = True) -> None:
        f.estado = CERRADO
        f.notas = motivo
        f.huella_a = f.huella_b = ""
        self.almacen.guardar_match(f)
        self.r.cerrados += 1
        if not avisar:
            return
        for pid, otra, avisado, resp in ((f.a, f.alias_b, f.aviso_a, f.respuesta_a),
                                         (f.b, f.alias_a, f.aviso_b, f.respuesta_b)):
            p = self.personas.get(pid)
            # A quien dijo «No me interesa» no se le escribe de nuevo.
            if p and avisado and resp != NO_INTERESA and correo_valido(p.correo):
                self._enviar(f, p, *redactar_cierre(p.alias, otra))

    def _enviar_propuestas(self, f: FilaMatch, pa: Persona, pb: Persona) -> None:
        for p in (pa, pb):
            lado = f.lado(p.id)
            if getattr(f, f"aviso_{lado}"):
                continue
            zona = self._zona(p)
            codigo = self.cfg.generar_codigo()
            setattr(f, f"huella_{lado}", huella(codigo, self.cfg.clave_codigos))
            asunto, cuerpo = redactar_propuesta(f, p, zona, codigo, self.cfg.url_formulario, self.cfg.resolver)
            # La huella se guarda ANTES de enviar: así el código del correo siempre es válido.
            self.almacen.guardar_match(f)
            if self._enviar(f, p, asunto, cuerpo):
                setattr(f, f"aviso_{lado}", True)
                self.almacen.guardar_match(f)

    def _enviar_confirmaciones(self, f: FilaMatch) -> None:
        if not enlace_valido(f.enlace):
            self.r.confirmados_sin_enlace += 1
            self.r.avisos.append(f"{f.id}: confirmado sin enlace de videollamada; no se envía la confirmación")
            return
        adjunto = ("encuentro-antropia.ics", "text/calendar", ics(f, self.ahora))
        for pid in (f.a, f.b):
            lado = f.lado(pid)
            p = self.personas.get(pid)
            if getattr(f, f"confirmacion_{lado}") or p is None:
                continue
            asunto, cuerpo = redactar_confirmacion(f, p, self._zona(p), self.cfg.resolver)
            if self._enviar(f, p, asunto, cuerpo, [adjunto]):
                setattr(f, f"confirmacion_{lado}", True)
                self.almacen.guardar_match(f)

    def _nuevos_matches(self) -> None:
        participantes, solicitudes = {}, []
        for p in self.personas.values():
            part, sol, avisos = a_modelo(p)
            if a2_match.motivos_participante_no_elegible(part):
                continue                       # sin autorización, aptitud o respaldo: no se usa
            problemas = validar_a1_automatico(p, self.cfg.resolver)
            if problemas:
                self.r.a1_con_problemas += 1
                self.r.avisos.append(f"participante {p.id[-6:]}: A1 automático: faltan o no son "
                                     f"válidos: " + ", ".join(problemas))
                continue
            participantes[p.id] = part
            solicitudes.append(sol)
            if avisos:
                self.r.avisos.append(f"participante {p.id[-6:]}: " + "; ".join(avisos))
        clave = f"auto-{self.ahora:%Y%m%dT%H%M}"
        contador = iter(range(1, 10_000))
        try:
            res = a2_match.ejecutar_a2(
                participantes, solicitudes, [_como_propuesta(f, self.ahora) for f in self.filas],
                self.ahora + ANTICIPACION, self.cfg.resolver, lambda: f"nuevo-{next(contador)}",
                clave, DIAS_BUSQUEDA,
            )
        except ZonaNoDisponible as e:
            self.r.avisos.append(f"A2 no se ejecutó: {e}")
            return
        self.r.elegibles = len(solicitudes) - len(res.excluidas)
        por_aclarar = set()
        for sid, resumen in res.por_solicitud.items():
            for otra, pendientes in resumen.bloqueadas.items():
                if any(x.startswith(REQUIERE_ACLARACION) for x in pendientes):
                    por_aclarar.add(tuple(sorted((sid[4:], otra[4:]))))
        for a, b in sorted(por_aclarar):
            self.r.avisos.append(f"par {a[-6:]}/{b[-6:]}: {REQUIERE_ACLARACION} de temas; no se propone match")
        self.r.pares_por_aclarar = len(por_aclarar)
        for m in res.propuestas:
            e = m.evidencia
            pa, pb = self.personas[m.participante_a], self.personas[m.participante_b]
            f = FilaMatch(
                id="", a=pa.id, b=pb.id, alias_a=pa.alias, alias_b=pb.alias,
                a_ensena=list(m.a_ensena), b_ensena=list(m.b_ensena),
                inicio_utc=datetime.fromisoformat(e["horario_comun_utc"]),
                minutos_a=e["minutos_por_persona"][pa.id], minutos_b=e["minutos_por_persona"][pb.id],
                clave=clave, notas="creado automáticamente por A2; temas: " + ", ".join(e["tipos_coincidencia"]),
            )
            f.id = self.almacen.crear_match(f)
            self.filas.append(f)
            self.r.matches_nuevos += 1
            self._enviar_propuestas(f, pa, pb)

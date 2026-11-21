"""Ciclo automático: formulario de Notion → match → respuestas → Jitsi → confirmación.

Decisiones del 2026-11-21 (todo automático, sin revisiones humanas de match,
pacto, respuestas ni confirmación; las únicas decisiones humanas siguen siendo
«Aptitud» y «Revisión humana del respaldo» en Participantes):

  1. A2 empareja a las personas elegibles de Participantes.
  2. Por cada par compatible se crea una fila en «Matches [PRUEBA]» y se envía a
     cada persona un correo con la fecha/hora propuesta (en su zona), los minutos
     y su CÓDIGO PERSONAL para responder en el formulario «Responder a tu match».
  3. Cada respuesta del formulario se aplica al match (se busca por la huella del
     código; el código nunca se guarda).
  4. Si ambas aceptan y el horario sigue siendo válido, se crea una sala de Jitsi
     y se envía la confirmación con el enlace y un archivo de calendario (.ics).
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
from .modelos import (
    DIAS_SEMANA, REVISION_APROBADA, DecisionHumana, Participante, PropuestaMatch, Solicitud,
)
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


def nueva_sala_jitsi() -> str:
    return "https://meet.jit.si/Antropia" + secrets.token_hex(10)


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
        motivo="", decision=DecisionHumana.RECHAZADA if inactiva else DecisionHumana.PENDIENTE,
    )


# ---------------------------------------------------------------------------
# Redacción
# ---------------------------------------------------------------------------
def _lista(temas: list[str]) -> str:
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
        f"• Tú compartes: {_lista(ensenas)}\n"
        f"• {otra} comparte: {_lista(aprendes)}\n"
        f"• Fecha: {hora_local(f.inicio_utc, f.duracion, zona, resolver)}\n"
        f"• Tiempo: {mis_min} min enseñas tú · {sus_min} min enseña {otra} · "
        f"duración total: {mis_min + sus_min} min\n"
        "• Modalidad: videollamada (Jitsi Meet)\n\n"
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
        f"• Enlace de la videollamada: {f.enlace}\n\n"
        "Adjuntamos una invitación (.ics) para añadirlo a tu calendario.\n"
        "Nota: Jitsi puede pedir que la primera persona en entrar inicie sesión "
        "(Google, GitHub o Facebook) para abrir la sala.\n\n"
        "— Comunidad Antropia"
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
        "SUMMARY:Encuentro Antropia (intercambio de conocimiento)",
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
    nueva_sala: Callable[[], str] = nueva_sala_jitsi


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
                f.enlace = f.enlace or self.cfg.nueva_sala()
                f.estado = CONFIRMADO
                f.notas = f"confirmado automáticamente el {self.ahora:%Y-%m-%d %H:%M} UTC"
                self.almacen.guardar_match(f)
                self.r.confirmados += 1
                self._enviar_confirmaciones(f)
                return
            return self._reprogramar(f, pa, pb, motivo)
        if vence:
            return self._reprogramar(f, pa, pb, "llegó la hora propuesta sin las dos aceptaciones")

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
            if not correo_valido(p.correo):
                continue                       # sin correo no se le puede avisar
            part, sol, avisos = a_modelo(p)
            participantes[p.id] = part
            solicitudes.append(sol)
            if avisos and not a2_match.motivos_participante_no_elegible(part):
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
        for m in res.propuestas:
            e = m.evidencia
            pa, pb = self.personas[m.participante_a], self.personas[m.participante_b]
            f = FilaMatch(
                id="", a=pa.id, b=pb.id, alias_a=pa.alias, alias_b=pb.alias,
                a_ensena=list(m.a_ensena), b_ensena=list(m.b_ensena),
                inicio_utc=datetime.fromisoformat(e["horario_comun_utc"]),
                minutos_a=e["minutos_por_persona"][pa.id], minutos_b=e["minutos_por_persona"][pb.id],
                clave=clave, notas="creado automáticamente por A2",
            )
            f.id = self.almacen.crear_match(f)
            self.filas.append(f)
            self.r.matches_nuevos += 1
            self._enviar_propuestas(f, pa, pb)

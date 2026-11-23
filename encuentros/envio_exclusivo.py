"""Envío exclusivo de cada correo, con resultados INMUTABLES (diseño del 2026-11-22).

NO activado y NO conectado todavía al agente de cursos: se prueba aislado con
servicios simulados (tests/test_envio_exclusivo.py).

Problemas que resuelve:
  1. Dos ejecuciones (de cualquier equipo o proceso) no pueden enviar el mismo correo.
  2. Una escritura tardía nunca puede borrar el resultado de un envío.
  3. Un intento solo se considera terminado con una PRUEBA POSITIVA de que su ejecución
     terminó, nunca solo porque pasó un plazo.
  4. Ningún correo se reintenta solo. El reenvío es una decisión humana explícita.

Idea: la verdad no vive en Notion. Vive en un REGISTRO con una única operación de
escritura, «crear solo si no existe» (atómica), donde nada se modifica ni se borra.
Para el correo de un lado de un par (su «base»), en cada intento n:

    <base>/reserva-<n>   quién intenta enviar (ejecución, hora, número aleatorio)
    <base>/cierre-<n>    resultado del intento: «enviado», «no salió», «duda» o
                         «abandonado» (este último solo por decisión humana)
    <base>/tardio-<n>    resultado que llegó DESPUÉS de que el intento ya estaba cerrado
                         (p. ej. el envío terminó tras un abandono humano): se conserva y
                         se marca como posible duplicado. Nunca sustituye al cierre.

Como «cierre-n» solo se puede crear una vez, el primero que lo escribe gana y nadie lo
puede sobrescribir. Un «Enviado» no se puede perder por una escritura tardía.

Notion es solo una VISTA calculada a partir del registro (`vista`). Se puede quedar
atrasada o sobrescribirse con un valor viejo, pero ninguna decisión se toma leyendo
Notion: la siguiente ejecución la recalcula. Para revisar o reenviar se consulta el
registro, nunca la columna de Notion.

¿Sigue activo un intento sin cierre? Solo se considera terminado si el servicio que
ejecuta el envío (GitHub Actions) confirma que ESA ejecución (id y reintento) está
«completed». Si está en curso, en cola o no se puede saber, el intento cuenta como
activo y no se hace nada. La hora solo se muestra; nunca decide.

La atomicidad real del registro (referencias de GitHub) está PENDIENTE de comprobar en
un repositorio aislado (ver reserva_envios.py y la propuesta de prueba).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Protocol

# Resultados que se escriben en «cierre-n»
ENVIADO, NO_SALIO, DUDA, ABANDONADO = "enviado", "no salió", "duda", "abandonado"
CANCELADO = "cancelado antes de enviar"     # la comprobación final falló: consta que no salió

# Estados calculados (los que se muestran)
PENDIENTE = "Pendiente"          # nunca se intentó
EN_CURSO = "Enviando"            # hay reserva sin cierre y su ejecución no consta terminada
ESTADO_ENVIADO = "Enviado"
POR_REVISAR = "Por revisar"      # fallo, duda, interrupción probada o resultado tardío

TERMINADA = "completed"


class Registro(Protocol):
    def crear(self, nombre: str, contenido: str) -> bool | None:
        """True: creado por esta llamada. False: ya existía. None: no se sabe."""

    def leer(self, nombre: str) -> str | None:
        """Contenido, o None si no existe. Lanza una excepción si no se puede saber."""


@dataclass(frozen=True)
class Ejecucion:
    """Identifica la ejecución que intenta enviar (en GitHub Actions: id y reintento)."""
    id: str
    reintento: str = "1"
    nonce: str = ""

    def texto(self, inicio: str) -> str:
        return json.dumps({"ejecucion": self.id, "reintento": self.reintento,
                           "inicio": inicio, "nonce": self.nonce}, sort_keys=True)


def _datos(texto: str | None) -> dict:
    try:
        return json.loads(texto or "") or {}
    except ValueError:
        return {}


@dataclass(frozen=True)
class EstadoCorreo:
    estado: str                    # PENDIENTE / EN_CURSO / ESTADO_ENVIADO / POR_REVISAR
    intento: int                   # último intento (0 si ninguno)
    detalle: str = ""              # sin datos personales
    posible_duplicado: bool = False


def _n_reservas(registro: Registro, base: str) -> int:
    n = 0
    while registro.leer(f"{base}/reserva-{n + 1}") is not None:
        n += 1
    return n


def estado_de(registro: Registro, base: str, estado_ejecucion: Callable[[str, str], str | None]
              ) -> EstadoCorreo:
    """Calcula el estado SOLO a partir del registro y del estado real de la ejecución."""
    n = _n_reservas(registro, base)
    if n == 0:
        return EstadoCorreo(PENDIENTE, 0)
    tardio = registro.leer(f"{base}/tardio-{n}") is not None or any(
        registro.leer(f"{base}/tardio-{k}") is not None for k in range(1, n))
    cierre = _datos(registro.leer(f"{base}/cierre-{n}")).get("resultado")
    if cierre == ENVIADO:
        return EstadoCorreo(ESTADO_ENVIADO, n, posible_duplicado=tardio)
    if cierre in (NO_SALIO, DUDA, CANCELADO):
        return EstadoCorreo(POR_REVISAR, n, cierre, posible_duplicado=tardio)
    if cierre == ABANDONADO:
        return EstadoCorreo(POR_REVISAR, n, "abandonado por decisión humana, sin nuevo intento",
                            posible_duplicado=tardio)
    reserva = _datos(registro.leer(f"{base}/reserva-{n}"))
    try:
        estado = estado_ejecucion(reserva.get("ejecucion", ""), reserva.get("reintento", ""))
    except Exception:
        estado = None
    if estado == TERMINADA:
        return EstadoCorreo(POR_REVISAR, n, "interrumpido: la ejecución terminó sin anotar el resultado",
                            posible_duplicado=tardio)
    return EstadoCorreo(EN_CURSO, n, "en curso o sin confirmar que terminó", posible_duplicado=tardio)


@dataclass
class Informe:
    enviado: bool = False
    motivo: str = ""


Comprobacion = Callable[[], "str | None"]      # None = todo vigente; texto = motivo para NO enviar


def _sin_comprobar() -> None:
    return None


def _intentar(registro: Registro, base: str, n: int, ejecucion: Ejecucion, inicio: str,
              enviar: Callable[[int], None], comprobar: Comprobacion) -> Informe:
    """Reserva el intento n en exclusiva, envía una vez y cierra. Nunca repite.

    `comprobar` (datos vigentes: autorización, correo, cursos...) se ejecuta ANTES de
    reservar y otra vez JUSTO ANTES de enviar. Si falla antes, no se reserva nada. Si
    falla después de reservar, no se envía y el intento se cierra como «cancelado antes de
    enviar» (consta que no salió; queda «Por revisar», sin reintento automático)."""
    from .correo import ErrorEnvioSeguro
    try:
        motivo = comprobar()
    except Exception:
        motivo = "no se pudo comprobar que los datos siguen vigentes"
    if motivo:
        return Informe(False, motivo)
    mia = ejecucion.texto(inicio)
    creada = registro.crear(f"{base}/reserva-{n}", mia)
    if creada is not True:
        # False: otra ejecución lo tiene. None: no se sabe. En ambos casos NO se envía,
        # aunque la reserva pudiera ser nuestra (respuesta perdida): quedará «en curso»
        # hasta que conste que esta ejecución terminó, y entonces «Por revisar».
        return Informe(False, "reserva ajena o no confirmada")
    try:
        if registro.leer(f"{base}/reserva-{n}") != mia:     # comprobación adicional
            return Informe(False, "la reserva no es de esta ejecución")
    except Exception:
        return Informe(False, "no se pudo comprobar la reserva")
    try:
        motivo = comprobar()
    except Exception:
        motivo = "no se pudo comprobar que los datos siguen vigentes"
    if motivo:
        resultado = CANCELADO
    else:
        try:
            enviar(n)
            resultado = ENVIADO
        except ErrorEnvioSeguro:
            resultado = NO_SALIO
        except Exception:
            resultado = DUDA
    cierre = json.dumps({"resultado": resultado, "ejecucion": ejecucion.id}, sort_keys=True)
    hecho = registro.crear(f"{base}/cierre-{n}", cierre)
    if hecho is False:
        # Alguien cerró antes (abandono humano): el resultado no se pierde ni sustituye.
        registro.crear(f"{base}/tardio-{n}", cierre)
    return Informe(resultado == ENVIADO, motivo if resultado == CANCELADO else resultado)


def vista_permite_primer_envio(estado_en_notion: str | None) -> bool:
    """La vista de Notion puede IMPEDIR un envío, nunca autorizarlo. Solo se permite el
    primer envío si Notion no muestra nada o muestra «Pendiente». Cualquier otro valor
    (p. ej. «Enviado» con el registro vacío) es una incoherencia: no se envía y se revisa."""
    return estado_en_notion in (None, "", PENDIENTE)


def enviar_automatico(registro: Registro, base: str, ejecucion: Ejecucion, inicio: str,
                      enviar: Callable[[int], None], comprobar: Comprobacion = _sin_comprobar,
                      estado_en_notion: str | None = None) -> Informe:
    """Envío AUTOMÁTICO: solo el primer intento y solo si nunca se intentó.

    Decide el REGISTRO. `estado_en_notion` (la vista) solo puede impedirlo."""
    try:
        if _n_reservas(registro, base) != 0:
            return Informe(False, "ya se intentó: no se repite automáticamente")
    except Exception:
        return Informe(False, "no se pudo leer el registro")
    if not vista_permite_primer_envio(estado_en_notion):
        return Informe(False, "la vista de Notion no coincide con el registro: revisar")
    return _intentar(registro, base, 1, ejecucion, inicio, enviar, comprobar)


def reenviar_por_decision_humana(registro: Registro, base: str, ejecucion: Ejecucion, inicio: str,
                                 enviar: Callable[[int], None],
                                 estado_ejecucion: Callable[[str, str], str | None],
                                 id_confirmado: str, id_de: Callable[[int], str],
                                 comprobar: Comprobacion = _sin_comprobar) -> Informe:
    """Reenvío explícito de un correo «Por revisar». La persona tiene que indicar el
    identificador COMPLETO Y EXACTO del ÚLTIMO intento (`id_de(n)`), tal como lo calcula el
    registro: no vale uno incompleto, de otro correo ni de un intento anterior. Además, el
    intento anterior no puede estar activo (prueba positiva) ni constar como enviado."""
    try:
        e = estado_de(registro, base, estado_ejecucion)
    except Exception:
        return Informe(False, "no se pudo leer el registro")
    if e.estado != POR_REVISAR:
        return Informe(False, f"no se reenvía un correo en estado «{e.estado}»")
    n = e.intento
    if not isinstance(id_confirmado, str) or id_confirmado != id_de(n):
        return Informe(False, "el identificador no es el completo y exacto del último intento")
    if registro.leer(f"{base}/cierre-{n}") is None:
        # Intento interrumpido (su ejecución consta terminada). Se cierra como abandonado
        # de forma atómica: si el envío original llegara a cerrar justo ahora, uno de los
        # dos gana y el otro queda como «tardío».
        hecho = registro.crear(f"{base}/cierre-{n}", json.dumps(
            {"resultado": ABANDONADO, "ejecucion": ejecucion.id}, sort_keys=True))
        if hecho is not True:
            actual = _datos(registro.leer(f"{base}/cierre-{n}")).get("resultado")
            if actual != ABANDONADO:
                return Informe(False, f"el intento anterior se cerró como «{actual}»: revisar")
    elif _datos(registro.leer(f"{base}/cierre-{n}")).get("resultado") == ENVIADO:
        return Informe(False, "el intento anterior consta como enviado")
    return _intentar(registro, base, n + 1, ejecucion, inicio, enviar, comprobar)


def vista(e: EstadoCorreo) -> tuple[str, str]:
    """Valores para Notion (estado e «Intento»). Solo informativos."""
    detalle = f"intento {e.intento}" + (f" · {e.detalle}" if e.detalle else "")
    if e.posible_duplicado:
        detalle += " · posible duplicado: revisar"
    return e.estado, detalle

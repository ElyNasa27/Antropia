"""Flujo completo con sus reglas. Cada paso humano exige el nombre de quien revisa.

Dos revisiones humanas distintas y separadas:
  1. Respaldo DECLARADO por el participante  -> revisar_respaldo_declarado()
     (columna «Revisión humana del respaldo» en Participantes).
  2. EVIDENCIA de la propuesta de match de A2 -> aprobar_match(evidencia_revisada=True)
     (columna «Decisión humana» en Propuestas).
Ninguna de las dos sustituye a la otra.

Tiempo del encuentro («Minutos por sesión» = minutos que cada persona ofrece enseñar):
  - Duración total = suma de ambos aportes; ambas personas deben estar disponibles
    toda la duración. Se vuelve a comprobar al revisar y al confirmar el pacto.
  - Aportes distintos: se permiten, pero quien aprueba la propuesta debe revisarlos
    expresamente (aprobar_match(..., aportes_distintos_revisados=True)).
  - Minutos marcados como «requieren revisión» (p. ej. valores antiguos de Notion que
    podrían ser la duración total) no se convierten: una persona escribe el aporte
    con revisar_minutos_por_sesion().
  - Si los minutos cambian después de una revisión humana, esa revisión deja de valer.
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime
from urllib.parse import urlparse

from . import a2_match, a3_pacto
from .canal import BandejaBorradores
from .mensajes import redactar_confirmacion, redactar_invitacion
from .modelos import (
    REVISION_APROBADA, REVISION_NO_REQUERIDA, REVISION_PENDIENTE, DecisionHumana,
    EstadoPacto, Franja, Mensaje, OperacionNoPermitida, Pacto, Participante,
    PropuestaMatch, Respuesta, Solicitud, TipoRespuesta,
)
from .repositorio import RepositorioMemoria
from .zonas import ResolverZona, ZonaNoDisponible, es_resolver_simulado, resolver_zona_real

AGENTES = {"A2", "A3"}
ESTADOS_ABIERTOS = {
    EstadoPacto.FALTA_INFORMACION, EstadoPacto.BORRADOR,
    EstadoPacto.INVITACIONES_PREPARADAS, EstadoPacto.CAMBIOS_SOLICITADOS,
    EstadoPacto.LISTO_PARA_CONFIRMAR,
}


def _validar_persona(revisor: str | None) -> str:
    if not revisor or not revisor.strip():
        raise OperacionNoPermitida("Se requiere el nombre de la persona que revisa.")
    if revisor.strip().upper() in AGENTES:
        raise OperacionNoPermitida("Un agente no puede aprobar, registrar ni confirmar; debe hacerlo una persona.")
    return revisor.strip()


def _validar_clave(clave: str | None) -> str:
    if not clave or not clave.strip():
        raise OperacionNoPermitida("Se requiere una clave de ejecución para evitar duplicados.")
    return clave.strip()


def validar_enlace(enlace: str | None) -> str:
    if not enlace or not enlace.strip():
        raise OperacionNoPermitida("Falta el enlace de la videollamada; debe agregarlo una persona.")
    enlace = enlace.strip()
    partes = urlparse(enlace)
    if partes.scheme != "https" or not partes.netloc or " " in enlace:
        raise OperacionNoPermitida("El enlace de la videollamada debe ser una URL https válida.")
    return enlace


class Coordinacion:
    def __init__(
        self,
        repo: RepositorioMemoria,
        bandeja: BandejaBorradores,
        resolver: ResolverZona = resolver_zona_real,
        dias_busqueda: int = a3_pacto.DIAS_BUSQUEDA,
        permitir_zonas_simuladas: bool = False,
    ) -> None:
        if es_resolver_simulado(resolver) and permitir_zonas_simuladas is not True:
            raise ValueError(
                "La tabla simulada de zonas horarias no puede usarse para encuentros reales."
            )
        self.repo = repo
        self.bandeja = bandeja
        self.resolver = resolver
        self.dias_busqueda = dias_busqueda
        self._contador = itertools.count(1)

    def _id(self, prefijo: str) -> str:
        return f"{prefijo}-{next(self._contador):03d}"

    def _pacto(self, pacto_id: str) -> Pacto:
        return self.repo.pactos[pacto_id]

    # 1. Cada participante proporciona sus datos por separado
    def registrar_datos_participante(self, participante: Participante) -> None:
        if participante.id in self.repo.participantes:
            raise OperacionNoPermitida(f"{participante.nombre} ya tiene datos registrados.")
        p = copy.deepcopy(participante)
        # La revisión del respaldo nunca viene en los datos de la propia persona.
        if p.revision_respaldo != REVISION_PENDIENTE or p.respaldo_revisado_por:
            self.repo.registrar("sistema", "revisión de respaldo ignorada en los datos de entrada", p.id)
        p.revision_respaldo, p.respaldo_revisado_por = REVISION_PENDIENTE, None
        self.repo.participantes[p.id] = p
        self.repo.registrar(p.nombre, "datos registrados", p.id)

    def registrar_solicitud(self, solicitud: Solicitud) -> None:
        self.repo.participante(solicitud.participante_id)   # debe existir
        if solicitud.id in self.repo.solicitudes:
            raise OperacionNoPermitida(f"La solicitud {solicitud.id} ya existe.")
        self.repo.solicitudes[solicitud.id] = copy.deepcopy(solicitud)
        self.repo.registrar("sistema", "solicitud registrada", solicitud.id)

    # Revisión humana 1: respaldo declarado por el participante
    def revisar_respaldo_declarado(self, participante_id: str, revisor: str, decision: str, nota: str = "") -> Participante:
        revisor = _validar_persona(revisor)
        if decision not in (REVISION_APROBADA, REVISION_NO_REQUERIDA, REVISION_PENDIENTE):
            raise OperacionNoPermitida(f"Decisión de revisión no válida: {decision!r}.")
        p = self.repo.participante(participante_id)
        tiene_respaldo = bool(p.respaldo_declarado and p.respaldo_declarado.strip())
        if decision == REVISION_APROBADA and not tiene_respaldo:
            raise OperacionNoPermitida("No hay respaldo declarado que aprobar.")
        if decision == REVISION_NO_REQUERIDA and tiene_respaldo:
            raise OperacionNoPermitida(
                "Hay una afirmación de respaldo: debe revisarse (Aprobada o Pendiente), "
                "no puede marcarse como «No requerida»."
            )
        p.revision_respaldo = decision
        p.respaldo_revisado_por = revisor if decision != REVISION_PENDIENTE else None
        self.repo.registrar(revisor, f"respaldo de {p.nombre}: {decision}", p.id, nota)
        return p

    def actualizar_respaldo_declarado(self, participante_id: str, texto: str | None) -> Participante:
        """La persona cambia su respaldo: cualquier revisión anterior deja de valer."""
        p = self.repo.participante(participante_id)
        p.respaldo_declarado = texto
        p.revision_respaldo, p.respaldo_revisado_por = REVISION_PENDIENTE, None
        self.repo.registrar(p.nombre, "respaldo declarado actualizado (vuelve a Pendiente)", p.id)
        return p

    # Revisión de minutos: una persona confirma el aporte cuando el valor es dudoso
    def revisar_minutos_por_sesion(
        self, solicitud_id: str, revisor: str, minutos_aporte: int, nota: str = ""
    ) -> Solicitud:
        """Una persona escribe cuántos minutos ofrece enseñar quien hizo la solicitud.

        Nunca se calcula a partir del valor anterior (que podría ser la duración total):
        el número lo aporta quien revisa, tras confirmarlo con la persona si hace falta.
        """
        revisor = _validar_persona(revisor)
        if not isinstance(minutos_aporte, int) or isinstance(minutos_aporte, bool) or minutos_aporte <= 0:
            raise OperacionNoPermitida("Los minutos que ofrece enseñar deben ser un número entero positivo.")
        s = self.repo.solicitud(solicitud_id)
        anterior = s.minutos_por_sesion
        s.minutos_por_sesion = minutos_aporte
        s.minutos_requieren_revision, s.minutos_revisados_por = False, revisor
        self.repo.registrar(
            revisor, "minutos por sesión revisados (aporte de la persona)", s.id,
            f"valor anterior: {anterior}; aporte revisado: {minutos_aporte}" + (f"; {nota}" if nota else ""),
        )
        return s

    # 2. A2 propone candidatos; una persona revisa la evidencia
    def proponer_matches(self, desde_utc: datetime, clave_ejecucion: str) -> a2_match.ResultadoA2:
        clave = _validar_clave(clave_ejecucion)
        if clave in self.repo.ejecuciones_a2:     # misma ejecución: no se duplica nada
            self.repo.registrar("A2", "ejecución repetida ignorada", clave)
            return self.repo.ejecuciones_a2[clave]
        res = a2_match.ejecutar_a2(
            self.repo.participantes, list(self.repo.solicitudes.values()),
            list(self.repo.matches.values()), desde_utc, self.resolver,
            lambda: self._id("match"), clave, self.dias_busqueda,
        )
        for sid, motivos in res.excluidas.items():
            self.repo.registrar("A2", "solicitud excluida", sid, "; ".join(motivos))
        for sid, r in res.por_solicitud.items():
            self.repo.registrar("A2", f"resultado de la solicitud: {r.resultado}", sid)
        for m in res.propuestas:
            self.repo.matches[m.id] = m
            self.repo.registrar("A2", "propuesta creada", m.id, m.motivo)
        self.repo.ejecuciones_a2[clave] = res
        return res

    def _exigir_elegibles(self, m: PropuestaMatch) -> None:
        """Personas y solicitudes se vuelven a comprobar en cada paso (pueden cambiar)."""
        for pid in (m.participante_a, m.participante_b):
            p = self.repo.participante(pid)
            motivos = a2_match.motivos_participante_no_elegible(p)
            if motivos:
                raise OperacionNoPermitida(f"{p.nombre} ya no es elegible: {'; '.join(motivos)}.")
        for sid in (m.solicitud_origen, m.solicitud_candidata):
            motivos = a2_match.motivos_solicitud_no_lista(self.repo.solicitud(sid))
            if motivos:
                raise OperacionNoPermitida(f"La solicitud {sid} ya no es válida: {'; '.join(motivos)}.")

    def _perfiles(self, m: PropuestaMatch):
        pa, pb = self.repo.participante(m.participante_a), self.repo.participante(m.participante_b)
        sa, sb = self.repo.solicitud(m.solicitud_origen), self.repo.solicitud(m.solicitud_candidata)
        return pa, sa, pb, sb

    # Revisión humana 2: evidencia de la propuesta de match
    def aprobar_match(
        self,
        match_id: str,
        revisor: str,
        evidencia_revisada: bool = False,
        aportes_distintos_revisados: bool = False,
    ) -> PropuestaMatch:
        revisor = _validar_persona(revisor)
        m = self.repo.matches[match_id]
        if m.decision is not DecisionHumana.PENDIENTE:
            raise OperacionNoPermitida(f"La propuesta ya tiene decisión «{m.decision.value}».")
        if evidencia_revisada is not True:
            raise OperacionNoPermitida(
                "La persona que aprueba debe confirmar que revisó la evidencia de la propuesta "
                "(coincidencias, idioma, modalidad, minutos y horario común)."
            )
        if not m.evidencia:
            raise OperacionNoPermitida("La propuesta no tiene evidencia de A2; no se puede aprobar.")
        if m.requiere_revision_de_aportes and aportes_distintos_revisados is not True:
            minutos = m.evidencia["minutos_por_persona"]
            raise OperacionNoPermitida(
                "Los aportes de minutos son distintos "
                f"({minutos[m.participante_a]} y {minutos[m.participante_b]} min): "
                "la persona que aprueba debe revisarlos expresamente "
                "(aportes_distintos_revisados=True)."
            )
        self._exigir_elegibles(m)
        pa, sa, pb, sb = self._perfiles(m)
        ev = a2_match.evaluar_par(
            pa, sa, pb, sb, datetime.fromisoformat(m.evidencia["buscado_desde_utc"]),
            self.resolver, m.evidencia["dias_busqueda"],
        )
        if ev.resultado != a2_match.PROPUESTA:
            raise OperacionNoPermitida(
                f"La propuesta ya no cumple los criterios ({ev.resultado}): "
                + "; ".join(ev.motivos + ev.datos_pendientes)
            )
        if ev.evidencia["minutos_por_persona"] != m.evidencia.get("minutos_por_persona"):
            raise OperacionNoPermitida(
                "Los minutos por sesión cambiaron desde que A2 hizo la propuesta; "
                "la evidencia revisada ya no corresponde. Hace falta una nueva propuesta."
            )
        m.decision, m.decidido_por, m.evidencia_revisada = DecisionHumana.APROBADA, revisor, True
        m.aportes_distintos_revisados = m.requiere_revision_de_aportes
        detalle = "incluye revisión de aportes de minutos distintos" if m.aportes_distintos_revisados else ""
        self.repo.registrar(revisor, "propuesta aprobada tras revisar la evidencia", m.id, detalle)
        return m

    def rechazar_match(self, match_id: str, revisor: str, motivo: str = "") -> PropuestaMatch:
        revisor = _validar_persona(revisor)
        m = self.repo.matches[match_id]
        if m.decision is not DecisionHumana.PENDIENTE:
            raise OperacionNoPermitida(f"La propuesta ya tiene decisión «{m.decision.value}».")
        m.decision, m.decidido_por = DecisionHumana.RECHAZADA, revisor
        self.repo.registrar(revisor, "propuesta rechazada", m.id, motivo)
        return m

    # 3. A3 sugiere el pacto
    def proponer_pacto(self, match_id: str, desde_utc: datetime, clave_ejecucion: str) -> Pacto:
        clave = _validar_clave(clave_ejecucion)
        previo = next((p for p in self.repo.pactos.values() if p.clave_ejecucion == clave), None)
        if previo is not None:
            if previo.match_id != match_id:
                raise OperacionNoPermitida("Esa clave de ejecución ya se usó para otra propuesta.")
            self.repo.registrar("A3", "ejecución repetida ignorada", clave)
            return previo
        m = self.repo.matches[match_id]
        if not m.es_valida:
            raise OperacionNoPermitida(
                "La propuesta debe estar aprobada por una persona, tras revisar la evidencia, "
                "antes de que A3 sugiera un pacto."
            )
        self._exigir_elegibles(m)
        if any(p.match_id == match_id and p.estado in ESTADOS_ABIERTOS for p in self.repo.pactos.values()):
            raise OperacionNoPermitida("Ya hay un pacto abierto para esta propuesta.")
        pacto = Pacto(id=self._id("pacto"), match_id=match_id,
                      participantes=(m.participante_a, m.participante_b), clave_ejecucion=clave)
        self.repo.pactos[pacto.id] = pacto
        self._ejecutar_a3(pacto, desde_utc)
        return pacto

    def proponer_nueva_version(self, pacto_id: str, desde_utc: datetime) -> Pacto:
        pacto = self._pacto(pacto_id)
        if pacto.estado not in (EstadoPacto.CAMBIOS_SOLICITADOS, EstadoPacto.FALTA_INFORMACION):
            raise OperacionNoPermitida(f"No se puede rehacer el pacto en estado «{pacto.estado.value}».")
        self._ejecutar_a3(pacto, desde_utc)
        return pacto

    def _ejecutar_a3(self, pacto: Pacto, desde_utc: datetime) -> None:
        m = self.repo.matches[pacto.match_id]
        pa, sa, pb, sb = self._perfiles(m)
        revisados = m.evidencia.get("minutos_por_persona")
        actuales = {pa.id: sa.minutos_por_sesion, pb.id: sb.minutos_por_sesion}
        if actuales != revisados:
            pacto.estado = EstadoPacto.FALTA_INFORMACION
            pacto.faltantes = [
                f"los minutos por sesión cambiaron desde la revisión humana de la propuesta "
                f"(revisados: {revisados}; actuales: {actuales}); hace falta una nueva propuesta"
            ]
            self.repo.registrar("A3", "pacto sin propuesta", pacto.id, pacto.faltantes[0])
            return
        resultado = a3_pacto.proponer_pacto(
            m, a2_match.perfil(pa, sa), a2_match.perfil(pb, sb), desde_utc, self.resolver,
            numero=len(pacto.versiones) + 1,
            inicios_excluidos=[v.inicio_utc for v in pacto.versiones],
            dias_busqueda=self.dias_busqueda,
        )
        if resultado.version is None:
            pacto.estado, pacto.faltantes = EstadoPacto.FALTA_INFORMACION, resultado.faltantes
            self.repo.registrar("A3", "pacto sin propuesta", pacto.id, "; ".join(resultado.faltantes))
            return
        v = resultado.version
        pacto.versiones.append(v)
        pacto.estado, pacto.faltantes, pacto.revisado_por = EstadoPacto.BORRADOR, [], None
        # Una versión nueva invalida cualquier respuesta anterior.
        pacto.respuestas = {pid: Respuesta(TipoRespuesta.PENDIENTE, v.numero) for pid in pacto.participantes}
        self.repo.registrar("A3", f"pacto v{v.numero} propuesto", pacto.id, v.inicio_utc.isoformat())

    def _exigir_tiempo_vigente(self, pacto: Pacto) -> None:
        """Los minutos siguen siendo los del pacto y ambas personas siguen disponibles
        durante toda la duración (desde el inicio hasta el final)."""
        v = pacto.version_actual
        m = self.repo.matches[pacto.match_id]
        pa, sa, pb, sb = self._perfiles(m)
        for p, s in ((pa, sa), (pb, sb)):
            if s.minutos_requieren_revision is not False or s.minutos_por_sesion != v.minutos[p.id]:
                raise OperacionNoPermitida(
                    f"Los minutos por sesión de {p.nombre} ya no coinciden con el pacto v{v.numero}; "
                    "hace falta una nueva versión."
                )
            perfil = a2_match.perfil(p, s)
            try:
                zona = self.resolver(s.zona_horaria or "")
            except ZonaNoDisponible:
                raise OperacionNoPermitida(f"No se puede resolver la zona horaria de {p.nombre}.") from None
            if not a3_pacto.disponible_durante(perfil, zona, v.inicio_utc, v.fin_utc):
                raise OperacionNoPermitida(
                    f"{p.nombre} ya no está disponible durante toda la duración del encuentro "
                    f"({v.duracion_min} min); hace falta una nueva versión."
                )

    # 4. Una persona revisa el pacto y se preparan invitaciones individuales
    def revisar_pacto(self, pacto_id: str, revisor: str) -> list[Mensaje]:
        revisor = _validar_persona(revisor)
        pacto = self._pacto(pacto_id)
        if pacto.estado is not EstadoPacto.BORRADOR:
            raise OperacionNoPermitida(f"Solo se revisa un borrador (estado actual: «{pacto.estado.value}»).")
        self._exigir_elegibles(self.repo.matches[pacto.match_id])
        self._exigir_tiempo_vigente(pacto)
        pacto.revisado_por, pacto.estado = revisor, EstadoPacto.INVITACIONES_PREPARADAS
        self.repo.registrar(revisor, f"pacto v{pacto.version_actual.numero} revisado", pacto.id)
        return self._preparar("invitación", pacto)

    # 5. Cada persona responde por separado
    def registrar_respuesta(
        self,
        pacto_id: str,
        participante_id: str,
        tipo: TipoRespuesta,
        version: int,
        registrado_por: str,
        origen: str,
        comentario: str | None = None,
        nueva_disponibilidad: list[Franja] | None = None,
    ) -> Pacto:
        registrado_por = _validar_persona(registrado_por)
        pacto = self._pacto(pacto_id)
        if not origen or not origen.strip():
            raise OperacionNoPermitida("Indica de dónde viene la respuesta (p. ej. «simulación»).")
        if tipo is TipoRespuesta.PENDIENTE:
            raise OperacionNoPermitida("«Pendiente» no es una respuesta.")
        if pacto.estado is not EstadoPacto.INVITACIONES_PREPARADAS:
            raise OperacionNoPermitida(f"El pacto no está esperando respuestas (estado: «{pacto.estado.value}»).")
        if participante_id not in pacto.participantes:
            raise OperacionNoPermitida(f"{participante_id!r} no participa en este pacto.")
        vigente = pacto.version_actual.numero
        if version != vigente:
            raise OperacionNoPermitida(f"La respuesta es para la v{version}, pero la vigente es la v{vigente}.")
        if pacto.respuestas[participante_id].tipo is not TipoRespuesta.PENDIENTE:
            raise OperacionNoPermitida("Esta persona ya respondió a esta versión.")
        if tipo is TipoRespuesta.CAMBIOS and not (comentario or nueva_disponibilidad):
            raise OperacionNoPermitida("Indica qué cambio solicita la persona.")

        pacto.respuestas[participante_id] = Respuesta(tipo, version, registrado_por, origen.strip(), comentario)
        nombre = self.repo.participante(participante_id).nombre
        self.repo.registrar(registrado_por, f"respuesta de {nombre}: {tipo.value} (v{version}, {origen})", pacto.id, comentario or "")
        if nueva_disponibilidad is not None:
            m = self.repo.matches[pacto.match_id]
            sid = m.solicitud_origen if participante_id == m.participante_a else m.solicitud_candidata
            self.repo.solicitud(sid).disponibilidad = list(nueva_disponibilidad)
            self.repo.registrar(registrado_por, f"{nombre} actualizó su disponibilidad", sid)

        if tipo is TipoRespuesta.RECHAZA:
            pacto.estado = EstadoPacto.CERRADO_SIN_PACTO
        elif tipo is TipoRespuesta.CAMBIOS:
            pacto.estado = EstadoPacto.CAMBIOS_SOLICITADOS
        elif self._ambos_aceptan(pacto):
            pacto.estado = EstadoPacto.LISTO_PARA_CONFIRMAR
        return pacto

    @staticmethod
    def _ambos_aceptan(pacto: Pacto) -> bool:
        vigente = pacto.version_actual.numero
        return all(
            pacto.respuestas[pid].tipo is TipoRespuesta.ACEPTA and pacto.respuestas[pid].version == vigente
            for pid in pacto.participantes
        )

    # 6 y 7. Una persona confirma, agrega el enlace y se preparan confirmaciones
    def confirmar_pacto(self, pacto_id: str, revisor: str, enlace: str | None) -> list[Mensaje]:
        revisor = _validar_persona(revisor)
        pacto = self._pacto(pacto_id)
        if pacto.estado is not EstadoPacto.LISTO_PARA_CONFIRMAR or not self._ambos_aceptan(pacto):
            raise OperacionNoPermitida(
                f"No se puede confirmar (estado: «{pacto.estado.value}»). "
                "Hacen falta las dos aceptaciones explícitas de la versión vigente."
            )
        self._exigir_tiempo_vigente(pacto)
        pacto.enlace_videollamada = validar_enlace(enlace)
        pacto.confirmado_por, pacto.estado = revisor, EstadoPacto.CONFIRMADO
        self.repo.registrar(revisor, f"pacto v{pacto.version_actual.numero} confirmado", pacto.id)
        return self._preparar("confirmación", pacto)

    def _preparar(self, tipo: str, pacto: Pacto) -> list[Mensaje]:
        v = pacto.version_actual
        mensajes = []
        for pid in pacto.participantes:
            dest = self.repo.participante(pid)
            otra = self.repo.participante(next(x for x in pacto.participantes if x != pid))
            if tipo == "invitación":
                texto = redactar_invitacion(dest, otra.nombre, v, self.resolver)
            else:
                texto = redactar_confirmacion(dest, otra.nombre, v, pacto.enlace_videollamada, self.resolver)
            m = Mensaje(self._id("msg"), pacto.id, pid, tipo, v.numero, texto)
            mensajes.append(self.bandeja.preparar(m))
            self.repo.registrar("sistema", f"borrador de {tipo} para {dest.nombre}", m.id)
        return mensajes

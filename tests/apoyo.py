"""Utilidades compartidas por las pruebas (solo datos ficticios).

Las personas que revisan son del directorio SIMULADO (datos/personas_simuladas.json):
no son cuentas reales ni se verifica ninguna identidad.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from encuentros.autorizacion_simulada import cargar_directorio_json
from encuentros.canal import BandejaBorradores
from encuentros.coordinacion import Coordinacion
from encuentros.modelos import REVISION_APROBADA, REVISION_NO_REQUERIDA, Pacto, TipoRespuesta
from encuentros.repositorio import RepositorioMemoria, cargar_datos_json
from encuentros.zonas import datos_de_zonas_disponibles, es_resolver_simulado, resolver_zona_real
from tests.zonas_simuladas import resolver_zona_simulada

RUTA_DATOS = Path(__file__).resolve().parent.parent / "datos" / "piloto_alba_bruno.json"
RUTA_ORIGINAL = Path(__file__).resolve().parent.parent / "datos" / "piloto_original.json"
RUTA_PERSONAS = Path(__file__).resolve().parent.parent / "datos" / "personas_simuladas.json"
DESDE = datetime(2026, 11, 26, tzinfo=UTC)   # jueves; la búsqueda empieza aquí
ENLACE_PRUEBA = "https://videollamada.example/sala-de-prueba"  # dominio reservado, no real

# Directorio SIMULADO compartido (no se puede editar después de crearlo).
DIRECTORIO = cargar_directorio_json(RUTA_PERSONAS)
REVISORA = DIRECTORIO.actuar_como("rev-ana")         # Ana (ficticia): revisora
COORDINADORA = DIRECTORIO.actuar_como("coord-luis")  # Luis (ficticio): coordinadora
REGISTRO = DIRECTORIO.actuar_como("reg-marta")       # Marta (ficticia): registro de respuestas

# Con tzdata (entorno virtual .venv) las pruebas usan zonas IANA reales.
# Sin tzdata recurren a la tabla simulada, que solo sirve para datos ficticios.
ZONAS_REALES = datos_de_zonas_disponibles()
RESOLVER_POR_DEFECTO = resolver_zona_real if ZONAS_REALES else resolver_zona_simulada


def nuevo_escenario(resolver=None, modificar=None, ruta=RUTA_DATOS, revisar_respaldos=True,
                    directorio=DIRECTORIO, revisora=REVISORA, **opciones) -> Coordinacion:
    participantes, solicitudes = cargar_datos_json(ruta)
    ps = {p.id: p for p in participantes}
    ss = {s.id: s for s in solicitudes}
    if modificar:
        modificar(ps, ss)
    r = resolver or RESOLVER_POR_DEFECTO
    coord = Coordinacion(RepositorioMemoria(), BandejaBorradores(), r,
                         permitir_zonas_simuladas=es_resolver_simulado(r),
                         directorio=directorio, **opciones)
    for p in ps.values():   # cada persona aporta sus datos por separado
        coord.registrar_datos_participante(p)
    for s in ss.values():
        coord.registrar_solicitud(s)
    if revisar_respaldos:
        # Revisión humana 1 (respaldo declarado). A quien no autoriza no se le revisa nada.
        for p in coord.repo.participantes.values():
            if p.autoriza_participar is True:
                decision = REVISION_APROBADA if (p.respaldo_declarado or "").strip() else REVISION_NO_REQUERIDA
                coord.revisar_respaldo_declarado(p.id, revisora, decision)
    return coord


def hasta_invitaciones(coord: Coordinacion, desde=DESDE, clave="ejec-1",
                       revisora=REVISORA, coordinadora=COORDINADORA) -> Pacto:
    res = coord.proponer_matches(desde, f"{clave}-a2")
    [match] = res.propuestas
    coord.aprobar_match(match.id, revisora, evidencia_revisada=True)   # revisión humana 2
    pacto = coord.proponer_pacto(match.id, desde, f"{clave}-a3")
    coord.revisar_pacto(pacto.id, coordinadora)
    return pacto


def responder(coord: Coordinacion, pacto: Pacto, pid: str, tipo: TipoRespuesta,
              registrado_por=REGISTRO, **kw) -> Pacto:
    return coord.registrar_respuesta(
        pacto.id, pid, tipo,
        version=pacto.version_actual.numero,
        registrado_por=registrado_por,
        origen="simulación",
        **kw,
    )


def revisar_respuestas(coord: Coordinacion, pacto: Pacto, revisor=COORDINADORA) -> Pacto:
    """Revisión humana (simulada) de ambas aceptaciones, para la versión vigente."""
    for pid in pacto.participantes:
        coord.revisar_respuesta(pacto.id, pid, revisor, pacto.version_actual.numero)
    return pacto


def aceptan_y_se_revisa(coord: Coordinacion, pacto: Pacto) -> Pacto:
    """Ambas personas aceptan y una persona revisa las dos aceptaciones."""
    for pid in pacto.participantes:
        responder(coord, pacto, pid, TipoRespuesta.ACEPTA)
    return revisar_respuestas(coord, pacto)

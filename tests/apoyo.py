"""Utilidades compartidas por las pruebas (solo datos ficticios)."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from encuentros.canal import BandejaBorradores
from encuentros.coordinacion import Coordinacion
from encuentros.modelos import REVISION_APROBADA, REVISION_NO_REQUERIDA, Pacto, TipoRespuesta
from encuentros.repositorio import RepositorioMemoria, cargar_datos_json
from encuentros.zonas import datos_de_zonas_disponibles, es_resolver_simulado, resolver_zona_real
from tests.zonas_simuladas import resolver_zona_simulada

RUTA_DATOS = Path(__file__).resolve().parent.parent / "datos" / "piloto_alba_bruno.json"
RUTA_ORIGINAL = Path(__file__).resolve().parent.parent / "datos" / "piloto_original.json"
DESDE = datetime(2026, 11, 26, tzinfo=UTC)   # jueves; la búsqueda empieza aquí
REVISORA = "Coordinadora del piloto"
ENLACE_PRUEBA = "https://videollamada.example/sala-de-prueba"  # dominio reservado, no real

# Con tzdata (entorno virtual .venv) las pruebas usan zonas IANA reales.
# Sin tzdata recurren a la tabla simulada, que solo sirve para datos ficticios.
ZONAS_REALES = datos_de_zonas_disponibles()
RESOLVER_POR_DEFECTO = resolver_zona_real if ZONAS_REALES else resolver_zona_simulada


def nuevo_escenario(resolver=None, modificar=None, ruta=RUTA_DATOS, revisar_respaldos=True, **opciones) -> Coordinacion:
    participantes, solicitudes = cargar_datos_json(ruta)
    ps = {p.id: p for p in participantes}
    ss = {s.id: s for s in solicitudes}
    if modificar:
        modificar(ps, ss)
    r = resolver or RESOLVER_POR_DEFECTO
    coord = Coordinacion(RepositorioMemoria(), BandejaBorradores(), r,
                         permitir_zonas_simuladas=es_resolver_simulado(r), **opciones)
    for p in ps.values():   # cada persona aporta sus datos por separado
        coord.registrar_datos_participante(p)
    for s in ss.values():
        coord.registrar_solicitud(s)
    if revisar_respaldos:
        # Revisión humana 1 (respaldo declarado). A quien no autoriza no se le revisa nada.
        for p in coord.repo.participantes.values():
            if p.autoriza_participar is True:
                decision = REVISION_APROBADA if (p.respaldo_declarado or "").strip() else REVISION_NO_REQUERIDA
                coord.revisar_respaldo_declarado(p.id, REVISORA, decision)
    return coord


def hasta_invitaciones(coord: Coordinacion, desde=DESDE, clave="ejec-1") -> Pacto:
    res = coord.proponer_matches(desde, f"{clave}-a2")
    [match] = res.propuestas
    coord.aprobar_match(match.id, REVISORA, evidencia_revisada=True)   # revisión humana 2
    pacto = coord.proponer_pacto(match.id, desde, f"{clave}-a3")
    coord.revisar_pacto(pacto.id, REVISORA)
    return pacto


def responder(coord: Coordinacion, pacto: Pacto, pid: str, tipo: TipoRespuesta, **kw) -> Pacto:
    return coord.registrar_respuesta(
        pacto.id, pid, tipo,
        version=pacto.version_actual.numero,
        registrado_por=REVISORA,
        origen="simulación",
        **kw,
    )

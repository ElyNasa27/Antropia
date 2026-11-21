"""Demostración local del flujo con Alba y Bruno (datos ficticios).

No envía mensajes, no crea reuniones y no toca Notion. Las revisiones humanas y
las respuestas que aparecen son SIMULADAS y se marcan como tales.
Requiere zonas horarias reales (tzdata): ejecutar con .\\.venv\\Scripts\\python.exe

Uso:
    .\\.venv\\Scripts\\python.exe demo_piloto.py                       # se detiene antes de confirmar
    .\\.venv\\Scripts\\python.exe demo_piloto.py --enlace https://...  # enlace escrito por una persona
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from encuentros.canal import BandejaBorradores
from encuentros.coordinacion import Coordinacion
from encuentros.modelos import REVISION_APROBADA, OperacionNoPermitida, TipoRespuesta
from encuentros.repositorio import RepositorioMemoria, cargar_datos_json
from encuentros.zonas import datos_de_zonas_disponibles, resolver_zona_real

DATOS = Path(__file__).resolve().parent / "datos" / "piloto_alba_bruno.json"
REVISORA = "Coordinadora del piloto"


def mostrar(titulo: str, mensajes) -> None:
    print(f"\n=== {titulo} ===")
    for m in mensajes:
        print(f"\n--- Para {m.destinatario_id} · {m.tipo} v{m.version} · [{m.estado}] ---")
        print(m.texto)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--enlace", help="Enlace de videollamada escrito por una persona")
    args = parser.parse_args()

    if not datos_de_zonas_disponibles():
        print("ERROR: faltan los datos reales de zonas horarias (tzdata).\n"
              "Ejecuta la demo con el entorno virtual: .\\.venv\\Scripts\\python.exe demo_piloto.py")
        return 2

    coord = Coordinacion(RepositorioMemoria(), BandejaBorradores(), resolver_zona_real)
    participantes, solicitudes = cargar_datos_json(DATOS)
    for p in participantes:
        coord.registrar_datos_participante(p)
        print(f"Datos recibidos por separado: {p.nombre}")
    for s in solicitudes:
        coord.registrar_solicitud(s)

    for p in participantes:
        coord.revisar_respaldo_declarado(p.id, REVISORA, REVISION_APROBADA, "[SIMULACIÓN]")
        print(f"[SIMULACIÓN] Revisión humana 1 · respaldo declarado de {p.nombre}: Aprobada")

    desde = datetime(2026, 11, 26, tzinfo=UTC)
    res = coord.proponer_matches(desde, "demo-a2-001")
    [match] = res.propuestas
    print(f"\nA2 propone: {match.motivo}")
    print(f"Evidencia para revisión humana: {match.evidencia}")
    if match.requiere_revision_de_aportes:
        # Aportes distintos: la persona revisora debe aceptarlos expresamente.
        coord.aprobar_match(match.id, REVISORA, evidencia_revisada=True, aportes_distintos_revisados=True)
        print("[SIMULACIÓN] Aportes de minutos distintos revisados por una persona")
    else:
        coord.aprobar_match(match.id, REVISORA, evidencia_revisada=True)
    print(f"[SIMULACIÓN] Revisión humana 2 · evidencia de la propuesta: Aprobada (válida: {match.es_valida})")

    pacto = coord.proponer_pacto(match.id, desde, "demo-a3-001")
    if pacto.version_actual is None:
        print("A3 no puede proponer pacto. Falta:", *pacto.faltantes, sep="\n  - ")
        return 1
    v = pacto.version_actual
    reparto = " · ".join(f"{coord.repo.participante(pid).nombre} enseña {mins} min" for pid, mins in v.minutos.items())
    print(f"A3 sugiere pacto v1 (inicio UTC {v.inicio_utc:%Y-%m-%d %H:%M})")
    print(f"Tiempo: {reparto} · duración total {v.duracion_min} min")

    mostrar("Invitaciones (borradores)", coord.revisar_pacto(pacto.id, REVISORA))

    for pid in pacto.participantes:
        coord.registrar_respuesta(pacto.id, pid, TipoRespuesta.ACEPTA, 1, REVISORA, origen="simulación")
        print(f"\n[SIMULACIÓN] Respuesta registrada: {pid} acepta v1")
    print(f"Estado del pacto: {pacto.estado.value}")

    try:
        mostrar("Confirmaciones (borradores)", coord.confirmar_pacto(pacto.id, REVISORA, args.enlace))
    except OperacionNoPermitida as exc:
        print(f"\nConfirmación bloqueada: {exc}")

    print(f"\nEstado final: {pacto.estado.value}")
    print("Nada se ha enviado. Todos los mensajes siguen en la bandeja de borradores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

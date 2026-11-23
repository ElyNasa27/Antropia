"""Simulación de la sincronización de la base «Cursos» con Participantes.

SOLO LECTURA: consulta Participantes y Cursos y muestra qué vínculos se añadirían
o quitarían y qué temas se crearían. No escribe nada en Notion: usa un cliente que
rechaza cualquier petición que no sea una consulta, y no existe código que
modifique Cursos. No envía correos.

Uso:  NOTION_TOKEN=... python simular_cursos.py [--solo-recuentos]

--solo-recuentos  solo recuentos (por acción, campo y motivo): sin temas ni filas.

El informe muestra los temas y referencias de fila («fila #N» del «ID consecutivo»),
nunca alias ni correos.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

from encuentros.cursos import PlanCursos, informe, planificar
from encuentros.notion_api import AlmacenNotion, ClienteNotion, ClienteSoloLectura, leer_cursos


def recuentos(plan: PlanCursos) -> list[str]:
    """Solo números y etiquetas fijas: nunca temas, filas, alias ni correos."""
    por_tipo = Counter((c.accion, c.campo, c.motivo, c.tema_id is None) for c in plan.cambios)
    lineas = [
        "SIMULACIÓN de Cursos (solo recuentos): no se ha modificado nada.",
        f"Perfiles vinculables: {plan.vinculables}",
    ]
    lineas += [f"No vinculables · {m}: {n}" for m, n in sorted(plan.no_vinculables.items())]
    for (accion, campo, motivo, nuevo), n in sorted(por_tipo.items()):
        lineas.append(f"Vínculos · {accion} · {campo} · {'tema nuevo' if nuevo else 'tema existente'} · "
                      f"{motivo}: {n}")
    lineas += [f"Temas nuevos: {len(plan.temas_nuevos)}",
               f"Temas que quedarían sin personas (se conservan): {len(plan.sin_personas)}"]
    lineas += [f"Aviso: {a}" for a in plan.avisos]       # los avisos ya son solo recuentos
    return lineas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo-recuentos", action="store_true")
    args = parser.parse_args(argv)
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        print("Falta NOTION_TOKEN. No se ha consultado ni modificado nada.", file=sys.stderr)
        return 2
    cliente = ClienteSoloLectura(ClienteNotion(token))
    personas = AlmacenNotion(cliente).personas()
    temas = leer_cursos(cliente)
    # Vínculos a filas que no aparecen: solo se dan por eliminadas si Notion lo confirma.
    conocidas = {p.id for p in personas}
    ausentes = {pid for t in temas for pid in t.ofrecen | t.quieren} - conocidas
    eliminadas = frozenset(pid for pid in ausentes if cliente.esta_en_la_papelera(pid) is True)
    plan = planificar(personas, temas, eliminadas)
    print(f"Participantes leídos: {len(personas)} · temas leídos en Cursos: {len(temas)} · "
          f"filas vinculadas que no aparecen: {len(ausentes)} (eliminación confirmada: {len(eliminadas)})")
    for linea in (recuentos(plan) if args.solo_recuentos else informe(plan)):
        print(linea)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Agente de match por CURSOS.

Lee Participantes y empareja personas teniendo en cuenta únicamente sus cursos
(ver encuentros/match_cursos.py). Nunca usa servicios de IA.

Modos:
  (sin opciones)        informe de SOLO LECTURA: no escribe ni envía nada.
  --ensayo-escritura    lee también «Matches por cursos [PRUEBA]» y muestra qué filas
                        se crearían, actualizarían o marcarían. No escribe nada.
  --escribir            escribe ese plan, SOLO en «Matches por cursos [PRUEBA]». Exige
                        ANTROPIA_ESCRIBIR_MATCHES_CURSOS=si. Nunca borra filas.
  --simular-correos     (con --ensayo-escritura) cuenta los correos que podrían enviarse
                        y lista lo que falta para poder enviar. No envía nada.
  --enviar              (con --escribir) primer envío de los correos pendientes.
  --reenviar ID         (con --escribir) reenvío por DECISIÓN HUMANA de UN correo
                        «Por revisar»: ID = su «Id correo» completo y exacto del último intento.
  --solo-recuentos      solo números: sin cursos, filas, alias ni correos.
  --solo-filas-de-la-base  usa ÚNICAMENTE las filas que una persona puso en «Matches por
                        cursos [PRUEBA]» (se adoptan): el agente no añade, cambia ni marca
                        matches calculados por él, ni les escribe.

--enviar y --reenviar exigen, ANTES de escribir nada: ANTROPIA_ENVIAR_CORREOS_CURSOS=si,
las instrucciones de respuesta, las credenciales de Gmail, ejecutarse en GitHub Actions
(una sola ejecución a la vez: ver .github/workflows/correos-cursos.yml), la plantilla sin
cambios y las columnas del correo en la base. El registro de envíos se guarda en la propia
base (columnas «Registro A/B»). Ningún secreto se escribe en el código.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys

from encuentros import reserva_envios
from encuentros.correo_cursos import PLANTILLA_PAGINA, plantilla_sin_cambios
from encuentros.envio_exclusivo import Ejecucion, vista_permite_primer_envio
from encuentros.match_cursos import ResultadoCursos, emparejar_por_cursos, informe, recuentos
from encuentros.match_cursos_notion import (
    ADOPTAR, ClienteSoloMatchesCursos, RegistroNotion, actualizar_vistas, aplicar, avisos_filas_manuales,
    ds_matches_cursos,
    enviar_correos, filas_tras_el_plan, leer_filas, planificar_envios, planificar_escritura,
    recuentos_plan, reenviar, tiene_columnas_de_correo,
)
from encuentros.notion_api import AlmacenNotion, ClienteNotion, ClienteSoloLectura, ErrorNotion

VARIABLE_ESCRIBIR = "ANTROPIA_ESCRIBIR_MATCHES_CURSOS"
VARIABLE_ENVIAR = "ANTROPIA_ENVIAR_CORREOS_CURSOS"
VARIABLE_INSTRUCCIONES = "ANTROPIA_CURSOS_INSTRUCCIONES"
SMTP = ("ANTROPIA_SMTP_USUARIO", "ANTROPIA_SMTP_CLAVE")
ACTIONS = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_REPOSITORY", "GITHUB_TOKEN")


# Servicios reales: solo se crean al enviar de verdad (en las pruebas se sustituyen).
def _crear_envio_real():
    from encuentros.correo import EnvioGmailSMTP
    return EnvioGmailSMTP()


def _crear_registro(cliente, filas):
    return RegistroNotion(cliente, filas)


def _crear_consulta_ejecuciones():
    return reserva_envios.ConsultaEjecucionesGitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])


def _falta(variables) -> list[str]:
    return [v for v in variables if not os.environ.get(v, "").strip()]


def bloqueos_de_envio(cliente, ds: str, simulacion: bool = False) -> list[str]:
    """Todo lo que impide enviar. Vacío = se puede enviar."""
    b = []
    if not simulacion and os.environ.get(VARIABLE_ENVIAR, "") != "si":
        b.append(f"falta {VARIABLE_ENVIAR}=si")
    if _falta([VARIABLE_INSTRUCCIONES]):
        b.append(f"falta {VARIABLE_INSTRUCCIONES} (cómo responder al correo)")
    if _falta(SMTP):
        b.append("faltan las credenciales de Gmail: " + ", ".join(_falta(SMTP)))
    if _falta(ACTIONS):
        b.append("solo se envía desde GitHub Actions (una ejecución a la vez); faltan: "
                 + ", ".join(_falta(ACTIONS)))
    try:
        if not plantilla_sin_cambios(cliente.leer_pagina(PLANTILLA_PAGINA).get("last_edited_time")):
            b.append("la plantilla de Notion cambió desde la versión revisada")
    except ErrorNotion:
        b.append("no se pudo leer la plantilla de Notion")
    try:
        if not tiene_columnas_de_correo(cliente, ds):
            b.append("la base no tiene las columnas de la vista del correo")
    except ErrorNotion:
        b.append("no se pudo leer el esquema de la base")
    return b


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo-recuentos", action="store_true")
    parser.add_argument("--solo-filas-de-la-base", action="store_true")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--ensayo-escritura", action="store_true")
    modo.add_argument("--escribir", action="store_true")
    correo = parser.add_mutually_exclusive_group()
    correo.add_argument("--simular-correos", action="store_true")
    correo.add_argument("--enviar", action="store_true")
    correo.add_argument("--reenviar", metavar="ID_CORREO")
    args = parser.parse_args(argv)
    envia = args.enviar or args.reenviar is not None

    def salir(mensaje: str) -> int:
        print(f"{mensaje} No se ha consultado ni modificado nada.", file=sys.stderr)
        return 2

    if args.simular_correos and not args.ensayo_escritura:
        return salir("--simular-correos solo se admite con --ensayo-escritura.")
    if envia and not args.escribir:
        return salir("--enviar y --reenviar solo se admiten con --escribir.")
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        return salir("Falta NOTION_TOKEN.")
    if args.escribir and os.environ.get(VARIABLE_ESCRIBIR, "") != "si":
        return salir(f"--escribir exige {VARIABLE_ESCRIBIR}=si.")
    if envia and os.environ.get(VARIABLE_ENVIAR, "") != "si":
        return salir(f"--enviar y --reenviar exigen {VARIABLE_ENVIAR}=si.")
    ds = ds_matches_cursos()

    real = ClienteNotion(token)
    try:
        cliente = ClienteSoloMatchesCursos(real, ds) if args.escribir else ClienteSoloLectura(real)
    except ValueError as e:
        return salir(str(e))
    personas = AlmacenNotion(cliente).personas()
    resultado = emparejar_por_cursos(personas)
    for linea in (recuentos(resultado) if args.solo_recuentos else informe(resultado)):
        print(linea)
    if not (args.ensayo_escritura or args.escribir):
        return 0

    # Antes de escribir nada: si se va a enviar, todo debe estar listo.
    if envia:
        bloqueos = bloqueos_de_envio(cliente, ds)
        if bloqueos:
            for b in bloqueos:
                print(f"Envío bloqueado: {b}")
            print("No se ha escrito nada ni enviado ningún correo.")
            return 3

    filas = leer_filas(cliente, ds)
    if args.solo_filas_de_la_base:
        # Sin pares calculados: solo se adoptan y se usan las filas puestas por personas.
        resultado = ResultadoCursos(perfiles=resultado.perfiles)
        plan = planificar_escritura(resultado, filas)
        plan.acciones = [a for a in plan.acciones if a.tipo == ADOPTAR]
        plan.avisos = [a for a in plan.avisos if "a mano" in a or "repetidas" in a]
        print("Modo: solo las filas puestas en la base por personas (no se añaden matches calculados).")
    else:
        plan = planificar_escritura(resultado, filas)
    hechas = aplicar(plan, cliente, ds) if args.escribir else 0
    for linea in recuentos_plan(plan, escrito=args.escribir):
        print(linea)
    if args.escribir:
        print(f"Escrituras hechas: {hechas}.")

    for aviso in avisos_filas_manuales(filas_tras_el_plan(filas, plan, resultado)):
        print(f"Aviso: {aviso}")

    if args.simular_correos:
        filas_sim = filas_tras_el_plan(filas, plan, resultado)
        pares = {f.clave for f in filas_sim}
        posibles = sum(1 for f in filas_sim if f.estado == "Vigente" and f.clave in pares
                       for lado in ("A", "B") if vista_permite_primer_envio(f.vista(lado)[0]))
        print(f"Correos que podrían enviarse como máximo (SIMULACIÓN, sin consultar el registro "
              f"de envíos; no se envía nada): {posibles}")
        for b in bloqueos_de_envio(cliente, ds, simulacion=True):
            print(f"Pendiente antes de poder enviar: {b}")

    if envia:
        filas = leer_filas(cliente, ds)                      # el estado real, tras escribir
        registro, consulta = _crear_registro(cliente, filas), _crear_consulta_ejecuciones()
        ejecucion = Ejecucion(os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"], secrets.token_hex(8))
        por_id = {p.id: p for p in personas}
        instrucciones = os.environ[VARIABLE_INSTRUCCIONES]
        servicio = _crear_envio_real()
        if args.enviar:
            pendientes = planificar_envios(resultado, filas, registro, consulta)
            r = enviar_correos(pendientes, por_id, cliente, servicio, registro, ejecucion, instrucciones)
            print(f"Correos enviados: {r.enviados}")
            for motivo, n in sorted(r.no_enviados.items()):
                print(f"No enviados · {motivo}: {n}")
        else:
            inf = reenviar(args.reenviar, resultado, filas, por_id, cliente, servicio, registro, ejecucion,
                           instrucciones, consulta)
            print(f"Reenvío: {'enviado' if inf.enviado else 'no enviado'} · {inf.motivo}")
        print(f"Vistas actualizadas en Notion: {actualizar_vistas(resultado, filas, cliente, registro, consulta)}")
    else:
        print("Ningún correo enviado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

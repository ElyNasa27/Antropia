"""Una ejecución del ciclo automático (la lanza GitHub Actions cada 30 minutos).

Variables de entorno (en GitHub: Settings → Secrets and variables → Actions):
  NOTION_TOKEN              token de la integración interna de Notion   (secreto)
  ANTROPIA_SMTP_USUARIO     cuenta de Gmail que envía                    (secreto)
  ANTROPIA_SMTP_CLAVE       contraseña de aplicación de Google           (secreto)
  ANTROPIA_CLAVE_CODIGOS    clave larga y aleatoria para las huellas     (secreto)
  ANTROPIA_FORMULARIO_URL   enlace público de «Responder a tu match»     (variable)
  ANTROPIA_SALAS            (variable, opcional) cómo se crea la sala al confirmar:
                              vacío         el sistema no crea enlaces; una persona
                                            escribe el enlace en «Enlace Jitsi»
                              jitsi-prueba  sala de Jitsi Meet marcada «PRUEBA» (piloto)
                              jitsi         sala de Jitsi Meet para encuentros reales
                            Siempre una sala aleatoria distinta por pareja, y solo
                            después de que ambas personas aceptan.

  --simulacion  lee Notion pero no escribe nada ni envía correos.

El registro solo muestra recuentos y finales de ids: nunca correos ni códigos.
"""
from __future__ import annotations

import argparse
import os
import sys

from encuentros.automatico import SALAS_JITSI, SALAS_PRUEBA, Ciclo, Configuracion, proveedor_de_salas
from encuentros.correo import EnvioGmailSMTP, EnvioSimulado
from encuentros.notion_api import AlmacenNotion, AlmacenSoloLectura, ClienteNotion
from encuentros.zonas import datos_de_zonas_disponibles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulacion", action="store_true")
    args = parser.parse_args(argv)

    if not datos_de_zonas_disponibles():
        print("Faltan datos de zonas horarias (tzdata).", file=sys.stderr)
        return 2
    faltan = [v for v in ("NOTION_TOKEN", "ANTROPIA_CLAVE_CODIGOS", "ANTROPIA_FORMULARIO_URL")
              if not os.environ.get(v, "").strip()]
    if not args.simulacion:
        faltan += [v for v in ("ANTROPIA_SMTP_USUARIO", "ANTROPIA_SMTP_CLAVE")
                   if not os.environ.get(v, "").strip()]
    if faltan:
        print("Faltan variables: " + ", ".join(faltan), file=sys.stderr)
        return 2
    if len(os.environ["ANTROPIA_CLAVE_CODIGOS"]) < 32:
        print("ANTROPIA_CLAVE_CODIGOS debe tener al menos 32 caracteres.", file=sys.stderr)
        return 2

    almacen = AlmacenNotion(ClienteNotion(os.environ["NOTION_TOKEN"]))
    if args.simulacion:
        almacen, envio = AlmacenSoloLectura(almacen), EnvioSimulado()
    else:
        envio = EnvioGmailSMTP()
    salas = os.environ.get("ANTROPIA_SALAS", "").strip().lower()
    try:
        proveedor = proveedor_de_salas(salas)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    cfg = Configuracion(url_formulario=os.environ["ANTROPIA_FORMULARIO_URL"].strip(),
                        clave_codigos=os.environ["ANTROPIA_CLAVE_CODIGOS"],
                        nueva_sala=proveedor)
    r = Ciclo(almacen, envio, cfg).ejecutar()

    print(f"Modo: {'SIMULACIÓN (no escribe ni envía)' if args.simulacion else 'real'}")
    print(f"Participantes leídos: {r.personas} · elegibles con correo: {r.elegibles}")
    print(f"Matches nuevos: {r.matches_nuevos} · confirmados: {r.confirmados} · "
          f"reprogramados: {r.reprogramados} · cerrados: {r.cerrados}")
    print(f"Respuestas procesadas: {r.respuestas or 'ninguna'}")
    print(f"A1 automático, personas con datos por completar: {r.a1_con_problemas} · "
          f"pares con temas por aclarar: {r.pares_por_aclarar} · "
          f"confirmados sin enlace: {r.confirmados_sin_enlace}")
    modo_salas = {SALAS_PRUEBA: "Jitsi Meet, enlaces de PRUEBA", SALAS_JITSI: "Jitsi Meet, encuentros reales"}
    print(f"Salas de videollamada: {modo_salas.get(salas, 'enlace escrito por una persona')}")
    print(f"Correos {'simulados' if args.simulacion else 'enviados'}: {r.correos_enviados} · "
          f"errores de envío: {r.errores_envio}")
    for a in r.avisos:
        print(f"Aviso: {a}")
    if args.simulacion:
        print(f"Escrituras que se habrían hecho en Notion: {len(almacen.escrituras)}")
    return 1 if r.errores_envio else 0


if __name__ == "__main__":
    sys.exit(main())

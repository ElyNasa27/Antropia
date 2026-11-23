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

  ANTROPIA_ACTIVO           (variable) «si» = permite el modo REAL. Se exige en las
                            ejecuciones programadas Y en las manuales: con cualquier
                            otro valor (o vacía) el modo real se detiene antes de
                            leer o escribir en Notion y de enviar correos.

  ANTROPIA_ANALISIS_SEMANTICO  (opcional, SOLO en la computadora con Ollama) «si» =
                            además de las reglas locales, compara temas por su
                            significado con qwen3:1.7b en Ollama LOCAL
                            (encuentros/consultor_ollama.py). Si Ollama no
                            responde, el ciclo se detiene antes de tocar Notion.
                            En GitHub Actions no se define: allí no hay Ollama.
  ANTROPIA_OLLAMA_URL       (opcional) por defecto http://127.0.0.1:11434; solo se
                            aceptan direcciones locales.
  ANTROPIA_OLLAMA_MAX_CONSULTAS  (opcional) consultas nuevas por ciclo (20); las
                            que pasen del límite quedan «requiere aclaración».
  ANTROPIA_CACHE_SEMANTICA  (opcional) archivo local con las respuestas ya dadas
                            (por defecto .cache/temas_semanticos.json; sin textos).

  --simulacion  lee Notion pero no escribe nada ni envía correos. No necesita
                ANTROPIA_ACTIVO ni las credenciales de Gmail. Doble cierre: el almacén
                solo anota las escrituras y el cliente de Notion rechaza cualquier
                petición que no sea una consulta.
  --solo-recuentos  (con --simulacion) muestra solo recuentos: sin avisos por fila,
                sin finales de ids, temas, alias ni correos. Para compartir el resultado.

El registro solo muestra recuentos y finales de ids: nunca correos ni códigos.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from encuentros import consultor_ollama
from encuentros.automatico import SALAS_JITSI, SALAS_PRUEBA, Ciclo, Configuracion, proveedor_de_salas
from encuentros.correo import EnvioGmailSMTP, EnvioSimulado
from encuentros.notion_api import AlmacenNotion, AlmacenSoloLectura, ClienteNotion, ClienteSoloLectura
from encuentros.temas_semantica import AnalizadorSemantico
from encuentros.zonas import datos_de_zonas_disponibles

VALOR_ACTIVO = "si"          # mismo valor exacto que exige el workflow
SALIDA_REAL_DESACTIVADO = 4
SALIDA_OLLAMA_NO_DISPONIBLE = 5


def modo_real_permitido() -> bool:
    return os.environ.get("ANTROPIA_ACTIVO", "") == VALOR_ACTIVO


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulacion", action="store_true")
    parser.add_argument("--solo-recuentos", action="store_true")
    args = parser.parse_args(argv)
    if args.solo_recuentos and not args.simulacion:
        print("--solo-recuentos solo se admite con --simulacion.", file=sys.stderr)
        return 2

    # Tercer cierre: el modo real exige ANTROPIA_ACTIVO=si, también en las ejecuciones
    # manuales. Se comprueba ANTES de crear el cliente de Notion o el de correo.
    if not args.simulacion and not modo_real_permitido():
        print("Modo real desactivado: ANTROPIA_ACTIVO no es «si». No se ha leído ni escrito "
              "nada en Notion ni se ha enviado ningún correo. Use --simulacion para probar.",
              file=sys.stderr)
        return SALIDA_REAL_DESACTIVADO

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

    # Análisis por significado con Ollama local: se comprueba ANTES de tocar Notion.
    analizador = memoria = None
    if os.environ.get(consultor_ollama.VARIABLE_ACTIVACION, "") == consultor_ollama.VALOR_ACTIVO:
        try:
            ollama = consultor_ollama.crear_consultor_real()
        except (RuntimeError, ValueError) as e:
            print(str(e), file=sys.stderr)
            return 2
        listo, motivo = ollama.disponible()
        if not listo:
            print(f"Análisis semántico activado, pero {motivo}. No se ha leído ni escrito nada "
                  "en Notion ni se ha enviado ningún correo.", file=sys.stderr)
            return SALIDA_OLLAMA_NO_DISPONIBLE
        ruta = os.environ.get("ANTROPIA_CACHE_SEMANTICA", "").strip() or ".cache/temas_semanticos.json"
        memoria = consultor_ollama.ConsultorConMemoria(ollama, Path(ruta))
        analizador = AnalizadorSemantico(memoria)

    cliente = ClienteNotion(os.environ["NOTION_TOKEN"])
    if args.simulacion:
        cliente = ClienteSoloLectura(cliente)        # segundo cierre: solo consultas
    almacen = AlmacenNotion(cliente)
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
                        nueva_sala=proveedor, analizador_temas=analizador)
    r = Ciclo(almacen, envio, cfg).ejecutar()

    print(f"Modo: {'SIMULACIÓN (no escribe ni envía)' if args.simulacion else 'real'}")
    print(f"Participantes leídos: {r.personas} · elegibles con correo: {r.elegibles}")
    print(f"Aptitud: automática {r.aptitud_automatica} · escrita «Apto» {r.aptitud_de_persona} · "
          f"bloqueada por una persona {r.bloqueo_escrito_por_persona} · "
          f"sin autorización {r.sin_autorizacion}")
    print(f"Respaldo: requiere revisión humana {r.revision_humana_respaldo} · "
          f"opcional pendiente, no se usa {r.respaldo_no_usado}")
    print(f"Matches nuevos: {r.matches_nuevos} · confirmados: {r.confirmados} · "
          f"reprogramados: {r.reprogramados} · cerrados: {r.cerrados}")
    print(f"Respuestas procesadas: {r.respuestas or 'ninguna'}")
    print(f"A1 automático, personas con datos por completar: {r.a1_con_problemas} · "
          f"pares con temas por aclarar: {r.pares_por_aclarar} · "
          f"confirmados sin enlace: {r.confirmados_sin_enlace}")
    modo_salas = {SALAS_PRUEBA: "Jitsi Meet, enlaces de PRUEBA", SALAS_JITSI: "Jitsi Meet, encuentros reales"}
    print(f"Salas de videollamada: {modo_salas.get(salas, 'enlace escrito por una persona')}")
    if memoria is None:
        print("Análisis de temas: solo reglas locales")
    else:
        print(f"Análisis de temas: reglas + {consultor_ollama.MODELO} en Ollama local · "
              f"consultas nuevas {memoria.nuevas} · recordadas {memoria.recordadas} · "
              f"sin respuesta (requieren aclaración) {analizador.fallos}")
    print(f"Correos {'simulados' if args.simulacion else 'enviados'}: {r.correos_enviados} · "
          f"errores de envío: {r.errores_envio}")
    print(f"Correos con problemas (filas): duplicados {r.correos_duplicados} · "
          f"pares con el mismo alias no propuestos: {r.pares_misma_persona} · "
          f"perfiles con datos en «Ofrece 2…7»/«Quiere aprender 2…7»: {r.temas_adicionales_con_datos}")
    for motivo, n in sorted(r.motivos_a1.items()):
        print(f"Motivo A1: {motivo} · perfiles: {n}")
    if args.solo_recuentos:
        print(f"Avisos: {len(r.avisos)} (no se muestran con --solo-recuentos)")
    else:
        for a in r.avisos:
            print(f"Aviso: {a}")
    if args.simulacion:
        print(f"Escrituras que se habrían hecho en Notion: {len(almacen.escrituras)}")
    return 1 if r.errores_envio else 0


if __name__ == "__main__":
    sys.exit(main())

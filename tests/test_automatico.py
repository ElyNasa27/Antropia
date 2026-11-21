"""Ciclo automático completo, con un almacén en memoria y envío simulado (datos ficticios)."""
import copy
import itertools
import unittest
from datetime import UTC, datetime, timedelta

from encuentros.automatico import (
    ACEPTO, APLICADA, CADUCADA, CERRADO, CODIGO_NO_VALIDO, CONFIRMADO, ESPERANDO, MAX_VERSIONES,
    NO_INTERESA, PENDIENTE, SIN_RESPUESTA, YA_RESPONDIDA, Ciclo, Configuracion, FilaRespuesta,
    Persona, huella, normalizar_codigo,
)
from encuentros.correo import EnvioSimulado, contiene_correo
from tests.apoyo import ZONAS_REALES

URL_FORM = "https://formulario.example/responder"
CLAVE = "clave-de-prueba-" + "x" * 32
LUNES = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)        # lunes; A2 busca desde +24 h
INICIO = datetime(2026, 11, 30, 17, 0, tzinfo=UTC)       # Madrid 18:00 · CDMX 11:00


def persona(pid, alias, ofrece, quiere, disp, zona, **kw):
    base = dict(id=pid, alias=alias, correo=f"{pid}@example.org", autoriza=True, aptitud="Apto",
                respaldo=None, revision_respaldo="No requerida", idioma="Español",
                modalidad="Virtual", acepta_videollamada="No aplica", ofrece=ofrece,
                quiere_aprender=quiere, disponibilidad=disp, zona_horaria=zona, minutos=30)
    base.update(kw)
    return Persona(**base)


def alba(**kw):
    return persona("alba", "Alba", "Fotografía con móvil", "inglés conversacional",
                   "lunes 18:00–20:00", "Europe/Madrid", **kw)


def bruno(**kw):
    return persona("bruno", "Bruno", "Inglés conversacional", "fotografia con movil",
                   "lunes 11:00-13:00; America/Mexico_City", None, **kw)


class AlmacenMemoria:
    def __init__(self, personas):
        self._personas = personas
        self.filas = {}
        self.respuestas = {}
        self._n = itertools.count(1)

    def personas(self):
        return copy.deepcopy(self._personas)

    def matches(self):
        return copy.deepcopy(list(self.filas.values()))

    def respuestas_pendientes(self):
        return [copy.deepcopy(r) for r in self.respuestas.values() if r.procesada in (None, PENDIENTE)]

    def crear_match(self, f):
        f.id = f"match-{next(self._n)}"
        self.filas[f.id] = copy.deepcopy(f)
        return f.id

    def guardar_match(self, f):
        self.filas[f.id] = copy.deepcopy(f)

    def marcar_respuesta(self, rid, estado, mid):
        self.respuestas[rid].procesada = estado
        self.respuestas[rid].match = mid

    # Lo que hace una persona al enviar el formulario de Notion
    def responder(self, codigo, respuesta):
        rid = f"resp-{next(self._n)}"
        self.respuestas[rid] = FilaRespuesta(rid, codigo, respuesta, None)
        return rid


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestCicloAutomatico(unittest.TestCase):
    def setUp(self):
        self.codigos = (f"C{n:03d}-AAAA".replace("0", "Q").replace("1", "R") for n in itertools.count(100))
        self.salas = (f"https://meet.jit.si/AntropiaPrueba{n}" for n in itertools.count(1))

    def cfg(self):
        return Configuracion(URL_FORM, CLAVE, generar_codigo=lambda: next(self.codigos),
                             nueva_sala=lambda: next(self.salas))

    def ciclo(self, almacen, envio, ahora=LUNES):
        return Ciclo(almacen, envio, self.cfg(), ahora).ejecutar()

    def codigo_de(self, envio, pid, i=-1):
        cuerpos = [c.cuerpo for c in envio.enviados if c.destinatario_id == pid]
        return normalizar_codigo(cuerpos[i].split("código personal:")[1])

    def preparar(self, personas=None):
        alm, envio = AlmacenMemoria(personas or [alba(), bruno()]), EnvioSimulado()
        self.ciclo(alm, envio)
        return alm, envio

    # -- 1. match y aviso --------------------------------------------------
    def test_match_automatico_con_fecha_codigo_y_formulario(self):
        alm, envio = self.preparar()
        [f] = alm.filas.values()
        self.assertEqual((f.a, f.b, f.estado, f.inicio_utc), ("alba", "bruno", ESPERANDO, INICIO))
        self.assertEqual((f.minutos_a, f.minutos_b, f.version), (30, 30, 1))
        self.assertTrue(f.aviso_a and f.aviso_b)
        self.assertEqual(len(envio.enviados), 2)
        a = next(c for c in envio.enviados if c.destinatario_id == "alba")
        b = next(c for c in envio.enviados if c.destinatario_id == "bruno")
        self.assertIn("lunes 30 de noviembre de 2026, 18:00–19:00 (hora de Madrid)", a.cuerpo)
        self.assertIn("lunes 30 de noviembre de 2026, 11:00–12:00 (hora de Ciudad de México)", b.cuerpo)
        self.assertIn("30 min enseñas tú · 30 min enseña Bruno · duración total: 60 min", a.cuerpo)
        self.assertIn(URL_FORM, a.cuerpo)
        self.assertEqual(a.para, "alba@example.org")

    def test_el_codigo_no_se_guarda_solo_su_huella(self):
        alm, envio = self.preparar()
        [f] = alm.filas.values()
        codigo = self.codigo_de(envio, "alba")
        self.assertEqual(f.huella_a, huella(codigo, CLAVE))
        self.assertNotIn(codigo, repr(f))
        self.assertNotEqual(f.huella_a, f.huella_b)

    def test_privacidad_de_los_correos(self):
        _, envio = self.preparar()
        for c in envio.enviados:
            self.assertFalse(contiene_correo(c.cuerpo + c.asunto))

    def test_repetir_el_ciclo_no_duplica(self):
        alm, envio = self.preparar()
        self.ciclo(alm, envio)
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        self.assertEqual(len(alm.filas), 1)
        self.assertEqual(len(envio.enviados), 2)

    # -- 2. respuestas y confirmación -------------------------------------
    def test_ambas_aceptan_se_crea_jitsi_y_se_confirma(self):
        alm, envio = self.preparar()
        ra = alm.responder(self.codigo_de(envio, "alba"), ACEPTO)
        # Con una sola aceptación aún no pasa nada.
        self.ciclo(alm, envio, LUNES + timedelta(hours=2))
        [f] = alm.filas.values()
        self.assertEqual((f.respuesta_a, f.respuesta_b, f.estado), (ACEPTO, PENDIENTE, ESPERANDO))
        rb = alm.responder("  código: " + self.codigo_de(envio, "bruno").lower(), ACEPTO)
        self.ciclo(alm, envio, LUNES + timedelta(hours=3))
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)
        self.assertEqual(f.enlace, "https://meet.jit.si/AntropiaPrueba1")
        self.assertTrue(f.confirmacion_a and f.confirmacion_b)
        self.assertEqual({alm.respuestas[ra].procesada, alm.respuestas[rb].procesada}, {APLICADA})
        conf = [c for c in envio.enviados if "confirmado" in c.asunto]
        self.assertEqual(sorted(c.destinatario_id for c in conf), ["alba", "bruno"])
        for c in conf:
            self.assertIn(f.enlace, c.cuerpo)
            [(nombre, tipo, ics)] = c.adjuntos
            self.assertEqual(tipo, "text/calendar")
            self.assertIn(b"DTSTART:20261130T170000Z", ics)
            self.assertIn(b"DTEND:20261130T180000Z", ics)
        # Otro ciclo no reenvía nada.
        n = len(envio.enviados)
        self.ciclo(alm, envio, LUNES + timedelta(hours=4))
        self.assertEqual(len(envio.enviados), n)

    def test_no_me_interesa_cierra_y_avisa_solo_a_la_otra(self):
        alm, envio = self.preparar()
        alm.responder(self.codigo_de(envio, "bruno"), NO_INTERESA)
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CERRADO)
        self.assertEqual((f.huella_a, f.huella_b), ("", ""))
        cierre = [c for c in envio.enviados if "no se realizará" in c.asunto]
        self.assertEqual([c.destinatario_id for c in cierre], ["alba"])

    def test_codigos_no_validos_repetidos_y_sin_respuesta(self):
        alm, envio = self.preparar()
        cod = self.codigo_de(envio, "alba")
        r1 = alm.responder("ZZZZ-ZZZZ", ACEPTO)
        r2 = alm.responder("hola", ACEPTO)
        r3 = alm.responder(cod, None)
        r4 = alm.responder(cod, ACEPTO)
        r5 = alm.responder(cod, NO_INTERESA)
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        estados = [alm.respuestas[r].procesada for r in (r1, r2, r3, r4, r5)]
        self.assertEqual(estados, [CODIGO_NO_VALIDO, CODIGO_NO_VALIDO, SIN_RESPUESTA, APLICADA, YA_RESPONDIDA])
        [f] = alm.filas.values()
        self.assertEqual(f.respuesta_a, ACEPTO)

    # -- 3. horarios ---------------------------------------------------------
    def test_sin_respuestas_a_tiempo_se_propone_otro_horario_con_codigos_nuevos(self):
        alm, envio = self.preparar()
        viejo = self.codigo_de(envio, "alba")
        self.ciclo(alm, envio, INICIO - timedelta(minutes=30))
        [f] = alm.filas.values()
        self.assertEqual((f.version, f.estado, f.respuesta_a), (2, ESPERANDO, PENDIENTE))
        self.assertEqual(f.inicio_utc, INICIO + timedelta(days=7))
        nuevos = [c for c in envio.enviados if "nuevo horario" in c.asunto]
        self.assertEqual(len(nuevos), 2)
        r = alm.responder(viejo, ACEPTO)
        self.ciclo(alm, envio, INICIO)
        self.assertEqual(alm.respuestas[r].procesada, CODIGO_NO_VALIDO)

    def test_tras_el_maximo_de_horarios_se_cierra(self):
        alm, envio = self.preparar()
        ahora = INICIO
        for _ in range(MAX_VERSIONES):
            self.ciclo(alm, envio, ahora)
            ahora += timedelta(days=7)
        [f] = alm.filas.values()
        self.assertEqual((f.estado, f.version), (CERRADO, MAX_VERSIONES))

    def test_aceptar_despues_de_la_hora_caduca(self):
        alm, envio = self.preparar()
        cod = self.codigo_de(envio, "alba")
        r = alm.responder(cod, ACEPTO)
        self.ciclo(alm, envio, INICIO + timedelta(minutes=5))
        self.assertEqual(alm.respuestas[r].procesada, CADUCADA)

    def test_choque_con_otro_encuentro_confirmado_reprograma(self):
        carla = persona("carla", "Carla", "inglés conversacional", "fotografía con móvil",
                        "lunes 11:00-13:00", "America/Mexico_City")
        alm, envio = self.preparar([alba(), bruno(), carla])
        self.assertEqual(len(alm.filas), 2)
        for pid in ("alba", "bruno", "carla"):
            for i in range(len([c for c in envio.enviados if c.destinatario_id == pid])):
                alm.responder(self.codigo_de(envio, pid, i), ACEPTO)
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        estados = sorted((f.estado, f.version) for f in alm.filas.values())
        self.assertEqual(estados, [(CONFIRMADO, 1), (ESPERANDO, 2)])
        nuevo = next(f for f in alm.filas.values() if f.estado == ESPERANDO)
        # Justo después del encuentro confirmado: Alba sigue libre hasta las 19:00 UTC.
        self.assertEqual(nuevo.inicio_utc, INICIO + timedelta(hours=1))

    # -- 4. fallos y elegibilidad -----------------------------------------
    def test_fallo_de_envio_se_reintenta_solo_a_quien_falta(self):
        alm, envio = AlmacenMemoria([alba(), bruno()]), EnvioSimulado(fallar_para={"bruno"})
        r = self.ciclo(alm, envio)
        self.assertEqual(r.errores_envio, 1)
        [f] = alm.filas.values()
        self.assertEqual((f.aviso_a, f.aviso_b), (True, False))
        envio.fallar_para.clear()
        self.ciclo(alm, envio, LUNES + timedelta(minutes=30))
        self.assertEqual(sorted(c.destinatario_id for c in envio.enviados), ["alba", "bruno"])
        [f] = alm.filas.values()
        self.assertEqual(f.huella_b, huella(self.codigo_de(envio, "bruno"), CLAVE))

    def test_fallo_en_la_confirmacion_se_reintenta(self):
        alm, envio = self.preparar()
        alm.responder(self.codigo_de(envio, "alba"), ACEPTO)
        alm.responder(self.codigo_de(envio, "bruno"), ACEPTO)
        envio.fallar_para.add("alba")
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        [f] = alm.filas.values()
        self.assertEqual((f.estado, f.confirmacion_a, f.confirmacion_b), (CONFIRMADO, False, True))
        envio.fallar_para.clear()
        self.ciclo(alm, envio, LUNES + timedelta(hours=2))
        [f] = alm.filas.values()
        self.assertTrue(f.confirmacion_a)
        self.assertEqual(f.enlace, "https://meet.jit.si/AntropiaPrueba1")   # misma sala

    def test_requisitos_humanos_de_la_persona_se_respetan(self):
        casos = {
            "sin correo": bruno(correo=None),
            "no apto": bruno(aptitud="Pendiente"),
            "respaldo sin revisar": bruno(respaldo="10 años de profesora", revision_respaldo="Pendiente"),
            "sin autorización": bruno(autoriza=False),
            "disponibilidad ilegible": bruno(disponibilidad="cuando pueda"),
            "minutos no válidos": bruno(minutos=None),
        }
        for nombre, b in casos.items():
            with self.subTest(nombre):
                alm, envio = self.preparar([alba(), b])
                self.assertEqual(alm.filas, {})
                self.assertEqual(envio.enviados, [])

    def test_respaldo_aprobado_en_notion_permite_el_match(self):
        alm, _ = self.preparar([alba(), bruno(respaldo="Profesor", revision_respaldo="Aprobada")])
        self.assertEqual(len(alm.filas), 1)

    def test_si_alguien_deja_de_ser_apto_no_se_confirma(self):
        alm, envio = self.preparar()
        alm.responder(self.codigo_de(envio, "alba"), ACEPTO)
        alm.responder(self.codigo_de(envio, "bruno"), ACEPTO)
        alm._personas[1] = bruno(aptitud="Incompleto")
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        [f] = alm.filas.values()
        self.assertNotEqual(f.estado, CONFIRMADO)
        self.assertIsNone(f.enlace)


class TestCodigos(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(normalizar_codigo(" abcd efgh "), "ABCD-EFGH")
        self.assertEqual(normalizar_codigo("Mi código: ABCD-EFGH"), "ABCD-EFGH")
        self.assertIsNone(normalizar_codigo("ABC"))

    def test_huella_depende_de_la_clave(self):
        self.assertNotEqual(huella("ABCD-EFGH", "a" * 32), huella("ABCD-EFGH", "b" * 32))


if __name__ == "__main__":
    unittest.main()

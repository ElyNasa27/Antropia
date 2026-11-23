"""Ciclo automático completo, con un almacén en memoria y envío simulado (datos ficticios)."""
import copy
import dataclasses
import itertools
import unittest
from datetime import UTC, datetime, timedelta

from encuentros.automatico import (
    ACEPTO, APLICADA, CADUCADA, CERRADO, CODIGO_NO_VALIDO, CONFIRMADO, ESPERANDO, MAX_VERSIONES,
    NO_INTERESA, PENDIENTE, SIN_RESPUESTA, YA_RESPONDIDA, Ciclo, Configuracion, FilaRespuesta,
    Persona, evaluar_participante, huella, normalizar_codigo,
)
from encuentros.modelos import (
    REVISION_APROBADA, REVISION_NO_REQUERIDA, RESPALDO_SIN_VERIFICAR_NO_USADO,
)
from encuentros.zonas import resolver_zona_real
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

    def test_match_con_temas_escritos_distinto(self):
        alm, envio = self.preparar([
            persona("alba", "Alba", "crear tablas en Excel para controlar gastos", "English",
                    "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", "clases de inglés", "aprender a organizar gastos usando Excel",
                    "lunes 11:00-13:00; America/Mexico_City", None),
        ])
        [f] = alm.filas.values()
        self.assertEqual(f.a_ensena, ["crear tablas en Excel para controlar gastos → "
                                      "aprender a organizar gastos usando Excel"])
        self.assertEqual(f.b_ensena, ["clases de inglés → English"])
        self.assertIn("temas: sinónimo, tema definido", f.notas)
        a = next(c for c in envio.enviados if c.destinatario_id == "alba")
        self.assertIn("Tú compartes: crear tablas en Excel para controlar gastos "
                      "(Bruno pidió: «aprender a organizar gastos usando Excel»)", a.cuerpo)
        self.assertIn("Bruno comparte: clases de inglés (tú pediste: «English»)", a.cuerpo)

    def test_tema_incierto_no_crea_match_ni_envia_correos(self):
        alm, envio = self.preparar([
            persona("alba", "Alba", "Excel", "English", "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", "clases de inglés", "Excel avanzado",
                    "lunes 11:00-13:00; America/Mexico_City", None),
        ])
        self.assertEqual(alm.filas, {})
        self.assertEqual(envio.enviados, [])
        r = Ciclo(alm, envio, self.cfg(), LUNES).ejecutar()
        self.assertEqual(r.pares_por_aclarar, 1)
        [aviso] = [x for x in r.avisos if "requiere aclaración" in x]
        self.assertNotIn("Excel", aviso)            # el registro no muestra los temas
        self.assertEqual(aviso, "par alba/bruno: requiere aclaración de temas; no se propone match")

    def test_coincidencia_en_una_sola_direccion_no_crea_match(self):
        alm, envio = self.preparar([
            persona("alba", "Alba", "crear tablas en Excel para controlar gastos", "guitarra",
                    "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", "inglés", "organizar gastos usando Excel",
                    "lunes 11:00-13:00; America/Mexico_City", None),
        ])
        self.assertEqual((alm.filas, envio.enviados), ({}, []))

    def test_sin_match_si_el_nivel_no_alcanza(self):
        alm, _ = self.preparar([
            persona("alba", "Alba", "Excel básico", "inglés", "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", "inglés", "Excel avanzado",
                    "lunes 11:00-13:00; America/Mexico_City", None),
        ])
        self.assertEqual(alm.filas, {})

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

    def test_sin_proveedor_de_salas_no_se_inventa_enlace(self):
        alm, envio = AlmacenMemoria([alba(), bruno()]), EnvioSimulado()
        cfg = Configuracion(URL_FORM, CLAVE, generar_codigo=lambda: next(self.codigos))
        self.assertIsNone(cfg.nueva_sala)              # por defecto no se crean salas
        Ciclo(alm, envio, cfg, LUNES).ejecutar()
        alm.responder(self.codigo_de(envio, "alba"), ACEPTO)
        alm.responder(self.codigo_de(envio, "bruno"), ACEPTO)
        r = Ciclo(alm, envio, cfg, LUNES + timedelta(hours=1)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)
        self.assertIsNone(f.enlace)
        self.assertIn("falta el enlace", f.notas)
        self.assertFalse(f.confirmacion_a or f.confirmacion_b)
        self.assertEqual([c for c in envio.enviados if "confirmado" in c.asunto], [])
        self.assertEqual(r.confirmados_sin_enlace, 1)
        # Un enlace no válido escrito a mano tampoco se envía.
        f.enlace = "meet.jit.si/sala"
        alm.guardar_match(f)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=2)).ejecutar()
        self.assertEqual([c for c in envio.enviados if "confirmado" in c.asunto], [])
        # Cuando una persona escribe un enlace real, se envía la confirmación a cada una.
        f.enlace = "https://videollamada.example/sala-de-prueba"
        alm.guardar_match(f)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=3)).ejecutar()
        conf = [c for c in envio.enviados if "confirmado" in c.asunto]
        self.assertEqual(sorted(c.destinatario_id for c in conf), ["alba", "bruno"])
        self.assertTrue(all(f.enlace in c.cuerpo and "Jitsi" not in c.cuerpo for c in conf))

    def test_solo_se_confirma_si_ambas_aceptan_la_misma_version(self):
        alm, envio = self.preparar()
        viejo_alba = self.codigo_de(envio, "alba")
        alm.responder(viejo_alba, ACEPTO)                       # Alba acepta la versión 1
        self.ciclo(alm, envio, INICIO - timedelta(minutes=30))  # Bruno no responde: versión 2
        [f] = alm.filas.values()
        self.assertEqual((f.version, f.respuesta_a, f.respuesta_b), (2, PENDIENTE, PENDIENTE))
        # La aceptación de la versión 1 no vale para la 2: con el código viejo no se aplica.
        r = alm.responder(viejo_alba, ACEPTO)
        alm.responder(self.codigo_de(envio, "bruno"), ACEPTO)  # Bruno acepta la versión 2
        self.ciclo(alm, envio, INICIO)
        [f] = alm.filas.values()
        self.assertEqual(alm.respuestas[r].procesada, CODIGO_NO_VALIDO)
        self.assertEqual((f.estado, f.respuesta_a, f.respuesta_b), (ESPERANDO, PENDIENTE, ACEPTO))
        # El código de una persona no sirve para responder por la otra.
        self.assertNotEqual(self.codigo_de(envio, "alba"), self.codigo_de(envio, "bruno"))
        alm.responder(self.codigo_de(envio, "alba"), ACEPTO)
        self.ciclo(alm, envio, INICIO + timedelta(hours=1))
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)
        self.assertIn("ambas aceptaron la versión 2", f.notas)

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
            # Un respaldo de experiencia sin credenciales ya no bloquea (ver TestAptitudAutomatica);
            # uno que afirma un título sí, mientras nadie lo revise.
            "respaldo con título sin revisar": bruno(respaldo="Licenciada en Filología Inglesa",
                                                     revision_respaldo="Pendiente"),
            "sin autorización": bruno(autoriza=False),
            "disponibilidad ilegible": bruno(disponibilidad="cuando pueda"),
            "minutos no válidos": bruno(minutos=None),
        }
        for nombre, b in casos.items():
            with self.subTest(nombre):
                alm, envio = self.preparar([alba(), b])
                self.assertEqual(alm.filas, {})
                self.assertEqual(envio.enviados, [])

    def test_a1_automatico_excluye_datos_no_validos_sin_parar_a_las_demas(self):
        carla = persona("carla", "Carla", "inglés conversacional", "fotografía con móvil",
                        "lunes 11:00-13:00", "Marte/Olympus")
        alm, envio = AlmacenMemoria([alba(), bruno(), carla]), EnvioSimulado()
        r = Ciclo(alm, envio, self.cfg(), LUNES).ejecutar()
        [f] = alm.filas.values()                       # Alba y Bruno siguen emparejándose
        self.assertEqual((f.a, f.b), ("alba", "bruno"))
        self.assertEqual(r.a1_con_problemas, 1)
        self.assertIn("participante carla: A1 automático: faltan o no son válidos: "
                      "Zona horaria (no existe en la base IANA; requiere aclaración)", r.avisos)

    def test_a1_automatico_no_marca_decisiones_humanas(self):
        from encuentros.automatico import validar_a1_automatico
        from encuentros.zonas import resolver_zona_real
        p = bruno(aptitud="Pendiente")
        self.assertEqual(validar_a1_automatico(p, resolver_zona_real), [])
        self.assertEqual(p.aptitud, "Pendiente")       # A1 no toca «Aptitud»
        alm, _ = self.preparar([alba(), p])
        self.assertEqual(alm.filas, {})                # sigue haciendo falta «Apto» (humano)

    def test_cierre_automatico_no_es_decision_humana(self):
        from encuentros.automatico import _como_propuesta
        from encuentros.modelos import DecisionHumana
        alm, envio = self.preparar()
        alm.responder(self.codigo_de(envio, "bruno"), NO_INTERESA)
        self.ciclo(alm, envio, LUNES + timedelta(hours=1))
        [f] = alm.filas.values()
        m = _como_propuesta(f, LUNES)
        self.assertTrue(m.cerrada_automaticamente)
        self.assertFalse(m.activa)
        self.assertEqual(m.decision, DecisionHumana.PENDIENTE)   # nadie decidió a mano
        self.assertIsNone(m.decidido_por)

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


def sin_aptitud(f, **kw):
    """Perfil con «Aptitud» y «Revisión humana del respaldo» vacías, como en Notion."""
    return dataclasses.replace(f(), **{"aptitud": None, "revision_respaldo": None, **kw})


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestAptitudAutomatica(unittest.TestCase):
    """Opción B: aptitud automática y respaldo opcional pendiente que no se usa."""

    def setUp(self):
        self.codigos = (f"C{n:03d}-AAAA".replace("0", "Q").replace("1", "R") for n in itertools.count(100))
        self.salas = (f"https://meet.jit.si/AntropiaPrueba{n}" for n in itertools.count(1))

    def ciclo(self, alm, envio, ahora=LUNES):
        cfg = Configuracion(URL_FORM, CLAVE, generar_codigo=lambda: next(self.codigos),
                            nueva_sala=lambda: next(self.salas))
        return Ciclo(alm, envio, cfg, ahora).ejecutar()

    def correr(self, personas):
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        return alm, envio, self.ciclo(alm, envio)

    def sin_match(self, alm, envio):
        self.assertEqual(alm.filas, {})
        self.assertEqual(envio.enviados, [])

    # -- aptitud calculada ---------------------------------------------------
    def test_aptitud_vacia_se_calcula_y_hay_match(self):
        alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno)])
        self.assertEqual((r.aptitud_automatica, r.aptitud_de_persona, r.elegibles), (2, 0, 2))
        self.assertEqual(r.matches_nuevos, 1)
        self.assertEqual(len(envio.enviados), 2)

    def test_apto_escrito_por_una_persona_sigue_valiendo(self):
        alm, envio, r = self.correr([alba(), sin_aptitud(bruno)])
        self.assertEqual((r.aptitud_de_persona, r.aptitud_automatica, r.matches_nuevos), (1, 1, 1))

    def test_no_escribe_aptitud_ni_revision_en_participantes(self):
        alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno, respaldo="Doy clases")])
        for p in alm._personas:
            self.assertIsNone(p.aptitud)
            self.assertIsNone(p.revision_respaldo)

    # -- respaldo opcional ---------------------------------------------------
    def test_respaldo_opcional_pendiente_no_bloquea_ni_se_muestra(self):
        b = sin_aptitud(bruno, respaldo="10 años dando clases particulares", revision_respaldo="Pendiente")
        alm, envio, r = self.correr([sin_aptitud(alba), b])
        self.assertEqual((r.matches_nuevos, r.respaldo_no_usado, r.revision_humana_respaldo), (1, 1, 0))
        [f] = alm.filas.values()
        self.assertNotIn("clases particulares", f.notas)
        for c in envio.enviados:
            texto = (c.asunto + c.cuerpo).lower()
            self.assertNotIn("clases particulares", texto)
            self.assertNotIn("10 años", texto)
            self.assertNotIn("verificad", texto)
            self.assertNotIn("respaldo", texto)

    def test_el_modelo_descarta_el_respaldo_y_no_consta_como_revisado(self):
        b = sin_aptitud(bruno, respaldo="Doy clases desde hace años")
        ev = evaluar_participante(b, resolver_zona_real)
        self.assertTrue(ev.apta)
        self.assertEqual(ev.origen_aptitud, "automático")
        self.assertIsNone(ev.participante.respaldo_declarado)
        self.assertIsNone(ev.participante.respaldo_revisado_por)
        self.assertEqual(ev.participante.revision_respaldo, RESPALDO_SIN_VERIFICAR_NO_USADO)
        self.assertNotIn(ev.participante.revision_respaldo, (REVISION_APROBADA, REVISION_NO_REQUERIDA))

    def test_a2_rechaza_el_estado_interno_si_el_respaldo_sigue_en_el_modelo(self):
        from encuentros import a2_match
        from encuentros.modelos import Participante
        p = Participante("x", "X", True, "Apto (automático)", "Doy clases", RESPALDO_SIN_VERIFICAR_NO_USADO)
        self.assertTrue(a2_match.motivos_participante_no_elegible(p))
        p.respaldo_declarado = None
        self.assertEqual(a2_match.motivos_participante_no_elegible(p), [])

    def test_afirmaciones_que_requieren_verificacion_bloquean(self):
        casos = {
            "título en el respaldo": dict(respaldo="Licenciada en Filología Inglesa"),
            "certificado en el respaldo": dict(respaldo="Certificado C1 de inglés"),
            "perfil Titulado sin respaldo": dict(tipo_perfil=("Titulado", "Tutor")),
            "tema que exige acreditación": dict(ofrece="Asesoría legal para inquilinos"),
        }
        for nombre, kw in casos.items():
            with self.subTest(nombre):
                alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno, **kw)])
                self.sin_match(alm, envio)
                self.assertEqual((r.revision_humana_respaldo, r.aptitud_automatica), (1, 1))
                [aviso] = [a for a in r.avisos if "bruno" in a]
                self.assertIn("requiere revisión humana", aviso)
                self.assertNotIn("Filología", aviso)       # el aviso no copia el respaldo

    def test_respaldo_aprobado_por_una_persona_permite_la_afirmacion(self):
        b = sin_aptitud(bruno, respaldo="Licenciada en Filología Inglesa", revision_respaldo="Aprobada")
        alm, envio, r = self.correr([sin_aptitud(alba), b])
        self.assertEqual((r.matches_nuevos, r.revision_humana_respaldo, r.respaldo_no_usado), (1, 0, 0))

    def test_contradicciones_bloquean_y_piden_revision(self):
        casos = {
            "No requerida con respaldo": dict(respaldo="Doy clases", revision_respaldo="No requerida"),
            "Aprobada sin respaldo": dict(respaldo=None, revision_respaldo="Aprobada"),
        }
        for nombre, kw in casos.items():
            with self.subTest(nombre):
                alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno, **kw)])
                self.sin_match(alm, envio)
                self.assertEqual(r.revision_humana_respaldo, 1)

    # -- estados escritos por una persona, autorización y A1 -----------------
    def test_estados_de_bloqueo_escritos_por_una_persona_se_respetan(self):
        for valor in ("Pendiente", "Incompleto", "Sin autorización", "Apto (automático)"):
            with self.subTest(valor):
                alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno, aptitud=valor)])
                self.sin_match(alm, envio)
                self.assertEqual((r.bloqueo_escrito_por_persona, r.aptitud_automatica), (1, 1))

    def test_sin_autorizacion_no_hay_aptitud_automatica(self):
        alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno, autoriza=False)])
        self.sin_match(alm, envio)
        self.assertEqual((r.sin_autorizacion, r.aptitud_automatica), (1, 1))

    def test_datos_incompletos_no_reciben_aptitud_automatica(self):
        alm, envio, r = self.correr([sin_aptitud(alba), sin_aptitud(bruno, correo=None)])
        self.sin_match(alm, envio)
        self.assertEqual((r.a1_con_problemas, r.aptitud_automatica), (1, 1))

    # -- zona horaria con tildes -----------------------------------------------
    def test_zona_con_tildes_equivalente_exacta_se_acepta(self):
        b = sin_aptitud(bruno, zona_horaria="América/Mexico_City")
        alm, envio, r = self.correr([sin_aptitud(alba), b])
        self.assertEqual((r.matches_nuevos, r.a1_con_problemas), (1, 0))
        self.assertIn("participante bruno: zona horaria escrita con tildes: se usa su "
                      "equivalente IANA exacto", r.avisos)
        b_correo = next(c for c in envio.enviados if c.destinatario_id == "bruno")
        self.assertIn("hora de Ciudad de México", b_correo.cuerpo)   # la zona IANA real
        self.assertEqual(alm._personas[1].zona_horaria, "América/Mexico_City")  # Notion intacto

    def test_zona_que_no_coincide_exactamente_pide_aclaracion(self):
        for zona in ("America/Ciudad de México", "Europe/Málaga", "américa/mexico_city"):
            with self.subTest(zona):
                # Sin zona en el texto: así solo se prueba la zona no IANA (no una contradicción).
                b = sin_aptitud(bruno, zona_horaria=zona, disponibilidad="lunes 11:00-13:00")
                alm, envio, r = self.correr([sin_aptitud(alba), b])
                self.sin_match(alm, envio)
                self.assertEqual(r.a1_con_problemas, 1)
                self.assertTrue(any("Zona horaria (no existe en la base IANA; requiere aclaración)" in a
                                    for a in r.avisos))

    # -- reciprocidad y aceptación separada ----------------------------------
    def test_reciprocidad_se_mantiene(self):
        b = sin_aptitud(bruno, ofrece="Cocina vegetariana")       # no es lo que busca Alba
        alm, envio, r = self.correr([sin_aptitud(alba), b])
        self.sin_match(alm, envio)
        self.assertEqual(r.aptitud_automatica, 2)

    def test_tema_incierto_sigue_pidiendo_aclaracion(self):
        a = sin_aptitud(alba, quiere_aprender="inglés básico")
        b = persona("bruno", "Bruno", "Inglés avanzado", "fotografia con movil",
                    "lunes 11:00-13:00; America/Mexico_City", None, aptitud=None, revision_respaldo=None)
        alm, envio, r = self.correr([a, b])
        self.sin_match(alm, envio)
        self.assertEqual(r.pares_por_aclarar, 1)

    def test_cada_persona_debe_aceptar_por_separado(self):
        alm, envio, _ = self.correr([sin_aptitud(alba), sin_aptitud(bruno)])
        codigo = lambda pid: normalizar_codigo(next(   # noqa: E731
            c.cuerpo for c in envio.enviados if c.destinatario_id == pid).split("código personal:")[1])
        alm.responder(codigo("alba"), ACEPTO)
        self.ciclo(alm, envio, LUNES + timedelta(hours=2))
        [f] = alm.filas.values()
        self.assertEqual((f.respuesta_a, f.respuesta_b, f.estado), (ACEPTO, PENDIENTE, ESPERANDO))
        alm.responder(codigo("bruno"), ACEPTO)
        self.ciclo(alm, envio, LUNES + timedelta(hours=3))
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)

    def test_si_deja_de_ser_apta_no_se_confirma(self):
        alm, envio, _ = self.correr([sin_aptitud(alba), sin_aptitud(bruno)])
        codigos = {c.destinatario_id: normalizar_codigo(c.cuerpo.split("código personal:")[1])
                   for c in envio.enviados}
        alm._personas[1].respaldo = "Licenciada en Filología Inglesa"   # ahora requiere revisión
        for pid in ("alba", "bruno"):
            alm.responder(codigos[pid], ACEPTO)
        self.ciclo(alm, envio, LUNES + timedelta(hours=2))
        [f] = alm.filas.values()
        self.assertNotEqual(f.estado, CONFIRMADO)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestSalasJitsi(unittest.TestCase):
    """Salas de Jitsi: de prueba primero, una por pareja, solo tras las dos aceptaciones.
    Nunca se conecta a Jitsi: el enlace es solo texto."""

    def setUp(self):
        self.codigos = (f"C{n:03d}-AAAA".replace("0", "Q").replace("1", "R") for n in itertools.count(100))

    def cfg(self, nueva_sala=None):
        from encuentros.automatico import nueva_sala_jitsi_prueba
        return Configuracion(URL_FORM, CLAVE, generar_codigo=lambda: next(self.codigos),
                             nueva_sala=nueva_sala or nueva_sala_jitsi_prueba)

    def codigo_de(self, envio, pid):
        cuerpos = [c.cuerpo for c in envio.enviados if c.destinatario_id == pid]
        return normalizar_codigo(cuerpos[-1].split("código personal:")[1])

    def dos_parejas(self):
        # Segunda pareja con otros temas: solo es compatible entre sí.
        carla = persona("carla", "Carla", "guitarra", "cocina", "lunes 11:00-13:00", "America/Mexico_City")
        dani = persona("dani", "Dani", "clases de cocina", "guitarras", "lunes 18:00–20:00", "Europe/Madrid")
        return [alba(), bruno(), carla, dani]

    def test_nombre_aleatorio_dificil_de_adivinar(self):
        import re
        from encuentros.automatico import es_enlace_de_prueba, nueva_sala_jitsi, nueva_sala_jitsi_prueba
        p, r = nueva_sala_jitsi_prueba(), nueva_sala_jitsi()
        self.assertRegex(p, r"^https://meet\.jit\.si/AntropiaPRUEBA[0-9a-f]{32}$")
        self.assertRegex(r, r"^https://meet\.jit\.si/Antropia[0-9a-f]{32}$")
        self.assertTrue(es_enlace_de_prueba(p))
        self.assertFalse(es_enlace_de_prueba(r))
        muestras = {nueva_sala_jitsi() for _ in range(1000)}
        self.assertEqual(len(muestras), 1000)
        self.assertTrue(all(re.search(r"[0-9a-f]{32}$", m) for m in muestras))

    def test_variable_antropia_salas(self):
        from encuentros.automatico import nueva_sala_jitsi, nueva_sala_jitsi_prueba, proveedor_de_salas
        self.assertIsNone(proveedor_de_salas(None))
        self.assertIsNone(proveedor_de_salas(""))
        self.assertIs(proveedor_de_salas("jitsi-prueba"), nueva_sala_jitsi_prueba)
        self.assertIs(proveedor_de_salas(" JITSI "), nueva_sala_jitsi)
        with self.assertRaises(ValueError):
            proveedor_de_salas("zoom")

    def test_enlace_solo_despues_de_que_ambas_aceptan(self):
        alm, envio = AlmacenMemoria([alba(), bruno()]), EnvioSimulado()
        cfg = self.cfg()
        Ciclo(alm, envio, cfg, LUNES).ejecutar()
        self.assertFalse(any("meet.jit.si" in c.cuerpo for c in envio.enviados))   # propuestas sin enlace
        alm.responder(self.codigo_de(envio, "alba"), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=1)).ejecutar()
        [f] = alm.filas.values()
        self.assertIsNone(f.enlace)                                 # con una sola aceptación, nada
        self.assertFalse(any("meet.jit.si" in c.cuerpo for c in envio.enviados))
        alm.responder(self.codigo_de(envio, "bruno"), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=2)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)
        self.assertTrue(f.enlace.startswith("https://meet.jit.si/AntropiaPRUEBA"))
        conf = [c for c in envio.enviados if "confirmado" in c.asunto]
        self.assertEqual(sorted(c.destinatario_id for c in conf), ["alba", "bruno"])
        for c in conf:
            self.assertIn(f.enlace, c.cuerpo)
            self.assertIn("Enlace de PRUEBA del piloto", c.cuerpo)
            self.assertIn(b"SUMMARY:[PRUEBA] Encuentro Antropia", c.adjuntos[0][2])

    def test_cada_pareja_tiene_su_propia_sala(self):
        alm, envio = AlmacenMemoria(self.dos_parejas()), EnvioSimulado()
        cfg = self.cfg()
        Ciclo(alm, envio, cfg, LUNES).ejecutar()
        self.assertEqual(len(alm.filas), 2)
        for pid in ("alba", "bruno", "carla", "dani"):
            alm.responder(self.codigo_de(envio, pid), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=1)).ejecutar()
        filas = list(alm.filas.values())
        self.assertTrue(all(f.estado == CONFIRMADO for f in filas))
        self.assertEqual(len({f.enlace for f in filas}), 2)
        # Cada persona recibe solo el enlace de su pareja.
        for f in filas:
            otros = {g.enlace for g in filas if g is not f}
            for c in envio.enviados:
                if c.destinatario_id in (f.a, f.b) and "confirmado" in c.asunto:
                    self.assertIn(f.enlace, c.cuerpo)
                    self.assertFalse(any(o in c.cuerpo for o in otros))

    def test_si_el_generador_repite_un_enlace_se_pide_otro(self):
        repetidos = iter(["https://meet.jit.si/AntropiaPRUEBAigual", "https://meet.jit.si/AntropiaPRUEBAigual",
                          "https://meet.jit.si/AntropiaPRUEBAotra"])
        alm, envio = AlmacenMemoria(self.dos_parejas()), EnvioSimulado()
        cfg = self.cfg(nueva_sala=lambda: next(repetidos))
        Ciclo(alm, envio, cfg, LUNES).ejecutar()
        for pid in ("alba", "bruno", "carla", "dani"):
            alm.responder(self.codigo_de(envio, pid), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=1)).ejecutar()
        self.assertEqual({f.enlace for f in alm.filas.values()},
                         {"https://meet.jit.si/AntropiaPRUEBAigual", "https://meet.jit.si/AntropiaPRUEBAotra"})


class TestCodigos(unittest.TestCase):
    def test_normalizar(self):
        self.assertEqual(normalizar_codigo(" abcd efgh "), "ABCD-EFGH")
        self.assertEqual(normalizar_codigo("Mi código: ABCD-EFGH"), "ABCD-EFGH")
        self.assertIsNone(normalizar_codigo("ABC"))

    def test_huella_depende_de_la_clave(self):
        self.assertNotEqual(huella("ABCD-EFGH", "a" * 32), huella("ABCD-EFGH", "b" * 32))


if __name__ == "__main__":
    unittest.main()

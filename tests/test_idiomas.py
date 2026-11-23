"""«Idioma» y «Otro idioma» (etapas 0 y 3): formato anterior y nuevo. Datos ficticios."""
import unittest

from encuentros.a2_match import evaluar_par
from encuentros.automatico import MODALIDAD_NO_VIRTUAL, a_modelo, evaluar_participante
from encuentros.correo import EnvioSimulado
from encuentros.idiomas import (
    FALTA, PENDIENTE_FORMATO, PENDIENTE_OTRO, PENDIENTE_OTRO_ILEGIBLE, PENDIENTE_OTRO_SIN_OPCION,
    idiomas_comunes, interpretar_idioma, leer_otro_idioma,
)
from encuentros.notion_api import AlmacenNotion, ClienteNotion
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import LUNES, AlmacenMemoria, alba, bruno
from tests.test_notion_api import FILA_PARTICIPANTE, HttpFalso


def multi(*nombres):
    return {"type": "multi_select", "multi_select": [{"name": n} for n in nombres]}


class TestInterpretarIdioma(unittest.TestCase):
    def test_formato_anterior_texto(self):
        r = interpretar_idioma("Español")
        self.assertEqual((r.idiomas, r.idioma, r.problema), (("Español",), "Español", None))
        self.assertEqual(interpretar_idioma("  Inglés ").idiomas, ("Inglés",))

    def test_formato_nuevo_uno_o_varios(self):
        self.assertEqual(interpretar_idioma(["Portugués"]).idiomas, ("Portugués",))
        r = interpretar_idioma(["Español", "Inglés", "Portugués"])
        self.assertEqual((r.idiomas, r.idioma, r.problema),
                         (("Español", "Inglés", "Portugués"), "Español, Inglés, Portugués", None))
        self.assertEqual(interpretar_idioma([{"name": "Español"}]).idiomas, ("Español",))

    def test_repetidos_y_vacios_no_cuentan(self):
        self.assertEqual(interpretar_idioma(["Español", " español ", ""]).idiomas, ("Español",))

    def test_vacio_es_falta(self):
        for v in (None, "", "   ", [], [""]):
            r = interpretar_idioma(v)
            self.assertEqual((r.idioma, r.problema), (None, FALTA), v)

    def test_otro_con_otro_idioma(self):
        r = interpretar_idioma(["Español", "Otro"], "Francés")
        self.assertEqual((r.idiomas, r.problema), (("Español", "Francés"), None))
        r = interpretar_idioma(["Otro"], "Francés, alemán y lengua de señas")
        self.assertEqual(r.idiomas, ("Francés", "alemán", "lengua de señas"))
        # «Otro idioma» repite una opción: no se duplica.
        self.assertEqual(interpretar_idioma(["Inglés", "Otro"], "ingles").idiomas, ("Inglés",))

    def test_otro_sin_otro_idioma_queda_pendiente(self):
        for v, otro in ((["Otro"], None), (["Español", "Otro"], "  "), ("otro", None)):
            r = interpretar_idioma(v, otro)
            self.assertEqual((r.idioma, r.problema), (None, PENDIENTE_OTRO), v)

    def test_otro_idioma_ilegible_queda_pendiente(self):
        for otro in ("123", "francés (un poco)", "x" * 50, "alemán; B2"):
            r = interpretar_idioma(["Otro"], otro)
            self.assertEqual((r.idioma, r.problema), (None, PENDIENTE_OTRO_ILEGIBLE), otro)

    def test_otro_idioma_sin_elegir_otro_pide_aclaracion(self):
        for otro in ("Francés", "123"):
            r = interpretar_idioma(["Español"], otro)
            self.assertEqual((r.idioma, r.problema), (None, PENDIENTE_OTRO_SIN_OPCION), otro)

    def test_formato_desconocido_queda_pendiente(self):
        for v in (42, {"name": "Español"}, [None], [3]):
            r = interpretar_idioma(v)
            self.assertEqual((r.idioma, r.problema), (None, PENDIENTE_FORMATO), v)

    def test_leer_otro_idioma(self):
        self.assertEqual(leer_otro_idioma(None), ())
        self.assertEqual(leer_otro_idioma("Catalán / Euskera"), ("Catalán", "Euskera"))
        self.assertIsNone(leer_otro_idioma("¿?"))

    def test_idiomas_comunes_sin_tildes_ni_mayusculas(self):
        self.assertEqual(idiomas_comunes(("Español", "Inglés"), ("ingles", "Portugués")), ("Inglés",))
        self.assertEqual(idiomas_comunes(("Inglés",), ("English",)), ())       # no se traduce


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestAptitudConIdioma(unittest.TestCase):
    def evaluar(self, idioma, otro=None, **kw):
        return evaluar_participante(alba(idioma=idioma, otro_idioma=otro, **kw), resolver_zona_real)

    def test_formatos_validos_son_aptos(self):
        for v, otro in (("Español", None), (["Español"], None), (["Español", "Inglés"], None),
                        (["Otro"], "Francés")):
            self.assertTrue(self.evaluar(v, otro).apta, (v, otro))

    def test_casos_dudosos_no_pasan_automaticamente(self):
        for v, otro, problema in ((["Español", "Otro"], None, PENDIENTE_OTRO),
                                  (["Otro"], "123", PENDIENTE_OTRO_ILEGIBLE),
                                  (["Español"], "Francés", PENDIENTE_OTRO_SIN_OPCION),
                                  ([], None, FALTA), (None, None, FALTA)):
            ev = self.evaluar(v, otro)
            self.assertFalse(ev.apta, v)
            self.assertIn(problema, ev.a1_problemas)
            self.assertIsNone(ev.solicitud.idioma)

    def test_solo_modalidad_virtual(self):
        self.assertTrue(self.evaluar("Español", modalidad="Virtual").apta)
        self.assertTrue(self.evaluar("Español", modalidad=" virtual ").apta)
        for m in ("Mixta", "Presencial", "Otra"):
            ev = self.evaluar("Español", modalidad=m)
            self.assertFalse(ev.apta, m)
            self.assertIn(MODALIDAD_NO_VIRTUAL, ev.a1_problemas)
        self.assertIn("Modalidad", self.evaluar("Español", modalidad=None).a1_problemas)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestParPorIdioma(unittest.TestCase):
    def par(self, idioma_a, idioma_b, otro_a=None, otro_b=None):
        pa, sa, _ = a_modelo(alba(idioma=idioma_a, otro_idioma=otro_a))
        pb, sb, _ = a_modelo(bruno(idioma=idioma_b, otro_idioma=otro_b))
        return evaluar_par(pa, sa, pb, sb, LUNES, resolver_zona_real)

    def test_un_idioma_en_comun_basta(self):
        ev = self.par(["Español", "Inglés", "Portugués"], ["Inglés"])
        self.assertEqual(ev.resultado, "Propuesta")
        self.assertEqual(ev.evidencia["idiomas_comunes"], ["Inglés"])

    def test_formato_anterior_con_lista(self):
        ev = self.par("Español", ["Portugués", "Español"])
        self.assertEqual((ev.resultado, ev.evidencia["idiomas_comunes"]), ("Propuesta", ["Español"]))

    def test_otro_idioma_cuenta(self):
        ev = self.par(["Otro"], ["Español", "Otro"], "Francés", "francés")
        self.assertEqual((ev.resultado, ev.evidencia["idiomas_comunes"]), ("Propuesta", ["Francés"]))

    def test_sin_idioma_comun(self):
        ev = self.par(["Español"], ["Inglés", "Portugués"])
        self.assertEqual(ev.resultado, "Sin coincidencia")
        self.assertTrue(any("sin idioma común" in m for m in ev.motivos))


class TestLecturaDesdeNotion(unittest.TestCase):
    def leer(self, idioma_prop):
        fila = {**FILA_PARTICIPANTE, "properties": {**FILA_PARTICIPANTE["properties"], "Idioma": idioma_prop}}
        http = HttpFalso([{"results": [fila], "has_more": False}])
        [p] = AlmacenNotion(ClienteNotion("token-ficticio", abrir=http)).personas()
        return p

    def test_seleccion_multiple_se_lee_como_lista(self):
        self.assertEqual(self.leer(multi("Español")).idioma, ["Español"])
        self.assertEqual(self.leer(multi("Español", "Otro")).idioma, ["Español", "Otro"])

    def test_seleccion_unica_sigue_funcionando(self):
        self.assertEqual(self.leer({"type": "select", "select": {"name": "Español"}}).idioma, "Español")

    @unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
    def test_lista_leida_de_notion_no_rompe_la_evaluacion(self):
        p = self.leer(multi("Español", "Inglés"))
        self.assertTrue(evaluar_participante(p, resolver_zona_real).apta)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestCicloConIdiomas(unittest.TestCase):
    """El ciclo completo con envío SIMULADO: ningún correo sale del proceso."""

    def ejecutar(self, personas):
        t = ta.TestCicloAutomatico()
        t.setUp()
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        t.ciclo(alm, envio)
        return alm, envio

    def test_idioma_comun_hace_match(self):
        for a, b in ((["Español"], "Español"), (["Español", "Inglés", "Portugués"], ["Portugués"])):
            alm, envio = self.ejecutar([alba(idioma=a), bruno(idioma=b)])
            self.assertEqual((len(alm.filas), len(envio.enviados)), (1, 2), (a, b))

    def test_sin_idioma_comun_o_dudoso_no_crea_match_ni_correos(self):
        for a, otro in ((["Inglés"], None), (["Español", "Otro"], None), ([], None)):
            alm, envio = self.ejecutar([alba(idioma=a, otro_idioma=otro), bruno(idioma=["Español"])])
            self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0), a)


if __name__ == "__main__":
    unittest.main()

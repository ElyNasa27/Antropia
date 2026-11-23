"""Etapa 5: zona horaria de cada participante. Datos ficticios.

«Zona horaria seleccionada» primero; si falta, la zona del formato anterior, solo si
es una zona IANA válida. Datos contradictorios -> pendiente de aclaración.
"""
import unittest

from encuentros import zona_participante as zp
from encuentros.automatico import evaluar_participante
from encuentros.correo import EnvioSimulado
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import INICIO, AlmacenMemoria, alba, bruno


class TestElegirZona(unittest.TestCase):
    def test_solo_seleccion(self):
        z = zp.elegir_zona("America/Costa_Rica")
        self.assertEqual((z.zona, z.origen, z.problema), ("America/Costa_Rica", zp.ORIGEN_SELECCION, None))

    def test_seleccion_y_texto_anterior_coinciden(self):
        z = zp.elegir_zona(" America/Costa_Rica ", None, "America/Costa_Rica")
        self.assertEqual((z.zona, z.problema), ("America/Costa_Rica", None))

    def test_seleccion_y_texto_anterior_distintos_piden_aclaracion(self):
        for anterior, texto in (("Europe/Madrid", None), (None, "Europe/Madrid"),
                                ("America/Costa_Rica", "Europe/Madrid")):
            z = zp.elegir_zona("America/Costa_Rica", anterior, texto)
            self.assertEqual((z.zona, z.problema), (None, zp.CONTRADICTORIA), (anterior, texto))

    def test_sin_seleccion_usa_el_formato_anterior(self):
        self.assertEqual(zp.elegir_zona(None, "Europe/Madrid").zona, "Europe/Madrid")
        self.assertEqual(zp.elegir_zona("", None, "America/Mexico_City").origen, zp.ORIGEN_ANTERIOR)

    def test_sin_seleccion_y_formato_anterior_contradictorio(self):
        z = zp.elegir_zona(None, "Europe/Madrid", "America/Mexico_City")
        self.assertEqual((z.zona, z.problema), (None, zp.CONTRADICTORIA))

    def test_nada(self):
        for v in (None, "", "   "):
            self.assertEqual(zp.elegir_zona(v).problema, zp.FALTA)

    def test_solo_tildes_si_el_resultado_es_iana_exacto(self):
        z = zp.elegir_zona(None, "America/Bogotá")
        self.assertEqual((z.zona, z.avisos), ("America/Bogota", (zp.AVISO_TILDES,)))
        # Con tildes y sin tildes es la misma zona: no es una contradicción.
        self.assertIsNone(zp.elegir_zona("America/Bogota", "America/Bogotá").problema)

    def test_no_corrige_nada_mas(self):
        for v in ("america/costa_rica", "America/Costa Rica", "Costa Rica", "UTC-6"):
            self.assertEqual(zp.elegir_zona(v).zona, v)          # se usa tal cual: A1 la rechaza


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestA1ConZona(unittest.TestCase):
    def evaluar(self, **kw):
        return evaluar_participante(alba(**kw), resolver_zona_real)

    def test_seleccion_valida_es_apta(self):
        ev = self.evaluar(zona_horaria=None, zona_horaria_seleccionada="Europe/Madrid")
        self.assertTrue(ev.apta)
        self.assertEqual(ev.solicitud.zona_horaria, "Europe/Madrid")

    def test_seleccion_no_iana_queda_pendiente(self):
        for v in ("Europe/Atlantida", "america/costa_rica", "UTC-6"):
            ev = self.evaluar(zona_horaria=None, zona_horaria_seleccionada=v)
            self.assertFalse(ev.apta)
            self.assertIn(zp.NO_IANA, ev.a1_problemas, v)

    def test_seleccion_no_valida_no_recurre_al_texto(self):
        # La selección no es válida y el texto da otra zona: se pide aclaración, no se elige.
        ev = self.evaluar(zona_horaria=None, zona_horaria_seleccionada="Europe/Atlantida",
                          disponibilidad="lunes 18:00–20:00; Europe/Madrid")
        self.assertFalse(ev.apta)
        self.assertIn(zp.CONTRADICTORIA, ev.a1_problemas)

    def test_sin_seleccion_texto_anterior_valido(self):
        ev = self.evaluar(zona_horaria=None, disponibilidad="lunes 18:00–20:00; Europe/Madrid")
        self.assertTrue(ev.apta)
        self.assertEqual(ev.solicitud.zona_horaria, "Europe/Madrid")

    def test_sin_seleccion_texto_anterior_no_valido(self):
        ev = self.evaluar(zona_horaria="Mars/Olympus_Mons")
        self.assertFalse(ev.apta)
        self.assertIn(zp.NO_IANA, ev.a1_problemas)

    def test_contradiccion_no_es_apta(self):
        ev = self.evaluar(zona_horaria_seleccionada="America/Costa_Rica")   # alba: Europe/Madrid
        self.assertFalse(ev.apta)
        self.assertIn(zp.CONTRADICTORIA, ev.a1_problemas)
        self.assertIsNone(ev.solicitud.zona_horaria)

    def test_sin_ninguna_zona(self):
        ev = self.evaluar(zona_horaria=None)
        self.assertIn(zp.FALTA, ev.a1_problemas)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestCicloConZona(unittest.TestCase):
    """Ciclo completo con envío SIMULADO: ningún correo sale del proceso."""

    def ciclo(self, personas):
        prueba = ta.TestCicloAutomatico()
        prueba.setUp()
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        return alm, envio, prueba.ciclo(alm, envio)

    def test_seleccion_nueva_y_texto_anterior_hacen_match(self):
        alm, envio, _ = self.ciclo([alba(zona_horaria=None, zona_horaria_seleccionada="Europe/Madrid"),
                                    bruno()])               # bruno: zona en el texto anterior
        [f] = alm.filas.values()
        self.assertEqual(f.inicio_utc, INICIO)
        a = next(c for c in envio.enviados if c.destinatario_id == "alba")
        self.assertIn("18:00–19:00 (hora de Madrid)", a.cuerpo)

    def test_contradiccion_no_crea_match_ni_correos(self):
        alm, envio, r = self.ciclo([alba(zona_horaria_seleccionada="America/Costa_Rica"), bruno()])
        self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0))
        self.assertTrue(any(zp.CONTRADICTORIA in a for a in r.avisos))
        self.assertFalse(any("Costa_Rica" in a or "Madrid" in a for a in r.avisos))


if __name__ == "__main__":
    unittest.main()

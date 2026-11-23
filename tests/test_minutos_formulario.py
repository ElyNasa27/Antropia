"""Etapa 7: «Minutos seleccionados» y «Minutos disponibles». Datos ficticios."""
import unittest

from encuentros import minutos_formulario as mf
from encuentros.automatico import evaluar_participante
from encuentros.correo import EnvioSimulado
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import AlmacenMemoria, alba, bruno


class TestElegirMinutos(unittest.TestCase):
    def test_cada_etiqueta_del_formulario(self):
        for m in (15, 30, 45, 60, 90, 120):
            r = mf.elegir_minutos(f"{m} minutos", None)
            self.assertEqual((r.minutos, r.origen, r.problema), (m, mf.ORIGEN_SELECCION, None))

    def test_etiqueta_y_numero_iguales(self):
        self.assertEqual(mf.elegir_minutos("45 minutos", 45).minutos, 45)
        self.assertEqual(mf.elegir_minutos("45 minutos", 45.0).minutos, 45)

    def test_etiqueta_y_numero_distintos_piden_aclaracion(self):
        for n in (30, 50, 0, -5, 45.5, "45"):
            r = mf.elegir_minutos("45 minutos", n)
            self.assertEqual((r.minutos, r.problema), (None, mf.CONTRADICTORIOS), n)

    def test_otro_usa_minutos_disponibles(self):
        r = mf.elegir_minutos("Otro", 25)
        self.assertEqual((r.minutos, r.origen, r.problema), (25, mf.ORIGEN_OTRO, None))
        self.assertEqual(mf.elegir_minutos(" otro ", 200.0).minutos, 200)

    def test_otro_sin_numero(self):
        for n in (None, "", "  "):
            self.assertEqual(mf.elegir_minutos("Otro", n).problema, mf.OTRO_SIN_NUMERO, n)

    def test_otro_con_numero_no_valido(self):
        for n in (0, -10, 12.5, "veinte", True):
            r = mf.elegir_minutos("Otro", n)
            self.assertEqual((r.minutos, r.problema), (None, mf.NO_VALIDO), n)

    def test_etiqueta_desconocida_no_se_adivina(self):
        for etiqueta in ("25 minutos", "30 min", "30", "media hora", "1 hora"):
            r = mf.elegir_minutos(etiqueta, 30)
            self.assertEqual((r.minutos, r.problema), (None, mf.OPCION_DESCONOCIDA), etiqueta)

    def test_formato_anterior_sin_seleccion(self):
        r = mf.elegir_minutos(None, 30)
        self.assertEqual((r.minutos, r.origen), (30, mf.ORIGEN_ANTERIOR))
        self.assertEqual(mf.elegir_minutos("", 60.0).minutos, 60)
        self.assertEqual(mf.elegir_minutos(None, None).problema, mf.FALTA)
        self.assertEqual(mf.elegir_minutos(None, 0).problema, mf.NO_VALIDO)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestMinutosEnElCiclo(unittest.TestCase):
    def ciclo(self, personas):
        prueba = ta.TestCicloAutomatico()
        prueba.setUp()
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        return alm, envio, prueba.ciclo(alm, envio)

    def test_seleccion_nueva_y_formato_anterior(self):
        alm, envio, _ = self.ciclo([alba(minutos=None, minutos_seleccionados="30 minutos"), bruno()])
        [f] = alm.filas.values()
        self.assertEqual((f.minutos_a, f.minutos_b), (30, 30))
        a = next(c for c in envio.enviados if c.destinatario_id == "alba")
        self.assertIn("30 min enseñas tú · 30 min enseña Bruno · duración total: 60 min", a.cuerpo)

    def test_otro_con_numero(self):
        alm, _, _ = self.ciclo([alba(minutos=40, minutos_seleccionados="Otro"), bruno(minutos=20)])
        [f] = alm.filas.values()
        self.assertEqual((f.minutos_a, f.minutos_b), (40, 20))

    def test_dudas_no_crean_match_ni_correos(self):
        for sel, n in (("45 minutos", 30), ("Otro", None), ("25 minutos", None)):
            alm, envio, r = self.ciclo([alba(minutos=n, minutos_seleccionados=sel), bruno()])
            self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0), sel)
            self.assertEqual(r.a1_con_problemas, 1)

    def test_a1_marca_el_motivo(self):
        ev = evaluar_participante(alba(minutos=30, minutos_seleccionados="45 minutos"), resolver_zona_real)
        self.assertFalse(ev.apta)
        self.assertIn(mf.CONTRADICTORIOS, ev.a1_problemas)


if __name__ == "__main__":
    unittest.main()

"""Etapa 4: un tema por línea, como máximo 7 por pregunta. Datos ficticios."""
import dataclasses
import unittest

from encuentros.automatico import a_modelo, evaluar_participante
from encuentros.correo import EnvioSimulado
from encuentros.temas_formulario import MAX_TEMAS, leer_temas_formulario, problema_demasiados
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import AlmacenMemoria, bruno
from tests.test_automatico import alba as _alba

def alba(**kw):
    """alba() ficticia permitiendo cambiar «Ofrece» y «Quiere aprender»."""
    return dataclasses.replace(_alba(), **kw)


SIETE = "\n".join(f"Tema ficticio {i}" for i in range(1, 8))
OCHO = SIETE + "\nTema ficticio 8"


class TestLeerTemas(unittest.TestCase):
    def test_un_tema_por_linea(self):
        self.assertEqual(leer_temas_formulario("Fotografía con móvil\nExcel básico\n"),
                         (["Fotografía con móvil", "Excel básico"], False))

    def test_cada_linea_es_un_tema_aunque_tenga_comas_o_y(self):
        self.assertEqual(leer_temas_formulario("Diseño y fotografía\nExcel, Word")[0],
                         ["Diseño y fotografía", "Excel, Word"])

    def test_una_sola_linea_usa_la_separacion_anterior(self):
        self.assertEqual(leer_temas_formulario("Fotografía, Excel y Word")[0], ["Fotografía", "Excel", "Word"])
        self.assertEqual(leer_temas_formulario("Inglés conversacional")[0], ["Inglés conversacional"])

    def test_lineas_vacias_espacios_y_repetidos(self):
        self.assertEqual(leer_temas_formulario("\n  Guitarra  \n\n guitarra\nGUITARRA.\nCanto\r\n")[0],
                         ["Guitarra", "Canto"])

    def test_vacio(self):
        for v in (None, "", "  \n \n"):
            self.assertEqual(leer_temas_formulario(v), ([], False))

    def test_siete_si_ocho_no_y_no_se_descarta_ninguno(self):
        self.assertEqual(leer_temas_formulario(SIETE), ([f"Tema ficticio {i}" for i in range(1, 8)], False))
        temas, demasiados = leer_temas_formulario(OCHO)
        self.assertTrue(demasiados)
        self.assertEqual(len(temas), 8)                    # se devuelven todos
        self.assertEqual(MAX_TEMAS, 7)

    def test_repetidos_no_cuentan_para_el_limite(self):
        self.assertFalse(leer_temas_formulario(SIETE + "\ntema ficticio 1")[1])

    def test_formato_anterior_con_mas_de_siete(self):
        self.assertTrue(leer_temas_formulario("a1, b2, c3, d4, e5, f6, g7, h8")[1])


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestTemasEnA1(unittest.TestCase):
    def test_mas_de_siete_bloquea_el_perfil(self):
        for campo, pregunta in (("ofrece", "Ofrece"), ("quiere_aprender", "Quiere aprender")):
            ev = evaluar_participante(alba(**{campo: OCHO}), resolver_zona_real)
            self.assertFalse(ev.apta, campo)
            self.assertIn(problema_demasiados(pregunta), ev.a1_problemas)

    def test_con_demasiados_no_se_usa_ninguno(self):
        _, sol, _ = a_modelo(alba(ofrece=OCHO))
        self.assertEqual(sol.tema_ofrece, [])

    def test_siete_temas_es_apto(self):
        self.assertTrue(evaluar_participante(alba(ofrece="Fotografía con móvil\n" + "\n".join(
            f"Tema ficticio {i}" for i in range(1, 7))), resolver_zona_real).apta)

    def test_vacio_sigue_siendo_falta(self):
        ev = evaluar_participante(alba(ofrece="  \n "), resolver_zona_real)
        self.assertIn("Ofrece", ev.a1_problemas)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestTemasEnElCiclo(unittest.TestCase):
    def ciclo(self, personas):
        prueba = ta.TestCicloAutomatico()
        prueba.setUp()
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        return alm, envio, prueba.ciclo(alm, envio)

    def test_temas_por_linea_hacen_match(self):
        alm, envio, _ = self.ciclo([
            alba(ofrece="Cerámica\nFotografía con móvil", quiere_aprender="Jardinería\nInglés conversacional"),
            bruno()])
        [f] = alm.filas.values()
        self.assertEqual(len(envio.enviados), 2)
        self.assertTrue(any("Fotografía con móvil" in t for t in f.a_ensena))

    def test_mas_de_siete_no_crea_match_ni_correos(self):
        alm, envio, r = self.ciclo([alba(ofrece=OCHO + "\nFotografía con móvil"), bruno()])
        self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0))
        self.assertTrue(any(problema_demasiados("Ofrece") in a for a in r.avisos))
        self.assertFalse(any("Tema ficticio" in a for a in r.avisos))     # no muestra los temas


if __name__ == "__main__":
    unittest.main()

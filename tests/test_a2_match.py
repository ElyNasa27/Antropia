"""A2: reciprocidad, idioma, modalidad (incluida Mixta) y horario común."""
import unittest
from datetime import time

from encuentros.modelos import DecisionHumana, Franja
from tests.apoyo import DESDE, nuevo_escenario


def _resumen(coord, sid="sol-alba"):
    return coord.repo.ejecuciones_a2["e1"].por_solicitud[sid]


class TestA2Match(unittest.TestCase):
    def test_propone_match_reciproco_con_evidencia(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual((m.solicitud_origen, m.solicitud_candidata), ("sol-alba", "sol-bruno"))
        self.assertEqual((m.participante_a, m.participante_b), ("alba", "bruno"))
        self.assertEqual(m.a_ensena, ["fotografía con móvil"])
        self.assertEqual(m.b_ensena, ["inglés conversacional"])
        self.assertEqual(m.decision, DecisionHumana.PENDIENTE)
        self.assertEqual(m.clave_ejecucion, "e1")
        e = m.evidencia
        self.assertEqual(e["idioma"], "Español")
        self.assertEqual(e["modalidad"], "videollamada")
        self.assertEqual(e["horario_comun_utc"], "2026-11-30T17:00:00+00:00")
        self.assertEqual(e["duracion_propuesta_min"], 60)
        self.assertFalse(m.es_valida)   # nadie ha revisado aún la evidencia

    def test_no_propone_el_mismo_par_dos_veces(self):
        coord = nuevo_escenario()
        coord.proponer_matches(DESDE, "e1")
        self.assertEqual(coord.proponer_matches(DESDE, "e2").propuestas, [])


class TestCriteriosDelPar(unittest.TestCase):
    def _resultado(self, modificar):
        coord = nuevo_escenario(modificar=modificar)
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        return res.por_solicitud["sol-alba"]

    def test_sin_reciprocidad(self):
        def otra_cosa(ps, ss):
            ss["sol-bruno"].tema_busca = ["cocina"]
        r = self._resultado(otra_cosa)
        self.assertEqual(r.resultado, "Sin coincidencia")
        self.assertIn("sin reciprocidad", r.sin_coincidencia["sol-bruno"])

    def test_sin_idioma_comun(self):
        def idioma(ps, ss):
            ss["sol-bruno"].idioma = "Inglés"
        r = self._resultado(idioma)
        self.assertTrue(any("sin idioma común" in x for x in r.sin_coincidencia["sol-bruno"]))

    def test_idioma_faltante_bloquea(self):
        def sin_idioma(ps, ss):
            ss["sol-bruno"].idioma = None
        r = self._resultado(sin_idioma)
        self.assertEqual(r.resultado, "Bloqueada")
        self.assertIn("Bruno: idioma de la solicitud", r.bloqueadas["sol-bruno"])

    def test_presencial_no_es_compatible(self):
        def presencial(ps, ss):
            ss["sol-bruno"].modalidad = "Presencial"
        r = self._resultado(presencial)
        self.assertTrue(any("Presencial no compatible" in x for x in r.sin_coincidencia["sol-bruno"]))

    def test_mixta_sin_aclaracion_pide_aclaracion(self):
        def mixta(ps, ss):
            ss["sol-bruno"].modalidad = "Mixta"
        r = self._resultado(mixta)
        self.assertEqual(r.resultado, "Bloqueada")
        self.assertTrue(any("requiere aclaración" in x for x in r.bloqueadas["sol-bruno"]))

    def test_mixta_que_rechaza_lo_virtual(self):
        def mixta_no(ps, ss):
            ss["sol-bruno"].modalidad = "Mixta"
            ss["sol-bruno"].acepta_virtual = False
        r = self._resultado(mixta_no)
        self.assertEqual(r.resultado, "Sin coincidencia")

    def test_mixta_que_acepta_lo_virtual_si_es_compatible(self):
        def mixta_si(ps, ss):
            ss["sol-bruno"].modalidad = "Mixta"
            ss["sol-bruno"].acepta_virtual = True
        coord = nuevo_escenario(modificar=mixta_si)
        self.assertEqual(len(coord.proponer_matches(DESDE, "e1").propuestas), 1)

    def test_mixta_con_aclaracion_ambigua_no_se_supone(self):
        def ambigua(ps, ss):
            ss["sol-bruno"].modalidad = "Mixta"
            ss["sol-bruno"].acepta_virtual = "quizá"
        r = self._resultado(ambigua)
        self.assertEqual(r.resultado, "Bloqueada")

    def test_sin_horario_comun(self):
        def solo_viernes(ps, ss):
            ss["sol-bruno"].disponibilidad = [Franja("viernes", time(9), time(10))]
        r = self._resultado(solo_viernes)
        self.assertTrue(any("sin horario común" in x for x in r.sin_coincidencia["sol-bruno"]))

    def test_horario_comun_demasiado_corto(self):
        def corto(ps, ss):   # se solapan 30 min, hacen falta 60
            ss["sol-alba"].disponibilidad = [Franja("lunes", time(18), time(18, 30))]
        r = self._resultado(corto)
        self.assertTrue(any("sin horario común de 60 min" in x for x in r.sin_coincidencia["sol-bruno"]))

    def test_zona_faltante_bloquea(self):
        def sin_zona(ps, ss):
            ss["sol-bruno"].zona_horaria = None
        r = self._resultado(sin_zona)
        self.assertEqual(r.resultado, "Bloqueada")
        self.assertIn("Bruno: zona horaria", r.bloqueadas["sol-bruno"])

    def test_solicitud_no_lista_se_excluye(self):
        def nueva(ps, ss):
            ss["sol-bruno"].estado = "Nueva"
        coord = nuevo_escenario(modificar=nueva)
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        self.assertIn("solicitud no Lista (estado: Nueva)", res.excluidas["sol-bruno"])


if __name__ == "__main__":
    unittest.main()

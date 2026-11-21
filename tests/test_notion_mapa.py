"""La correspondencia con Notion usa solo valores que existen en las bases leídas."""
import unittest

from encuentros import a2_match
from encuentros.modelos import REVISIONES_RESPALDO, DecisionHumana, EstadoPacto
from encuentros.notion_mapa import ESTADO_PACTO_A_NOTION, OPCIONES, SIN_COLUMNA_EN_NOTION


class TestMapaNotion(unittest.TestCase):
    def test_todos_los_estados_del_pacto_tienen_equivalente_valido(self):
        self.assertEqual(set(ESTADO_PACTO_A_NOTION), set(EstadoPacto))
        for valor in ESTADO_PACTO_A_NOTION.values():
            self.assertIn(valor, OPCIONES["Pactos.Estado"])

    def test_decision_humana_coincide_con_propuestas(self):
        self.assertEqual({d.value for d in DecisionHumana}, set(OPCIONES["Propuestas.Decisión humana"]))

    def test_revision_del_respaldo_coincide_con_participantes(self):
        self.assertEqual(set(REVISIONES_RESPALDO), set(OPCIONES["Participantes.Revisión humana del respaldo"]))

    def test_resultados_de_a2_coinciden_con_propuestas(self):
        self.assertEqual({a2_match.PROPUESTA, a2_match.SIN_COINCIDENCIA, a2_match.BLOQUEADA},
                         set(OPCIONES["Propuestas.Resultado"]))

    def test_requisitos_existen_como_opciones(self):
        self.assertIn("Apto", OPCIONES["Participantes.Aptitud"])
        self.assertIn("Lista", OPCIONES["Solicitudes.Estado"])

    def test_carencias_documentadas(self):
        self.assertTrue(any("enlace de la videollamada" in x for x in SIN_COLUMNA_EN_NOTION))


if __name__ == "__main__":
    unittest.main()

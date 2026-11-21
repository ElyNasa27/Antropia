"""Dos revisiones humanas SEPARADAS:
  1. Respaldo declarado por el participante («Revisión humana del respaldo»).
  2. Evidencia de la propuesta de match («Decisión humana» en Propuestas).
"""
import unittest

from encuentros.modelos import (
    REVISION_APROBADA, REVISION_NO_REQUERIDA, REVISION_PENDIENTE, DecisionHumana, OperacionNoPermitida,
)
from tests.apoyo import DESDE, REVISORA, nuevo_escenario


class TestRevisionDelRespaldoDeclarado(unittest.TestCase):
    def test_respaldo_pendiente_excluye_de_a2(self):
        coord = nuevo_escenario(revisar_respaldos=False)
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        self.assertIn("respaldo declarado pendiente de revisión humana", res.excluidas["sol-alba"])

    def test_la_aprobacion_no_puede_venir_en_los_datos_de_la_persona(self):
        def autoaprobado(ps, ss):
            ps["alba"].revision_respaldo = REVISION_APROBADA
            ps["alba"].respaldo_revisado_por = "Alba"
        coord = nuevo_escenario(modificar=autoaprobado, revisar_respaldos=False)
        self.assertEqual(coord.repo.participante("alba").revision_respaldo, REVISION_PENDIENTE)
        self.assertIsNone(coord.repo.participante("alba").respaldo_revisado_por)

    def test_no_requerida_con_respaldo_declarado_se_rechaza(self):
        coord = nuevo_escenario(revisar_respaldos=False)
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_respaldo_declarado("alba", REVISORA, REVISION_NO_REQUERIDA)
        self.assertEqual(coord.repo.participante("alba").revision_respaldo, REVISION_PENDIENTE)

    def test_no_requerida_sin_respaldo_permite_continuar_sin_aprobar(self):
        def sin_respaldo(ps, ss):
            ps["alba"].respaldo_declarado = ""
        coord = nuevo_escenario(modificar=sin_respaldo)
        p = coord.repo.participante("alba")
        self.assertEqual(p.revision_respaldo, REVISION_NO_REQUERIDA)   # no es «Aprobada»
        self.assertEqual(len(coord.proponer_matches(DESDE, "e1").propuestas), 1)

    def test_aprobar_sin_respaldo_declarado_se_rechaza(self):
        def sin_respaldo(ps, ss):
            ps["alba"].respaldo_declarado = None
        coord = nuevo_escenario(modificar=sin_respaldo, revisar_respaldos=False)
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_respaldo_declarado("alba", REVISORA, REVISION_APROBADA)

    def test_contradiccion_detectada_pide_revision_humana(self):
        coord = nuevo_escenario()
        coord.repo.participante("alba").revision_respaldo = REVISION_NO_REQUERIDA  # con respaldo declarado
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        self.assertTrue(any("contradicción" in x for x in res.excluidas["sol-alba"]))

    def test_aprobada_sin_persona_revisora_no_vale(self):
        coord = nuevo_escenario()
        coord.repo.participante("bruno").respaldo_revisado_por = None
        res = coord.proponer_matches(DESDE, "e1")
        self.assertTrue(any("sin persona revisora" in x for x in res.excluidas["sol-bruno"]))

    def test_un_agente_no_revisa_el_respaldo(self):
        coord = nuevo_escenario(revisar_respaldos=False)
        for agente in ("A2", "a3", "", None):
            with self.assertRaises(OperacionNoPermitida):
                coord.revisar_respaldo_declarado("alba", agente, REVISION_APROBADA)
        self.assertEqual(coord.repo.participante("alba").revision_respaldo, REVISION_PENDIENTE)

    def test_queda_registrado_el_id_de_la_persona_simulada(self):
        coord = nuevo_escenario()
        self.assertEqual(coord.repo.participante("alba").respaldo_revisado_por, "rev-ana")

    def test_cambiar_el_respaldo_invalida_la_revision(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.actualizar_respaldo_declarado("bruno", "Tengo un certificado C1 (declarado).")
        self.assertEqual(coord.repo.participante("bruno").revision_respaldo, REVISION_PENDIENTE)
        with self.assertRaises(OperacionNoPermitida):
            coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)


class TestRevisionDeLaEvidenciaDelMatch(unittest.TestCase):
    def test_aprobar_sin_confirmar_revision_de_la_evidencia_falla(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        for valor in (False, None, "sí", 1):
            with self.assertRaises(OperacionNoPermitida):
                coord.aprobar_match(m.id, REVISORA, evidencia_revisada=valor)
        self.assertFalse(m.es_valida)
        self.assertEqual(m.decision, DecisionHumana.PENDIENTE)

    def test_aprobacion_con_revision_hace_valida_la_propuesta(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        self.assertTrue(m.es_valida)
        self.assertEqual((m.decision, m.decidido_por), (DecisionHumana.APROBADA, "rev-ana"))

    def test_un_agente_no_aprueba_la_evidencia(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida):
            coord.aprobar_match(m.id, "A2", evidencia_revisada=True)

    def test_si_los_datos_cambian_antes_de_aprobar_se_rechaza(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.repo.solicitud("sol-bruno").idioma = "Portugués"
        with self.assertRaises(OperacionNoPermitida):
            coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)

    def test_a3_no_actua_sin_revision_de_la_evidencia(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida):
            coord.proponer_pacto(m.id, DESDE, "p1")

    def test_propuesta_rechazada_no_genera_pacto(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.rechazar_match(m.id, REVISORA, "prueba")
        self.assertEqual(m.decision, DecisionHumana.RECHAZADA)
        with self.assertRaises(OperacionNoPermitida):
            coord.proponer_pacto(m.id, DESDE, "p1")


class TestLasDosRevisionesSonIndependientes(unittest.TestCase):
    def test_aprobar_la_evidencia_no_toca_el_respaldo(self):
        coord = nuevo_escenario()
        antes = {pid: (p.revision_respaldo, p.respaldo_revisado_por) for pid, p in coord.repo.participantes.items()}
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        despues = {pid: (p.revision_respaldo, p.respaldo_revisado_por) for pid, p in coord.repo.participantes.items()}
        self.assertEqual(antes, despues)

    def test_revisar_el_respaldo_no_aprueba_ninguna_propuesta(self):
        coord = nuevo_escenario()   # respaldos ya revisados
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.decision, DecisionHumana.PENDIENTE)
        self.assertFalse(m.es_valida)

    def test_evidencia_aprobada_no_salva_un_respaldo_pendiente(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        coord.revisar_respaldo_declarado("alba", REVISORA, REVISION_PENDIENTE)
        with self.assertRaises(OperacionNoPermitida):
            coord.proponer_pacto(m.id, DESDE, "p1")


if __name__ == "__main__":
    unittest.main()

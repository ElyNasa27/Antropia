"""Caso original ficticio:
  Alba  ofrece Excel,      busca inglés.
  Bruno ofrece inglés,     busca Excel.
  Dani  ofrece inglés,     busca Excel  -> recíproco con Alba, pero SIN autorización.
  Cora  ofrece fotografía, busca Excel  -> elegible, pero nadie busca fotografía.
"""
import unittest

from encuentros.modelos import EstadoPacto, OperacionNoPermitida
from tests.apoyo import (
    COORDINADORA, DESDE, ENLACE_PRUEBA, REVISORA, RUTA_ORIGINAL, aceptan_y_se_revisa,
    hasta_invitaciones, nuevo_escenario,
)
from tests.test_mensajes import CORREO, TELEFONO, textos_del_flujo


def escenario(modificar=None, **kw):
    return nuevo_escenario(ruta=RUTA_ORIGINAL, modificar=modificar, **kw)


def companeros_de(coord, pid):
    out = set()
    for m in coord.repo.matches.values():
        if pid in (m.participante_a, m.participante_b):
            out.add(m.participante_b if m.participante_a == pid else m.participante_a)
    return out


class TestCasoOriginal(unittest.TestCase):
    def test_a2_propone_solo_alba_bruno(self):
        coord = escenario()
        res = coord.proponer_matches(DESDE, "e1")
        [m] = res.propuestas
        self.assertEqual((m.participante_a, m.participante_b), ("alba", "bruno"))
        self.assertEqual((m.a_ensena, m.b_ensena), (["Excel"], ["inglés"]))

    def test_a2_no_propone_ni_a_dani_ni_a_cora_para_alba(self):
        coord = escenario()
        coord.proponer_matches(DESDE, "e1")
        self.assertEqual(companeros_de(coord, "alba"), {"bruno"})
        self.assertEqual(companeros_de(coord, "dani"), set())
        self.assertEqual(companeros_de(coord, "cora"), set())

    def test_flujo_completo_excel_ingles(self):
        coord = escenario()
        pacto = hasta_invitaciones(coord)
        [inv_alba] = coord.bandeja.para("alba", "invitación")
        [inv_bruno] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("tú compartes Excel; Bruno comparte inglés", inv_alba.texto)
        self.assertIn("tú compartes inglés; Alba comparte Excel", inv_bruno.texto)
        aceptan_y_se_revisa(coord, pacto)
        coord.confirmar_pacto(pacto.id, COORDINADORA, ENLACE_PRUEBA)
        self.assertEqual(pacto.estado, EstadoPacto.CONFIRMADO)
        self.assertEqual({m.destinatario_id for m in coord.bandeja.mensajes}, {"alba", "bruno"})
        for texto in textos_del_flujo(coord):   # sin datos de contacto en mensajes ni bitácora
            self.assertIsNone(TELEFONO.search(texto), texto)
            self.assertIsNone(CORREO.search(texto), texto)


class TestDaniSinAutorizacion(unittest.TestCase):
    def test_solicitud_de_dani_excluida_por_falta_de_autorizacion(self):
        coord = escenario()
        res = coord.proponer_matches(DESDE, "e1")
        self.assertIn("sin autorización para participar", res.excluidas["sol-dani"])
        # Dani no se usa en ningún cálculo: no aparece como candidata de nadie
        for resumen in res.por_solicitud.values():
            for grupo in (resumen.propuestas, resumen.sin_coincidencia, resumen.bloqueadas,
                          resumen.omitidas_por_limite, resumen.ya_propuestas):
                self.assertNotIn("sol-dani", grupo)
        self.assertNotIn("sol-dani", res.por_solicitud)

    def test_dani_no_recibe_mensajes_ni_aparece_en_ellos(self):
        coord = escenario()
        pacto = hasta_invitaciones(coord)
        aceptan_y_se_revisa(coord, pacto)
        coord.confirmar_pacto(pacto.id, COORDINADORA, ENLACE_PRUEBA)
        self.assertEqual(coord.bandeja.para("dani"), [])
        self.assertTrue(all("Dani" not in m.texto for m in coord.bandeja.mensajes))

    def test_control_si_dani_autorizara_seria_candidato_de_alba(self):
        def dani_autoriza(ps, ss):
            ps["dani"].autoriza_participar = True
            ps["dani"].aptitud = "Apto"
        coord = escenario(dani_autoriza)
        coord.proponer_matches(DESDE, "e1")
        self.assertEqual(companeros_de(coord, "dani"), {"alba"})

    def test_autorizacion_no_booleana_no_cuenta(self):
        def ambigua(ps, ss):
            ps["dani"].autoriza_participar = "sí"
            ps["dani"].aptitud = "Apto"
        coord = escenario(ambigua)
        res = coord.proponer_matches(DESDE, "e1")
        self.assertIn("sin autorización para participar", res.excluidas["sol-dani"])
        self.assertEqual(companeros_de(coord, "dani"), set())


class TestCoraSinReciprocidad(unittest.TestCase):
    def test_cora_es_elegible_pero_no_reciproca(self):
        coord = escenario()
        res = coord.proponer_matches(DESDE, "e1")
        self.assertNotIn("sol-cora", res.excluidas)                 # sí es elegible
        self.assertEqual(companeros_de(coord, "cora"), set())
        self.assertIn("sin reciprocidad", res.por_solicitud["sol-alba"].sin_coincidencia["sol-cora"])
        self.assertEqual(res.por_solicitud["sol-cora"].resultado, "Sin coincidencia")

    def test_cora_sin_respaldo_usa_no_requerida(self):
        coord = escenario()
        self.assertEqual(coord.repo.participante("cora").revision_respaldo, "No requerida")


class TestRequisitosDeA2(unittest.TestCase):
    def _sin_propuestas(self, modificar, motivo):
        coord = escenario(modificar)
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        self.assertTrue(any(motivo in x for x in res.excluidas["sol-alba"]), res.excluidas)

    def test_aptitud_no_apto(self):
        def pendiente(ps, ss):
            ps["alba"].aptitud = "Pendiente"
        self._sin_propuestas(pendiente, "aptitud no Apto")

    def test_aptitud_incompleto(self):
        def incompleto(ps, ss):
            ps["alba"].aptitud = "Incompleto"
        self._sin_propuestas(incompleto, "aptitud no Apto")

    def test_solicitud_no_lista(self):
        def incompleta(ps, ss):
            ss["sol-alba"].estado = "Incompleta"
        self._sin_propuestas(incompleta, "solicitud no Lista")

    def test_sin_autorizacion(self):
        def sin_autorizacion(ps, ss):
            ps["alba"].autoriza_participar = False
        self._sin_propuestas(sin_autorizacion, "sin autorización")

    def test_requisitos_retirados_despues_bloquean(self):
        coord = escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.repo.participante("bruno").autoriza_participar = False
        with self.assertRaises(OperacionNoPermitida):
            coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)

    def test_solicitud_procesada_antes_del_pacto_bloquea(self):
        coord = escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        coord.repo.solicitud("sol-alba").estado = "Bloqueada"
        with self.assertRaises(OperacionNoPermitida):
            coord.proponer_pacto(m.id, DESDE, "p1")

    def test_aptitud_retirada_antes_de_invitar_bloquea(self):
        coord = escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        coord.repo.participante("bruno").aptitud = "Incompleto"
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.revisar_pacto(pacto.id, COORDINADORA)
        self.assertIn("ya no es elegible", str(ctx.exception))
        self.assertEqual(coord.bandeja.mensajes, [])


if __name__ == "__main__":
    unittest.main()

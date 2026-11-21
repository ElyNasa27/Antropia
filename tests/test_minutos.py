"""Tiempo del encuentro: «Minutos por sesión» = minutos que cada persona ofrece enseñar.

Reglas probadas:
  - Duración total = suma de ambos aportes.
  - Ambas personas disponibles durante toda la duración (también al revisar y confirmar).
  - Aportes distintos: se permiten, pero requieren revisión humana expresa.
  - Pacto y mensajes muestran los minutos de cada persona y la duración total.
  - Hacen falta las dos aceptaciones explícitas.
  - Valores dudosos (p. ej. antiguos de Notion) no se convierten: los revisa una persona.
"""
import unittest
from datetime import UTC, datetime, time

from encuentros.modelos import EstadoPacto, Franja, OperacionNoPermitida, TipoRespuesta as T
from encuentros.notion_mapa import (
    INTERPRETACION_MINUTOS, MINUTOS_EXISTENTES_EN_NOTION_REQUIEREN_REVISION, SIN_COLUMNA_EN_NOTION,
)
from encuentros.repositorio import solicitud_desde_dict
from tests.apoyo import DESDE, ENLACE_PRUEBA, REVISORA, hasta_invitaciones, nuevo_escenario, responder
from tests.test_a3_pacto import _a3


def _bruno_45(ps, ss):
    ss["sol-bruno"].minutos_por_sesion = 45


def _alba_solo_lunes(inicio, fin):
    def modificar(ps, ss):
        ss["sol-alba"].disponibilidad = [Franja("lunes", inicio, fin)]
    return modificar


def _hasta_invitaciones_con_aportes_distintos(coord):
    [m] = coord.proponer_matches(DESDE, "e1").propuestas
    coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True, aportes_distintos_revisados=True)
    pacto = coord.proponer_pacto(m.id, DESDE, "p1")
    coord.revisar_pacto(pacto.id, REVISORA)
    return m, pacto


def _listo_para_confirmar(coord):
    pacto = hasta_invitaciones(coord)
    responder(coord, pacto, "alba", T.ACEPTA)
    responder(coord, pacto, "bruno", T.ACEPTA)
    return pacto


class TestDuracionEsLaSumaDeLosAportes(unittest.TestCase):
    def test_aportes_iguales(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.evidencia["minutos_por_persona"], {"alba": 30, "bruno": 30})
        self.assertEqual(m.evidencia["duracion_propuesta_min"], 60)
        self.assertFalse(m.evidencia["aportes_distintos"])
        self.assertIn("Alba enseña 30 min, Bruno enseña 30 min (duración total 60 min)", m.motivo)

    def test_aportes_distintos_se_suman(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.evidencia["minutos_por_persona"], {"alba": 30, "bruno": 45})
        self.assertEqual(m.evidencia["duracion_propuesta_min"], 75)
        self.assertTrue(m.evidencia["aportes_distintos"])
        self.assertIn("aportes distintos: requieren revisión humana", m.motivo)

    def test_el_pacto_guarda_cada_aporte_y_la_duracion_total(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        _, pacto = _hasta_invitaciones_con_aportes_distintos(coord)
        v = pacto.version_actual
        self.assertEqual(v.minutos, {"alba": 30, "bruno": 45})
        self.assertEqual(v.duracion_min, 75)
        self.assertTrue(v.aportes_distintos)
        self.assertEqual(v.inicio_utc, datetime(2026, 11, 30, 17, 0, tzinfo=UTC))
        self.assertEqual(v.fin_utc, datetime(2026, 11, 30, 18, 15, tzinfo=UTC))


class TestDisponiblesDuranteTodaLaDuracion(unittest.TestCase):
    def test_franja_que_cubre_justo_la_duracion(self):
        # Alba lunes 18:00–19:00 Madrid = 17:00–18:00 UTC: exactamente 60 min.
        coord = nuevo_escenario(modificar=_alba_solo_lunes(time(18), time(19)))
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.evidencia["horario_comun_utc"], "2026-11-30T17:00:00+00:00")

    def test_un_minuto_menos_no_basta(self):
        coord = nuevo_escenario(modificar=_alba_solo_lunes(time(18), time(18, 59)))
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        motivos = res.por_solicitud["sol-alba"].sin_coincidencia["sol-bruno"]
        self.assertTrue(any("sin horario común de 60 min" in x for x in motivos))

    def test_un_aporte_mayor_exige_mas_disponibilidad(self):
        def mod(ps, ss):
            _alba_solo_lunes(time(18), time(19))(ps, ss)   # 60 min comunes
            _bruno_45(ps, ss)                              # hacen falta 75
        res = nuevo_escenario(modificar=mod).proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        motivos = res.por_solicitud["sol-alba"].sin_coincidencia["sol-bruno"]
        self.assertTrue(any("sin horario común de 75 min" in x for x in motivos))

    def test_a3_no_propone_si_la_franja_no_cubre_la_suma(self):
        r = _a3(cambio_a={"disponibilidad": [Franja("lunes", time(18), time(19))]},
                cambio_b={"minutos": 45})
        self.assertIsNone(r.version)
        self.assertIn("franja común de 75 min", r.faltantes[0])

    def test_disponibilidad_reducida_antes_de_revisar_el_pacto(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        coord.repo.solicitud("sol-bruno").disponibilidad = [Franja("lunes", time(11), time(11, 30))]
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.revisar_pacto(pacto.id, REVISORA)
        self.assertIn("toda la duración", str(ctx.exception))
        self.assertEqual(coord.bandeja.mensajes, [])

    def test_disponibilidad_reducida_antes_de_confirmar(self):
        coord = nuevo_escenario()
        pacto = _listo_para_confirmar(coord)
        coord.repo.solicitud("sol-alba").disponibilidad = [Franja("lunes", time(18), time(18, 30))]
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        self.assertIn("Alba ya no está disponible durante toda la duración", str(ctx.exception))
        self.assertEqual(pacto.estado, EstadoPacto.LISTO_PARA_CONFIRMAR)
        self.assertEqual(coord.bandeja.para("alba", "confirmación"), [])


class TestAportesDistintosRequierenRevisionHumana(unittest.TestCase):
    def test_sin_revisar_los_aportes_no_se_aprueba(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        self.assertIn("30 y 45 min", str(ctx.exception))
        self.assertFalse(m.es_valida)
        with self.assertRaises(OperacionNoPermitida):   # A3 no puede seguir
            coord.proponer_pacto(m.id, DESDE, "p1")

    def test_valores_ambiguos_no_cuentan_como_revision(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        for valor in ("sí", 1, None):
            with self.assertRaises(OperacionNoPermitida):
                coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True, aportes_distintos_revisados=valor)
        self.assertFalse(m.es_valida)

    def test_un_agente_no_revisa_los_aportes(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida):
            coord.aprobar_match(m.id, "A2", evidencia_revisada=True, aportes_distintos_revisados=True)

    def test_con_revision_expresa_se_aprueba_y_queda_registrada(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True, aportes_distintos_revisados=True)
        self.assertTrue(m.es_valida)
        self.assertTrue(m.aportes_distintos_revisados)
        self.assertTrue(any("aportes de minutos distintos" in e.detalle for e in coord.repo.bitacora))

    def test_la_revision_de_aportes_no_sustituye_a_la_de_evidencia(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida):
            coord.aprobar_match(m.id, REVISORA, evidencia_revisada=False, aportes_distintos_revisados=True)

    def test_aportes_iguales_no_piden_esa_revision(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        self.assertTrue(m.es_valida)
        self.assertFalse(m.aportes_distintos_revisados)


class TestCambiosDeMinutosAnulanLasRevisiones(unittest.TestCase):
    def test_cambio_antes_de_aprobar(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.repo.solicitud("sol-bruno").minutos_por_sesion = 45
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True, aportes_distintos_revisados=True)
        self.assertIn("cambiaron", str(ctx.exception))

    def test_cambio_despues_de_aprobar(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        coord.repo.solicitud("sol-bruno").minutos_por_sesion = 45
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        self.assertEqual(pacto.estado, EstadoPacto.FALTA_INFORMACION)
        self.assertIn("cambiaron desde la revisión humana", pacto.faltantes[0])
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_pacto(pacto.id, REVISORA)
        self.assertEqual(coord.bandeja.mensajes, [])

    def test_cambio_despues_de_aceptar(self):
        coord = nuevo_escenario()
        pacto = _listo_para_confirmar(coord)
        coord.repo.solicitud("sol-alba").minutos_por_sesion = 60
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        self.assertIn("ya no coinciden con el pacto v1", str(ctx.exception))
        self.assertEqual(coord.bandeja.para("alba", "confirmación"), [])


class TestAceptacionExplicitaDeAmbos(unittest.TestCase):
    def test_con_aportes_distintos_hacen_falta_las_dos_aceptaciones(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        _, pacto = _hasta_invitaciones_con_aportes_distintos(coord)
        responder(coord, pacto, "alba", T.ACEPTA)
        with self.assertRaises(OperacionNoPermitida):
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        responder(coord, pacto, "bruno", T.ACEPTA)
        coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        self.assertEqual(pacto.estado, EstadoPacto.CONFIRMADO)

    def test_pedir_otro_reparto_es_un_cambio_y_no_una_aceptacion(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        _, pacto = _hasta_invitaciones_con_aportes_distintos(coord)
        responder(coord, pacto, "alba", T.ACEPTA)
        responder(coord, pacto, "bruno", T.CAMBIOS, comentario="prefiero 30 y 30")
        self.assertEqual(pacto.estado, EstadoPacto.CAMBIOS_SOLICITADOS)
        with self.assertRaises(OperacionNoPermitida):
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)


class TestMensajesMuestranElTiempo(unittest.TestCase):
    def test_invitaciones(self):
        coord = nuevo_escenario(modificar=_bruno_45)
        _hasta_invitaciones_con_aportes_distintos(coord)
        [inv_alba] = coord.bandeja.para("alba", "invitación")
        [inv_bruno] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("30 min enseñas tú · 45 min enseña Bruno · duración total: 75 min", inv_alba.texto)
        self.assertIn("45 min enseñas tú · 30 min enseña Alba · duración total: 75 min", inv_bruno.texto)
        self.assertIn("18:00–19:15 (hora de Madrid)", inv_alba.texto)
        self.assertIn("11:00–12:15 (hora de Ciudad de México)", inv_bruno.texto)
        self.assertIn("aceptas también este reparto de minutos y la duración total", inv_alba.texto)

    def test_confirmaciones(self):
        coord = nuevo_escenario()
        pacto = _listo_para_confirmar(coord)
        for m in coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA):
            self.assertIn("30 min enseñas tú · 30 min enseña", m.texto)
            self.assertIn("duración total: 60 min", m.texto)


def _bruno_sin_revisar(ps, ss):
    # Valor antiguo: podría ser la duración total (60) y no el aporte de Bruno.
    ss["sol-bruno"].minutos_por_sesion = 60
    ss["sol-bruno"].minutos_requieren_revision = True


class TestValoresExistentesNoSeConvierten(unittest.TestCase):
    def test_bloquean_a2_y_no_se_modifican(self):
        coord = nuevo_escenario(modificar=_bruno_sin_revisar)
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(res.propuestas, [])
        r = res.por_solicitud["sol-alba"]
        self.assertEqual(r.resultado, "Bloqueada")
        self.assertTrue(any("pendientes de revisión humana" in x for x in r.bloqueadas["sol-bruno"]))
        s = coord.repo.solicitud("sol-bruno")
        self.assertEqual(s.minutos_por_sesion, 60)          # sin dividir ni convertir
        self.assertTrue(s.minutos_requieren_revision)

    def test_a3_tambien_los_bloquea(self):
        r = _a3(cambio_b={"minutos": 60, "minutos_pendientes_revision": True})
        self.assertIsNone(r.version)
        self.assertTrue(any("pendientes de revisión humana" in f for f in r.faltantes))

    def test_una_persona_escribe_el_aporte(self):
        coord = nuevo_escenario(modificar=_bruno_sin_revisar)
        coord.revisar_minutos_por_sesion("sol-bruno", REVISORA, 30, "confirmado con Bruno")
        s = coord.repo.solicitud("sol-bruno")
        self.assertEqual((s.minutos_por_sesion, s.minutos_requieren_revision, s.minutos_revisados_por),
                         (30, False, REVISORA))
        self.assertTrue(any("valor anterior: 60; aporte revisado: 30" in e.detalle for e in coord.repo.bitacora))
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.evidencia["duracion_propuesta_min"], 60)

    def test_la_persona_puede_confirmar_el_mismo_valor(self):
        coord = nuevo_escenario(modificar=_bruno_sin_revisar)
        coord.revisar_minutos_por_sesion("sol-bruno", REVISORA, 60)
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.evidencia["duracion_propuesta_min"], 90)
        self.assertTrue(m.evidencia["aportes_distintos"])   # 30 y 60: sigue la revisión humana

    def test_revision_solo_por_persona_y_con_valor_valido(self):
        coord = nuevo_escenario(modificar=_bruno_sin_revisar)
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_minutos_por_sesion("sol-bruno", "A2", 30)
        for valor in (0, -5, "30", True, 30.0, None):
            with self.assertRaises(OperacionNoPermitida):
                coord.revisar_minutos_por_sesion("sol-bruno", REVISORA, valor)
        self.assertTrue(coord.repo.solicitud("sol-bruno").minutos_requieren_revision)

    def test_cargador_json(self):
        base = {"id": "s", "participante_id": "p", "minutos_por_sesion": 60}
        self.assertFalse(solicitud_desde_dict(base).minutos_requieren_revision)
        for valor, esperado in ((False, False), (True, True), ("sí", True), (None, True)):
            s = solicitud_desde_dict({**base, "minutos_requieren_revision": valor})
            self.assertEqual(s.minutos_requieren_revision, esperado, valor)
            self.assertEqual(s.minutos_por_sesion, 60)

    def test_regla_documentada_para_notion(self):
        self.assertEqual(INTERPRETACION_MINUTOS, "aporte por persona")
        self.assertTrue(MINUTOS_EXISTENTES_EN_NOTION_REQUIEREN_REVISION)
        self.assertTrue(any("Minutos por sesión" in x for x in SIN_COLUMNA_EN_NOTION))


if __name__ == "__main__":
    unittest.main()

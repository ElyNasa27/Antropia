"""Escenarios pedidos: aceptación de ambos, rechazo, cambio de horario,
zona horaria (real y simulada) y enlace faltante, más casos límite."""
import unittest
from datetime import UTC, datetime, time, timedelta

from encuentros import zonas
from encuentros.canal import BandejaBorradores
from encuentros.coordinacion import Coordinacion
from encuentros.modelos import EstadoPacto, Franja, OperacionNoPermitida, TipoRespuesta as T
from encuentros.repositorio import RepositorioMemoria
from encuentros.zonas import resolver_zona_real
from tests.apoyo import (
    DESDE, ENLACE_PRUEBA, REVISORA, ZONAS_REALES, hasta_invitaciones, nuevo_escenario, responder,
)
from tests.zonas_simuladas import ZONAS_FIJAS_PILOTO, resolver_zona_simulada


class TestAceptacionDeAmbos(unittest.TestCase):
    def test_flujo_completo(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        self.assertEqual(len(coord.bandeja.mensajes), 2)  # una invitación por persona

        responder(coord, pacto, "alba", T.ACEPTA)
        self.assertEqual(pacto.estado, EstadoPacto.INVITACIONES_PREPARADAS)
        with self.assertRaises(OperacionNoPermitida):   # falta la aceptación de Bruno
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)

        responder(coord, pacto, "bruno", T.ACEPTA)
        self.assertEqual(pacto.estado, EstadoPacto.LISTO_PARA_CONFIRMAR)

        confirmaciones = coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        self.assertEqual(pacto.estado, EstadoPacto.CONFIRMADO)
        self.assertEqual(pacto.confirmado_por, REVISORA)
        self.assertEqual({m.destinatario_id for m in confirmaciones}, {"alba", "bruno"})
        self.assertTrue(all(ENLACE_PRUEBA in m.texto for m in confirmaciones))
        self.assertTrue(all(m.estado == "pendiente de revisión" for m in coord.bandeja.mensajes))


class TestRechazo(unittest.TestCase):
    def test_rechazo_cierra_sin_pacto(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        responder(coord, pacto, "alba", T.ACEPTA)
        responder(coord, pacto, "bruno", T.RECHAZA, comentario="no me interesa ahora")
        self.assertEqual(pacto.estado, EstadoPacto.CERRADO_SIN_PACTO)
        with self.assertRaises(OperacionNoPermitida):
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        self.assertEqual(coord.bandeja.para("alba", "confirmación"), [])
        self.assertEqual(coord.bandeja.para("bruno", "confirmación"), [])


class TestCambioDeHorario(unittest.TestCase):
    def test_cambio_genera_v2_e_invalida_aceptaciones_previas(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        responder(coord, pacto, "bruno", T.ACEPTA)
        responder(coord, pacto, "alba", T.CAMBIOS, comentario="el lunes no puedo")
        self.assertEqual(pacto.estado, EstadoPacto.CAMBIOS_SOLICITADOS)
        with self.assertRaises(OperacionNoPermitida):
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)

        coord.proponer_nueva_version(pacto.id, DESDE)
        v2 = pacto.version_actual
        self.assertEqual(v2.numero, 2)
        self.assertEqual(v2.inicio_utc, datetime(2026, 12, 2, 18, 0, tzinfo=UTC))  # miércoles 2-dic
        self.assertEqual(pacto.estado, EstadoPacto.BORRADOR)
        self.assertTrue(all(r.tipo is T.PENDIENTE for r in pacto.respuestas.values()))

        coord.revisar_pacto(pacto.id, REVISORA)
        with self.assertRaises(OperacionNoPermitida):   # una respuesta a la v1 ya no vale
            coord.registrar_respuesta(pacto.id, "bruno", T.ACEPTA, version=1,
                                      registrado_por=REVISORA, origen="simulación")
        responder(coord, pacto, "alba", T.ACEPTA)
        responder(coord, pacto, "bruno", T.ACEPTA)
        coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
        self.assertEqual(pacto.estado, EstadoPacto.CONFIRMADO)

    def test_cambio_con_nueva_disponibilidad_aportada_por_la_persona(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        responder(coord, pacto, "alba", T.CAMBIOS,
                  nueva_disponibilidad=[Franja("miércoles", time(19), time(20, 30))])
        self.assertEqual(coord.repo.solicitud("sol-alba").disponibilidad,
                         [Franja("miércoles", time(19), time(20, 30))])
        coord.proponer_nueva_version(pacto.id, DESDE)
        self.assertEqual(pacto.version_actual.inicio_utc, datetime(2026, 12, 2, 18, 0, tzinfo=UTC))

    def test_cambio_sin_alternativa_no_inventa_horario(self):
        def solo_lunes(ps, ss):
            ss["sol-alba"].disponibilidad = [Franja("lunes", time(18), time(19))]
            ss["sol-bruno"].disponibilidad = [Franja("lunes", time(11), time(12))]
        desde = datetime(2026, 11, 30, tzinfo=UTC)
        coord = nuevo_escenario(modificar=solo_lunes, dias_busqueda=6)
        pacto = hasta_invitaciones(coord, desde=desde)
        responder(coord, pacto, "alba", T.CAMBIOS, comentario="otro día")
        coord.proponer_nueva_version(pacto.id, desde)
        self.assertEqual(pacto.estado, EstadoPacto.FALTA_INFORMACION)
        self.assertEqual(len(pacto.versiones), 1)
        with self.assertRaises(OperacionNoPermitida):
            coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)


class TestZonaHoraria(unittest.TestCase):
    def test_cada_persona_ve_su_hora_local(self):
        coord = nuevo_escenario()
        hasta_invitaciones(coord)
        [inv_alba] = coord.bandeja.para("alba", "invitación")
        [inv_bruno] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("lunes 30 de noviembre de 2026, 18:00–19:00 (hora de Madrid)", inv_alba.texto)
        self.assertIn("lunes 30 de noviembre de 2026, 11:00–12:00 (hora de Ciudad de México)", inv_bruno.texto)

    def test_zona_faltante_impide_la_propuesta(self):
        def sin_zona(ps, ss):
            ss["sol-alba"].zona_horaria = ""
        coord = nuevo_escenario(modificar=sin_zona)
        self.assertEqual(coord.proponer_matches(DESDE, "e1").propuestas, [])
        self.assertEqual(coord.bandeja.mensajes, [])

    def test_zona_retirada_tras_aprobar_bloquea_el_pacto(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        coord.repo.solicitud("sol-bruno").zona_horaria = None
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        self.assertEqual(pacto.estado, EstadoPacto.FALTA_INFORMACION)
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_pacto(pacto.id, REVISORA)
        self.assertEqual(coord.bandeja.mensajes, [])


class TestTablaSimuladaNoSeUsaParaEncuentrosReales(unittest.TestCase):
    def test_el_paquete_no_contiene_la_tabla_simulada(self):
        self.assertFalse(hasattr(zonas, "ZONAS_FIJAS_PILOTO"))
        self.assertFalse(hasattr(zonas, "resolver_zona_fija_piloto"))

    def test_coordinacion_rechaza_la_tabla_simulada_sin_permiso(self):
        with self.assertRaises(ValueError):
            Coordinacion(RepositorioMemoria(), BandejaBorradores(), resolver_zona_simulada)

    def test_por_defecto_se_usan_zonas_reales(self):
        coord = Coordinacion(RepositorioMemoria(), BandejaBorradores())
        self.assertIs(coord.resolver, resolver_zona_real)


@unittest.skipUnless(ZONAS_REALES, "Requiere tzdata (usar el entorno virtual .venv del proyecto)")
class TestZonasReales(unittest.TestCase):
    """Estas pruebas usan la base IANA real (paquete tzdata), no la tabla simulada."""

    def test_noviembre_con_zonas_reales(self):
        coord = nuevo_escenario(resolver=resolver_zona_real)
        pacto = hasta_invitaciones(coord)
        self.assertEqual(pacto.version_actual.inicio_utc, datetime(2026, 11, 30, 17, 0, tzinfo=UTC))
        [inv_alba] = coord.bandeja.para("alba", "invitación")
        [inv_bruno] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("18:00–19:00 (hora de Madrid)", inv_alba.texto)
        self.assertIn("11:00–12:00 (hora de Ciudad de México)", inv_bruno.texto)

    def test_cambio_de_horario_de_verano_con_zonas_reales(self):
        # 28-mar-2027 Madrid pasa a UTC+2; Ciudad de México sigue en UTC-6.
        # Alba 18-20 Madrid = 16-18 UTC; Bruno 11-13 CDMX = 17-19 UTC -> común 17-18 UTC.
        coord = nuevo_escenario(resolver=resolver_zona_real)
        pacto = hasta_invitaciones(coord, desde=datetime(2027, 3, 29, tzinfo=UTC))
        self.assertEqual(pacto.version_actual.inicio_utc, datetime(2027, 3, 29, 17, 0, tzinfo=UTC))
        [inv_alba] = coord.bandeja.para("alba", "invitación")
        [inv_bruno] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("lunes 29 de marzo de 2027, 19:00–20:00 (hora de Madrid)", inv_alba.texto)
        self.assertIn("lunes 29 de marzo de 2027, 11:00–12:00 (hora de Ciudad de México)", inv_bruno.texto)

    def test_semana_anterior_al_cambio_de_hora(self):
        coord = nuevo_escenario(resolver=resolver_zona_real)
        pacto = hasta_invitaciones(coord, desde=datetime(2027, 3, 22, tzinfo=UTC))
        self.assertEqual(pacto.version_actual.inicio_utc, datetime(2027, 3, 22, 17, 0, tzinfo=UTC))
        [inv_alba] = coord.bandeja.para("alba", "invitación")
        self.assertIn("18:00–19:00 (hora de Madrid)", inv_alba.texto)

    def test_la_tabla_simulada_coincide_con_tzdata_en_su_rango(self):
        dia, fin = datetime(2026, 10, 25, 12, tzinfo=UTC), datetime(2027, 3, 27, 12, tzinfo=UTC)
        while dia <= fin:
            for zona, fija in ZONAS_FIJAS_PILOTO.items():
                real = resolver_zona_real(zona)
                self.assertEqual(dia.astimezone(real).utcoffset(), dia.astimezone(fija).utcoffset(),
                                 f"{zona} en {dia:%Y-%m-%d}")
            dia += timedelta(days=1)

    def test_la_tabla_simulada_es_incorrecta_fuera_de_su_rango(self):
        dia = datetime(2027, 3, 29, 12, tzinfo=UTC)
        real = dia.astimezone(resolver_zona_real("Europe/Madrid")).utcoffset()
        fija = dia.astimezone(ZONAS_FIJAS_PILOTO["Europe/Madrid"]).utcoffset()
        self.assertNotEqual(real, fija)


class TestEnlaceFaltante(unittest.TestCase):
    def _listo(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        responder(coord, pacto, "alba", T.ACEPTA)
        responder(coord, pacto, "bruno", T.ACEPTA)
        return coord, pacto

    def test_sin_enlace_no_confirma(self):
        coord, pacto = self._listo()
        for enlace in (None, "", "   "):
            with self.assertRaises(OperacionNoPermitida):
                coord.confirmar_pacto(pacto.id, REVISORA, enlace)
        self.assertEqual(pacto.estado, EstadoPacto.LISTO_PARA_CONFIRMAR)
        self.assertEqual(coord.bandeja.para("alba", "confirmación"), [])

    def test_enlace_no_https_no_confirma(self):
        coord, pacto = self._listo()
        for enlace in ("http://videollamada.example/x", "sala 3", "https://"):
            with self.assertRaises(OperacionNoPermitida):
                coord.confirmar_pacto(pacto.id, REVISORA, enlace)

    def test_un_agente_no_confirma(self):
        coord, pacto = self._listo()
        with self.assertRaises(OperacionNoPermitida):
            coord.confirmar_pacto(pacto.id, "A3", ENLACE_PRUEBA)


class TestReglasDeRespuesta(unittest.TestCase):
    def test_no_se_responde_antes_de_la_revision_humana(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        with self.assertRaises(OperacionNoPermitida):
            responder(coord, pacto, "alba", T.ACEPTA)

    def test_respuesta_duplicada_y_sin_origen(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        responder(coord, pacto, "alba", T.ACEPTA)
        with self.assertRaises(OperacionNoPermitida):
            responder(coord, pacto, "alba", T.ACEPTA)
        with self.assertRaises(OperacionNoPermitida):
            coord.registrar_respuesta(pacto.id, "bruno", T.ACEPTA, version=1,
                                      registrado_por=REVISORA, origen="")

    def test_cambio_requiere_detalle(self):
        coord = nuevo_escenario()
        pacto = hasta_invitaciones(coord)
        with self.assertRaises(OperacionNoPermitida):
            responder(coord, pacto, "alba", T.CAMBIOS)


if __name__ == "__main__":
    unittest.main()

"""Aviso automático de match por correo (envío simulado: no sale nada de la máquina)."""
import unittest

from encuentros.correo import (
    ASUNTO_MATCH, ENVIADO, FALLIDO, SIN_CORREO, VAR_CLAVE, VAR_USUARIO,
    AgendaCorreos, CorreoMatch, EnvioGmailSMTP, EnvioSimulado, NotificadorMatch,
    contiene_correo, redactar_aviso_match,
)
from tests.apoyo import DESDE, nuevo_escenario

# Dominio reservado para ejemplos (RFC 2606): no son personas reales.
CORREOS = {"alba": "alba@example.org", "bruno": "bruno@example.org"}


def escenario(correos=CORREOS, fallar_para=None, **kw):
    envio = EnvioSimulado(fallar_para=fallar_para)
    notificador = NotificadorMatch(AgendaCorreos(correos), envio)
    return nuevo_escenario(notificador=notificador, **kw), envio


class TestAvisoAutomatico(unittest.TestCase):
    def test_a2_detecta_compatibilidad_y_envia_a_las_dos_personas(self):
        coord, envio = escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(sorted(c.destinatario_id for c in envio.enviados), ["alba", "bruno"])
        para = {c.destinatario_id: c.para for c in envio.enviados}
        self.assertEqual(para, CORREOS)
        self.assertTrue(coord.avisos_match[m.id].completo)
        # Sin revisión humana previa: el envío es automático.
        self.assertFalse(m.es_valida)

    def test_contenido_solo_aviso(self):
        coord, envio = escenario()
        coord.proponer_matches(DESDE, "e1")
        alba = next(c for c in envio.enviados if c.destinatario_id == "alba")
        self.assertEqual(alba.asunto, ASUNTO_MATCH)
        self.assertIn("Hola, Alba", alba.cuerpo)
        self.assertIn("Persona: Bruno", alba.cuerpo)
        self.assertIn("Tú compartes: fotografía con móvil", alba.cuerpo)
        self.assertIn("Bruno comparte: inglés conversacional", alba.cuerpo)

    def test_ningun_correo_muestra_direcciones(self):
        coord, envio = escenario()
        coord.proponer_matches(DESDE, "e1")
        for c in envio.enviados:
            self.assertFalse(contiene_correo(c.cuerpo + c.asunto))
            self.assertNotIn("@", repr(c))
        for ev in coord.repo.bitacora:
            self.assertNotIn("@", f"{ev.actor} {ev.accion} {ev.referencia} {ev.detalle}")
        self.assertNotIn("@", repr(coord.notificador.agenda))

    def test_repetir_la_ejecucion_no_reenvia(self):
        coord, envio = escenario()
        coord.proponer_matches(DESDE, "e1")
        coord.proponer_matches(DESDE, "e1")    # misma clave
        coord.proponer_matches(DESDE, "e2")    # el par ya existe
        coord.reintentar_avisos_pendientes()
        self.assertEqual(len(envio.enviados), 2)

    def test_sin_correo_no_se_envia_a_ninguna(self):
        coord, envio = escenario(correos={"alba": "alba@example.org"})
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(envio.enviados, [])
        self.assertEqual(set(coord.avisos_match[m.id].estado_por_persona.values()), {SIN_CORREO})
        # Cuando llega el correo que faltaba, el reintento envía a las dos.
        coord.notificador.agenda.guardar("bruno", "bruno@example.org")
        coord.reintentar_avisos_pendientes()
        self.assertEqual(len(envio.enviados), 2)

    def test_fallo_de_envio_queda_pendiente_y_se_reintenta_solo_a_quien_falta(self):
        coord, envio = escenario(fallar_para={"bruno"})
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        estados = coord.avisos_match[m.id].estado_por_persona
        self.assertEqual(estados, {"alba": ENVIADO, "bruno": FALLIDO})
        self.assertTrue(any("falló el envío" in ev.accion for ev in coord.repo.bitacora))
        envio.fallar_para.clear()
        coord.reintentar_avisos_pendientes()
        self.assertEqual(sorted(c.destinatario_id for c in envio.enviados), ["alba", "bruno"])
        self.assertTrue(coord.avisos_match[m.id].completo)

    def test_sin_par_compatible_no_hay_correo(self):
        def sin_reciprocidad(ps, ss):
            ss["sol-bruno"].tema_busca = ["cocina"]
        coord, envio = escenario(modificar=sin_reciprocidad)
        coord.proponer_matches(DESDE, "e1")
        self.assertEqual(envio.enviados, [])

    def test_sin_notificador_no_cambia_nada(self):
        coord = nuevo_escenario()
        coord.proponer_matches(DESDE, "e1")
        self.assertEqual(coord.avisos_match, {})


class TestRedaccionYAgenda(unittest.TestCase):
    def test_nombres_con_saltos_de_linea_se_aplanan(self):
        cuerpo = redactar_aviso_match("Alba\nBcc: x", "Bruno", ["a"], ["b"])
        self.assertIn("Hola, Alba Bcc: x:", cuerpo)

    def test_agenda_rechaza_correos_invalidos(self):
        for malo in ("sin-arroba", "a@b", "a b@example.org", "x@example.org\nBcc: y@example.org"):
            with self.assertRaises(ValueError):
                AgendaCorreos({"p": malo})


class TestGmailSMTP(unittest.TestCase):
    """Solo se prueba la configuración: nunca se conecta a Gmail en las pruebas."""

    def test_exige_variables_de_entorno(self):
        with self.assertRaises(ValueError) as ctx:
            EnvioGmailSMTP(entorno={})
        self.assertIn(VAR_USUARIO, str(ctx.exception))
        self.assertIn(VAR_CLAVE, str(ctx.exception))

    def test_construye_el_mensaje_sin_mostrar_credenciales(self):
        envio = EnvioGmailSMTP(entorno={VAR_USUARIO: "remitente@example.org", VAR_CLAVE: "abcd efgh"})
        self.assertNotIn("abcd", repr(envio))
        msg = envio.construir(CorreoMatch("m1", "alba", "alba@example.org", cuerpo="Hola"))
        self.assertEqual(msg["To"], "alba@example.org")
        self.assertIn("remitente@example.org", msg["From"])
        self.assertEqual(msg["Subject"], ASUNTO_MATCH)


if __name__ == "__main__":
    unittest.main()

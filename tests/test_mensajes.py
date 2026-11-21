import unittest

from encuentros.modelos import TipoRespuesta as T
from tests.apoyo import ENLACE_PRUEBA, REVISORA, hasta_invitaciones, nuevo_escenario, responder

TELEFONOS = {"alba": "+00 0000 0001", "bruno": "+00 0000 0002"}


def _flujo_confirmado():
    coord = nuevo_escenario()
    pacto = hasta_invitaciones(coord)
    responder(coord, pacto, "alba", T.ACEPTA)
    responder(coord, pacto, "bruno", T.ACEPTA)
    coord.confirmar_pacto(pacto.id, REVISORA, ENLACE_PRUEBA)
    return coord


class TestPrivacidad(unittest.TestCase):
    def test_ningun_mensaje_ni_bitacora_contiene_telefonos(self):
        coord = _flujo_confirmado()
        textos = [m.texto for m in coord.bandeja.mensajes]
        textos += [f"{e.accion} {e.referencia} {e.detalle}" for e in coord.repo.bitacora]
        for texto in textos:
            for tel in TELEFONOS.values():
                self.assertNotIn(tel, texto)
                self.assertNotIn(tel.replace(" ", ""), texto.replace(" ", ""))

    def test_cada_persona_solo_ve_el_nombre_de_la_otra(self):
        coord = _flujo_confirmado()
        for m in coord.bandeja.para("alba"):
            self.assertIn("Bruno", m.texto)
            self.assertNotIn("America/Mexico_City", m.texto)


class TestBorradores(unittest.TestCase):
    def test_todo_queda_pendiente_de_revision(self):
        coord = _flujo_confirmado()
        self.assertEqual(len(coord.bandeja.mensajes), 4)  # 2 invitaciones + 2 confirmaciones
        self.assertTrue(all(m.estado == "pendiente de revisión" for m in coord.bandeja.mensajes))

    def test_aprobar_un_borrador_no_lo_envia(self):
        coord = _flujo_confirmado()
        m = coord.bandeja.mensajes[0]
        coord.bandeja.aprobar(m.id, REVISORA)
        self.assertEqual(m.estado, "aprobado (piloto: no se envía)")
        self.assertFalse(hasattr(coord.bandeja, "enviar"))

    def test_invitacion_incluye_version_y_opciones(self):
        coord = nuevo_escenario()
        hasta_invitaciones(coord)
        [inv] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("propuesta v1", inv.texto)
        for opcion in ("ACEPTO", "RECHAZO", "CAMBIO"):
            self.assertIn(opcion, inv.texto)


if __name__ == "__main__":
    unittest.main()

import unittest

from encuentros.modelos import OperacionNoPermitida
from tests.apoyo import (
    COORDINADORA, ENLACE_PRUEBA, REVISORA, aceptan_y_se_revisa, hasta_invitaciones, nuevo_escenario,
)

TELEFONOS = {"alba": "+00 0000 0001", "bruno": "+00 0000 0002"}


def _flujo_confirmado():
    coord = nuevo_escenario()
    pacto = hasta_invitaciones(coord)
    aceptan_y_se_revisa(coord, pacto)
    coord.confirmar_pacto(pacto.id, COORDINADORA, ENLACE_PRUEBA)
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
        coord.bandeja.aprobar(m.id, COORDINADORA)
        self.assertEqual(m.estado, "aprobado (piloto: no se envía)")
        self.assertEqual(m.revisado_por, "coord-luis")
        self.assertFalse(hasattr(coord.bandeja, "enviar"))

    def test_aprobar_un_borrador_exige_rol_de_coordinacion(self):
        coord = _flujo_confirmado()
        m = coord.bandeja.mensajes[0]
        for quien in (REVISORA, "Luis (ficticio)", "A3"):
            with self.assertRaises(OperacionNoPermitida):
                coord.bandeja.aprobar(m.id, quien)
        self.assertEqual(m.estado, "pendiente de revisión")

    def test_invitacion_incluye_version_y_opciones(self):
        coord = nuevo_escenario()
        hasta_invitaciones(coord)
        [inv] = coord.bandeja.para("bruno", "invitación")
        self.assertIn("propuesta v1", inv.texto)
        for opcion in ("ACEPTO", "RECHAZO", "CAMBIO"):
            self.assertIn(opcion, inv.texto)


if __name__ == "__main__":
    unittest.main()

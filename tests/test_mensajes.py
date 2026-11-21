import dataclasses
import re
import unittest

from encuentros.modelos import OperacionNoPermitida, Participante
from encuentros.repositorio import participante_desde_dict
from tests.apoyo import (
    COORDINADORA, ENLACE_PRUEBA, REVISORA, aceptan_y_se_revisa, hasta_invitaciones, nuevo_escenario,
)

# Patrones de datos de contacto que nunca deben aparecer en mensajes ni en la bitácora.
TELEFONO = re.compile(r"\+\d{1,3}[\s\d]{6,}|\b\d{9,}\b")
CORREO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _flujo_confirmado():
    coord = nuevo_escenario()
    pacto = hasta_invitaciones(coord)
    aceptan_y_se_revisa(coord, pacto)
    coord.confirmar_pacto(pacto.id, COORDINADORA, ENLACE_PRUEBA)
    return coord


def textos_del_flujo(coord) -> list[str]:
    textos = [m.texto for m in coord.bandeja.mensajes]
    textos += [f"{e.actor} {e.accion} {e.referencia} {e.detalle}" for e in coord.repo.bitacora]
    return textos


class TestPrivacidad(unittest.TestCase):
    def test_ningun_mensaje_ni_bitacora_contiene_datos_de_contacto(self):
        coord = _flujo_confirmado()
        for texto in textos_del_flujo(coord):
            self.assertIsNone(TELEFONO.search(texto), texto)
            self.assertIsNone(CORREO.search(texto), texto)

    def test_el_modelo_no_tiene_campo_de_telefono(self):
        campos = {f.name for f in dataclasses.fields(Participante)}
        self.assertFalse(campos & {"telefono", "teléfono", "phone", "celular", "whatsapp"})

    def test_los_datos_con_telefono_se_rechazan(self):
        for clave in ("telefono", "Teléfono", "phone", "whatsapp"):
            with self.assertRaises(ValueError):
                participante_desde_dict({"id": "x", "alias": "X (ficticia)", clave: "+00 0000 0009"})

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

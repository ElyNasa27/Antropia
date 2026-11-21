"""A3 probado directamente: aunque A2 ya filtra, A3 se defiende por sí mismo."""
import unittest
from dataclasses import replace
from datetime import UTC, datetime, time

from encuentros import a3_pacto
from encuentros.a2_match import perfil
from encuentros.modelos import Franja, PropuestaMatch
from encuentros.repositorio import cargar_datos_json
from tests.apoyo import DESDE, RESOLVER_POR_DEFECTO, RUTA_DATOS


def _perfiles():
    ps, ss = cargar_datos_json(RUTA_DATOS)
    ps = {p.id: p for p in ps}
    ss = {s.id: s for s in ss}
    return perfil(ps["alba"], ss["sol-alba"]), perfil(ps["bruno"], ss["sol-bruno"])


def _a3(cambio_a=None, cambio_b=None):
    a, b = _perfiles()
    if cambio_a:
        a = replace(a, **cambio_a)
    if cambio_b:
        b = replace(b, **cambio_b)
    m = PropuestaMatch("match-x", "sol-alba", "sol-bruno", "alba", "bruno",
                       ["fotografía con móvil"], ["inglés conversacional"], "prueba")
    return a3_pacto.proponer_pacto(m, a, b, DESDE, RESOLVER_POR_DEFECTO)


class TestA3Pacto(unittest.TestCase):
    def test_propone_primera_franja_comun_con_datos_disponibles(self):
        v = _a3().version
        self.assertEqual(v.inicio_utc, datetime(2026, 11, 30, 17, 0, tzinfo=UTC))
        self.assertEqual(v.minutos, {"alba": 30, "bruno": 30})
        self.assertEqual(v.objetivos, {"alba": "fotografía con móvil", "bruno": "inglés conversacional"})
        self.assertEqual(v.modalidad, "videollamada")
        self.assertEqual(v.zonas, {"alba": "Europe/Madrid", "bruno": "America/Mexico_City"})
        self.assertEqual(v.propuesto_por, "A3")

    def test_sin_zona_horaria_no_propone_fecha(self):
        r = _a3(cambio_b={"zona_horaria": None})
        self.assertIsNone(r.version)
        self.assertIn("Bruno: zona horaria", r.faltantes)

    def test_zona_irresoluble_no_propone_fecha(self):
        r = _a3(cambio_a={"zona_horaria": "Marte/Olympus"})
        self.assertIsNone(r.version)
        self.assertTrue(any(f.startswith("Alba:") for f in r.faltantes))

    def test_sin_disponibilidad_ni_minutos(self):
        r = _a3(cambio_a={"disponibilidad": []}, cambio_b={"minutos": None})
        self.assertIsNone(r.version)
        self.assertIn("Alba: disponibilidad", r.faltantes)
        self.assertIn("Bruno: minutos por sesión", r.faltantes)

    def test_sin_aceptacion_de_lo_virtual(self):
        r = _a3(cambio_b={"acepta_virtual": None})
        self.assertIsNone(r.version)
        self.assertTrue(any("no consta que acepte" in f for f in r.faltantes))

    def test_sin_coincidencia_de_horarios_no_inventa(self):
        r = _a3(cambio_b={"disponibilidad": [Franja("viernes", time(9), time(10))]})
        self.assertIsNone(r.version)
        self.assertIn("no hay una franja común", r.faltantes[0])


if __name__ == "__main__":
    unittest.main()

"""Lectura del texto libre del formulario («Disponibilidad + zona horaria», temas)."""
import unittest
from datetime import time

from encuentros.a2_match import temas_en_comun
from encuentros.disponibilidad import leer_disponibilidad, leer_temas


def franjas(texto):
    return [(f.dia, f.inicio.strftime("%H:%M"), f.fin.strftime("%H:%M")) for f in leer_disponibilidad(texto).franjas]


class TestDisponibilidad(unittest.TestCase):
    def test_formato_del_formulario(self):
        d = leer_disponibilidad("lunes 18:00–20:00; America/Costa_Rica")
        self.assertEqual(franjas("lunes 18:00–20:00; America/Costa_Rica"), [("lunes", "18:00", "20:00")])
        self.assertEqual(d.zona_en_texto, "America/Costa_Rica")
        self.assertEqual(d.no_reconocido, [])

    def test_variantes(self):
        self.assertEqual(franjas("martes y jueves 18-20"),
                         [("martes", "18:00", "20:00"), ("jueves", "18:00", "20:00")])
        self.assertEqual(len(franjas("lunes a viernes de 9:00 a 11:30")), 5)
        self.assertEqual(franjas("Sábado 10:00–12:00, domingo 16:00–18:00"),
                         [("sábado", "10:00", "12:00"), ("domingo", "16:00", "18:00")])
        self.assertEqual(franjas("miércoles 19 a 21h y sábados 10-12"),
                         [("miércoles", "19:00", "21:00"), ("sábado", "10:00", "12:00")])

    def test_no_se_adivina(self):
        self.assertEqual(franjas("cuando pueda"), [])
        d = leer_disponibilidad("lunes 20:00-18:00")
        self.assertEqual(d.franjas, [])
        self.assertEqual(d.no_reconocido, ["lunes 20:00-18:00"])
        self.assertEqual(leer_disponibilidad("lunes 18:00-20:00; tardes 5 a 7").no_reconocido, ["tardes 5 a 7"])

    def test_medianoche(self):
        self.assertEqual(leer_disponibilidad("viernes 22:00-24:00").franjas[0].fin, time(23, 59))


class TestTemas(unittest.TestCase):
    def test_separadores(self):
        self.assertEqual(leer_temas("Excel básico, inglés y fotografía; cocina"),
                         ["Excel básico", "inglés", "fotografía", "cocina"])
        self.assertEqual(leer_temas(None), [])

    def test_comparacion_sin_tildes_ni_mayusculas_pero_entera(self):
        self.assertEqual(temas_en_comun(["Inglés"], ["ingles"]), ["Inglés"])
        self.assertEqual(temas_en_comun(["Excel"], ["Excel básico"]), [])


if __name__ == "__main__":
    unittest.main()

"""Zona horaria escrita con tildes: solo se acepta su equivalente IANA exacto."""
import unittest

from encuentros.zonas import datos_de_zonas_disponibles, zona_sin_tildes


@unittest.skipUnless(datos_de_zonas_disponibles(), "requiere tzdata (usar .venv)")
class TestZonaSinTildes(unittest.TestCase):
    def test_quitar_tildes_da_una_zona_iana_exacta(self):
        self.assertEqual(zona_sin_tildes("America/Bogotá"), "America/Bogota")
        self.assertEqual(zona_sin_tildes("América/Bogotá"), "America/Bogota")
        self.assertEqual(zona_sin_tildes(" America/Asunción "), "America/Asuncion")

    def test_sin_tildes_no_hay_nada_que_cambiar(self):
        self.assertIsNone(zona_sin_tildes("America/Bogota"))
        self.assertIsNone(zona_sin_tildes("Marte/Olympus"))
        self.assertIsNone(zona_sin_tildes(None))
        self.assertIsNone(zona_sin_tildes(""))

    def test_no_corrige_nada_mas_que_las_tildes(self):
        for zona in ("Europe/Málaga",                  # no es una zona IANA
                     "america/bogotá",                 # mayúsculas distintas
                     "America/Ciudad de México",       # nombre traducido
                     "America/Bogotá ciudad"):         # texto adicional
            with self.subTest(zona):
                self.assertIsNone(zona_sin_tildes(zona))


if __name__ == "__main__":
    unittest.main()

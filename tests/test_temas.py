"""Comparación conservadora de temas (encuentros/temas.py). Solo datos ficticios."""
import unittest

from encuentros.temas import (
    IGUAL, REQUIERE_ACLARACION, SINONIMO, TEMA_DEFINIDO, comparar, comparar_tema, coincidencias,
)


def tipo(ofrece, busca):
    r = comparar_tema(ofrece, busca)
    return r.tipo if r else None


class TestFrasesDiferentesMismoTema(unittest.TestCase):
    def test_ejemplo_alba_bruno(self):
        self.assertEqual(tipo("crear tablas en Excel para controlar gastos",
                              "aprender a organizar gastos usando Excel"), TEMA_DEFINIDO)

    def test_otras_frases_equivalentes(self):
        casos = [
            ("Inglés", "ingles", IGUAL),
            ("Clases de cocina", "cocina", IGUAL),
            ("Guitarras", "guitarra", IGUAL),
            ("inglés", "English", SINONIMO),
            ("Fotos con el celular", "fotografía con móvil", SINONIMO),
            ("Inglés conversacional", "practicar inglés hablado", TEMA_DEFINIDO),
            ("Python", "programación en Python", TEMA_DEFINIDO),
            ("planillas de Excel para registrar gastos", "Microsoft Excel para gastos", TEMA_DEFINIDO),
            ("Excel intermedio", "Excel intermedio", IGUAL),
        ]
        for ofrece, busca, esperado in casos:
            with self.subTest(ofrece=ofrece, busca=busca):
                self.assertEqual(tipo(ofrece, busca), esperado)


class TestRequiereAclaracion(unittest.TestCase):
    """Temas relacionados con alcance o nivel incierto: nunca son compatibles solos."""

    def test_casos_inciertos(self):
        casos = [
            ("Excel", "Excel avanzado", "nivel incierto"),              # no se inventa el nivel
            ("inglés avanzado", "inglés básico", "nivel incierto"),     # decisión: tampoco se supone
            ("Excel", "crear tablas en Excel para controlar gastos", "más general"),
            ("crear tablas en Excel para controlar gastos", "Excel", "más concreto"),
            ("Excel para gastos personales", "organizar gastos en Excel", "dicen cosas distintas"),
            ("Excel para contabilidad", "Excel para finanzas", "dicen cosas distintas"),
            ("inglés", "inglés para negocios", "más general"),
            ("fotografia", "fotogarfía", "posible errata"),
        ]
        for ofrece, busca, motivo in casos:
            with self.subTest(ofrece=ofrece, busca=busca):
                r = comparar_tema(ofrece, busca)
                self.assertIsNotNone(r)
                self.assertEqual(r.tipo, REQUIERE_ACLARACION)
                self.assertFalse(r.compatible)
                self.assertIn(motivo, r.motivo)

    def test_lo_incierto_no_cuenta_como_coincidencia(self):
        self.assertEqual(coincidencias(["Excel"], ["Excel avanzado"]), [])
        c = comparar(["Excel"], ["Excel avanzado"])
        self.assertFalse(c.cubre)
        self.assertTrue(c.requiere_aclaracion)


class TestSinCoincidencia(unittest.TestCase):
    def test_categoria_amplia_o_temas_distintos(self):
        casos = [
            ("cocina italiana", "cocina mexicana"),          # solo comparten la categoría
            ("programación en Python", "programación en Java"),
            ("idiomas", "inglés"),                           # categoría frente a tema
            ("música", "guitarra"),                          # no se infiere pertenencia
            ("Excel", "Word"),
            ("clases", "clases"),                            # sin tema concreto
            ("coser", "cocer"),                              # palabras distintas, no errata
            ("Excel básico", "Excel avanzado"),              # quien enseña declara menos nivel
        ]
        for ofrece, busca in casos:
            with self.subTest(ofrece=ofrece, busca=busca):
                self.assertIsNone(comparar_tema(ofrece, busca))


class TestListas(unittest.TestCase):
    def test_elige_la_coincidencia_mas_directa_y_etiqueta(self):
        [c] = coincidencias(["Inglés"], ["English", "inglés"])
        self.assertEqual((c.tipo, c.etiqueta), (IGUAL, "Inglés"))
        [c] = coincidencias(["crear tablas en Excel para controlar gastos"],
                            ["organizar gastos usando Excel"])
        self.assertEqual(c.etiqueta, "crear tablas en Excel para controlar gastos → organizar gastos usando Excel")

    def test_aclaraciones_solo_de_lo_no_cubierto(self):
        c = comparar(["inglés", "Excel"], ["English", "Excel avanzado"])
        self.assertEqual([x.ofrece for x in c.coincidencias], ["inglés"])
        self.assertEqual([(a.ofrece, a.busca) for a in c.aclaraciones], [("Excel", "Excel avanzado")])
        self.assertTrue(c.cubre)
        self.assertFalse(c.requiere_aclaracion)   # ya hay una coincidencia clara


if __name__ == "__main__":
    unittest.main()

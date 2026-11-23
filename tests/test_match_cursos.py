"""Agente de match por cursos. Datos ficticios; nunca se conecta a Notion."""
import contextlib
import io
import os
import unittest
from unittest import mock

import match_cursos
from encuentros.automatico import CORREO_DUPLICADO, CORREO_FALTA
from encuentros.correo import contiene_correo
from encuentros.cursos import MOTIVO_SIN_AUTORIZACION
from encuentros.match_cursos import (
    RECIPROCO, UNA_DIRECCION, Coincidencia, emparejar_por_cursos, informe, recuentos,
)
from encuentros.notion_api import DS_PARTICIPANTES, ClienteNotion
from tests.test_automatico import persona
from tests.test_notion_api import FILA_PARTICIPANTE, HttpFalso


def p(pid, ofrece="", quiere="", n=None, **kw):
    """Perfil ficticio con correo válido y único; sin horario, zona ni minutos."""
    alias = kw.pop("alias", pid.capitalize())
    base = dict(id_consecutivo=n, minutos=None)
    base.update(kw)
    return persona(pid, alias, ofrece, quiere, None, None, **base)


def pares(lista):
    return [(x.ref_a, x.ref_b, x.tipo) for x in lista]


class TestEmparejar(unittest.TestCase):
    def test_reciproco(self):
        r = emparejar_por_cursos([p("ana", "Cerámica", "Guitarra", n=1), p("beto", "Guitarra", "Cerámica", n=2)])
        self.assertEqual(pares(r.reciprocos), [("fila #1", "fila #2", RECIPROCO)])
        [x] = r.reciprocos
        self.assertEqual((x.a_ensena, x.b_ensena),
                         ((Coincidencia("Cerámica", "Cerámica"),), (Coincidencia("Guitarra", "Guitarra"),)))
        self.assertEqual(r.una_direccion, [])

    def test_en_una_direccion_quien_ensena_va_primero(self):
        r = emparejar_por_cursos([p("ana", "", "Guitarra", n=1), p("beto", "Guitarra", "", n=2)])
        self.assertEqual(pares(r.una_direccion), [("fila #2", "fila #1", UNA_DIRECCION)])
        self.assertEqual(r.reciprocos, [])

    def test_los_dos_tipos_por_separado(self):
        r = emparejar_por_cursos([
            p("ana", "Cerámica", "Guitarra", n=1), p("beto", "Guitarra", "Cerámica", n=2),
            p("caro", "Cerámica", "", n=3),
        ])
        self.assertEqual(pares(r.reciprocos), [("fila #1", "fila #2", RECIPROCO)])
        # caro enseña Cerámica a beto, que la quiere aprender.
        self.assertEqual(pares(r.una_direccion), [("fila #3", "fila #2", UNA_DIRECCION)])

    def test_mismo_texto_sin_mayusculas_ni_tildes(self):
        r = emparejar_por_cursos([p("ana", "INGLÉS ", "x", n=1), p("beto", "", "ingles", n=2)])
        [x] = r.una_direccion
        self.assertEqual(x.a_ensena, (Coincidencia("INGLÉS", "ingles"),))

    def test_temas_parecidos_no_coinciden(self):
        r = emparejar_por_cursos([p("ana", "Soporte computadoras", n=1), p("beto", "", "Soporte computadores", n=2)])
        self.assertEqual((r.reciprocos, r.una_direccion), ([], []))

    def test_un_curso_por_linea(self):
        r = emparejar_por_cursos([p("ana", "Excel, Word y PowerPoint\nGuitarra", n=1),
                                  p("beto", "", "Guitarra\nExcel, Word y PowerPoint", n=2)])
        [x] = r.una_direccion
        self.assertEqual([c.curso for c in x.a_ensena], ["Excel, Word y PowerPoint", "Guitarra"])

    def test_ignora_idioma_horario_minutos_zona_y_modalidad(self):
        r = emparejar_por_cursos([
            p("ana", "Cerámica", "Guitarra", n=1, idioma=["Inglés"], modalidad="Presencial"),
            p("beto", "Guitarra", "Cerámica", n=2, idioma="Español", zona_horaria="Zona/Inexistente"),
        ])
        self.assertEqual(len(r.reciprocos), 1)

    def test_correo_que_falta_o_duplicado_excluye(self):
        r = emparejar_por_cursos([
            p("ana", "Cerámica", "Guitarra", n=1, correo="Comun@example.org"),
            p("beto", "Guitarra", "Cerámica", n=2, correo=" comun@example.ORG"),
            p("caro", "Guitarra", "Cerámica", n=3, correo=None),
        ])
        self.assertEqual((r.reciprocos, r.una_direccion), ([], []))
        self.assertEqual(r.excluidos, {CORREO_DUPLICADO: 2, CORREO_FALTA: 1})
        self.assertEqual((r.perfiles, r.considerados), (3, 0))

    def test_duplicado_con_una_fila_sin_cursos_tambien_excluye(self):
        r = emparejar_por_cursos([p("ana", "Cerámica", "Guitarra", n=1),
                                  p("beto", "Guitarra", "Cerámica", n=2),
                                  p("caro", n=3, correo="ANA@example.org")])
        self.assertEqual(r.reciprocos, [])

    def test_mismo_alias_no_se_empareja_pero_si_con_otras(self):
        r = emparejar_por_cursos([
            p("s1", "Cerámica", "Guitarra", n=1, alias="Persona Ficticia"),
            p("s2", "Guitarra", "Cerámica", n=2, alias="persona  ficticia"),
            p("beto", "Guitarra", "Cerámica", n=3),
        ])
        self.assertEqual(r.pares_mismo_alias, 1)
        self.assertEqual(pares(r.reciprocos), [("fila #1", "fila #3", RECIPROCO)])

    def test_mas_de_siete_no_se_usa_ese_campo(self):
        ocho = "\n".join(f"Tema {i}" for i in range(8))
        r = emparejar_por_cursos([p("ana", ocho, "Guitarra", n=1), p("beto", "Guitarra", "Tema 1", n=2)])
        self.assertEqual(pares(r.una_direccion), [("fila #2", "fila #1", UNA_DIRECCION)])
        self.assertEqual(r.campos_con_demasiados, 1)

    def test_sin_autorizacion_se_excluye(self):
        r = emparejar_por_cursos([p("ana", "Cerámica", "Guitarra", n=1, autoriza=False),
                                  p("beto", "Guitarra", "Cerámica", n=2)])
        self.assertEqual((r.reciprocos, r.una_direccion), ([], []))
        self.assertEqual(r.excluidos, {MOTIVO_SIN_AUTORIZACION: 1})

    def test_sin_autorizacion_cuenta_para_duplicados(self):
        # Aunque no autorice, su correo sigue contando: no se unen ni se confunden filas.
        r = emparejar_por_cursos([p("ana", "Cerámica", "Guitarra", n=1),
                                  p("beto", "Guitarra", "Cerámica", n=2),
                                  p("caro", n=3, autoriza=False, correo="ana@example.org")])
        self.assertEqual(r.reciprocos, [])
        self.assertEqual(r.excluidos, {CORREO_DUPLICADO: 1, MOTIVO_SIN_AUTORIZACION: 1})

    def test_orden_mas_cursos_primero(self):
        r = emparejar_por_cursos([
            p("ana", "A\nB", "C\nD", n=1), p("beto", "C", "A", n=2), p("caro", "C\nD", "A\nB", n=3)])
        self.assertEqual([x.ref_b for x in r.reciprocos], ["fila #3", "fila #2"])

    def test_no_compara_una_fila_consigo_misma(self):
        r = emparejar_por_cursos([p("ana", "Cerámica", "Cerámica", n=1)])
        self.assertEqual((r.reciprocos, r.una_direccion), ([], []))


class TestInformes(unittest.TestCase):
    def resultado(self):
        return emparejar_por_cursos([
            p("ana", "Cerámica ficticia", "Guitarra ficticia", n=1, alias="Ana Ficticia"),
            p("beto", "Guitarra ficticia", "Cerámica ficticia", n=2, alias="Beto Ficticio"),
            p("caro", "Cerámica ficticia", "", n=3, alias="Caro Ficticia"),
        ])

    def test_informe_con_cursos_y_filas_sin_alias_ni_correos(self):
        texto = "\n".join(informe(self.resultado()))
        self.assertIn("fila #1 ↔ fila #2", texto)
        self.assertIn("fila #3 → fila #2", texto)
        self.assertIn("Cerámica ficticia", texto)
        for privado in ("Ana Ficticia", "Beto", "Caro"):
            self.assertNotIn(privado, texto)
        self.assertFalse(contiene_correo(texto))

    def test_solo_recuentos_sin_cursos_ni_filas(self):
        texto = "\n".join(recuentos(self.resultado()))
        self.assertIn("Matches recíprocos: 1 · en una dirección: 1", texto)
        for privado in ("Cerámica", "Guitarra", "fila #", "Ana", "Beto", "Caro"):
            self.assertNotIn(privado, texto)
        self.assertFalse(contiene_correo(texto))


class TestScript(unittest.TestCase):
    def ejecutar(self, argv):
        http = HttpFalso([{"results": [FILA_PARTICIPANTE], "has_more": False}])
        salida = io.StringIO()
        with mock.patch.dict(os.environ, {"NOTION_TOKEN": "token-ficticio"}, clear=True), \
             mock.patch.object(match_cursos, "ClienteNotion", lambda token: ClienteNotion(token, abrir=http)), \
             contextlib.redirect_stdout(salida):
            codigo = match_cursos.main(argv)
        return codigo, salida.getvalue(), http

    def test_solo_consulta_participantes(self):
        codigo, salida, http = self.ejecutar(["--solo-recuentos"])
        self.assertEqual(codigo, 0)
        self.assertEqual([(m, u.split("/v1", 1)[1]) for m, u, _, _ in http.pedidos],
                         [("POST", f"/data_sources/{DS_PARTICIPANTES}/query")])
        self.assertIn("Perfiles leídos: 1", salida)
        for privado in ("Alba", "alba@example.org", "Fotografía", "Inglés", "fila #"):
            self.assertNotIn(privado, salida)

    def test_sin_token_no_consulta(self):
        salida = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(salida):
            self.assertEqual(match_cursos.main([]), 2)


if __name__ == "__main__":
    unittest.main()

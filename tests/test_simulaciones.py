"""Las dos simulaciones (ciclo y Cursos) con un Notion SIMULADO. Datos ficticios.

Comprueba: solo consultas a Notion (ninguna escritura), ningún correo (no se crea
el servicio de Gmail), ninguna IA (no se crea el consultor de Ollama) y que
--solo-recuentos no muestra alias, correos, temas ni finales de ids.
"""
import contextlib
import copy
import io
import os
import unittest
from unittest import mock

import ciclo_automatico
import simular_cursos
from encuentros.notion_api import DS_CURSOS, DS_MATCHES, DS_PARTICIPANTES, DS_RESPUESTAS, ClienteNotion
from tests.apoyo import ZONAS_REALES
from tests.test_notion_api import FILA_PARTICIPANTE, HttpFalso, t


def sel(n):
    return {"type": "select", "select": {"name": n} if n else None}


def segunda_fila():
    f = copy.deepcopy(FILA_PARTICIPANTE)
    f["id"] = "bbbb-2222"
    p = f["properties"]
    p["Alias"] = t("Bruno", "title")
    p["Correo electrónico"] = {"type": "email", "email": "bruno@example.org"}
    p["Ofrece"], p["Quiere aprender"] = t("Inglés"), t("Fotografía")
    p["Disponibilidad + zona horaria"] = t("lunes 11:00-13:00")
    p["Zona horaria seleccionada"] = sel("America/Mexico_City")
    p["ID consecutivo"] = {"type": "unique_id", "unique_id": {"prefix": None, "number": 8}}
    return f


VACIO = {"results": [], "has_more": False}
PRIVADO = ("Alba", "Bruno", "alba@example.org", "bruno@example.org", "aaaa1111", "bbbb2222",
           "111", "222", "Fotografía", "Inglés")
ENTORNO = {"NOTION_TOKEN": "token-ficticio", "ANTROPIA_CLAVE_CODIGOS": "t" * 64,
           "ANTROPIA_FORMULARIO_URL": "https://ejemplo.invalid/simulacion"}


def no_debe_usarse(*a, **k):
    raise AssertionError("no debe usarse en la simulación")


class Base(unittest.TestCase):
    def ejecutar(self, modulo, argv, respuestas):
        self.http = HttpFalso(respuestas)
        salida = io.StringIO()
        entorno = {k: v for k, v in os.environ.items()
                   if k not in ("ANTROPIA_ANALISIS_SEMANTICO", "ANTROPIA_SALAS", "ANTROPIA_ACTIVO")}
        entorno.update(ENTORNO)
        with mock.patch.dict(os.environ, entorno, clear=True), \
             mock.patch.object(modulo, "ClienteNotion", lambda token: ClienteNotion(token, abrir=self.http)), \
             contextlib.redirect_stdout(salida):
            codigo = modulo.main(argv)
        return codigo, salida.getvalue()

    def assert_sin_datos_privados(self, texto):
        for dato in PRIVADO:
            self.assertNotIn(dato, texto, dato)

    def metodos(self):
        return [(m, u.split("/v1", 1)[1]) for m, u, _, _ in self.http.pedidos]


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestSimulacionDelCiclo(Base):
    def correr(self, argv):
        with mock.patch.object(ciclo_automatico, "EnvioGmailSMTP", no_debe_usarse), \
             mock.patch.object(ciclo_automatico.consultor_ollama, "crear_consultor_real", no_debe_usarse):
            return self.ejecutar(ciclo_automatico, argv,
                                 [{"results": [FILA_PARTICIPANTE, segunda_fila()], "has_more": False},
                                  VACIO, VACIO])

    def test_solo_consulta_no_envia_ni_usa_ia(self):
        codigo, salida = self.correr(["--simulacion", "--solo-recuentos"])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.metodos(), [
            ("POST", f"/data_sources/{DS_PARTICIPANTES}/query"),
            ("POST", f"/data_sources/{DS_MATCHES}/query"),
            ("POST", f"/data_sources/{DS_RESPUESTAS}/query"),
        ])
        self.assertIn("Modo: SIMULACIÓN", salida)
        self.assertIn("Matches nuevos: 1", salida)
        self.assertIn("Correos simulados: 2", salida)
        # Las escrituras solo se ANOTAN (crear el match y actualizarlo al enviar los avisos).
        self.assertRegex(salida, r"Escrituras que se habrían hecho en Notion: [1-9]")

    def test_solo_recuentos_no_muestra_datos(self):
        _, salida = self.correr(["--simulacion", "--solo-recuentos"])
        self.assert_sin_datos_privados(salida)
        self.assertNotIn("Aviso:", salida)

    def test_solo_recuentos_exige_simulacion(self):
        codigo, _ = self.ejecutar(ciclo_automatico, ["--solo-recuentos"], [])
        self.assertEqual(codigo, 2)
        self.assertEqual(self.http.pedidos, [])

    def test_el_cliente_de_la_simulacion_rechaza_escrituras(self):
        # Aunque algo intentara escribir, el cliente de solo lectura lo impediría.
        from encuentros.notion_api import ClienteSoloLectura, EscrituraNoPermitida
        c = ClienteSoloLectura(ClienteNotion("token-ficticio", abrir=HttpFalso([])))
        with self.assertRaises(EscrituraNoPermitida):
            c.crear(DS_MATCHES, {})


class TestSimulacionDeCursos(Base):
    CURSO = {"id": "cccc-0001", "properties": {
        "Tema": t("Cerámica ficticia", "title"),
        "Personas que ofrecen": {"type": "relation", "relation": [{"id": "dddd-9999"}], "has_more": False},
        "Personas que quieren aprender": {"type": "relation", "relation": [], "has_more": False}}}

    def correr(self, argv, papelera):
        return self.ejecutar(simular_cursos, argv, [
            {"results": [FILA_PARTICIPANTE], "has_more": False},
            {"results": [self.CURSO], "has_more": False},
            papelera,
        ])

    def test_solo_consulta_y_solo_recuentos(self):
        codigo, salida = self.correr(["--solo-recuentos"], {"object": "page", "in_trash": True})
        self.assertEqual(codigo, 0)
        self.assertEqual(self.metodos(), [
            ("POST", f"/data_sources/{DS_PARTICIPANTES}/query"),
            ("POST", f"/data_sources/{DS_CURSOS}/query"),
            ("GET", "/pages/dddd9999"),
        ])
        self.assert_sin_datos_privados(salida)
        self.assertNotIn("Cerámica ficticia", salida)
        self.assertIn("(eliminación confirmada: 1)", salida)
        self.assertIn("Temas nuevos: 2", salida)
        self.assertIn("Vínculos · quitar · Personas que ofrecen · tema existente", salida)

    def test_sin_acceso_no_se_propone_quitar(self):
        _, salida = self.correr(["--solo-recuentos"], {"object": "error", "status": 404})
        self.assertIn("(eliminación confirmada: 0)", salida)
        self.assertNotIn("· quitar ·", salida)
        self.assertIn("sus vínculos se mantienen", salida)

    def test_sin_token_no_consulta(self):
        salida = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(salida):
            self.assertEqual(simular_cursos.main([]), 2)


if __name__ == "__main__":
    unittest.main()

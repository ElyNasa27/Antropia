"""Base aparte «Matches por cursos [PRUEBA]»: plan, cliente guardado y script.

Datos ficticios; nunca se conecta a Notion (respuestas HTTP simuladas).
"""
import contextlib
import io
import os
import unittest
from unittest import mock

import match_cursos
from encuentros.match_cursos import Coincidencia, ParCursos, RECIPROCO, ResultadoCursos, UNA_DIRECCION
from encuentros.match_cursos_notion import (
    ACTUALIZAR, ADOPTAR, COL_ESTADO, CREAR, DS_MATCHES_CURSOS, MARCAR, VARIABLE_DS, VIGENTE, YA_NO_COINCIDE,
    clave_manual,
    ds_matches_cursos,
    ClienteSoloMatchesCursos, FilaMatchCursos, clave_par, planificar_escritura, propiedades,
)
from encuentros.notion_api import (
    DS_CURSOS, DS_MATCHES, DS_PARTICIPANTES, ClienteNotion, EscrituraNoPermitida,
)
from tests.test_notion_api import FILA_PARTICIPANTE, HttpFalso
from tests.test_simulaciones import segunda_fila

DS_NUEVA = "eeeeeeee-0000-0000-0000-000000000001"


def par(a="aaaa", b="bbbb", tipo=RECIPROCO, a_ens=("Cerámica",), b_ens=("Guitarra",)):
    return ParCursos(tipo, a, b, "fila #1", "fila #2",
                     tuple(Coincidencia(c, c) for c in a_ens), tuple(Coincidencia(c, c) for c in b_ens))


def resultado(*pares, perfiles=2):
    r = ResultadoCursos(perfiles=perfiles)
    for p in pares:
        (r.reciprocos if p.tipo == RECIPROCO else r.una_direccion).append(p)
    return r


def fila(pid="pag1", clave=None, estado=VIGENTE, tipo="Recíproco", a="aaaa", b="bbbb",
         a_ens="Cerámica", b_ens="Guitarra"):
    return FilaMatchCursos(pid, clave if clave is not None else clave_par(a, b), estado, tipo, a, b, a_ens, b_ens)


class TestPlan(unittest.TestCase):
    def test_clave_estable_sin_importar_el_orden(self):
        self.assertEqual(clave_par("bb-bb", "aaaa"), clave_par("aaaa", "bbbb"))
        self.assertEqual(clave_par("aaaa", "bbbb"), "cursos:aaaa:bbbb")

    def test_par_nuevo_se_crea_sin_alias_en_el_titulo(self):
        plan = planificar_escritura(resultado(par()), [])
        [a] = plan.acciones
        self.assertEqual(a.tipo, CREAR)
        props = a.propiedades
        self.assertEqual(props["Match"]["title"][0]["text"]["content"], "fila #1 ↔ fila #2")
        self.assertEqual(props["Tipo"]["select"]["name"], "Recíproco")
        self.assertEqual(props[COL_ESTADO]["select"]["name"], VIGENTE)
        self.assertEqual(props["Participante A"], {"relation": [{"id": "aaaa"}]})
        self.assertEqual(props["A enseña"]["rich_text"][0]["text"]["content"], "Cerámica")

    def test_una_direccion_usa_flecha_y_b_vacio(self):
        props = propiedades(par(tipo=UNA_DIRECCION, b_ens=()))
        self.assertEqual(props["Match"]["title"][0]["text"]["content"], "fila #1 → fila #2")
        self.assertEqual((props["Tipo"]["select"]["name"], props["B enseña"]), ("En una dirección", {"rich_text": []}))

    def test_sin_cambios_no_escribe(self):
        plan = planificar_escritura(resultado(par()), [fila()])
        self.assertEqual((plan.acciones, plan.sin_cambios), ([], 1))

    def test_cambio_de_cursos_o_tipo_actualiza(self):
        for f in (fila(a_ens="Otra cosa"), fila(tipo="En una dirección"), fila(estado=YA_NO_COINCIDE)):
            [a] = planificar_escritura(resultado(par()), [f]).acciones
            self.assertEqual((a.tipo, a.pagina), (ACTUALIZAR, "pag1"))

    def test_par_que_ya_no_coincide_se_marca_no_se_borra(self):
        plan = planificar_escritura(resultado(), [fila()])
        [a] = plan.acciones
        self.assertEqual((a.tipo, a.propiedades), (MARCAR, {COL_ESTADO: {"select": {"name": YA_NO_COINCIDE}}}))

    def test_ya_marcado_no_se_vuelve_a_marcar(self):
        self.assertEqual(planificar_escritura(resultado(), [fila(estado=YA_NO_COINCIDE)]).acciones, [])

    def test_sin_perfiles_leidos_no_se_marca_nada(self):
        plan = planificar_escritura(resultado(perfiles=0), [fila()])
        self.assertEqual(plan.acciones, [])
        self.assertTrue(plan.avisos)

    def test_claves_repetidas_no_se_tocan(self):
        plan = planificar_escritura(resultado(par()), [fila("p1"), fila("p2")])
        self.assertEqual(plan.acciones, [])
        self.assertEqual(len(plan.avisos), 1)

    def test_fila_sin_clave_se_adopta_y_sin_par_no_se_toca(self):
        # Decisión del 2026-11-23: las filas puestas a mano se adoptan (no se ignoran).
        plan = planificar_escritura(resultado(), [fila("p3", clave="", estado=None), fila("p4", clave="", b=None)])
        [a] = plan.acciones
        self.assertEqual((a.tipo, a.pagina, a.clave), (ADOPTAR, "p3", clave_manual("aaaa", "bbbb")))
        self.assertEqual(a.propiedades["Estado"], {"select": {"name": VIGENTE}})
        self.assertTrue(any("sin una persona en A" in x for x in plan.avisos))


# Columnas de la base creada en Notion el 2026-11-22 (leídas al crearla).
ESQUEMA_MATCHES_CURSOS = {"Match", "Participante A", "Participante B", "Tipo", "A enseña", "B enseña",
                          "Clave", "Estado", "Notas del sistema"}


class TestEsquema(unittest.TestCase):
    def test_columnas_y_opciones_coinciden_con_notion(self):
        props = propiedades(par())
        self.assertEqual(set(props), ESQUEMA_MATCHES_CURSOS)
        self.assertIn(props["Tipo"]["select"]["name"], ("Recíproco", "En una dirección"))
        self.assertIn(props[COL_ESTADO]["select"]["name"], (VIGENTE, YA_NO_COINCIDE))

    def test_base_por_defecto_es_la_creada_y_no_la_del_ciclo(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ds_matches_cursos(), DS_MATCHES_CURSOS)
        self.assertNotEqual(DS_MATCHES_CURSOS.replace("-", ""), DS_MATCHES.replace("-", ""))


class TestClienteGuardado(unittest.TestCase):
    def cliente(self, respuestas=()):
        self.http = HttpFalso(list(respuestas))
        return ClienteSoloMatchesCursos(ClienteNotion("token-ficticio", abrir=self.http), DS_NUEVA)

    def test_no_puede_ser_la_base_del_ciclo(self):
        with self.assertRaises(ValueError):
            ClienteSoloMatchesCursos(ClienteNotion("token-ficticio", abrir=HttpFalso([])), DS_MATCHES)

    def test_no_crea_en_otras_bases(self):
        c = self.cliente()
        for ds in (DS_PARTICIPANTES, DS_CURSOS, DS_MATCHES):
            with self.assertRaises(EscrituraNoPermitida):
                c.crear(ds, {})
        self.assertEqual(self.http.pedidos, [])

    def test_solo_actualiza_paginas_leidas_de_la_base_nueva(self):
        c = self.cliente([{"results": [{"id": "pag-propia", "properties": {}}], "has_more": False},
                          {"results": [{"id": "pag-ajena", "properties": {}}], "has_more": False},
                          {"id": "pag-propia"}])
        c.consultar(DS_NUEVA)
        c.consultar(DS_PARTICIPANTES)
        with self.assertRaises(EscrituraNoPermitida):
            c.actualizar("pag-ajena", {})
        with self.assertRaises(EscrituraNoPermitida):
            c.actualizar("otra-cualquiera", {})
        c.actualizar("pag-propia", {})
        self.assertEqual(self.http.pedidos[-1][0], "PATCH")
        with self.assertRaises(EscrituraNoPermitida):
            c.pedir("DELETE", "/blocks/x")


class TestScript(unittest.TestCase):
    PARTICIPANTES = {"results": [FILA_PARTICIPANTE, segunda_fila()], "has_more": False}
    VACIO = {"results": [], "has_more": False}

    def ejecutar(self, argv, respuestas, **entorno):
        self.http = HttpFalso(list(respuestas))
        salida, error = io.StringIO(), io.StringIO()
        env = {"NOTION_TOKEN": "token-ficticio", **entorno}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(match_cursos, "ClienteNotion", lambda token: ClienteNotion(token, abrir=self.http)), \
             contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
            codigo = match_cursos.main(argv)
        return codigo, salida.getvalue()

    def peticiones(self):
        return [(m, u.split("/v1", 1)[1], (c or {}).get("parent")) for m, u, _, c in self.http.pedidos]

    def test_informe_solo_lee_participantes(self):
        codigo, salida = self.ejecutar(["--solo-recuentos"], [self.PARTICIPANTES])
        self.assertEqual(codigo, 0)
        self.assertEqual(self.peticiones(), [("POST", f"/data_sources/{DS_PARTICIPANTES}/query", None)])
        self.assertIn("Matches recíprocos: 1", salida)

    def test_ensayo_no_escribe(self):
        codigo, salida = self.ejecutar(["--ensayo-escritura", "--solo-recuentos"],
                                       [self.PARTICIPANTES, self.VACIO], **{VARIABLE_DS: DS_NUEVA})
        self.assertEqual(codigo, 0)
        self.assertEqual([m for m, _, _ in self.peticiones()], ["POST", "POST"])
        self.assertTrue(all(u.endswith("/query") for _, u, _ in self.peticiones()))
        self.assertIn("ENSAYO: no se ha escrito nada", salida)
        self.assertIn("crear 1", salida)

    def test_escribir_exige_el_segundo_cierre_y_otra_base(self):
        for argv, entorno in ((["--escribir"], {}),
                              (["--escribir"], {VARIABLE_DS: DS_NUEVA}),
                              (["--escribir"], {match_cursos.VARIABLE_ESCRIBIR: "sí"}),
                              (["--escribir"], {VARIABLE_DS: DS_MATCHES, match_cursos.VARIABLE_ESCRIBIR: "si"})):
            codigo, _ = self.ejecutar(argv, [], **entorno)
            self.assertEqual(codigo, 2, (argv, entorno))
            self.assertEqual(self.http.pedidos, [], (argv, entorno))

    def test_escribir_solo_crea_en_la_base_nueva(self):
        codigo, salida = self.ejecutar(
            ["--escribir", "--solo-recuentos"], [self.PARTICIPANTES, self.VACIO, {"id": "nueva-1"}],
            **{VARIABLE_DS: DS_NUEVA, match_cursos.VARIABLE_ESCRIBIR: "si"})
        self.assertEqual(codigo, 0)
        self.assertEqual(self.peticiones(), [
            ("POST", f"/data_sources/{DS_PARTICIPANTES}/query", None),
            ("POST", f"/data_sources/{DS_NUEVA}/query", None),
            ("POST", "/pages", {"type": "data_source_id", "data_source_id": DS_NUEVA}),
        ])
        self.assertIn("Escrituras hechas: 1.", salida)
        self.assertIn("Ningún correo enviado.", salida)
        for privado in ("Alba", "Bruno", "alba@example.org", "Fotografía"):
            self.assertNotIn(privado, salida)


if __name__ == "__main__":
    unittest.main()

"""Simulación de Cursos (solo lectura). Datos ficticios; nunca se conecta a Notion."""
import io
import unittest
import urllib.error

from encuentros.automatico import CORREO_DUPLICADO, CORREO_FALTA, CORREO_NO_VALIDO
from encuentros.correo import contiene_correo
from encuentros.cursos import (
    AÑADIR, MAX_TEMAS, MOTIVO_FILA_NO_EXISTE, MOTIVO_NUEVO, MOTIVO_SIN_AUTORIZACION,
    MOTIVO_YA_NO_INDICA, OFRECEN, QUIEREN, QUITAR, TemaExistente, clave_tema, informe,
    planificar, temas_de_campo,
)
from encuentros.notion_api import (
    DS_CURSOS, DS_PARTICIPANTES, AlmacenNotion, ClienteNotion, ClienteSoloLectura,
    EscrituraNoPermitida, leer_cursos,
)
from tests.test_automatico import persona
from tests.test_notion_api import FILA_PARTICIPANTE, HttpFalso, t


def p(pid, ofrece="", quiere="", n=None, **kw):
    """Perfil ficticio; por defecto con autorización y correo válido y único."""
    return persona(pid, kw.pop("alias", pid.capitalize()), ofrece, quiere, None, None,
                   id_consecutivo=n, **kw)


def tema(tid, titulo, ofrecen=(), quieren=(), incompleta=False):
    return TemaExistente(tid, titulo, frozenset(ofrecen), frozenset(quieren), incompleta)


def cambios(plan):
    return {(c.accion, c.tema, c.campo, c.persona, c.motivo) for c in plan.cambios}


class TestTemasDeCampo(unittest.TestCase):
    def test_un_tema_por_linea(self):
        self.assertEqual(temas_de_campo("Fotografía\n\n  Excel básico \nfotografia\n"),
                         (["Fotografía", "Excel básico"], None))

    def test_misma_lectura_que_el_ciclo(self):
        # Una sola línea (respuesta anterior): separación anterior, igual que el ciclo.
        self.assertEqual(temas_de_campo("Excel, Word y PowerPoint")[0], ["Excel", "Word", "PowerPoint"])
        # Varias líneas: cada línea es un tema, aunque tenga comas o «y».
        self.assertEqual(temas_de_campo("Excel, Word y PowerPoint\nGuitarra")[0],
                         ["Excel, Word y PowerPoint", "Guitarra"])

    def test_siete_si_ocho_no(self):
        siete = "\n".join(f"Tema {i}" for i in range(MAX_TEMAS))
        self.assertIsNone(temas_de_campo(siete)[1])
        temas, problema = temas_de_campo(siete + "\nTema extra")
        self.assertEqual(len(temas), 8)                 # no se descarta ninguno
        self.assertIn("requiere aclaración", problema)

    def test_vacio(self):
        self.assertEqual(temas_de_campo(None), ([], None))

    def test_clave_no_fusiona_temas_parecidos(self):
        self.assertEqual(clave_tema(" Inglés  Básico. "), clave_tema("ingles basico"))
        self.assertNotEqual(clave_tema("Soporte computadoras"), clave_tema("Soporte computadores"))


class TestPlanificar(unittest.TestCase):
    def test_tema_nuevo_con_sus_vinculos(self):
        plan = planificar([p("ana", "Cerámica", "Guitarra", n=1), p("beto", "Guitarra", "", n=2)], [])
        self.assertEqual(plan.temas_nuevos, ["Cerámica", "Guitarra"])
        self.assertEqual(cambios(plan), {
            (AÑADIR, "Cerámica", OFRECEN, "fila #1", MOTIVO_NUEVO),
            (AÑADIR, "Guitarra", QUIEREN, "fila #1", MOTIVO_NUEVO),
            (AÑADIR, "Guitarra", OFRECEN, "fila #2", MOTIVO_NUEVO),
        })

    def test_tema_existente_sin_distinguir_mayusculas_ni_tildes(self):
        plan = planificar([p("ana", "INGLES", n=1)], [tema("c1", "inglés")])
        self.assertEqual(plan.temas_nuevos, [])
        self.assertEqual(cambios(plan), {(AÑADIR, "inglés", OFRECEN, "fila #1", MOTIVO_NUEVO)})

    def test_vinculo_ya_existente_no_se_repite(self):
        plan = planificar([p("ana", "Inglés", n=1)], [tema("c1", "Inglés", ofrecen={"ana"})])
        self.assertEqual(plan.cambios, [])

    def test_quita_vinculos_solo_a_filas_eliminadas_confirmadas(self):
        plan = planificar([p("ana", "Inglés", n=1)],
                          [tema("c1", "Inglés", ofrecen={"ana", "borrada1"}, quieren={"borrada2"})],
                          eliminadas_confirmadas=frozenset({"borrada1", "borrada2"}))
        self.assertEqual(cambios(plan), {
            (QUITAR, "Inglés", OFRECEN, "fila …rrada1", MOTIVO_FILA_NO_EXISTE),   # sin «ID consecutivo»
            (QUITAR, "Inglés", QUIEREN, "fila …rrada2", MOTIVO_FILA_NO_EXISTE),
        })

    def test_tema_sin_personas_se_conserva(self):
        plan = planificar([p("ana", "Cerámica", n=1)], [tema("c1", "Soporte computadoras", ofrecen={"borrada"})],
                          eliminadas_confirmadas=frozenset({"borrada"}))
        self.assertEqual(plan.sin_personas, ["Soporte computadoras"])
        self.assertFalse(any(c.tema_id == "c1" and c.accion != QUITAR for c in plan.cambios))

    def test_temas_parecidos_no_se_fusionan(self):
        plan = planificar([p("ana", "Soporte computadores", n=1)],
                          [tema("c1", "Soporte computadoras"), tema("c2", "Soporte computadores")])
        self.assertEqual(cambios(plan), {(AÑADIR, "Soporte computadores", OFRECEN, "fila #1", MOTIVO_NUEVO)})
        self.assertEqual(plan.sin_personas, ["Soporte computadoras"])

    def test_sin_autorizacion_no_se_vincula_y_se_propone_quitar(self):
        plan = planificar([p("ana", "Inglés", n=1, autoriza=False)], [tema("c1", "Inglés", ofrecen={"ana"})])
        self.assertEqual(cambios(plan), {(QUITAR, "Inglés", OFRECEN, "fila #1", MOTIVO_SIN_AUTORIZACION)})
        self.assertEqual(plan.no_vinculables, {MOTIVO_SIN_AUTORIZACION: 1})

    def test_correo_duplicado_no_vincula_ni_quita(self):
        ps = [p("ana", "Inglés", n=1, correo="Comun@example.org"),
              p("beto", "Cerámica", n=2, correo=" comun@EXAMPLE.org")]
        plan = planificar(ps, [tema("c1", "Inglés", ofrecen={"ana"})])
        self.assertEqual(plan.cambios, [])                     # el vínculo actual se mantiene
        self.assertEqual(plan.no_vinculables, {CORREO_DUPLICADO: 2})
        self.assertEqual(plan.vinculables, 0)

    def test_correo_que_falta_o_no_valido_no_se_vincula(self):
        plan = planificar([p("ana", "Inglés", correo=None), p("beto", "Inglés", correo="no-es-correo")], [])
        self.assertEqual(plan.cambios, [])
        self.assertEqual(plan.no_vinculables, {CORREO_FALTA: 1, CORREO_NO_VALIDO: 1})

    def test_otros_datos_pendientes_no_impiden_vincular(self):
        # Sin disponibilidad, sin zona, varios idiomas y sin minutos: no es apta para el
        # ciclo, pero tiene correo válido y único, así que se vincula.
        plan = planificar([p("ana", "Inglés", n=1, idioma=["Español", "Inglés"], minutos=None)], [])
        self.assertEqual(cambios(plan), {(AÑADIR, "Inglés", OFRECEN, "fila #1", MOTIVO_NUEVO)})

    def test_ya_no_indica_el_tema(self):
        plan = planificar([p("ana", "Cerámica", "Guitarra", n=1)],
                          [tema("c1", "Inglés", ofrecen={"ana"}, quieren={"ana"})])
        self.assertIn((QUITAR, "Inglés", OFRECEN, "fila #1", MOTIVO_YA_NO_INDICA), cambios(plan))
        self.assertIn((QUITAR, "Inglés", QUIEREN, "fila #1", MOTIVO_YA_NO_INDICA), cambios(plan))

    def test_mas_de_siete_temas_no_toca_ese_campo(self):
        ocho = "\n".join(f"Tema {i}" for i in range(8))
        plan = planificar([p("ana", ocho, "Guitarra", n=1)], [tema("c1", "Inglés", ofrecen={"ana"})])
        self.assertEqual(cambios(plan), {(AÑADIR, "Guitarra", QUIEREN, "fila #1", MOTIVO_NUEVO)})
        self.assertTrue(any("más de 7 temas" in a for a in plan.avisos))

    def test_alias_repetido_con_correos_distintos_se_senala_sin_unir(self):
        ps = [p("s1", "Inglés", n=1, alias="Persona Ficticia"), p("s2", "Inglés", n=2, alias="persona ficticia ")]
        plan = planificar(ps, [])
        self.assertEqual(cambios(plan), {(AÑADIR, "Inglés", OFRECEN, "fila #1", MOTIVO_NUEVO),
                                         (AÑADIR, "Inglés", OFRECEN, "fila #2", MOTIVO_NUEVO)})
        self.assertTrue(any("podrían ser la misma persona" in a for a in plan.avisos))

    def test_temas_repetidos_en_cursos_no_se_tocan(self):
        plan = planificar([p("ana", "Inglés", n=1)], [tema("c1", "Inglés"), tema("c2", "inglés ")])
        self.assertEqual((plan.cambios, plan.temas_nuevos), ([], []))
        self.assertTrue(any("repetidos" in a for a in plan.avisos))

    def test_fila_que_solo_no_aparece_no_se_quita(self):
        # Podría faltar acceso: que no aparezca en la lectura no prueba que se eliminó.
        plan = planificar([p("ana", "Inglés", n=1)], [tema("c1", "Inglés", ofrecen={"ana", "invisible"})])
        self.assertFalse(plan.de(QUITAR))
        self.assertTrue(any("no aparecen al leer Participantes" in a for a in plan.avisos))
        self.assertEqual(plan.sin_personas, [])

    def test_eliminada_confirmada_pero_sin_leer_participantes_no_se_quita(self):
        plan = planificar([], [tema("c1", "Inglés", ofrecen={"x"})], eliminadas_confirmadas=frozenset({"x"}))
        self.assertFalse(plan.de(QUITAR))

    def test_lectura_incompleta_no_propone_quitar(self):
        plan = planificar([p("ana", "Cerámica", n=1, autoriza=True)],
                          [tema("c1", "Inglés", ofrecen={"borrada", "ana"}, incompleta=True)],
                          eliminadas_confirmadas=frozenset({"borrada"}))
        self.assertFalse(plan.de(QUITAR))      # ni la eliminada ni «ya no indica este tema»
        self.assertTrue(any("no devolvió completos" in a for a in plan.avisos))

    def test_sin_participantes_leidos_no_propone_quitar(self):
        plan = planificar([], [tema("c1", "Inglés", ofrecen={"x"})])
        self.assertFalse(plan.de(QUITAR))

    def test_informe_sin_alias_ni_correos(self):
        ps = [p("ana", "Inglés", n=1, alias="Ana Ficticia"), p("beto", "Inglés", n=2, correo="dup@example.org"),
              p("caro", "Inglés", n=3, correo="DUP@example.org")]
        texto = "\n".join(informe(planificar(ps, [tema("c1", "Cerámica", ofrecen={"borrada"})])))
        self.assertIn("SIMULACIÓN", texto)
        self.assertNotIn("Ana Ficticia", texto)
        self.assertFalse(contiene_correo(texto))
        self.assertIn("fila #1", texto)


def multi(*n):
    return {"type": "multi_select", "multi_select": [{"name": x} for x in n]}


def rel(*ids, has_more=False):
    return {"type": "relation", "relation": [{"id": i} for i in ids], "has_more": has_more}


class TestLecturaYSoloLectura(unittest.TestCase):
    PAGINA_CURSO = {"id": "cccc-0001", "properties": {
        "Tema": t("Fotografía", "title"), OFRECEN: rel("aaaa-1111"), QUIEREN: rel(has_more=True)}}

    def test_leer_cursos(self):
        http = HttpFalso([{"results": [self.PAGINA_CURSO], "has_more": False}])
        [c] = leer_cursos(ClienteSoloLectura(ClienteNotion("token-ficticio", abrir=http)))
        self.assertEqual((c.id, c.titulo, c.ofrecen, c.quieren, c.lectura_incompleta),
                         ("cccc0001", "Fotografía", frozenset({"aaaa1111"}), frozenset(), True))

    def test_cliente_de_solo_lectura_no_escribe(self):
        http = HttpFalso([])
        c = ClienteSoloLectura(ClienteNotion("token-ficticio", abrir=http))
        for intento in (lambda: c.crear(DS_CURSOS, {}), lambda: c.actualizar("x", {}),
                        lambda: c.pedir("PATCH", "/pages/x", {})):
            with self.assertRaises(EscrituraNoPermitida):
                intento()
        self.assertEqual(http.pedidos, [])
        self.assertNotIn("token", repr(c).replace("token oculto", ""))

    def papelera(self, respuesta):
        http = HttpFalso([respuesta])
        r = ClienteSoloLectura(ClienteNotion("token-ficticio", abrir=http, esperar=lambda s: None)
                               ).esta_en_la_papelera("pppp-0001")
        [(metodo, url, _, cuerpo)] = http.pedidos
        self.assertEqual((metodo, url.rsplit("/", 1)[-1], cuerpo), ("GET", "pppp-0001", None))
        return r

    def test_papelera_confirmada_solo_si_notion_lo_dice(self):
        self.assertIs(self.papelera({"object": "page", "in_trash": True}), True)
        self.assertIs(self.papelera({"object": "page", "archived": True}), True)
        self.assertIs(self.papelera({"object": "page", "in_trash": False}), False)

    def test_sin_acceso_no_se_sabe(self):
        error = urllib.error.HTTPError("https://api.notion.com/v1/pages/x", 404, "Not Found", {},
                                       io.BytesIO(b'{"code": "object_not_found"}'))
        self.assertIsNone(self.papelera(error))
        self.assertIsNone(self.papelera({"object": "error"}))

    def test_simulacion_completa_solo_consulta(self):
        http = HttpFalso([{"results": [FILA_PARTICIPANTE], "has_more": False},
                          {"results": [self.PAGINA_CURSO], "has_more": False}])
        cliente = ClienteSoloLectura(ClienteNotion("token-ficticio", abrir=http))
        plan = planificar(AlmacenNotion(cliente).personas(), leer_cursos(cliente))
        self.assertEqual([(m, u.rsplit("/", 2)[-2]) for m, u, _, _ in http.pedidos],
                         [("POST", DS_PARTICIPANTES), ("POST", DS_CURSOS)])
        self.assertTrue(all(u.endswith("/query") for _, u, _, _ in http.pedidos))
        # «Fotografía» ya vincula a la fila; «Inglés» se crearía.
        self.assertEqual(plan.temas_nuevos, ["Inglés"])
        self.assertEqual(cambios(plan), {(AÑADIR, "Inglés", QUIEREN, "fila #7", MOTIVO_NUEVO)})


if __name__ == "__main__":
    unittest.main()

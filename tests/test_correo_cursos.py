"""Correos de coincidencias de cursos: texto, registro de envíos, vista y cierres.

Datos ficticios y servicios SIMULADOS: un Notion en memoria, el registro de envíos en
memoria y EnvioSimulado. Ninguna prueba envía correos ni se conecta a nada; se
comprueba además que el servicio real de Gmail nunca se crea.
"""
import contextlib
import copy
import io
import os
import unittest
from unittest import mock

import match_cursos

from encuentros.automatico import Persona
from encuentros.correo import EnvioSimulado, ErrorEnvioDudoso, contiene_correo
from encuentros.correo_cursos import (
    NO_COMPROBADO, PLANTILLA_PAGINA, SIN_RESPALDO, plantilla_sin_cambios, redactar,
)
from encuentros.envio_exclusivo import (
    CANCELADO, EN_CURSO, ESTADO_ENVIADO, PENDIENTE, POR_REVISAR, TERMINADA, Ejecucion, estado_de,
)
from encuentros.match_cursos import emparejar_por_cursos
from encuentros.match_cursos_notion import (
    COLUMNAS_CORREO, DS_MATCHES_CURSOS, VIGENTE, YA_NO_COINCIDE, FilaMatchCursos, RegistroNotion,
    actualizar_vistas, avisos_filas_manuales, clave_manual, clave_par, enviar_correos, filas_tras_el_plan, id_correo,
    planificar_envios, planificar_escritura, reenviar,
)
from encuentros.notion_api import DS_PARTICIPANTES, _id
from encuentros.reserva_envios import base_correo
from tests.test_envio_exclusivo import RegistroSimulado
from tests.test_notion_api import FILA_PARTICIPANTE
from tests.test_simulaciones import segunda_fila


def ficticia(pid, n, alias, ofrece, quiere, **kw):
    base = dict(id=pid, alias=alias, correo=f"{pid}@example.org", autoriza=True, ofrece=ofrece,
                quiere_aprender=quiere, id_consecutivo=n)
    base.update(kw)
    return Persona(**base)


ANA = dict(objetivo_concreto="Tocar tres canciones", minutos_seleccionados="45 minutos",
           respaldo="Título ficticio en música")
BETO = dict(objetivo_concreto="Hacer una taza secreta", minutos_seleccionados="30 minutos",
            respaldo="Diploma ficticio de cerámica")


def personas():
    return [ficticia("p1", 1, "Ana Ficticia", "Cerámica", "Guitarra", **ANA),
            ficticia("p2", 2, "Beto Ficticio", "Guitarra", "Cerámica", **BETO),
            ficticia("p3", 3, "Caro Ficticia", "Huerto", "", minutos_seleccionados="60 minutos",
                     objetivo_concreto="Objetivo secreto de Caro"),
            ficticia("p4", 4, "Dani Ficticio", "", "Huerto", minutos_seleccionados="15 minutos")]


INSTR = "Si te interesa, responde a este correo."


class TestTexto(unittest.TestCase):
    def setUp(self):
        self.ps = {p.id: p for p in personas()}
        self.r = emparejar_por_cursos(list(self.ps.values()))
        [self.rec] = self.r.reciprocos
        [self.una] = self.r.una_direccion

    def correo(self, par, lado):
        yo, otra = (par.a, par.b) if lado == "A" else (par.b, par.a)
        return redactar(par, lado, self.ps[yo], self.ps[otra], INSTR)

    def test_asunto_de_la_plantilla(self):
        asunto, _ = self.correo(self.rec, "A")
        self.assertEqual(asunto, "Ana Ficticia, tienes una posible oportunidad de intercambio en Antropia")

    def test_reciproco_tiene_las_dos_secciones(self):
        _, cuerpo = self.correo(self.rec, "A")
        self.assertIn("Lo que podrías aprender", cuerpo)
        self.assertIn("Curso o tema que ofrece Beto Ficticio: Guitarra.", cuerpo)
        self.assertIn("Lo que podrías compartir", cuerpo)
        self.assertIn("Curso o tema que ofreces: Cerámica.", cuerpo)
        self.assertNotIn("una sola dirección", cuerpo)

    def test_es_una_posibilidad_y_no_afirma_compatibilidad(self):
        _, cuerpo = self.correo(self.rec, "B")
        self.assertIn("posible oportunidad", cuerpo)
        self.assertIn(NO_COMPROBADO, cuerpo)
        self.assertIn("el encuentro solo se confirma cuando ambas personas aceptan", cuerpo)
        for afirmacion in ("compatible", "confirmado", "horario común", "mismo idioma"):
            self.assertNotIn(afirmacion, cuerpo.lower())

    def test_datos_propios_si_de_la_otra_persona_no(self):
        _, cuerpo = self.correo(self.rec, "A")             # Ana recibe
        self.assertIn("Tu objetivo al aprenderlo: Tocar tres canciones.", cuerpo)
        self.assertIn("Tu tiempo de enseñanza disponible: 45 minutos.", cuerpo)
        for de_beto in ("Hacer una taza secreta", "30 minutos", "Diploma ficticio", "p2@example.org"):
            self.assertNotIn(de_beto, cuerpo)
        self.assertIn(f"Experiencia o respaldo de Beto Ficticio: {SIN_RESPALDO}", cuerpo)
        self.assertNotIn("verificad", cuerpo.lower())
        self.assertFalse(contiene_correo(cuerpo))

    def test_una_direccion_quien_ensena(self):
        _, cuerpo = self.correo(self.una, "A")             # Caro enseña a Dani
        self.assertIn("una sola dirección: podrías enseñar a Dani Ficticio", cuerpo)
        self.assertIn("Lo que podrías compartir", cuerpo)
        self.assertNotIn("Lo que podrías aprender", cuerpo)
        self.assertIn("60 minutos", cuerpo)
        self.assertNotIn("Objetivo secreto de Caro", cuerpo.replace("Tu objetivo", ""))  # no hay sección de aprender

    def test_una_direccion_quien_aprende(self):
        _, cuerpo = self.correo(self.una, "B")             # Dani aprende de Caro
        self.assertIn("una sola dirección: Caro Ficticia podría enseñarte", cuerpo)
        self.assertIn("Lo que podrías aprender", cuerpo)
        self.assertNotIn("Lo que podrías compartir", cuerpo)
        self.assertNotIn("Tu tiempo de enseñanza", cuerpo)  # no enseña en este par
        for de_caro in ("Objetivo secreto de Caro", "60 minutos"):
            self.assertNotIn(de_caro, cuerpo)

    def test_instrucciones_configuradas(self):
        self.assertIn(INSTR, self.correo(self.rec, "A")[1])

    def test_plantilla_sin_cambios(self):
        self.assertTrue(plantilla_sin_cambios("2026-11-22T22:18:00.000Z"))
        for v in ("2026-11-23T10:00:00.000Z", None, ""):
            self.assertFalse(plantilla_sin_cambios(v))


# ---------------------------------------------------------------------------
# Notion SIMULADO en memoria (lectura y escritura con el formato de la API)
# ---------------------------------------------------------------------------
def _a_lectura(props: dict) -> dict:
    """Propiedades en formato de ESCRITURA -> formato de LECTURA de la API."""
    res = {}
    for nombre, v in props.items():
        if "title" in v or "rich_text" in v:
            tipo = "title" if "title" in v else "rich_text"
            res[nombre] = {"type": tipo, tipo: [{"plain_text": x["text"]["content"]} for x in v[tipo]]}
        elif "select" in v:
            res[nombre] = {"type": "select", "select": v["select"]}
        elif "relation" in v:
            res[nombre] = {"type": "relation", "relation": v["relation"]}
        elif "checkbox" in v:
            res[nombre] = {"type": "checkbox", "checkbox": v["checkbox"]}
    return res


ESQUEMA_VISTA = {"properties": {
    **{COLUMNAS_CORREO[l]["estado"]: {"type": "select", "select": {"options": [
        {"name": n} for n in (PENDIENTE, EN_CURSO, ESTADO_ENVIADO, POR_REVISAR)]}} for l in "AB"},
    **{COLUMNAS_CORREO[l][k]: {"type": "rich_text"} for l in "AB" for k in ("id", "registro")},
}}


class NotionFalso:
    """Imita ClienteNotion: consultar, crear, actualizar y pedir("GET", …)."""

    def __init__(self, participantes, esquema=ESQUEMA_VISTA, plantilla="2026-11-22T22:18:00.000Z"):
        self.participantes = {_id(p["id"]): copy.deepcopy(p) for p in participantes}
        self.filas: dict[str, dict] = {}
        self.esquema, self.plantilla = esquema, plantilla
        self.creadas_en, self.actualizadas = [], []
        self._n = 0

    def consultar(self, ds, filtro=None):
        if _id(ds) == _id(DS_PARTICIPANTES):
            pags = list(self.participantes.values())
            if filtro:
                correo = filtro["email"]["equals"]
                pags = [p for p in pags if p["properties"]["Correo electrónico"]["email"] == correo]
            return copy.deepcopy(pags)
        if _id(ds) == _id(DS_MATCHES_CURSOS):
            return copy.deepcopy(list(self.filas.values()))
        return []

    def crear(self, ds, props):
        self.creadas_en.append(_id(ds))
        self._n += 1
        pid = f"00000000-0000-0000-0000-{self._n:012d}"
        self.filas[_id(pid)] = {"id": pid, "properties": _a_lectura(props)}
        return {"id": pid}

    def actualizar(self, page_id, props):
        self.actualizadas.append(_id(page_id))
        self.filas[_id(page_id)]["properties"].update(_a_lectura(props))
        return {}

    def pedir(self, metodo, ruta, cuerpo=None):
        assert metodo == "GET", metodo
        if ruta == f"/pages/{PLANTILLA_PAGINA}":
            return {"object": "page", "last_edited_time": self.plantilla}
        if ruta.startswith("/data_sources/"):
            return self.esquema
        pid = _id(ruta.rsplit("/", 1)[1])
        return copy.deepcopy(self.participantes.get(pid) or self.filas[pid])


def participantes_ficticios():
    """Alba (fila #7) ofrece Fotografía y quiere Inglés; Bruno (fila #8), al revés."""
    return [FILA_PARTICIPANTE, segunda_fila()]


def leer_todo(notion):
    from encuentros.match_cursos_notion import ClienteSoloMatchesCursos, leer_filas
    from encuentros.notion_api import AlmacenNotion
    cliente = ClienteSoloMatchesCursos(notion, DS_MATCHES_CURSOS)
    ps = AlmacenNotion(cliente).personas()
    r = emparejar_por_cursos(ps)
    from encuentros.match_cursos_notion import aplicar
    aplicar(planificar_escritura(r, leer_filas(cliente, DS_MATCHES_CURSOS)), cliente, DS_MATCHES_CURSOS)
    return cliente, {p.id: p for p in ps}, r, leer_filas(cliente, DS_MATCHES_CURSOS)


def terminadas(*ids):
    return lambda ejecucion, reintento: TERMINADA if ejecucion in ids else "in_progress"


class TestEnvioConRegistro(unittest.TestCase):
    def setUp(self):
        self.notion = NotionFalso(participantes_ficticios())
        self.cliente, self.ps, self.r, self.filas = leer_todo(self.notion)
        self.reg = RegistroSimulado()
        [self.fila] = self.filas

    def enviar(self, servicio=None, ejecucion="E1", filas=None):
        servicio = servicio or EnvioSimulado()
        pend = planificar_envios(self.r, filas or self.filas, self.reg, terminadas())
        res = enviar_correos(pend, self.ps, self.cliente, servicio, self.reg, Ejecucion(ejecucion, "1", "n"), INSTR)
        return res, servicio

    def test_primer_envio_a_las_dos_personas_con_ids_distintos(self):
        res, envio = self.enviar()
        self.assertEqual(res.enviados, 2)
        ids = {c.destinatario_id: c.message_id for c in envio.enviados}
        self.assertEqual(ids, {"aaaa1111": id_correo(self.fila.clave, "A", 1),
                               "bbbb2222": id_correo(self.fila.clave, "B", 1)})
        self.assertNotEqual(ids["aaaa1111"], ids["bbbb2222"])
        self.assertEqual({c.para for c in envio.enviados}, {"alba@example.org", "bruno@example.org"})

    def test_segunda_ejecucion_no_reenvia_aunque_notion_este_vacio(self):
        self.enviar()
        res, envio = self.enviar(ejecucion="E2")                # la vista sigue vacía
        self.assertEqual((res.enviados, envio.enviados), (0, []))

    def test_vista_incoherente_impide_el_primer_envio(self):
        props = {COLUMNAS_CORREO["A"]["estado"]: {"select": {"name": ESTADO_ENVIADO}}}
        self.notion.actualizar(self.fila.id, props)                # Notion dice «Enviado»...
        _, _, _, filas = leer_todo(self.notion)                    # ...y el registro está vacío
        res, envio = self.enviar(filas=filas)
        self.assertEqual([c.destinatario_id for c in envio.enviados], ["bbbb2222"])   # solo B
        self.assertIn("la vista de Notion no coincide con el registro: revisar", res.no_enviados)
        self.assertEqual(estado_de(self.reg, base_correo(self.fila.clave, "A"), terminadas()).estado, PENDIENTE)

    def cambiar_participante(self, pid, **cambios):
        p = self.notion.participantes[pid]["properties"]
        if "autoriza" in cambios:
            p["Autorización para participar"] = {"type": "checkbox", "checkbox": cambios["autoriza"]}
        if "correo" in cambios:
            p["Correo electrónico"] = {"type": "email", "email": cambios["correo"]}
        if "ofrece" in cambios:
            p["Ofrece"] = {"type": "rich_text", "rich_text": [{"plain_text": cambios["ofrece"]}]}

    def test_autorizacion_retirada_antes_de_enviar(self):
        self.cambiar_participante("bbbb2222", autoriza=False)      # la OTRA persona (cuyo alias se comparte)
        res, envio = self.enviar()
        self.assertEqual(envio.enviados, [])
        self.assertEqual(res.no_enviados, {"sin autorización para participar (comprobado antes de enviar)": 2})
        for lado in "AB":
            self.assertEqual(estado_de(self.reg, base_correo(self.fila.clave, lado), terminadas()).estado, PENDIENTE)

    def test_autorizacion_retirada_entre_la_reserva_y_el_envio(self):
        original = self.notion.pedir
        lecturas = {"n": 0}

        def pedir(metodo, ruta, cuerpo=None):
            pg = original(metodo, ruta, cuerpo)
            if ruta.endswith("bbbb2222"):
                lecturas["n"] += 1
                if lecturas["n"] >= 2:                          # tras la comprobación previa
                    pg["properties"]["Autorización para participar"]["checkbox"] = False
            return pg
        self.notion.pedir = pedir
        res, envio = self.enviar()
        self.assertEqual(envio.enviados, [])
        e = estado_de(self.reg, base_correo(self.fila.clave, "A"), terminadas("E1"))
        self.assertEqual((e.estado, e.detalle), (POR_REVISAR, CANCELADO))
        # El lado B nunca llegó a reservar (su comprobación previa ya vio la autorización
        # retirada): sigue «Pendiente».
        self.assertEqual(estado_de(self.reg, base_correo(self.fila.clave, "B"), terminadas("E1")).estado, PENDIENTE)
        self.notion.pedir = original                            # la autorización vuelve
        res, envio = self.enviar(ejecucion="E2")
        # A (cancelado tras reservar) NUNCA se reintenta solo; B recibe su PRIMER envío.
        self.assertEqual([c.destinatario_id for c in envio.enviados], ["bbbb2222"])
        e = estado_de(self.reg, base_correo(self.fila.clave, "A"), terminadas("E1", "E2"))
        self.assertEqual((e.estado, e.detalle, e.intento), (POR_REVISAR, CANCELADO, 1))

    def test_correo_cambiado_repetido_o_cursos_distintos_no_envian(self):
        casos = (
            ("aaaa1111", dict(correo="otra@example.org"), "el correo de quien recibe cambió desde la lectura"),
            ("aaaa1111", dict(ofrece="Cocina"), "los cursos ya no coinciden como en la lectura"),
        )
        for pid, cambios, motivo in casos:
            self.setUp()
            self.cambiar_participante(pid, **cambios)
            res, envio = self.enviar()
            self.assertNotIn("aaaa1111", [c.destinatario_id for c in envio.enviados], motivo)
            self.assertIn(motivo, res.no_enviados)
        # Correo repetido en otra fila (alta nueva entre la lectura y el envío)
        self.setUp()
        otra = copy.deepcopy(FILA_PARTICIPANTE)
        otra["id"] = "cccc-3333"
        self.notion.participantes["cccc3333"] = otra
        res, envio = self.enviar()
        self.assertNotIn("aaaa1111", [c.destinatario_id for c in envio.enviados])
        self.assertIn("el correo de quien recibe está repetido (comprobado antes de enviar)", res.no_enviados)

    def test_vistas_se_calculan_desde_el_registro(self):
        self.enviar()
        self.assertEqual(actualizar_vistas(self.r, self.filas, self.cliente, self.reg, terminadas("E1")), 1)
        _, _, _, filas = leer_todo(self.notion)
        self.assertEqual(filas[0].vista("A"), (ESTADO_ENVIADO, id_correo(self.fila.clave, "A", 1)))
        self.assertEqual(actualizar_vistas(self.r, filas, self.cliente, self.reg, terminadas("E1")), 0)  # sin cambios
        # Una escritura tardía deja una vista vieja: la siguiente ejecución la corrige.
        self.notion.actualizar(self.fila.id, {COLUMNAS_CORREO["A"]["estado"]: {"select": {"name": POR_REVISAR}}})
        _, _, _, filas = leer_todo(self.notion)
        self.assertEqual(actualizar_vistas(self.r, filas, self.cliente, self.reg, terminadas("E1")), 1)
        _, _, _, filas = leer_todo(self.notion)
        self.assertEqual(filas[0].vista("A")[0], ESTADO_ENVIADO)

    def test_envio_manual_marcado_en_notion_se_respeta(self):
        # Alguien envió a mano el correo de A y puso «Enviado» en Notion.
        self.notion.actualizar(self.fila.id, {COLUMNAS_CORREO["A"]["estado"]: {"select": {"name": ESTADO_ENVIADO}}})
        _, _, _, filas = leer_todo(self.notion)
        res, envio = self.enviar(filas=filas)
        self.assertEqual([c.destinatario_id for c in envio.enviados], ["bbbb2222"])   # A no se repite
        actualizar_vistas(self.r, filas, self.cliente, self.reg, terminadas("E1"))
        _, _, _, filas = leer_todo(self.notion)
        self.assertEqual(filas[0].vista("A")[0], ESTADO_ENVIADO)                     # no se sobrescribe


def poner_fila_a_mano(notion, a="aaaa-1111", b="bbbb-2222", tipo="En una dirección", a_ens="Cocina ficticia",
                      b_ens="", pid="99999999-0000-0000-0000-000000000001"):
    """Una fila como las que una persona escribe en la base: sin «Clave» ni «Estado»."""
    rt = lambda t: {"type": "rich_text", "rich_text": [{"plain_text": t}] if t else []}  # noqa: E731
    notion.filas[_id(pid)] = {"id": pid, "properties": {
        "Match": {"type": "title", "title": [{"plain_text": "puesta a mano"}]},
        "Participante A": {"type": "relation", "relation": [{"id": a}] if a else []},
        "Participante B": {"type": "relation", "relation": [{"id": b}] if b else []},
        "Tipo": {"type": "select", "select": {"name": tipo} if tipo else None},
        "A enseña": rt(a_ens), "B enseña": rt(b_ens), "Notas del sistema": rt("escrita por una persona"),
    }}
    return _id(pid)


class TestFilasPuestasAMano(unittest.TestCase):
    """Las filas que una persona pone en «Matches por cursos [PRUEBA]» son la fuente: se
    toman sus personas (alias y correo desde Participantes) y sus cursos."""

    def preparar(self, **kw):
        self.notion = NotionFalso(participantes_ficticios())
        self.pid = poner_fila_a_mano(self.notion, **kw)
        self.cliente, self.ps, self.r, self.filas = leer_todo(self.notion)
        self.reg = RegistroNotion(self.cliente, self.filas)

    def enviar(self, ejecucion="E1", filas=None):
        filas = filas or leer_todo(self.notion)[3]
        reg = RegistroNotion(self.cliente, filas)
        pend = planificar_envios(self.r, filas, reg, terminadas())
        envio = EnvioSimulado()
        res = enviar_correos(pend, self.ps, self.cliente, envio, reg, Ejecucion(ejecucion, "1", "n"), INSTR)
        return res, envio

    def test_se_adopta_y_no_se_duplica_el_par_calculado(self):
        self.preparar()
        [f] = self.filas                                  # el par calculado no crea otra fila
        self.assertEqual((f.id, f.clave, f.estado), (self.pid, clave_manual("aaaa1111", "bbbb2222"), VIGENTE))

    def test_envia_a_las_dos_personas_con_sus_correos_y_los_cursos_escritos(self):
        self.preparar()
        res, envio = self.enviar()
        self.assertEqual(res.enviados, 2)
        por = {c.destinatario_id: c for c in envio.enviados}
        self.assertEqual({por["aaaa1111"].para, por["bbbb2222"].para}, {"alba@example.org", "bruno@example.org"})
        self.assertIn("Hola, Alba:", por["aaaa1111"].cuerpo)                 # alias desde Participantes
        self.assertIn("podrías enseñar a Bruno", por["aaaa1111"].cuerpo)    # A enseña (una dirección)
        self.assertIn("Curso o tema que ofreces: Cocina ficticia.", por["aaaa1111"].cuerpo)
        self.assertIn("Curso o tema que ofrece Alba: Cocina ficticia.", por["bbbb2222"].cuerpo)
        res, envio = self.enviar(ejecucion="E2")                             # nunca dos veces
        self.assertEqual(envio.enviados, [])

    def test_reciproca_puesta_a_mano(self):
        self.preparar(tipo="Recíproco", a_ens="Cocina ficticia", b_ens="Jardinería ficticia")
        _, envio = self.enviar()
        por = {c.destinatario_id: c.cuerpo for c in envio.enviados}
        self.assertIn("Curso o tema que ofreces: Cocina ficticia.", por["aaaa1111"])
        self.assertIn("Curso o tema que ofrece Bruno: Jardinería ficticia.", por["aaaa1111"])

    def test_nunca_se_marca_ya_no_coincide(self):
        self.preparar(a_ens="Algo que nadie pidió")
        plan = planificar_escritura(self.r, leer_todo(self.notion)[3])
        self.assertFalse([a for a in plan.acciones if a.pagina == self.pid])

    def test_ya_no_coincide_puesto_por_una_persona_detiene_el_envio(self):
        self.preparar()
        self.notion.actualizar(self.pid, {"Estado": {"select": {"name": YA_NO_COINCIDE}}})
        res, envio = self.enviar()
        self.assertEqual(envio.enviados, [])

    def test_si_la_fila_cambia_antes_de_enviar_no_se_envia(self):
        self.preparar()
        filas = leer_todo(self.notion)[3]
        self.notion.filas[self.pid]["properties"]["A enseña"] = {
            "type": "rich_text", "rich_text": [{"plain_text": "Otro curso"}]}
        res, envio = self.enviar(filas=filas)
        self.assertEqual(envio.enviados, [])
        self.assertIn("la fila puesta a mano cambió o ya no está «Vigente»", res.no_enviados)

    def test_filas_incompletas_no_se_usan_y_se_avisa(self):
        for kw, motivo in ((dict(tipo="Otro"), "«Tipo» no es"), (dict(a_ens=""), "falta «A enseña»"),
                           (dict(tipo="Recíproco", b_ens=""), "falta «B enseña»"),
                           (dict(b_ens="algo"), "«B enseña» tiene texto")):
            self.preparar(**kw)
            _, envio = self.enviar()
            self.assertEqual(envio.enviados, [], kw)
            self.assertTrue(any(motivo in x for x in avisos_filas_manuales(leer_todo(self.notion)[3])), kw)

    def test_sin_persona_en_b_no_se_adopta(self):
        self.preparar(b=None)
        self.assertEqual([f for f in self.filas if f.id == self.pid][0].clave, "")

    def test_autorizacion_retirada_o_mismo_alias(self):
        self.preparar()
        self.notion.participantes["bbbb2222"]["properties"]["Autorización para participar"]["checkbox"] = False
        _, envio = self.enviar()
        self.assertEqual(envio.enviados, [])
        self.preparar()
        self.notion.participantes["bbbb2222"]["properties"]["Alias"] = {
            "type": "title", "title": [{"plain_text": "alba"}]}
        res, envio = self.enviar()
        self.assertEqual(envio.enviados, [])
        self.assertIn("posible misma persona (mismo alias en las dos filas)", res.no_enviados)

    def test_ficha_que_no_se_puede_leer_se_salta_sin_error(self):
        # La fila apunta a una persona cuya ficha no se leyó (p. ej. la integración no la ve).
        self.preparar(b="cccc-3333")
        res, envio = self.enviar()                       # no lanza ninguna excepción
        clave = clave_manual("aaaa1111", "cccc3333")
        # (el par calculado Alba↔Bruno sí recibe sus correos: aquí no se usa --solo-filas-de-la-base)
        self.assertEqual([c for c in envio.enviados if c.match_id == clave], [])
        self.assertEqual(res.no_enviados,
                         {"no se pudo leer la ficha de alguna de las dos personas en Participantes": 2})
        base = base_correo(clave_manual("aaaa1111", "cccc3333"), "A")
        self.assertIsNone(RegistroNotion(self.cliente, leer_todo(self.notion)[3]).leer(f"{base}/reserva-1"))


class TestReenvioExacto(unittest.TestCase):
    def setUp(self):
        self.notion = NotionFalso(participantes_ficticios())
        self.cliente, self.ps, self.r, self.filas = leer_todo(self.notion)
        self.reg = RegistroSimulado()
        [self.fila] = self.filas
        # Primer envío a A que queda en DUDA.

        class Dudoso(EnvioSimulado):
            def enviar(s, correo):
                raise ErrorEnvioDudoso("x")
        pend = [e for e in planificar_envios(self.r, self.filas, self.reg, terminadas()) if e.lado == "A"]
        enviar_correos(pend, self.ps, self.cliente, Dudoso(), self.reg, Ejecucion("E1", "1", "n"), INSTR)

    def reenviar(self, identificador, consulta=None):
        envio = EnvioSimulado()
        antes = dict(self.reg.datos)
        inf = reenviar(identificador, self.r, self.filas, self.ps, self.cliente, envio, self.reg,
                       Ejecucion("H", "1", "h"), INSTR, consulta or terminadas("E1", "H"))
        return inf, envio, antes

    def test_identificador_exacto_reenvia_una_vez(self):
        inf, envio, _ = self.reenviar(id_correo(self.fila.clave, "A", 1))
        self.assertTrue(inf.enviado)
        [c] = envio.enviados
        self.assertEqual((c.destinatario_id, c.message_id), ("aaaa1111", id_correo(self.fila.clave, "A", 2)))

    def test_identificadores_no_validos(self):
        exacto = id_correo(self.fila.clave, "A", 1)
        for caso, identificador in {
            "incompleto": exacto[:-3], "prefijo": exacto.split(".a.")[0] + ".a.",
            "con espacios": exacto + " ", "del lado B": id_correo(self.fila.clave, "B", 1),
            "intento futuro": id_correo(self.fila.clave, "A", 2), "vacío": "", "no es texto": None,
        }.items():
            inf, envio, antes = self.reenviar(identificador)
            self.assertFalse(inf.enviado, caso)
            self.assertEqual((envio.enviados, self.reg.datos), ([], antes), caso)

    def test_identificador_de_un_intento_anterior(self):
        class Dudoso(EnvioSimulado):
            def enviar(s, correo):
                raise ErrorEnvioDudoso("x")
        reenviar(id_correo(self.fila.clave, "A", 1), self.r, self.filas, self.ps, self.cliente, Dudoso(),
                 self.reg, Ejecucion("H1", "1", "h"), INSTR, terminadas("E1", "H1"))
        inf, envio, _ = self.reenviar(id_correo(self.fila.clave, "A", 1), terminadas("E1", "H1", "H"))
        self.assertFalse(inf.enviado)
        inf, envio, _ = self.reenviar(id_correo(self.fila.clave, "A", 2), terminadas("E1", "H1", "H"))
        self.assertTrue(inf.enviado)

    def test_sin_prueba_de_que_termino_no_reenvia(self):
        self.reg.datos.pop(f"{base_correo(self.fila.clave, 'A')}/cierre-1")    # intento sin cierre
        inf, envio, _ = self.reenviar(id_correo(self.fila.clave, "A", 1), lambda e, r: "in_progress")
        self.assertFalse(inf.enviado)
        self.assertEqual(envio.enviados, [])


# ---------------------------------------------------------------------------
# Script con todo SIMULADO
# ---------------------------------------------------------------------------
TODO = {"ANTROPIA_ESCRIBIR_MATCHES_CURSOS": "si", "ANTROPIA_ENVIAR_CORREOS_CURSOS": "si",
        "ANTROPIA_CURSOS_INSTRUCCIONES": INSTR, "ANTROPIA_SMTP_USUARIO": "remitente@example.org",
        "ANTROPIA_SMTP_CLAVE": "clave-ficticia", "GITHUB_RUN_ID": "101", "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": "ficticio/antropia", "GITHUB_TOKEN": "token-ficticio"}


def no_debe_usarse(*a, **k):
    raise AssertionError("no debe crearse ningún servicio real")


class TestRegistroNotion(unittest.TestCase):
    """El registro de envíos guardado en la columna «Registro X» (Notion simulado)."""

    def setUp(self):
        self.notion = NotionFalso(participantes_ficticios())
        self.cliente, _, _, [self.fila] = leer_todo(self.notion)
        self.reg = RegistroNotion(self.cliente, [self.fila])
        self.base = base_correo(self.fila.clave, "A")

    def test_crear_leer_y_no_sobrescribir(self):
        self.assertIsNone(self.reg.leer(f"{self.base}/reserva-1"))
        self.assertIs(self.reg.crear(f"{self.base}/reserva-1", "mía"), True)
        self.assertEqual(self.reg.leer(f"{self.base}/reserva-1"), "mía")
        self.assertIs(self.reg.crear(f"{self.base}/reserva-1", "otra"), False)
        self.assertEqual(self.reg.leer(f"{self.base}/reserva-1"), "mía")
        # Lado B: columna distinta.
        self.assertIsNone(self.reg.leer(f"{base_correo(self.fila.clave, 'B')}/reserva-1"))

    def test_registro_roto_o_desconocido_no_permite_enviar(self):
        col = COLUMNAS_CORREO["A"]["registro"]
        self.notion.actualizar(self.fila.id, {col: {"rich_text": [{"type": "text", "text": {"content": "{roto"}}]}})
        with self.assertRaises(ValueError):
            self.reg.leer(f"{self.base}/reserva-1")
        self.assertIsNone(self.reg.crear(f"{self.base}/reserva-1", "mía"))
        with self.assertRaises(KeyError):
            self.reg.leer("antropia-correos/otra-base-a/reserva-1")
        self.assertIsNone(self.reg.crear("antropia-correos/otra-base-a/reserva-1", "x"))

    def test_si_la_relectura_no_muestra_la_entrada_no_es_nuestra(self):
        original = self.notion.actualizar
        self.notion.actualizar = lambda pid, props: {}            # la escritura «se pierde»
        self.assertIsNone(self.reg.crear(f"{self.base}/reserva-1", "mía"))
        self.notion.actualizar = original

    def test_envio_completo_con_el_registro_en_notion(self):
        r, ps = emparejar_por_cursos(list(leer_todo(self.notion)[1].values())), leer_todo(self.notion)[1]
        envio = EnvioSimulado()
        pend = planificar_envios(r, [self.fila], self.reg, terminadas())
        res = enviar_correos(pend, ps, self.cliente, envio, self.reg, Ejecucion("E1", "1", "n"), INSTR)
        self.assertEqual(res.enviados, 2)
        # Segunda ejecución (otro registro leído de nuevo): nada que enviar.
        _, _, _, filas = leer_todo(self.notion)
        reg2 = RegistroNotion(self.cliente, filas)
        self.assertEqual(planificar_envios(r, filas, reg2, terminadas("E1")), [])
        # La columna «Registro A» no contiene datos personales.
        texto = str(self.notion.filas[_id(self.fila.id)]["properties"][COLUMNAS_CORREO["A"]["registro"]])
        self.assertNotIn("@", texto)
        self.assertNotIn("Alba", texto)


class TestScript(unittest.TestCase):
    def ejecutar(self, argv, notion, envio=None, consulta=None, **entorno):
        salida, error = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"NOTION_TOKEN": "token-ficticio", **entorno}, clear=True), \
             mock.patch.object(match_cursos, "ClienteNotion", lambda t: notion), \
             mock.patch.object(match_cursos, "_crear_envio_real", (lambda: envio) if envio else no_debe_usarse), \
             mock.patch.object(match_cursos, "_crear_consulta_ejecuciones",
                               (lambda: consulta or terminadas("101"))), \
             contextlib.redirect_stdout(salida), contextlib.redirect_stderr(error):
            codigo = match_cursos.main(argv)
        return codigo, salida.getvalue() + error.getvalue()

    def test_faltan_requisitos_bloquea_antes_de_escribir(self):
        notion = NotionFalso(participantes_ficticios(), esquema={"properties": {}})
        entorno = {k: v for k, v in TODO.items() if not k.startswith("GITHUB")}
        codigo, salida = self.ejecutar(["--escribir", "--enviar", "--solo-recuentos"], notion, **entorno)
        self.assertEqual(codigo, 3)
        for falta in ("solo se envía desde GitHub Actions", "columnas de la vista"):
            self.assertIn(falta, salida)
        self.assertEqual((notion.creadas_en, notion.actualizadas), ([], []))

    def test_simulacion_cuenta_y_lista_lo_que_falta(self):
        notion = NotionFalso(participantes_ficticios())
        codigo, salida = self.ejecutar(["--ensayo-escritura", "--simular-correos", "--solo-recuentos"], notion)
        self.assertEqual(codigo, 0)
        self.assertIn("Correos que podrían enviarse como máximo", salida)
        self.assertIn(": 2", salida)
        self.assertIn("solo se envía desde GitHub Actions", salida)
        self.assertEqual((notion.creadas_en, notion.actualizadas), ([], []))
        for privado in ("Alba", "Bruno", "@example.org", "Fotografía"):
            self.assertNotIn(privado, salida)

    def test_envio_completo_simulado_y_sin_duplicados(self):
        notion, envio = NotionFalso(participantes_ficticios()), EnvioSimulado()
        codigo, salida = self.ejecutar(["--escribir", "--enviar", "--solo-recuentos"], notion, envio, **TODO)
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(len(envio.enviados), 2)
        self.assertIn("Correos enviados: 2", salida)
        self.assertEqual(set(notion.creadas_en), {_id(DS_MATCHES_CURSOS)})          # solo en la base aparte
        self.assertTrue(set(notion.actualizadas) <= set(notion.filas))             # solo sus filas
        [fila] = notion.filas.values()
        self.assertEqual(fila["properties"][COLUMNAS_CORREO["A"]["estado"]]["select"]["name"], ESTADO_ENVIADO)
        for privado in ("Alba", "Bruno", "@example.org"):
            self.assertNotIn(privado, salida)
        envio2 = EnvioSimulado()
        self.ejecutar(["--escribir", "--enviar", "--solo-recuentos"], notion, envio2, **{**TODO, "GITHUB_RUN_ID": "102"})
        self.assertEqual(envio2.enviados, [])

    def test_reenviar_por_linea_de_ordenes_exige_el_id_exacto(self):
        notion = NotionFalso(participantes_ficticios())

        class Dudoso(EnvioSimulado):
            def enviar(s, correo):
                raise ErrorEnvioDudoso("x")
        self.ejecutar(["--escribir", "--enviar"], notion, Dudoso(), **TODO)
        [fila] = notion.filas.values()
        clave = fila["properties"]["Clave"]["rich_text"][0]["plain_text"]
        envio = EnvioSimulado()
        otra = {**TODO, "GITHUB_RUN_ID": "102"}
        _, salida = self.ejecutar(["--escribir", "--reenviar", id_correo(clave, "A", 1)[:-2]], notion, envio,
                                  consulta=terminadas("101", "102"), **otra)
        self.assertEqual(envio.enviados, [])
        self.assertIn("Reenvío: no enviado", salida)
        _, salida = self.ejecutar(["--escribir", "--reenviar", id_correo(clave, "A", 1)], notion, envio,
                                  consulta=terminadas("101", "102"), **otra)
        self.assertEqual([c.message_id for c in envio.enviados], [id_correo(clave, "A", 2)])
        self.assertIn("Reenvío: enviado", salida)

    def test_solo_filas_de_la_base(self):
        # Alba y Bruno coinciden por cursos (el agente calcularía un par recíproco), pero hay
        # una fila puesta a mano entre ellos con otro curso: solo se usa esa fila.
        notion, envio = NotionFalso(participantes_ficticios()), EnvioSimulado()
        pid = poner_fila_a_mano(notion, a_ens="Cocina ficticia")
        _, salida = self.ejecutar(["--solo-filas-de-la-base", "--ensayo-escritura", "--simular-correos",
                                   "--solo-recuentos"], notion)
        self.assertIn("crear 0", salida)
        self.assertIn("adoptar filas puestas a mano 1", salida)
        self.assertEqual(notion.actualizadas, [])                     # el ensayo no escribe
        codigo, salida = self.ejecutar(["--solo-filas-de-la-base", "--escribir", "--enviar", "--solo-recuentos"],
                                       notion, envio, **TODO)
        self.assertEqual(codigo, 0, salida)
        self.assertEqual(list(notion.filas), [pid])                   # ninguna fila nueva
        self.assertEqual(len(envio.enviados), 2)
        self.assertTrue(all("Cocina ficticia" in c.cuerpo for c in envio.enviados))
        self.assertFalse(any("Fotografía" in c.cuerpo for c in envio.enviados))   # el par calculado no
        self.assertEqual(notion.filas[pid]["properties"]["Estado"]["select"]["name"], VIGENTE)

    def test_cierres_de_la_linea_de_ordenes(self):
        for argv, entorno in ((["--enviar"], TODO), (["--reenviar", "x"], TODO),
                              (["--escribir", "--enviar"], {"ANTROPIA_ESCRIBIR_MATCHES_CURSOS": "si"}),
                              (["--simular-correos"], {})):
            notion = NotionFalso(participantes_ficticios())
            codigo, _ = self.ejecutar(argv, notion, **entorno)
            self.assertEqual(codigo, 2, argv)
            self.assertEqual((notion.creadas_en, notion.actualizadas), ([], []), argv)


if __name__ == "__main__":
    unittest.main()

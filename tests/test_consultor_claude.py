"""Consultor de Claude Haiku 5.5 con un cliente SIMULADO: ninguna prueba llama a la API."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from encuentros.consultor_claude import (
    ESQUEMA, MODELO, VARIABLE_ACTIVACION, ConsultaFallida, ConsultorClaude, crear_consultor_real,
    crear_peticion,
)
from encuentros.temas_semantica import (
    CUBRE, ORIGEN_REGLAS, ORIGEN_SEMANTICO, REQUIERE, AnalizadorSemantico, construir_consulta,
)
from tests.apoyo import DESDE, nuevo_escenario

CLAUDE_BASICO = "Claude Code básico"
CODING_CLAUDE = "un poco de coding con Claude Code"
SOPORTE = "Soporte técnico"


def respuesta(texto=None, stop_reason="end_turn", con_thinking=True):
    bloques = [SimpleNamespace(type="thinking", thinking="")] if con_thinking else []
    if texto is not None:
        bloques.append(SimpleNamespace(type="text", text=texto))
    return SimpleNamespace(content=bloques, stop_reason=stop_reason)


class ClienteSimulado:
    """Imita client.messages.create y guarda cada petición. No usa la red."""

    def __init__(self, *respuestas):
        self._respuestas = list(respuestas)
        self.peticiones = []
        self.messages = self

    def create(self, **kw):
        self.peticiones.append(kw)
        r = self._respuestas.pop(0) if len(self._respuestas) > 1 else self._respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


CUBRE_JSON = json.dumps({"veredicto": CUBRE, "motivo": "simulado",
                         "coincidencias": [{"ofrece": CLAUDE_BASICO, "busca": CODING_CLAUDE}]},
                        ensure_ascii=False)


class TestPeticion(unittest.TestCase):
    def test_peticion_exacta(self):
        consulta = construir_consulta([CLAUDE_BASICO], [CODING_CLAUDE])
        p = crear_peticion(consulta)
        self.assertEqual(set(p), {"model", "max_tokens", "thinking", "output_config", "system", "messages"})
        self.assertEqual(p["model"], "claude-haiku-5-5")
        self.assertEqual(p["thinking"], {"type": "adaptive"})
        self.assertEqual(p["output_config"]["format"], {"type": "json_schema", "schema": ESQUEMA})
        self.assertEqual(p["system"], consulta["instrucciones"])
        [m] = p["messages"]
        self.assertEqual(m["role"], "user")
        self.assertEqual(json.loads(m["content"]),
                         {"ofrece": [CLAUDE_BASICO], "quiere_aprender": [CODING_CLAUDE]})

    def test_sin_parametros_que_haiku_5_5_rechaza(self):
        p = crear_peticion(construir_consulta(["a"], ["b"]))
        for prohibido in ("temperature", "top_p", "top_k", "fallbacks", "tool_choice"):
            self.assertNotIn(prohibido, p)
        self.assertEqual(p["messages"][-1]["role"], "user")    # sin texto de respuesta preescrito


class TestConsultor(unittest.TestCase):
    def test_lee_el_json_aunque_haya_bloque_thinking(self):
        c = ConsultorClaude(ClienteSimulado(respuesta(CUBRE_JSON)))
        r = c(construir_consulta([CLAUDE_BASICO], [CODING_CLAUDE]))
        self.assertEqual(r["veredicto"], CUBRE)

    def test_fallos_lanzan_consulta_fallida(self):
        for nombre, resp in (("rechazo", respuesta(None, "refusal")),
                             ("cortada", respuesta('{"veredicto": "cu', "max_tokens")),
                             ("sin texto", respuesta(None)),
                             ("no json", respuesta("cubre, claramente"))):
            with self.subTest(nombre):
                with self.assertRaises(ConsultaFallida):
                    ConsultorClaude(ClienteSimulado(resp))(construir_consulta(["a"], ["b"]))

    def test_sin_cliente_no_se_crea_ninguno(self):
        with self.assertRaises(ValueError):
            ConsultorClaude(None)

    def test_consultor_real_desactivado_por_defecto(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(VARIABLE_ACTIVACION, None)
            with self.assertRaises(RuntimeError):
                crear_consultor_real()


class TestConAnalizadorYA2(unittest.TestCase):
    def test_rechazo_pide_aclaracion(self):
        a = AnalizadorSemantico(ConsultorClaude(ClienteSimulado(respuesta(None, "refusal"))))
        d = a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((d.estado, d.origen), (REQUIERE, ORIGEN_SEMANTICO))
        self.assertEqual(a.fallos, 1)

    def test_error_de_conexion_pide_aclaracion(self):
        a = AnalizadorSemantico(ConsultorClaude(ClienteSimulado(ConnectionError("simulado"))))
        d = a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((d.estado, d.origen), (REQUIERE, ORIGEN_SEMANTICO))

    def test_json_con_veredicto_invalido_pide_aclaracion(self):
        malo = json.dumps({"veredicto": "quizá", "coincidencias": [], "motivo": "x"})
        a = AnalizadorSemantico(ConsultorClaude(ClienteSimulado(respuesta(malo))))
        d = a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((d.estado, d.origen), (REQUIERE, ORIGEN_SEMANTICO))

    def test_caso_claude_code_de_punta_a_punta_con_cliente_simulado(self):
        cliente = ClienteSimulado(respuesta(CUBRE_JSON))

        def modificar(ps, ss):
            ss["sol-alba"].tema_ofrece, ss["sol-alba"].tema_busca = [CLAUDE_BASICO], [SOPORTE]
            ss["sol-bruno"].tema_ofrece, ss["sol-bruno"].tema_busca = [SOPORTE], [CODING_CLAUDE]
        coord = nuevo_escenario(modificar=modificar,
                                analizador_temas=AnalizadorSemantico(ConsultorClaude(cliente)))
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        self.assertEqual(m.a_ensena, [f"{CLAUDE_BASICO} → {CODING_CLAUDE}"])
        self.assertEqual(m.evidencia["tipos_coincidencia"], ["igual", "semántico"])
        # Una sola petición, con el modelo previsto y sin datos de las personas.
        [p] = cliente.peticiones
        self.assertEqual(p["model"], MODELO)
        enviado = json.dumps(p, ensure_ascii=False)
        for persona in coord.repo.participantes.values():
            for dato in (persona.nombre, persona.respaldo_declarado):
                if dato:
                    self.assertNotIn(dato, enviado)
        self.assertNotIn("@", enviado)


if __name__ == "__main__":
    unittest.main()

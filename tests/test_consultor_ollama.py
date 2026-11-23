"""Consultor de Ollama local (qwen3:1.7b).

Dos partes:
  - Pruebas con transporte SIMULADO (siempre se ejecutan; no usan la red).
  - Pruebas EN VIVO con el Ollama de esta computadora y SOLO datos ficticios.
    Se saltan salvo con ANTROPIA_PRUEBA_OLLAMA=si (en GitHub Actions no hay Ollama):
        $env:ANTROPIA_PRUEBA_OLLAMA = "si"
        .\\.venv\\Scripts\\python.exe -m unittest tests.test_consultor_ollama -v
"""
import itertools
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from encuentros import consultor_ollama as co
from encuentros.automatico import ACEPTO, CERRADO, CONFIRMADO, ESPERANDO, NO_INTERESA, PENDIENTE, \
    Ciclo, Configuracion, normalizar_codigo
from encuentros.correo import EnvioSimulado
from encuentros.temas_semantica import (
    CUBRE, NO_CUBRE, ORIGEN_SEMANTICO, REQUIERE, AnalizadorSemantico, construir_consulta,
)
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import CLAVE, LUNES, URL_FORM, AlmacenMemoria, persona

CLAUDE_BASICO = "Claude Code básico"
CODING_CLAUDE = "un poco de coding con Claude Code"
SOPORTE = "Soporte técnico"


def chat(contenido, done_reason="stop"):
    texto = contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False)
    return {"model": co.MODELO, "message": {"role": "assistant", "content": texto, "thinking": "…"},
            "done": True, "done_reason": done_reason}


def veredicto(v, tema, alcance, citas=()):
    return {"mismo_tema": tema, "alcance_incluido": alcance, "veredicto": v, "motivo": "simulado",
            "coincidencias": [{"ofrece": o, "busca": b} for o, b in citas]}


class Transporte:
    """Imita la API HTTP de Ollama y guarda cada petición. No usa la red."""

    def __init__(self, *respuestas, modelos=(co.MODELO,)):
        self.respuestas, self.modelos, self.peticiones = list(respuestas), modelos, []

    def __call__(self, url, cuerpo, tiempo):
        self.peticiones.append((url, cuerpo))
        if url.endswith("/api/tags"):
            return {"models": [{"name": m} for m in self.modelos]}
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


CUBRE_CLAUDE = chat(veredicto(CUBRE, "si", "si", [(CLAUDE_BASICO, CODING_CLAUDE)]))


class TestUrlYPeticion(unittest.TestCase):
    def test_solo_direcciones_locales(self):
        for buena in ("http://127.0.0.1:11434", "http://localhost:11434/", "http://[::1]:11434"):
            co.validar_url_local(buena)
        for mala in ("https://api.ejemplo.com", "http://192.168.1.20:11434", "http://10.0.0.5:11434",
                     "http://127.0.0.1.ejemplo.com:11434", "https://127.0.0.1:11434",
                     "http://usuario:clave@127.0.0.1:11434", "http://127.0.0.1:11434/otra"):
            with self.subTest(mala), self.assertRaises(ValueError):
                co.validar_url_local(mala)

    def test_peticion_exacta_solo_con_textos_de_temas(self):
        p = co.crear_peticion(construir_consulta([CLAUDE_BASICO], [CODING_CLAUDE]))
        self.assertEqual(p["model"], "qwen3:1.7b")
        self.assertIs(p["stream"], False)
        self.assertIs(p["think"], True)
        self.assertEqual(p["format"], co.ESQUEMA)
        self.assertEqual(p["options"]["temperature"], 0)
        sistema, usuario = p["messages"]
        self.assertEqual(sistema, {"role": "system", "content": co.INSTRUCCIONES_OLLAMA})
        self.assertEqual(json.loads(usuario["content"]),
                         {"ofrece": [CLAUDE_BASICO], "quiere_aprender": [CODING_CLAUDE]})
        self.assertIn("mismo_tema", co.INSTRUCCIONES_OLLAMA)


class TestInterpretar(unittest.TestCase):
    def test_veredictos_coherentes_se_respetan(self):
        for v, tema, alcance in ((CUBRE, "si", "si"), (NO_CUBRE, "no", "no"), (NO_CUBRE, "no", "no_se_sabe"),
                                 (REQUIERE, "si", "no"), (REQUIERE, "no_se_sabe", "si")):
            with self.subTest(v=v, tema=tema, alcance=alcance):
                self.assertEqual(co.interpretar(veredicto(v, tema, alcance))["veredicto"], v)

    def test_incoherencias_piden_aclaracion(self):
        for v, tema, alcance in ((CUBRE, "si", "no"), (CUBRE, "no", "no"), (CUBRE, "si", "no_se_sabe"),
                                 (NO_CUBRE, "si", "si"), (REQUIERE, "si", "si"), (CUBRE, None, None)):
            with self.subTest(v=v, tema=tema, alcance=alcance):
                r = co.interpretar(veredicto(v, tema, alcance))
                self.assertEqual((r["veredicto"], r["coincidencias"]), (REQUIERE, []))
                self.assertIn("no clara", r["motivo"])


class TestConsultor(unittest.TestCase):
    def test_cubre_coherente(self):
        t = Transporte(CUBRE_CLAUDE)
        d = AnalizadorSemantico(co.ConsultorOllama(t)).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((d.estado, d.origen), (CUBRE, ORIGEN_SEMANTICO))
        [(url, _)] = t.peticiones
        self.assertEqual(url, "http://127.0.0.1:11434/api/chat")

    def test_fallos_piden_aclaracion_y_no_se_guardan(self):
        casos = {"sin conexión": ConnectionRefusedError("simulado"), "tiempo agotado": TimeoutError(),
                 "error de Ollama": {"error": "model not found"}, "cortada": chat('{"vered', "length"),
                 "sin texto": chat(""), "no JSON": chat("cubre, claramente"), "lista": chat("[]")}
        for nombre, r in casos.items():
            with self.subTest(nombre):
                a = AnalizadorSemantico(co.ConsultorOllama(Transporte(r)))
                d = a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
                self.assertEqual((d.estado, d.origen), (REQUIERE, ORIGEN_SEMANTICO))
                self.assertIn("el modelo no respondió", d.motivo)
                a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
                self.assertEqual(a.fallos, 2)                  # se reintenta, no se guarda

    def test_un_fallo_nunca_se_toma_por_no_cubre(self):
        # Las reglas dirían «no cubre» (sin palabras comunes); sin respuesta del modelo: aclaración.
        a = AnalizadorSemantico(co.ConsultorOllama(Transporte(OSError("simulado"))))
        self.assertEqual(a.analizar(["reparar computadoras"], ["arreglar mi portátil"]).estado, REQUIERE)

    def test_cubre_incoherente_pide_aclaracion(self):
        t = Transporte(chat(veredicto(CUBRE, "si", "no", [(CLAUDE_BASICO, CODING_CLAUDE)])))
        d = AnalizadorSemantico(co.ConsultorOllama(t)).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual(d.estado, REQUIERE)

    def test_cita_inventada_pide_aclaracion(self):
        t = Transporte(chat(veredicto(CUBRE, "si", "si", [("Claude Code avanzado", CODING_CLAUDE)])))
        d = AnalizadorSemantico(co.ConsultorOllama(t)).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual(d.estado, REQUIERE)

    def test_limite_de_consultas_por_ciclo(self):
        t = Transporte(chat(veredicto(NO_CUBRE, "no", "no")))
        a = AnalizadorSemantico(co.ConsultorOllama(t, max_consultas=2))
        estados = [a.analizar([f"tema {i}"], ["otra cosa"]).estado for i in range(4)]
        self.assertEqual(estados, [NO_CUBRE, NO_CUBRE, REQUIERE, REQUIERE])
        self.assertEqual(len(t.peticiones), 2)

    def test_disponible(self):
        self.assertEqual(co.ConsultorOllama(Transporte(None)).disponible(), (True, "ok"))
        ok, motivo = co.ConsultorOllama(Transporte(None, modelos=("otro:1b",))).disponible()
        self.assertFalse(ok)
        self.assertIn("ollama pull qwen3:1.7b", motivo)
        ok, _ = co.ConsultorOllama(lambda *a: (_ for _ in ()).throw(ConnectionRefusedError())).disponible()
        self.assertFalse(ok)

    def test_sin_transporte_no_se_crea_ninguno(self):
        with self.assertRaises(ValueError):
            co.ConsultorOllama(None)

    def test_consultor_real_desactivado_por_defecto(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(co.VARIABLE_ACTIVACION, None)
            with self.assertRaises(RuntimeError):
                co.crear_consultor_real()

    def test_consultor_real_rechaza_url_no_local(self):
        with mock.patch.dict(os.environ, {co.VARIABLE_ACTIVACION: "si",
                                          "ANTROPIA_OLLAMA_URL": "http://ollama.ejemplo.com:11434"}):
            with self.assertRaises(ValueError):
                co.crear_consultor_real()


class TestMemoria(unittest.TestCase):
    def test_recuerda_entre_ciclos_sin_guardar_textos(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "memoria.json"
            t = Transporte(CUBRE_CLAUDE)
            m1 = co.ConsultorConMemoria(co.ConsultorOllama(t), ruta)
            self.assertEqual(AnalizadorSemantico(m1).analizar([CLAUDE_BASICO], [CODING_CLAUDE]).estado, CUBRE)
            guardado = ruta.read_text("utf-8")
            self.assertNotIn("Claude", guardado)
            m2 = co.ConsultorConMemoria(co.ConsultorOllama(t), ruta)       # «ciclo siguiente»
            d2 = AnalizadorSemantico(m2).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
            self.assertEqual(d2.estado, CUBRE)
            self.assertEqual(d2.coincidencias[0].ofrece, CLAUDE_BASICO)
            self.assertEqual((m2.recordadas, m2.nuevas, len(t.peticiones)), (1, 0, 1))

    def test_no_recuerda_fallos(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "memoria.json"
            m = co.ConsultorConMemoria(co.ConsultorOllama(Transporte(TimeoutError())), ruta)
            AnalizadorSemantico(m).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
            self.assertFalse(ruta.exists())


# ---------------------------------------------------------------------------
# En vivo: Ollama de esta computadora, solo datos ficticios
# ---------------------------------------------------------------------------
EN_VIVO = os.environ.get("ANTROPIA_PRUEBA_OLLAMA", "") == "si"


def consultor_vivo(**kw):
    return co.ConsultorOllama(co.transporte_http, max_consultas=None, **kw)


@unittest.skipUnless(EN_VIVO, "en vivo: definir ANTROPIA_PRUEBA_OLLAMA=si (usa el Ollama local)")
class TestEnVivoTemas(unittest.TestCase):
    COMPATIBLES = [(["guitarra acústica para principiantes"], ["tocar acordes básicos en guitarra"]),
                   ([CLAUDE_BASICO], [CODING_CLAUDE]),
                   (["inglés conversacional"], ["practicar conversación en inglés"])]
    INCOMPATIBLES = [(["jardinería urbana"], ["programación en Python"]),
                     (["cocina italiana"], ["cocina mexicana"]),
                     (["fotografía"], ["contabilidad para pymes"])]
    AMBIGUOS = [(["Excel"], ["análisis de datos avanzado con Power BI"]),
                (["programación"], ["desarrollo de videojuegos en Unity"]),
                (["marketing"], ["SEO técnico avanzado"])]

    @classmethod
    def setUpClass(cls):
        ok, motivo = consultor_vivo().disponible()
        if not ok:
            raise unittest.SkipTest(motivo)
        cls.analizador = AnalizadorSemantico(consultor_vivo())

    def _ver(self, casos, aceptables):
        for o, b in casos:
            with self.subTest(ofrece=o, busca=b):
                d = self.analizador.analizar(o, b)
                print(f"\n  [{d.origen}] {o} → {b}: {d.estado} · {d.motivo[:120]}")
                self.assertIn(d.estado, aceptables)

    def test_compatibles_cubren(self):
        self._ver(self.COMPATIBLES, {CUBRE})

    def test_incompatibles_no_cubren(self):
        self._ver(self.INCOMPATIBLES, {NO_CUBRE})

    def test_ambiguos_nunca_cubren(self):
        self._ver(self.AMBIGUOS, {REQUIERE, NO_CUBRE})

    def test_sin_ollama_pide_aclaracion(self):
        a = AnalizadorSemantico(co.ConsultorOllama(co.transporte_http, url="http://127.0.0.1:9"))
        d = a.analizar(["reparar computadoras"], ["arreglar mi portátil"])
        self.assertEqual(d.estado, REQUIERE)


@unittest.skipUnless(EN_VIVO and ZONAS_REALES, "en vivo: ANTROPIA_PRUEBA_OLLAMA=si y tzdata")
class TestEnVivoCiclo(unittest.TestCase):
    """Ciclo completo con personas ficticias, almacén en memoria y correo simulado."""

    def _ciclo(self, alba, bruno):
        codigos = (f"C{n:03d}-AAAA".replace("0", "Q").replace("1", "R") for n in itertools.count(100))
        salas = (f"https://meet.jit.si/AntropiaPrueba{n}" for n in itertools.count(1))
        cfg = Configuracion(URL_FORM, CLAVE, generar_codigo=lambda: next(codigos), nueva_sala=lambda: next(salas),
                            analizador_temas=AnalizadorSemantico(consultor_vivo()))
        alm = AlmacenMemoria([alba, bruno])
        envio = EnvioSimulado()
        r = Ciclo(alm, envio, cfg, LUNES).ejecutar()
        return cfg, alm, envio, r

    @staticmethod
    def _codigo(envio, pid):
        c = next(c for c in envio.enviados if c.destinatario_id == pid)
        return normalizar_codigo(c.cuerpo.split("código personal:")[1])

    def test_reciproco_con_horario_espera_a_las_dos_y_confirma(self):
        cfg, alm, envio, _ = self._ciclo(
            persona("alba", "Alba", CLAUDE_BASICO, SOPORTE, "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", SOPORTE, CODING_CLAUDE, "lunes 11:00-13:00; America/Mexico_City", None))
        [f] = alm.filas.values()
        self.assertEqual(f.estado, ESPERANDO)
        self.assertIn("semántico", f.notas)
        alm.responder(self._codigo(envio, "alba"), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=2)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual((f.respuesta_a, f.respuesta_b, f.estado, f.enlace), (ACEPTO, PENDIENTE, ESPERANDO, None))
        alm.responder(self._codigo(envio, "bruno"), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=3)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)
        self.assertTrue(f.enlace.startswith("https://meet.jit.si/AntropiaPrueba"))

    def test_si_una_no_acepta_no_se_confirma(self):
        cfg, alm, envio, _ = self._ciclo(
            persona("alba", "Alba", CLAUDE_BASICO, SOPORTE, "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", SOPORTE, CODING_CLAUDE, "lunes 11:00-13:00; America/Mexico_City", None))
        alm.responder(self._codigo(envio, "alba"), ACEPTO)
        alm.responder(self._codigo(envio, "bruno"), NO_INTERESA)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=2)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CERRADO)
        self.assertIsNone(f.enlace)

    def test_sin_reciprocidad_no_hay_match(self):
        _, alm, envio, _ = self._ciclo(
            persona("alba", "Alba", "jardinería urbana", SOPORTE, "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", SOPORTE, "programación en Python", "lunes 11:00-13:00; America/Mexico_City", None))
        self.assertEqual(alm.filas, {})
        self.assertEqual(envio.enviados, [])

    def test_sin_horario_comun_no_hay_match(self):
        _, alm, envio, _ = self._ciclo(
            persona("alba", "Alba", CLAUDE_BASICO, SOPORTE, "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", SOPORTE, CODING_CLAUDE, "domingo 03:00-04:00; America/Mexico_City", None))
        self.assertEqual(alm.filas, {})

    def test_tema_ambiguo_no_crea_match(self):
        _, alm, envio, r = self._ciclo(
            persona("alba", "Alba", "Excel", SOPORTE, "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", SOPORTE, "análisis de datos avanzado con Power BI",
                    "lunes 11:00-13:00; America/Mexico_City", None))
        self.assertEqual(alm.filas, {})
        self.assertEqual(envio.enviados, [])


if __name__ == "__main__":
    unittest.main()

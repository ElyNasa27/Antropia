"""Análisis de temas por significado en A2, con un consultor FICTICIO (sin red).

Las respuestas del consultor de estas pruebas están escritas a mano: sirven para
comprobar cómo A2 usa y valida un veredicto, NO lo que diría un modelo real.
"""
import itertools
import unittest
from datetime import timedelta

from encuentros.automatico import ACEPTO, CONFIRMADO, ESPERANDO, PENDIENTE, Ciclo, Configuracion, normalizar_codigo
from encuentros.correo import EnvioSimulado
from encuentros.temas_semantica import (
    CUBRE, NO_CUBRE, ORIGEN_REGLAS, ORIGEN_SEMANTICO, REQUIERE, AnalizadorSemantico,
    construir_consulta,
)
from tests.apoyo import DESDE, ZONAS_REALES, nuevo_escenario
from tests.test_automatico import CLAVE, LUNES, URL_FORM, AlmacenMemoria, persona

CLAUDE_BASICO = "Claude Code básico"
CODING_CLAUDE = "un poco de coding con Claude Code"
SOPORTE = "Soporte técnico"


class ConsultorFicticio:
    """Devuelve respuestas fijas por (ofrece, quiere_aprender) y guarda cada consulta."""

    NO_CUBRE_FICTICIO = {"veredicto": NO_CUBRE, "motivo": "ficticio: otro tema"}

    def __init__(self, respuestas=None, por_defecto=NO_CUBRE_FICTICIO):
        self.respuestas = respuestas or {}
        self.por_defecto = por_defecto      # puede ser None o {} a propósito (respuesta mal formada)
        self.consultas = []

    def __call__(self, consulta):
        self.consultas.append(consulta)
        r = self.respuestas.get((tuple(consulta["ofrece"]), tuple(consulta["quiere_aprender"])),
                                self.por_defecto)
        if isinstance(r, Exception):
            raise r
        return r


def cubre(ofrece, busca, motivo="ficticio: lo buscado está dentro de lo ofrecido"):
    return {"veredicto": CUBRE, "coincidencias": [{"ofrece": ofrece, "busca": busca}], "motivo": motivo}


CLAUDE_CUBRE = {((CLAUDE_BASICO,), (CODING_CLAUDE,)): cubre(CLAUDE_BASICO, CODING_CLAUDE)}


# ---------------------------------------------------------------------------
# El analizador por sí solo
# ---------------------------------------------------------------------------
class TestAnalizadorSemantico(unittest.TestCase):
    def test_coincidencia_clara_por_reglas_no_consulta(self):
        c = ConsultorFicticio()
        d = AnalizadorSemantico(c).analizar([SOPORTE], ["soporte tecnico"])
        self.assertEqual((d.estado, d.origen), (CUBRE, ORIGEN_REGLAS))
        self.assertEqual(c.consultas, [])

    def test_caso_claude_code_cubre_segun_el_consultor(self):
        c = ConsultorFicticio(CLAUDE_CUBRE)
        d = AnalizadorSemantico(c).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((d.estado, d.origen), (CUBRE, ORIGEN_SEMANTICO))
        [co] = d.coincidencias
        self.assertEqual((co.ofrece, co.busca, co.tipo), (CLAUDE_BASICO, CODING_CLAUDE, "semántico"))

    def test_cita_inventada_requiere_aclaracion(self):
        c = ConsultorFicticio({((CLAUDE_BASICO,), (CODING_CLAUDE,)): cubre("Python avanzado", CODING_CLAUDE)})
        d = AnalizadorSemantico(c).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual(d.estado, REQUIERE)
        self.assertIn("no figura en los datos", d.motivo)

    def test_respuestas_mal_formadas_requieren_aclaracion(self):
        for mala in (None, "cubre", {}, {"veredicto": "quizá"}, {"veredicto": CUBRE},
                     {"veredicto": CUBRE, "coincidencias": []},
                     {"veredicto": CUBRE, "coincidencias": ["texto suelto"]}):
            with self.subTest(mala=mala):
                c = ConsultorFicticio(por_defecto=mala)
                d = AnalizadorSemantico(c).analizar([CLAUDE_BASICO], [CODING_CLAUDE])
                self.assertEqual(d.estado, REQUIERE)
                self.assertEqual(d.coincidencias, ())

    def test_si_el_consultor_falla_pide_aclaracion_y_no_se_guarda(self):
        c = ConsultorFicticio(por_defecto=TimeoutError("sin respuesta"))
        a = AnalizadorSemantico(c)
        d = a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((d.estado, d.origen), (REQUIERE, ORIGEN_SEMANTICO))
        self.assertIn("el modelo no respondió", d.motivo)
        self.assertIn("alcance incierto", d.motivo)                         # y lo que dicen las reglas
        a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual((a.consultas, a.fallos), (2, 2))                    # se reintenta

    def test_cada_direccion_se_consulta_una_vez(self):
        c = ConsultorFicticio(CLAUDE_CUBRE)
        a = AnalizadorSemantico(c)
        for _ in range(3):
            a.analizar([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual(len(c.consultas), 1)

    def test_la_consulta_solo_lleva_textos_de_temas(self):
        consulta = construir_consulta([CLAUDE_BASICO], [CODING_CLAUDE])
        self.assertEqual(set(consulta), {"instrucciones", "ofrece", "quiere_aprender"})
        self.assertEqual((consulta["ofrece"], consulta["quiere_aprender"]), ([CLAUDE_BASICO], [CODING_CLAUDE]))


# ---------------------------------------------------------------------------
# A2 con el analizador (escenario ficticio Alba / Bruno)
# ---------------------------------------------------------------------------
class TestA2PorSignificado(unittest.TestCase):
    def _a2(self, consultor=None, alba_ofrece=(CLAUDE_BASICO,), alba_busca=(SOPORTE,),
            bruno_ofrece=(SOPORTE,), bruno_busca=(CODING_CLAUDE,), otros=None):
        def modificar(ps, ss):
            ss["sol-alba"].tema_ofrece, ss["sol-alba"].tema_busca = list(alba_ofrece), list(alba_busca)
            ss["sol-bruno"].tema_ofrece, ss["sol-bruno"].tema_busca = list(bruno_ofrece), list(bruno_busca)
            if otros:
                otros(ps, ss)
        analizador = AnalizadorSemantico(consultor) if consultor else None
        coord = nuevo_escenario(modificar=modificar, analizador_temas=analizador)
        return coord, coord.proponer_matches(DESDE, "e1")

    def test_claude_code_sin_analisis_semantico_sigue_pidiendo_aclaracion(self):
        _, res = self._a2()
        self.assertEqual(res.propuestas, [])
        r = res.por_solicitud["sol-alba"]
        self.assertEqual(r.resultado, "Bloqueada")
        [aclaracion] = r.bloqueadas["sol-bruno"]
        self.assertIn(f"Alba ofrece «{CLAUDE_BASICO}» y Bruno busca «{CODING_CLAUDE}» (alcance incierto",
                      aclaracion)

    def test_claude_code_cubierto_por_significado_genera_propuesta(self):
        c = ConsultorFicticio(CLAUDE_CUBRE)
        _, res = self._a2(c)
        [m] = res.propuestas
        self.assertEqual(m.a_ensena, [f"{CLAUDE_BASICO} → {CODING_CLAUDE}"])
        self.assertEqual(m.b_ensena, [SOPORTE])
        e = m.evidencia
        self.assertEqual(e["tipos_coincidencia"], ["igual", "semántico"])
        self.assertEqual(e["analisis_temas"]["a_b"]["origen"], ORIGEN_SEMANTICO)
        self.assertEqual(e["analisis_temas"]["b_a"]["origen"], ORIGEN_REGLAS)
        # Idioma, modalidad y horario se siguen comprobando y constan en la evidencia.
        self.assertEqual((e["idioma"], e["modalidad"]), ("Español", "videollamada"))
        self.assertEqual(e["horario_comun_utc"], "2026-11-30T17:00:00+00:00")
        # Solo se consultó la dirección que las reglas no resolvían, una vez.
        self.assertEqual(len(c.consultas), 1)
        self.assertFalse(m.es_valida)                    # sigue haciendo falta la revisión

    def test_la_consulta_no_lleva_datos_personales(self):
        c = ConsultorFicticio(CLAUDE_CUBRE)
        coord, _ = self._a2(c)
        texto = repr(c.consultas)
        for p in coord.repo.participantes.values():
            for dato in (p.nombre, p.id, p.respaldo_declarado):
                if dato:
                    self.assertNotIn(dato, texto)
        self.assertNotIn("@", texto)

    def test_claude_code_incierto_para_el_consultor_pide_aclaracion(self):
        c = ConsultorFicticio({((CLAUDE_BASICO,), (CODING_CLAUDE,)): {
            "veredicto": REQUIERE, "motivo": "ficticio: no consta si incluye programar"}})
        _, res = self._a2(c)
        self.assertEqual(res.propuestas, [])
        [aclaracion] = res.por_solicitud["sol-alba"].bloqueadas["sol-bruno"]
        self.assertTrue(aclaracion.startswith("requiere aclaración de temas"))
        self.assertIn("análisis semántico: ficticio: no consta si incluye programar", aclaracion)

    def test_no_cubre_es_sin_reciprocidad(self):
        _, res = self._a2(ConsultorFicticio())          # por defecto: no_cubre
        self.assertIn("sin reciprocidad", res.por_solicitud["sol-alba"].sin_coincidencia["sol-bruno"])

    def test_significado_sin_palabras_comunes(self):
        c = ConsultorFicticio({(("reparar computadoras",), ("arreglar mi portátil",)):
                               cubre("reparar computadoras", "arreglar mi portátil")})
        _, res = self._a2(c, alba_ofrece=("reparar computadoras",), bruno_busca=("arreglar mi portátil",))
        [m] = res.propuestas
        self.assertEqual(m.a_ensena, ["reparar computadoras → arreglar mi portátil"])

    def test_idioma_distinto_impide_el_match_aunque_cubra(self):
        def idioma(ps, ss):
            ss["sol-bruno"].idioma = "Inglés"
        _, res = self._a2(ConsultorFicticio(CLAUDE_CUBRE), otros=idioma)
        self.assertEqual(res.propuestas, [])
        self.assertTrue(any("sin idioma común" in x
                            for x in res.por_solicitud["sol-alba"].sin_coincidencia["sol-bruno"]))

    def test_presencial_impide_el_match_aunque_cubra(self):
        def presencial(ps, ss):
            ss["sol-bruno"].modalidad = "Presencial"
        _, res = self._a2(ConsultorFicticio(CLAUDE_CUBRE), otros=presencial)
        self.assertEqual(res.propuestas, [])
        self.assertTrue(any("no compatible" in x
                            for x in res.por_solicitud["sol-alba"].sin_coincidencia["sol-bruno"]))

    def test_sin_horario_comun_impide_el_match_aunque_cubra(self):
        from datetime import time
        from encuentros.modelos import Franja

        def otra_hora(ps, ss):
            ss["sol-bruno"].disponibilidad = [Franja("domingo", time(3, 0), time(4, 0))]   # de madrugada
        _, res = self._a2(ConsultorFicticio(CLAUDE_CUBRE), otros=otra_hora)
        self.assertEqual(res.propuestas, [])
        self.assertTrue(any("sin horario común" in x
                            for x in res.por_solicitud["sol-alba"].sin_coincidencia["sol-bruno"]))


# ---------------------------------------------------------------------------
# Ciclo automático: el match sigue necesitando la aceptación de las dos personas
# ---------------------------------------------------------------------------
@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestCicloConAnalisisSemantico(unittest.TestCase):
    def test_match_por_significado_espera_a_que_acepten_las_dos(self):
        codigos = (f"C{n:03d}-AAAA".replace("0", "Q").replace("1", "R") for n in itertools.count(100))
        salas = (f"https://meet.jit.si/AntropiaPrueba{n}" for n in itertools.count(1))
        consultor = ConsultorFicticio(CLAUDE_CUBRE)
        cfg = Configuracion(URL_FORM, CLAVE, generar_codigo=lambda: next(codigos),
                            nueva_sala=lambda: next(salas), analizador_temas=AnalizadorSemantico(consultor))
        alm = AlmacenMemoria([
            persona("alba", "Alba", CLAUDE_BASICO, SOPORTE, "lunes 18:00–20:00", "Europe/Madrid"),
            persona("bruno", "Bruno", SOPORTE, CODING_CLAUDE, "lunes 11:00-13:00; America/Mexico_City", None),
        ])
        envio = EnvioSimulado()                                   # nada sale de la prueba
        Ciclo(alm, envio, cfg, LUNES).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual(f.estado, ESPERANDO)
        self.assertIn("temas: igual, semántico", f.notas)

        def codigo(pid):
            c = next(c for c in envio.enviados if c.destinatario_id == pid)
            return normalizar_codigo(c.cuerpo.split("código personal:")[1])

        alm.responder(codigo("alba"), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=2)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual((f.respuesta_a, f.respuesta_b, f.estado), (ACEPTO, PENDIENTE, ESPERANDO))
        alm.responder(codigo("bruno"), ACEPTO)
        Ciclo(alm, envio, cfg, LUNES + timedelta(hours=3)).ejecutar()
        [f] = alm.filas.values()
        self.assertEqual(f.estado, CONFIRMADO)


if __name__ == "__main__":
    unittest.main()

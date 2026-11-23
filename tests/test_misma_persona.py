"""Dos filas con el mismo alias: se bloquea SOLO ese par. Datos ficticios.

No se unen registros ni se bloquean los perfiles: cada uno puede emparejarse con
otras personas.
"""
import dataclasses
import unittest
from datetime import timedelta

from encuentros.a2_match import POSIBLE_MISMA_PERSONA, evaluar_par
from encuentros.automatico import ACEPTO, CERRADO, CONFIRMADO, a_modelo, evaluar_participante
from encuentros.correo import EnvioSimulado, contiene_correo
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import LUNES, AlmacenMemoria, alba, bruno, persona


def con_alias(p, alias):
    return dataclasses.replace(p, alias=alias)


def sofia(pid, alias="Sofía Prueba", **kw):
    """Fila ficticia compatible con alba: ofrece inglés, busca fotografía."""
    return persona(pid, alias, "Inglés conversacional", "fotografia con movil",
                   "lunes 11:00-13:00; America/Mexico_City", None, **kw)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestMismaPersona(unittest.TestCase):
    def ciclo(self, personas, alm=None, envio=None, ahora=LUNES):
        prueba = ta.TestCicloAutomatico()
        prueba.setUp()
        self.prueba = prueba
        alm, envio = alm or AlmacenMemoria(personas), envio or EnvioSimulado()
        return alm, envio, prueba.ciclo(alm, envio, ahora)

    def test_par_con_el_mismo_alias_queda_bloqueado(self):
        # Mismo alias escrito distinto (mayúsculas, tildes, espacios), correos distintos.
        pa, sa, _ = a_modelo(con_alias(alba(), "Sofía  Prueba"))
        pb, sb, _ = a_modelo(con_alias(bruno(), "sofia prueba"))
        ev = evaluar_par(pa, sa, pb, sb, LUNES, resolver_zona_real)
        self.assertEqual(ev.resultado, "Bloqueada")
        self.assertIn(POSIBLE_MISMA_PERSONA, ev.datos_pendientes)

    def test_alias_distintos_no_se_bloquean(self):
        pa, sa, _ = a_modelo(alba())
        pb, sb, _ = a_modelo(bruno())
        self.assertEqual(evaluar_par(pa, sa, pb, sb, LUNES, resolver_zona_real).resultado, "Propuesta")

    def test_el_ciclo_no_propone_el_par_ni_envia_correos(self):
        alm, envio, r = self.ciclo([con_alias(alba(), "Sofía Prueba"), sofia("sofia2")])
        self.assertEqual((len(alm.filas), len(envio.enviados), r.pares_misma_persona), (0, 0, 1))
        [aviso] = [a for a in r.avisos if POSIBLE_MISMA_PERSONA in a]
        self.assertNotIn("Sofía", aviso)
        self.assertFalse(contiene_correo(aviso))

    def test_los_perfiles_no_se_bloquean(self):
        for p in (con_alias(alba(), "Sofía Prueba"), sofia("sofia2")):
            self.assertTrue(evaluar_participante(p, resolver_zona_real).apta)

    def test_cada_fila_puede_emparejarse_con_otra_persona(self):
        # alba (alias «Sofía Prueba») y sofia2 comparten alias; bruno es otra persona.
        alm, envio, r = self.ciclo([con_alias(alba(), "Sofía Prueba"), sofia("sofia2"), bruno()])
        pares = {frozenset((f.a, f.b)) for f in alm.filas.values()}
        self.assertNotIn(frozenset(("alba", "sofia2")), pares)
        self.assertIn(frozenset(("alba", "bruno")), pares)
        self.assertEqual(r.pares_misma_persona, 1)

    def test_no_se_unen_registros(self):
        alm, _, r = self.ciclo([con_alias(alba(), "Sofía Prueba"), sofia("sofia2")])
        self.assertEqual(r.personas, 2)
        self.assertEqual(len(alm.personas()), 2)

    def test_un_match_ya_creado_con_el_mismo_alias_se_cierra_sin_confirmar(self):
        alm, envio, _ = self.ciclo([alba(), bruno()])
        alm.responder(self.prueba.codigo_de(envio, "alba"), ACEPTO)
        alm.responder(self.prueba.codigo_de(envio, "bruno"), ACEPTO)
        alm._personas[1] = con_alias(bruno(), "Alba")          # ahora las dos filas tienen el mismo alias
        enviados_antes = len(envio.enviados)
        self.ciclo(None, alm, envio, LUNES + timedelta(hours=1))
        [f] = alm.filas.values()
        self.assertNotEqual(f.estado, CONFIRMADO)
        self.assertEqual(f.estado, CERRADO)
        self.assertIsNone(f.enlace)
        self.assertEqual(len(envio.enviados), enviados_antes)     # sin avisos nuevos


if __name__ == "__main__":
    unittest.main()

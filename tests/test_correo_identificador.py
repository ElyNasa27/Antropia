"""Etapa 2: el correo electrónico como identificador central. Datos ficticios.

Correo que falta, no es válido o está duplicado -> el perfil queda bloqueado.
Nunca se unen registros y las direcciones no aparecen en avisos ni resúmenes.
"""
import unittest
from datetime import timedelta

from encuentros.automatico import (
    ACEPTO, CONFIRMADO, CORREO_DUPLICADO, CORREO_FALTA, CORREO_NO_VALIDO, clave_correo,
    evaluar_participante, marcar_correos_duplicados,
)
from encuentros.correo import EnvioSimulado, contiene_correo
from encuentros.notion_mapa import MINUTOS_POR_OPCION, OPCIONES_MINUTOS, minutos_de_opcion
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import LUNES, AlmacenMemoria, alba, bruno, persona


def carla(**kw):
    """Tercera persona ficticia, con datos incompletos y sin autorización."""
    base = dict(autoriza=False, ofrece=None, quiere=None)
    base.update(kw)
    return persona("carla", "Carla", base.pop("ofrece"), base.pop("quiere"), None, None, **base)


class TestClaveYDuplicados(unittest.TestCase):
    def test_clave_ignora_espacios_y_mayusculas(self):
        self.assertEqual(clave_correo("  Alba.Prueba@Example.ORG "), "alba.prueba@example.org")
        for v in (None, "", "   ", 42):
            self.assertIsNone(clave_correo(v))

    def test_duplicados_por_espacios_o_mayusculas(self):
        ps = [alba(correo="Comun@Example.org"), bruno(correo="  comun@example.ORG  "),
              persona("dani", "Dani", "x", "y", None, None, correo="dani@example.org")]
        self.assertEqual(marcar_correos_duplicados(ps), 2)
        self.assertEqual([p.correo_duplicado for p in ps], [True, True, False])

    def test_vacios_no_cuentan_como_duplicados(self):
        ps = [alba(correo=None), bruno(correo="  ")]
        self.assertEqual(marcar_correos_duplicados(ps), 0)

    def test_tambien_entre_perfiles_incompletos_o_sin_autorizacion(self):
        ps = [alba(), bruno(), carla(correo="ALBA@example.org")]
        self.assertEqual(marcar_correos_duplicados(ps), 2)
        self.assertTrue(ps[0].correo_duplicado and ps[2].correo_duplicado)
        self.assertFalse(ps[1].correo_duplicado)

    def test_no_une_ni_modifica_registros(self):
        ps = [alba(correo="Comun@example.org"), bruno(correo="comun@example.org ")]
        marcar_correos_duplicados(ps)
        self.assertEqual(len(ps), 2)
        self.assertEqual([(p.id, p.correo) for p in ps],
                         [("alba", "Comun@example.org"), ("bruno", "comun@example.org ")])

    def test_volver_a_marcar_quita_la_marca_si_se_corrige(self):
        ps = [alba(correo="comun@example.org"), bruno(correo="comun@example.org")]
        marcar_correos_duplicados(ps)
        ps[1].correo = "bruno@example.org"
        self.assertEqual(marcar_correos_duplicados(ps), 0)


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestEvaluacion(unittest.TestCase):
    def problemas(self, p):
        ev = evaluar_participante(p, resolver_zona_real)
        self.assertFalse(ev.apta)
        return ev.a1_problemas

    def test_correo_que_falta(self):
        for v in (None, "", "   "):
            self.assertIn(CORREO_FALTA, self.problemas(alba(correo=v)))

    def test_correo_no_valido(self):
        for v in ("no-es-un-correo", "alba@", "alba@example", "dos @example.org"):
            self.assertIn(CORREO_NO_VALIDO, self.problemas(alba(correo=v)))

    def test_correo_duplicado(self):
        p = alba()
        p.correo_duplicado = True
        self.assertIn(CORREO_DUPLICADO, self.problemas(p))

    def test_correo_valido_con_espacios_sigue_siendo_apto(self):
        self.assertTrue(evaluar_participante(alba(correo="  alba@example.org "), resolver_zona_real).apta)

    def test_los_motivos_no_muestran_la_direccion(self):
        for m in (CORREO_FALTA, CORREO_NO_VALIDO, CORREO_DUPLICADO):
            self.assertFalse(contiene_correo(m))


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestCicloConCorreos(unittest.TestCase):
    """Ciclo completo con envío SIMULADO: ningún correo sale del proceso."""

    def setUp(self):
        self.t = ta.TestCicloAutomatico()
        self.t.setUp()

    def ciclo(self, personas, alm=None, envio=None, ahora=LUNES):
        alm, envio = alm or AlmacenMemoria(personas), envio or EnvioSimulado()
        return alm, envio, self.t.ciclo(alm, envio, ahora)

    def sin_datos_personales(self, r):
        for a in r.avisos:
            self.assertFalse(contiene_correo(a), a)
            self.assertNotIn("comun", a.lower())

    def test_duplicado_por_mayusculas_y_espacios_bloquea_a_ambas(self):
        alm, envio, r = self.ciclo([alba(correo="Comun@Example.org"), bruno(correo=" comun@example.org ")])
        self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0))
        self.assertEqual((r.correos_duplicados, r.personas, r.a1_con_problemas), (2, 2, 2))
        self.assertTrue(any(CORREO_DUPLICADO in a for a in r.avisos))
        self.sin_datos_personales(r)

    def test_duplicado_con_un_perfil_incompleto_y_sin_autorizacion(self):
        alm, envio, r = self.ciclo([alba(), bruno(), carla(correo="  ALBA@example.org")])
        self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0))
        self.assertEqual((r.correos_duplicados, r.personas), (2, 3))     # tres filas, ninguna unida
        self.sin_datos_personales(r)

    def test_correo_que_falta_o_no_valido_no_crea_match(self):
        for v in (None, "no-es-un-correo"):
            alm, envio, r = self.ciclo([alba(correo=v), bruno()])
            self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0), v)
            self.sin_datos_personales(r)

    def test_sin_duplicados_el_match_sigue_igual(self):
        alm, envio, r = self.ciclo([alba(), bruno(), carla()])
        self.assertEqual((len(alm.filas), len(envio.enviados), r.correos_duplicados), (1, 2, 0))

    def test_si_aparece_un_duplicado_no_se_confirma_el_encuentro(self):
        alm, envio, _ = self.ciclo([alba(), bruno()])
        alm.responder(self.t.codigo_de(envio, "alba"), ACEPTO)
        alm.responder(self.t.codigo_de(envio, "bruno"), ACEPTO)
        alm._personas.append(carla(correo="BRUNO@example.org"))
        self.ciclo(None, alm, envio, LUNES + timedelta(hours=1))
        [f] = alm.filas.values()
        self.assertNotEqual(f.estado, CONFIRMADO)
        self.assertIsNone(f.enlace)


class TestEtiquetasDeMinutos(unittest.TestCase):
    """Etiquetas del formulario («15 minutos»…). Aún no se usan en las reglas (etapa 7)."""

    ETIQUETAS_FORMULARIO = ("15 minutos", "30 minutos", "45 minutos", "60 minutos",
                            "90 minutos", "120 minutos", "Otro")

    def test_opciones_con_las_etiquetas_del_formulario(self):
        self.assertEqual(OPCIONES_MINUTOS, self.ETIQUETAS_FORMULARIO)

    def test_cada_etiqueta_da_sus_minutos(self):
        esperados = (15, 30, 45, 60, 90, 120)
        self.assertEqual(tuple(minutos_de_opcion(e) for e in self.ETIQUETAS_FORMULARIO[:-1]), esperados)
        self.assertEqual(set(MINUTOS_POR_OPCION.values()), set(esperados))

    def test_otro_vacio_o_desconocido_no_se_adivina(self):
        for e in ("Otro", None, "", "25 minutos", "media hora", "30 min", "15"):
            self.assertIsNone(minutos_de_opcion(e), e)

    def test_espacios_sobrantes(self):
        self.assertEqual(minutos_de_opcion("  90   minutos "), 90)


if __name__ == "__main__":
    unittest.main()

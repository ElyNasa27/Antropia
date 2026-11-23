"""Etapa 6: días y franjas del formulario nuevo, con compatibilidad del texto anterior.

Datos ficticios. Nunca se inventa un horario: ante la duda, aclaración.
"""
import unittest
from datetime import time

from encuentros import disponibilidad_formulario as df
from encuentros.automatico import evaluar_participante
from encuentros.correo import EnvioSimulado
from encuentros.modelos import Franja
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import INICIO, AlmacenMemoria, alba, bruno


def F(dia, h1, m1, h2, m2):
    return Franja(dia, time(h1, m1), time(h2, m2))


def elegir(dias=(), franjas=None, otras=None, anterior=None):
    return df.elegir_disponibilidad(dias, franjas or {}, otras or {}, anterior)


class TestFormularioNuevo(unittest.TestCase):
    def test_bloques_de_una_hora(self):
        r = elegir(("Lunes", "Martes"), {"lunes": ("01:00–02:00", "09:00–10:00"), "martes": ("18:00–19:00",)})
        self.assertEqual((r.franjas, r.origen, r.problemas), (
            (F("lunes", 1, 0, 2, 0), F("lunes", 9, 0, 10, 0), F("martes", 18, 0, 19, 0)), df.ORIGEN_NUEVO, ()))

    def test_bloques_contiguos_se_unen(self):
        r = elegir(("Lunes",), {"lunes": ("19:00–20:00", "18:00–19:00", "20:00–21:00")})
        self.assertEqual(r.franjas, (F("lunes", 18, 0, 21, 0),))

    def test_ultimo_bloque_del_dia(self):
        r = elegir(("Domingo",), {"domingo": ("23:00–24:00",)})
        self.assertEqual(r.franjas, (F("domingo", 23, 0, 23, 59),))

    def test_dias_con_tildes_y_mayusculas(self):
        r = elegir(("miercoles", "SÁBADO"), {"miércoles": ("10:00–11:00",), "sábado": ("10:00–11:00",)})
        self.assertEqual(len(r.franjas), 2)
        self.assertFalse(r.problemas)

    def test_otro_con_inicio_y_fin(self):
        r = elegir(("Jueves",), {"jueves": ("Otro", "18:00–19:00")}, {"jueves": "07:30–08:15; 19:00 - 19:45"})
        self.assertEqual(r.franjas, (F("jueves", 7, 30, 8, 15), F("jueves", 18, 0, 19, 45)))

    def test_otro_sin_texto(self):
        r = elegir(("Jueves",), {"jueves": ("Otro",)})
        self.assertEqual((r.franjas, r.problemas), ((), ("Otras franjas Jueves (eligió «Otro» pero falta el horario)",)))

    def test_otro_ambiguo_pide_aclaracion(self):
        for texto in ("por la tarde", "18-20", "7:30–8:15", "19:00–18:00", "18:00–25:00", "desde las 18:00"):
            r = elegir(("Jueves",), {"jueves": ("Otro",)}, {"jueves": texto})
            self.assertEqual(r.franjas, (), texto)
            self.assertIn("requiere aclaración", r.problema, texto)

    def test_texto_en_otras_franjas_sin_elegir_otro(self):
        r = elegir(("Lunes",), {"lunes": ("18:00–19:00",)}, {"lunes": "07:30–08:15"})
        self.assertEqual(r.franjas, ())
        self.assertIn("no se eligió «Otro»", r.problema)

    def test_dia_marcado_sin_franjas(self):
        r = elegir(("Lunes", "Martes"), {"lunes": ("18:00–19:00",)})
        self.assertEqual((r.franjas, r.problemas), ((), ("Franjas Martes (falta)",)))

    def test_franjas_de_un_dia_no_marcado(self):
        r = elegir(("Lunes",), {"lunes": ("18:00–19:00",), "viernes": ("10:00–11:00",)})
        self.assertEqual(r.franjas, ())
        self.assertIn("el día no está marcado", r.problema)

    def test_opcion_o_dia_desconocidos(self):
        self.assertIn("opción no reconocida", elegir(("Lunes",), {"lunes": ("mañana",)}).problema)
        self.assertIn("Días disponibles", elegir(("Lunes", "Feriado"), {"lunes": ("18:00–19:00",)}).problema)

    def test_un_problema_bloquea_toda_la_disponibilidad(self):
        r = elegir(("Lunes", "Martes"), {"lunes": ("18:00–19:00",), "martes": ("Otro",)})
        self.assertEqual(r.franjas, ())                       # no se usa solo el lunes


class TestCompatibilidad(unittest.TestCase):
    def test_sin_datos_nuevos_usa_el_texto_anterior(self):
        r = elegir(anterior="lunes 18:00–20:00; miércoles 19:00 a 21:00")
        self.assertEqual((r.franjas, r.origen), ((F("lunes", 18, 0, 20, 0), F("miércoles", 19, 0, 21, 0)),
                                                 df.ORIGEN_ANTERIOR))

    def test_texto_anterior_con_partes_ilegibles_pide_aclaracion(self):
        r = elegir(anterior="lunes 18:00–20:00; fines de semana a partir de las 5")
        self.assertEqual((r.franjas, r.problemas), ((), (df.ANTERIOR_AMBIGUA,)))

    def test_nada(self):
        for anterior in (None, "", "America/Costa_Rica"):
            self.assertEqual(elegir(anterior=anterior).problemas, (df.FALTA,), anterior)

    def test_nuevo_y_anterior_iguales(self):
        r = elegir(("Lunes",), {"lunes": ("18:00–19:00", "19:00–20:00")}, anterior="lunes 18:00-20:00")
        self.assertEqual((r.franjas, r.origen), ((F("lunes", 18, 0, 20, 0),), df.ORIGEN_NUEVO))

    def test_nuevo_y_anterior_distintos_piden_aclaracion(self):
        r = elegir(("Lunes",), {"lunes": ("18:00–19:00",)}, anterior="martes 10:00-12:00")
        self.assertEqual((r.franjas, r.problemas), ((), (df.CONTRADICTORIA,)))

    def test_texto_anterior_solo_con_zona_no_contradice(self):
        r = elegir(("Lunes",), {"lunes": ("18:00–19:00",)}, anterior="Europe/Madrid")
        self.assertEqual(r.franjas, (F("lunes", 18, 0, 19, 0),))


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestEnElCiclo(unittest.TestCase):
    def ciclo(self, personas):
        prueba = ta.TestCicloAutomatico()
        prueba.setUp()
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        return alm, envio, prueba.ciclo(alm, envio)

    def alba_nueva(self, **kw):
        base = dict(disponibilidad=None, zona_horaria=None, zona_horaria_seleccionada="Europe/Madrid",
                    dias_disponibles=("Lunes",), franjas={"lunes": ("18:00–19:00", "19:00–20:00")})
        base.update(kw)
        return alba(**base)

    def test_formulario_nuevo_y_texto_anterior_hacen_match(self):
        alm, envio, _ = self.ciclo([self.alba_nueva(), bruno()])
        [f] = alm.filas.values()
        self.assertEqual(f.inicio_utc, INICIO)        # lunes 18:00 Madrid, como con el texto anterior
        self.assertEqual(len(envio.enviados), 2)

    def test_horario_ambiguo_no_crea_match_ni_correos(self):
        alm, envio, r = self.ciclo([self.alba_nueva(franjas={"lunes": ("Otro",)},
                                                    otras_franjas={"lunes": "por la tarde"}), bruno()])
        self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0))
        self.assertTrue(any("requiere aclaración" in a for a in r.avisos))

    def test_bloques_que_no_alcanzan_la_duracion_no_se_inventan(self):
        # Alba solo 18:00–18:30 con «Otro»: no hay 60 min seguidos; no se amplía.
        alm, envio, _ = self.ciclo([self.alba_nueva(franjas={"lunes": ("Otro",)},
                                                    otras_franjas={"lunes": "18:00–18:30"}), bruno()])
        self.assertEqual((len(alm.filas), len(envio.enviados)), (0, 0))

    def test_a1_marca_el_problema(self):
        ev = evaluar_participante(self.alba_nueva(dias_disponibles=("Lunes", "Martes")), resolver_zona_real)
        self.assertFalse(ev.apta)
        self.assertIn("Franjas Martes (falta)", ev.a1_problemas)


if __name__ == "__main__":
    unittest.main()

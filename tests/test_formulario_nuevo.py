"""Etapa 1: lectura de las columnas del formulario nuevo (2026-11-22). Datos ficticios.

Estas columnas solo se LEEN: no cambian la elegibilidad ni los horarios.
"""
import dataclasses
import unittest

from encuentros.automatico import evaluar_participante
from encuentros.correo import EnvioSimulado
from encuentros.notion_api import AlmacenNotion, ClienteNotion
from encuentros.notion_mapa import (
    COLUMNAS_FRANJAS, COLUMNAS_NUEVAS_PARTICIPANTES, COLUMNAS_OTRAS_FRANJAS,
    COLUMNAS_REALES_PARTICIPANTES, COLUMNAS_TEMAS_ADICIONALES, OPCIONES_FRANJA, OPCIONES_MINUTOS,
)
from encuentros.zonas import resolver_zona_real
from tests import test_automatico as ta    # módulo: así sus pruebas no se ejecutan dos veces
from tests.apoyo import ZONAS_REALES
from tests.test_automatico import AlmacenMemoria, alba, bruno
from tests.test_notion_api import FILA_PARTICIPANTE, HttpFalso, t

# Columnas de Participantes leídas del esquema de Notion (solo nombres), releídas el
# 2026-11-22 tras eliminar «ID», «Acepta videollamada» y «Zona horaria» y crear «ID consecutivo».
ESQUEMA_NOTION_2026_11_22 = {
    "Alias", "Tipo de perfil", "Ofrece", "Quiere aprender", "Objetivo concreto", "Idioma",
    "Otro idioma", "Modalidad", "Disponibilidad + zona horaria",
    "Zona horaria seleccionada", "Días disponibles", "Minutos disponibles",
    "Minutos seleccionados", "Respaldo declarado", "Autorización para participar",
    "Correo electrónico", "Aptitud", "Revisión humana del respaldo", "Faltantes", "ID consecutivo",
    *(f"Franjas {d}" for d in ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")),
    *(f"Otras franjas {d}" for d in ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")),
    *(f"Ofrece {n}" for n in range(2, 8)), *(f"Quiere aprender {n}" for n in range(2, 8)),
}


def multi(*nombres):
    return {"type": "multi_select", "multi_select": [{"name": n} for n in nombres]}


def sel(n):
    return {"type": "select", "select": {"name": n} if n else None}


def leer(extra, base=None):
    fila = {**FILA_PARTICIPANTE, "properties": {**(base or FILA_PARTICIPANTE["properties"]), **extra}}
    http = HttpFalso([{"results": [fila], "has_more": False}])
    [p] = AlmacenNotion(ClienteNotion("token-ficticio", abrir=http)).personas()
    return p


NUEVAS = {
    "Otro idioma": t("Idioma ficticio"),
    "Zona horaria seleccionada": sel("America/Costa_Rica"),
    "Días disponibles": multi("Lunes", "Miércoles"),
    "Franjas Lunes": multi("18:00–19:00", "19:00–20:00"),
    "Franjas Miércoles": multi("Otro"),
    "Otras franjas Miércoles": t("07:30–08:15"),
    "Franjas Sábado": multi(),
    "Otras franjas Domingo": t(None),
    "Minutos seleccionados": sel("Otro"),
}


class TestMapa(unittest.TestCase):
    def test_columnas_coinciden_con_el_esquema_de_notion(self):
        self.assertEqual(COLUMNAS_REALES_PARTICIPANTES, ESQUEMA_NOTION_2026_11_22)
        self.assertTrue(COLUMNAS_NUEVAS_PARTICIPANTES <= ESQUEMA_NOTION_2026_11_22)

    def test_una_columna_de_franjas_por_dia(self):
        self.assertEqual(COLUMNAS_FRANJAS["miércoles"], "Franjas Miércoles")
        self.assertEqual(COLUMNAS_OTRAS_FRANJAS["sábado"], "Otras franjas Sábado")
        self.assertEqual(len(COLUMNAS_FRANJAS), 7)
        self.assertEqual(len(COLUMNAS_OTRAS_FRANJAS), 7)

    def test_opciones_del_formulario(self):
        self.assertEqual(len(OPCIONES_FRANJA), 25)
        self.assertEqual((OPCIONES_FRANJA[0], OPCIONES_FRANJA[23], OPCIONES_FRANJA[24]),
                         ("00:00–01:00", "23:00–24:00", "Otro"))
        self.assertEqual(OPCIONES_MINUTOS, ("15 minutos", "30 minutos", "45 minutos", "60 minutos",
                                            "90 minutos", "120 minutos", "Otro"))

    def test_temas_adicionales(self):
        self.assertEqual(len(COLUMNAS_TEMAS_ADICIONALES), 12)
        self.assertIn("Ofrece 7", COLUMNAS_TEMAS_ADICIONALES)
        self.assertNotIn("Ofrece", COLUMNAS_TEMAS_ADICIONALES)


class TestLectura(unittest.TestCase):
    def test_lee_las_columnas_nuevas(self):
        p = leer(NUEVAS)
        self.assertEqual(p.otro_idioma, "Idioma ficticio")
        self.assertEqual(p.zona_horaria_seleccionada, "America/Costa_Rica")
        self.assertEqual(p.dias_disponibles, ("Lunes", "Miércoles"))
        self.assertEqual(p.franjas, {"lunes": ("18:00–19:00", "19:00–20:00"), "miércoles": ("Otro",)})
        self.assertEqual(p.otras_franjas, {"miércoles": "07:30–08:15"})
        self.assertEqual(p.minutos_seleccionados, "Otro")
        self.assertEqual(p.temas_adicionales_con_datos, ())

    def test_conserva_las_columnas_anteriores(self):
        p = leer(NUEVAS)
        self.assertEqual((p.disponibilidad, p.minutos), ("lunes 18:00-20:00", 30))
        self.assertIsNone(p.zona_horaria)        # columna eliminada de Notion: ya no se lee

    def test_formato_anterior_sin_columnas_nuevas(self):
        p = leer({})
        self.assertEqual((p.otro_idioma, p.minutos_seleccionados), (None, None))
        sin_zona = {**FILA_PARTICIPANTE["properties"]}
        del sin_zona["Zona horaria seleccionada"]
        self.assertIsNone(leer({}, base=sin_zona).zona_horaria_seleccionada)
        self.assertEqual((p.dias_disponibles, p.franjas, p.otras_franjas), ((), {}, {}))

    def test_minutos_seleccionados_numericos(self):
        self.assertEqual(leer({"Minutos seleccionados": sel("45 minutos")}).minutos_seleccionados,
                         "45 minutos")
        self.assertIsNone(leer({"Minutos seleccionados": sel(None)}).minutos_seleccionados)

    def test_temas_adicionales_solo_se_nombran(self):
        p = leer({"Ofrece 3": t("contenido ficticio"), "Quiere aprender 2": t("otro contenido"),
                  "Ofrece 4": t(None)})
        self.assertEqual(p.temas_adicionales_con_datos, ("Ofrece 3", "Quiere aprender 2"))
        self.assertNotIn("contenido ficticio", repr(dataclasses.asdict(p)))


@unittest.skipUnless(ZONAS_REALES, "requiere tzdata (usar .venv)")
class TestFormularioNuevoCompleto(unittest.TestCase):
    """Con todas las columnas del formulario nuevo (y sin las anteriores) el perfil es
    apto y el ciclo propone la misma hora que con el formato anterior. Las reglas de
    cada campo están en test_zona_participante, test_idiomas,
    test_disponibilidad_formulario, test_minutos_formulario y test_temas_formulario."""

    NUEVO = dict(disponibilidad=None, zona_horaria=None, minutos=None,
                 zona_horaria_seleccionada="Europe/Madrid", idioma=["Español", "Inglés"],
                 dias_disponibles=("Lunes",), franjas={"lunes": ("18:00–19:00", "19:00–20:00")},
                 minutos_seleccionados="30 minutos")

    def test_solo_con_columnas_nuevas_es_apta(self):
        ev = evaluar_participante(alba(**self.NUEVO), resolver_zona_real)
        self.assertTrue(ev.apta, ev.a1_problemas)
        self.assertEqual((ev.solicitud.minutos_por_sesion, ev.solicitud.zona_horaria), (30, "Europe/Madrid"))

    def ciclo(self, personas):
        prueba = ta.TestCicloAutomatico()
        prueba.setUp()
        alm, envio = AlmacenMemoria(personas), EnvioSimulado()
        return alm, envio, prueba.ciclo(alm, envio)

    def test_el_ciclo_propone_el_mismo_horario(self):
        alm1, _, _ = self.ciclo([alba(), bruno()])
        alm2, _, _ = self.ciclo([alba(**self.NUEVO), bruno()])
        [f1], [f2] = alm1.filas.values(), alm2.filas.values()
        self.assertEqual((f1.inicio_utc, f1.minutos_a, f1.minutos_b),
                         (f2.inicio_utc, f2.minutos_a, f2.minutos_b))

    def test_aviso_de_temas_adicionales_sin_mostrar_contenido(self):
        alm, envio, r = self.ciclo([alba(temas_adicionales_con_datos=("Ofrece 2",)), bruno()])
        self.assertEqual(r.temas_adicionales_con_datos, 1)
        [aviso] = [a for a in r.avisos if "Ofrece 2…7" in a]
        self.assertIn("1 perfil(es)", aviso)
        self.assertNotIn("alba", aviso.lower())
        self.assertEqual(len(alm.filas), 1)          # el aviso no cambia el emparejamiento

    def test_sin_datos_adicionales_no_hay_aviso(self):
        _, _, r = self.ciclo([alba(), bruno()])
        self.assertEqual(r.temas_adicionales_con_datos, 0)
        self.assertFalse([a for a in r.avisos if "Ofrece 2…7" in a])


if __name__ == "__main__":
    unittest.main()

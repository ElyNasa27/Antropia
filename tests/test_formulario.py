"""Formulario de Participantes: columnas reales, campos internos y privacidad."""
import unittest
from pathlib import Path

from encuentros.formulario import RespuestaFormulario, cargar_respuestas_json, respuesta_desde_columnas
from encuentros.notion_mapa import (
    CAMPOS_INTERNOS_PARTICIPANTES, COLUMNAS_FORMULARIO, COLUMNAS_REALES_PARTICIPANTES, OPCIONES,
    SELECCION_MULTIPLE,
)

RUTA = Path(__file__).resolve().parent.parent / "datos" / "formulario_ficticio.json"


class TestColumnasDelFormulario(unittest.TestCase):
    def test_todas_las_preguntas_usan_columnas_reales(self):
        self.assertTrue(set(COLUMNAS_FORMULARIO.values()) <= COLUMNAS_REALES_PARTICIPANTES)

    def test_ningun_campo_interno_es_pregunta(self):
        self.assertFalse(set(COLUMNAS_FORMULARIO.values()) & CAMPOS_INTERNOS_PARTICIPANTES)
        for interno in ("Aptitud", "Revisión humana del respaldo", "Faltantes", "ID"):
            self.assertIn(interno, CAMPOS_INTERNOS_PARTICIPANTES)

    def test_minutos_de_ensenanza_en_minutos_disponibles(self):
        # «Minutos que enseña por encuentro» ya no existe en Notion (leído el 2026-11-21).
        self.assertEqual(COLUMNAS_FORMULARIO["minutos_que_ensena"], "Minutos disponibles")
        self.assertNotIn("Minutos que enseña por encuentro", COLUMNAS_REALES_PARTICIPANTES)
        self.assertNotIn("Minutos disponibles", CAMPOS_INTERNOS_PARTICIPANTES)

    def test_tipo_de_perfil_es_seleccion_multiple(self):
        self.assertIn("Participantes.Tipo de perfil", SELECCION_MULTIPLE)
        r = respuesta_desde_columnas({"Alias": "[PRUEBA] X", "Tipo de perfil": ["Tutor", "Mentor"]})
        self.assertEqual(r.tipo_perfil, ("Tutor", "Mentor"))
        r = respuesta_desde_columnas({"Alias": "[PRUEBA] X", "Tipo de perfil": "Tutor, Mentor"})
        self.assertEqual(r.tipo_perfil, ("Tutor", "Mentor"))
        r = respuesta_desde_columnas({"Alias": "[PRUEBA] X", "Tipo de perfil": [{"name": "Empírico"}]})
        self.assertEqual(r.tipo_perfil, ("Empírico",))
        self.assertEqual(respuesta_desde_columnas({"Alias": "[PRUEBA] X"}).tipo_perfil, ())

    def test_columna_de_telegram_eliminada(self):
        self.assertNotIn("Autorización para mensajes por Telegram", COLUMNAS_REALES_PARTICIPANTES)
        self.assertNotIn("Autorización para mensajes por Telegram", COLUMNAS_FORMULARIO.values())

    def test_catorce_preguntas_y_opciones_reales(self):
        self.assertEqual(len(COLUMNAS_FORMULARIO), 14)
        self.assertEqual(OPCIONES["Participantes.Tipo de perfil"],
                         ("Titulado", "Empírico", "Tutor", "Mentor", "Emprendedor", "Público general"))
        self.assertEqual(OPCIONES["Participantes.Acepta videollamada"], ("Sí", "No", "No aplica"))


class TestCargaDeRespuestas(unittest.TestCase):
    def test_carga_las_cinco_respuestas_ficticias(self):
        rs = cargar_respuestas_json(RUTA)
        self.assertEqual([r.referencia for r in rs], [f"prueba-0{i}" for i in range(1, 6)])
        self.assertTrue(all(r.alias.startswith("[PRUEBA]") for r in rs))

    def test_campos_internos_en_los_datos_se_ignoran(self):
        dani = cargar_respuestas_json(RUTA)[3]
        self.assertEqual(set(dani.columnas_ignoradas), {"Aptitud", "Revisión humana del respaldo"})
        self.assertFalse(hasattr(dani, "aptitud"))

    def test_telefono_rechazado(self):
        with self.assertRaises(ValueError):
            respuesta_desde_columnas({"Alias": "[PRUEBA] X", "Teléfono": "+00 0000 0009"})

    def test_el_correo_no_aparece_en_repr(self):
        r = respuesta_desde_columnas({"Alias": "[PRUEBA] X", "Correo electrónico": "x.prueba@example.com"})
        self.assertEqual(r.correo, "x.prueba@example.com")
        self.assertNotIn("example.com", repr(r))

    def test_la_respuesta_no_se_puede_modificar(self):
        r = RespuestaFormulario(alias="[PRUEBA] X")
        with self.assertRaises(Exception):
            r.alias = "otra"


if __name__ == "__main__":
    unittest.main()

"""A1: informe local para la persona revisora. No decide ni escribe nada."""
import dataclasses
import unittest
from pathlib import Path

from encuentros import a1_revision
from encuentros.a1_revision import AVISO_FINAL, InformeA1, revisar
from encuentros.formulario import cargar_respuestas_json, respuesta_desde_columnas
from tests.apoyo import ZONAS_REALES
from tests.test_mensajes import CORREO

RUTA = Path(__file__).resolve().parent.parent / "datos" / "formulario_ficticio.json"


def _informes():
    return {r.referencia: revisar(r) for r in cargar_respuestas_json(RUTA)}


class TestInformesFicticios(unittest.TestCase):
    def setUp(self):
        self.inf = _informes()

    def test_alba_completa(self):
        i = self.inf["prueba-01"]
        self.assertTrue(i.autoriza_participar)
        self.assertTrue(i.datos_completos)
        self.assertEqual(i.faltantes, [])
        self.assertIn("pendiente de revisión humana", i.respaldo)
        self.assertEqual(i.correo, "indicado (no se muestra aquí)")

    def test_bruno_mixta_que_acepta_videollamada(self):
        i = self.inf["prueba-02"]
        self.assertTrue(i.datos_completos)
        self.assertFalse(any("videollamada" in o for o in i.observaciones))
        self.assertIn("no indicado", i.correo)
        self.assertIn("no declarado", i.respaldo)

    def test_cora_incompleta(self):
        i = self.inf["prueba-03"]
        self.assertFalse(i.datos_completos)
        self.assertEqual(i.faltantes, ["Objetivo concreto", "Zona horaria", "Minutos disponibles"])

    def test_dani_sin_autorizacion_y_datos_internos_ignorados(self):
        i = self.inf["prueba-04"]
        self.assertFalse(i.autoriza_participar)
        self.assertIn("NO (no puede continuar)", i.texto())
        self.assertIn("Acepta videollamada (la modalidad es Mixta)", i.faltantes)
        self.assertTrue(any("formato Continente/Ciudad" in o for o in i.observaciones))
        self.assertTrue(any("Aptitud" in a for a in i.avisos))   # su «Apto» autoescrito no cuenta

    def test_bruno_con_varios_tipos_de_perfil(self):
        self.assertFalse(any("Tipo de perfil" in o for o in self.inf["prueba-02"].observaciones))

    def test_tipo_de_perfil_multiple_valores_y_vacio(self):
        base = {"Alias": "[PRUEBA] X", "Autorización para participar": True}
        r = respuesta_desde_columnas({**base, "Tipo de perfil": ["Tutor", "Doctora"]})
        obs = revisar(r).observaciones
        [o] = [o for o in obs if "Tipo de perfil" in o]        # solo la opción desconocida
        self.assertTrue(o.startswith("Tipo de perfil: valor no reconocido 'Doctora'"))
        self.assertIn("Tipo de perfil", revisar(respuesta_desde_columnas({**base, "Tipo de perfil": []})).faltantes)

    def test_eva_valores_que_la_revisora_debe_mirar(self):
        obs = " | ".join(self.inf["prueba-05"].observaciones)
        self.assertIn("Tipo de perfil: valor no reconocido 'Doctora'", obs)
        self.assertIn("Modalidad Presencial", obs)
        self.assertIn("no es un número entero (22.5)", obs)
        if ZONAS_REALES:
            self.assertIn("'Marte/Olympus' no existe en la base IANA", obs)
        self.assertIn("formato no parece válido", self.inf["prueba-05"].correo)


class TestA1NoDecideNiExpone(unittest.TestCase):
    def test_el_informe_no_tiene_campos_de_decision(self):
        campos = {f.name for f in dataclasses.fields(InformeA1)}
        self.assertFalse(campos & {"aptitud", "apto", "estado", "lista", "revision_respaldo", "aprobado"})

    def test_ningun_informe_muestra_correos(self):
        for i in _informes().values():
            self.assertIsNone(CORREO.search(i.texto()), i.texto())

    def test_todos_terminan_con_el_aviso(self):
        for i in _informes().values():
            self.assertTrue(i.texto().endswith(AVISO_FINAL))

    def test_no_propone_aptitud_ni_estado(self):
        for i in _informes().values():
            texto = i.texto()
            for palabra in ("Apto:", "Aptitud sugerida", "Estado:", "Lista"):
                self.assertNotIn(palabra, texto)

    def test_no_usa_ninguna_red_ni_notion(self):
        fuente = Path(a1_revision.__file__).read_text(encoding="utf-8")
        for prohibido in ("urllib", "requests", "http.client", "socket", "api.notion"):
            self.assertNotIn(prohibido, fuente)

    def test_no_inventa_datos(self):
        vacia = respuesta_desde_columnas({"Alias": "[PRUEBA] Vacía"})
        i = revisar(vacia)
        self.assertEqual(len(i.faltantes), 9)   # todo lo obligatorio salvo el alias
        self.assertFalse(i.autoriza_participar)
        self.assertEqual(i.observaciones, [])


if __name__ == "__main__":
    unittest.main()

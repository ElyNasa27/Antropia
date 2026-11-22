"""Tercer cierre: el modo REAL exige ANTROPIA_ACTIVO=si (programado y manual).

Notion, Gmail y el ciclo se sustituyen por dobles que registran si se crearon:
estas pruebas nunca se conectan a nada. Variables y valores son ficticios.
"""
import contextlib
import io
import os
import unittest
from pathlib import Path
from unittest import mock

import ciclo_automatico
from encuentros.automatico import Resumen
from encuentros.correo import EnvioSimulado
from encuentros.notion_api import AlmacenSoloLectura

BASE = {
    "NOTION_TOKEN": "token-ficticio-de-prueba",
    "ANTROPIA_CLAVE_CODIGOS": "clave-ficticia-" + "x" * 32,
    "ANTROPIA_FORMULARIO_URL": "https://formulario.example/responder",
}
GMAIL = {"ANTROPIA_SMTP_USUARIO": "remitente@example.org", "ANTROPIA_SMTP_CLAVE": "clave-ficticia"}
WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ciclo-automatico.yml"


class TestTercerCierre(unittest.TestCase):
    def ejecutar(self, argv, entorno):
        """Ejecuta main() con dobles. Devuelve (código, dobles, salida de error)."""
        dobles = {n: mock.MagicMock(name=n) for n in ("ClienteNotion", "AlmacenNotion", "EnvioGmailSMTP", "Ciclo")}
        dobles["Ciclo"].return_value.ejecutar.return_value = Resumen()
        err = io.StringIO()
        with mock.patch.dict(os.environ, entorno, clear=True), \
                mock.patch.multiple(ciclo_automatico, **dobles), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            codigo = ciclo_automatico.main(argv)
        return codigo, dobles, err.getvalue()

    def assertNadaCreado(self, dobles):
        for nombre in ("ClienteNotion", "AlmacenNotion", "EnvioGmailSMTP", "Ciclo"):
            self.assertFalse(dobles[nombre].called, f"{nombre} no debía crearse")

    # -- modo real desactivado ------------------------------------------------
    def test_real_sin_antropia_activo_se_detiene_antes_de_notion_y_correo(self):
        codigo, dobles, err = self.ejecutar([], {**BASE, **GMAIL})
        self.assertEqual(codigo, ciclo_automatico.SALIDA_REAL_DESACTIVADO)
        self.assertNadaCreado(dobles)
        self.assertIn("Modo real desactivado", err)

    def test_real_con_valores_distintos_de_si_tambien_se_detiene(self):
        for valor in ("", "no", "Si", "SI", "sí", " si", "si ", "true", "1"):
            with self.subTest(valor=valor):
                codigo, dobles, _ = self.ejecutar([], {**BASE, **GMAIL, "ANTROPIA_ACTIVO": valor})
                self.assertEqual(codigo, ciclo_automatico.SALIDA_REAL_DESACTIVADO)
                self.assertNadaCreado(dobles)

    def test_real_desactivado_se_detiene_aunque_falten_credenciales(self):
        # El cierre va primero: ni siquiera se comprueban ni usan las demás variables.
        codigo, dobles, err = self.ejecutar([], {})
        self.assertEqual(codigo, ciclo_automatico.SALIDA_REAL_DESACTIVADO)
        self.assertNadaCreado(dobles)
        self.assertNotIn("Faltan variables", err)

    # -- modo real activado -----------------------------------------------------
    def test_real_con_antropia_activo_si_usa_notion_y_gmail(self):
        codigo, dobles, _ = self.ejecutar([], {**BASE, **GMAIL, "ANTROPIA_ACTIVO": "si"})
        self.assertEqual(codigo, 0)
        dobles["ClienteNotion"].assert_called_once_with(BASE["NOTION_TOKEN"])
        dobles["EnvioGmailSMTP"].assert_called_once_with()
        almacen, envio, _ = dobles["Ciclo"].call_args.args
        self.assertIs(almacen, dobles["AlmacenNotion"].return_value)       # escribe en Notion
        self.assertIs(envio, dobles["EnvioGmailSMTP"].return_value)        # envío real

    def test_real_activo_pero_sin_gmail_se_detiene_antes_de_notion(self):
        codigo, dobles, err = self.ejecutar([], {**BASE, "ANTROPIA_ACTIVO": "si"})
        self.assertEqual(codigo, 2)
        self.assertIn("ANTROPIA_SMTP_USUARIO", err)
        self.assertNadaCreado(dobles)

    # -- simulación ---------------------------------------------------------------
    def test_simulacion_funciona_sin_antropia_activo_ni_gmail(self):
        for activo in ({}, {"ANTROPIA_ACTIVO": "no"}):
            with self.subTest(activo=activo):
                codigo, dobles, _ = self.ejecutar(["--simulacion"], {**BASE, **activo})
                self.assertEqual(codigo, 0)
                self.assertFalse(dobles["EnvioGmailSMTP"].called)          # nunca Gmail
                almacen, envio, _ = dobles["Ciclo"].call_args.args
                self.assertIsInstance(almacen, AlmacenSoloLectura)          # no escribe en Notion
                self.assertIsInstance(envio, EnvioSimulado)                 # no envía correos

    def test_simulacion_con_antropia_activo_si_sigue_sin_escribir_ni_enviar(self):
        codigo, dobles, _ = self.ejecutar(["--simulacion"], {**BASE, **GMAIL, "ANTROPIA_ACTIVO": "si"})
        self.assertEqual(codigo, 0)
        self.assertFalse(dobles["EnvioGmailSMTP"].called)
        almacen, envio, _ = dobles["Ciclo"].call_args.args
        self.assertIsInstance(almacen, AlmacenSoloLectura)
        self.assertIsInstance(envio, EnvioSimulado)

    # -- workflow -------------------------------------------------------------------
    def test_el_workflow_pasa_antropia_activo_al_programa(self):
        texto = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ANTROPIA_ACTIVO: ${{ vars.ANTROPIA_ACTIVO }}", texto)
        self.assertIn("vars.ANTROPIA_ACTIVO == 'si'", texto)          # el programado sigue igual
        self.assertIn("default: simulacion", texto)                   # el manual, en simulación


if __name__ == "__main__":
    unittest.main()

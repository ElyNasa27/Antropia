"""Consultor del análisis de temas por significado con Claude Haiku 5.5 (API de Anthropic).

Estado: PREPARADO EN LOCAL, SIN USAR. Nada de este proyecto lo crea por sí solo:
ni el ciclo automático ni A2 lo activan. Para una llamada real hacen falta las
tres cosas a la vez:
  1. ANTROPIA_ANALISIS_SEMANTICO=si en el entorno;
  2. el paquete «anthropic» instalado y una credencial (ANTHROPIC_API_KEY);
  3. llamar expresamente a crear_consultor_real().

Qué se envía en cada consulta (ver crear_peticion): las instrucciones fijas de
temas_semantica.INSTRUCCIONES y los TEXTOS de «Ofrece» y «Quiere aprender» de
una sola dirección. Nada más: ni nombres, ni correos, ni ids, ni respaldos, ni
horarios. Lo que sí llegaría es cualquier dato que una persona haya escrito
dentro de esos textos.

Si la respuesta es un rechazo, queda cortada o no es JSON válido, se lanza
ConsultaFallida: AnalizadorSemantico usa entonces las reglas locales. Si es
JSON pero no cumple las reglas, temas_semantica.validar_respuesta la convierte
en «requiere aclaración».
"""
from __future__ import annotations

import json
import os

from .temas_semantica import CUBRE, NO_CUBRE, REQUIERE

MODELO = "claude-haiku-5-5"
ESFUERZO = "low"           # clasificación breve: basta con poco razonamiento
MAX_TOKENS = 2048
VARIABLE_ACTIVACION = "ANTROPIA_ANALISIS_SEMANTICO"
VALOR_ACTIVO = "si"

ESQUEMA = {
    "type": "object",
    "properties": {
        "veredicto": {"type": "string", "enum": [CUBRE, NO_CUBRE, REQUIERE]},
        "coincidencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ofrece": {"type": "string"}, "busca": {"type": "string"}},
                "required": ["ofrece", "busca"],
                "additionalProperties": False,
            },
        },
        "motivo": {"type": "string"},
    },
    "required": ["veredicto", "coincidencias", "motivo"],
    "additionalProperties": False,
}


class ConsultaFallida(Exception):
    """La consulta no dio un veredicto utilizable (rechazo, respuesta cortada, JSON inválido)."""


def crear_peticion(consulta: dict) -> dict:
    """Los argumentos EXACTOS de messages.create. No hace ninguna llamada."""
    datos = {"ofrece": list(consulta["ofrece"]), "quiere_aprender": list(consulta["quiere_aprender"])}
    return {
        "model": MODELO,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": ESFUERZO, "format": {"type": "json_schema", "schema": ESQUEMA}},
        "system": consulta["instrucciones"],
        "messages": [{"role": "user", "content": json.dumps(datos, ensure_ascii=False)}],
    }


class ConsultorClaude:
    """Consultor para AnalizadorSemantico. El cliente se inyecta (en las pruebas, uno simulado)."""

    def __init__(self, cliente) -> None:
        if cliente is None:
            raise ValueError("Hace falta un cliente explícito; no se crea ninguno por defecto.")
        self.cliente = cliente

    def __call__(self, consulta: dict) -> dict:
        resp = self.cliente.messages.create(**crear_peticion(consulta))
        if resp.stop_reason == "refusal":       # Haiku 5.5 no tiene modelo de respaldo
            raise ConsultaFallida("la consulta fue rechazada")
        if resp.stop_reason == "max_tokens":
            raise ConsultaFallida("respuesta cortada")
        texto = next((b.text for b in resp.content if b.type == "text"), None)  # puede haber bloques «thinking»
        if texto is None:
            raise ConsultaFallida("respuesta sin texto")
        try:
            return json.loads(texto)
        except json.JSONDecodeError as e:
            raise ConsultaFallida("respuesta que no es JSON") from e


def crear_consultor_real() -> ConsultorClaude:
    """Solo con ANTROPIA_ANALISIS_SEMANTICO=si. Importa «anthropic» aquí, no antes."""
    if os.environ.get(VARIABLE_ACTIVACION, "") != VALOR_ACTIVO:
        raise RuntimeError(f"Análisis semántico desactivado: {VARIABLE_ACTIVACION} no es «{VALOR_ACTIVO}».")
    import anthropic   # noqa: PLC0415 - dependencia opcional, solo para llamadas reales

    return ConsultorClaude(anthropic.Anthropic())

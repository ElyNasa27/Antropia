"""Canal de salida del piloto: una bandeja de borradores.

No existe ninguna función de envío. Más adelante, un canal de WhatsApp
implementaría la misma interfaz y solo enviaría mensajes aprobados.
"""
from __future__ import annotations

from .modelos import Mensaje, OperacionNoPermitida


class BandejaBorradores:
    def __init__(self) -> None:
        self.mensajes: list[Mensaje] = []

    def preparar(self, mensaje: Mensaje) -> Mensaje:
        self.mensajes.append(mensaje)
        return mensaje

    def aprobar(self, mensaje_id: str, revisor: str) -> Mensaje:
        if not revisor or not revisor.strip():
            raise OperacionNoPermitida("Se requiere el nombre de la persona que revisa.")
        m = next((m for m in self.mensajes if m.id == mensaje_id), None)
        if m is None:
            raise KeyError(f"Mensaje {mensaje_id} no encontrado")
        m.estado = "aprobado (piloto: no se envía)"
        m.revisado_por = revisor
        return m

    def para(self, participante_id: str, tipo: str | None = None) -> list[Mensaje]:
        return [
            m for m in self.mensajes
            if m.destinatario_id == participante_id and (tipo is None or m.tipo == tipo)
        ]

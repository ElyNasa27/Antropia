"""Canal de salida del piloto: una bandeja de borradores.

No existe ninguna función de envío. Más adelante, un canal de WhatsApp
implementaría la misma interfaz y solo enviaría mensajes aprobados.

Aprobar un borrador exige un actor del directorio SIMULADO con rol de
coordinación. Es una simulación: no verifica identidades reales.
"""
from __future__ import annotations

from .autorizacion_simulada import Accion, DirectorioSimulado
from .modelos import Mensaje, OperacionNoPermitida


class BandejaBorradores:
    def __init__(self, directorio: DirectorioSimulado | None = None) -> None:
        self.mensajes: list[Mensaje] = []
        self.directorio = directorio   # Coordinacion lo asigna si falta

    def preparar(self, mensaje: Mensaje) -> Mensaje:
        self.mensajes.append(mensaje)
        return mensaje

    def aprobar(self, mensaje_id: str, revisor: object) -> Mensaje:
        if self.directorio is None:
            raise OperacionNoPermitida("La bandeja no tiene directorio de personas simuladas.")
        autorizado = self.directorio.autorizar(revisor, Accion.APROBAR_BORRADOR)
        m = next((m for m in self.mensajes if m.id == mensaje_id), None)
        if m is None:
            raise KeyError(f"Mensaje {mensaje_id} no encontrado")
        m.estado = "aprobado (piloto: no se envía)"
        m.revisado_por = autorizado.id
        return m

    def para(self, participante_id: str, tipo: str | None = None) -> list[Mensaje]:
        return [
            m for m in self.mensajes
            if m.destinatario_id == participante_id and (tipo is None or m.tipo == tipo)
        ]

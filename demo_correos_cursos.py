"""Demo con datos FICTICIOS de los correos de coincidencias de cursos.

No se conecta a Notion ni envía nada: imprime cómo quedarían los correos para que
una persona revise el texto. Uso:  python demo_correos_cursos.py
"""
from __future__ import annotations

from encuentros.automatico import Persona
from encuentros.correo_cursos import redactar
from encuentros.match_cursos import emparejar_por_cursos

INSTRUCCIONES = "[Instrucciones para responder: pendientes de configurar en ANTROPIA_CURSOS_INSTRUCCIONES]"


def ficticia(pid, n, alias, ofrece, quiere, objetivo=None, minutos=None):
    return Persona(id=pid, alias=alias, correo=f"{pid}@example.org", autoriza=True, ofrece=ofrece,
                   quiere_aprender=quiere, objetivo_concreto=objetivo, minutos_seleccionados=minutos,
                   id_consecutivo=n, respaldo="Título ficticio (sin revisar)")


def main() -> None:
    personas = [
        ficticia("p1", 1, "Ana Ficticia", "Cerámica básica", "Guitarra acústica",
                 objetivo="Tocar tres canciones en una reunión familiar", minutos="45 minutos"),
        ficticia("p2", 2, "Beto Ficticio", "Guitarra acústica", "Cerámica básica",
                 objetivo="Hacer una taza para regalar", minutos="30 minutos"),
        ficticia("p3", 3, "Caro Ficticia", "Huerto en macetas", "", minutos="60 minutos"),
        ficticia("p4", 4, "Dani Ficticio", "", "Huerto en macetas", objetivo="Cultivar hierbas en el balcón"),
    ]
    por_id = {p.id: p for p in personas}
    r = emparejar_por_cursos(personas)
    for par in r.reciprocos + r.una_direccion:
        for lado, yo_id, otra_id in (("A", par.a, par.b), ("B", par.b, par.a)):
            asunto, cuerpo = redactar(par, lado, por_id[yo_id], por_id[otra_id], INSTRUCCIONES)
            print("=" * 72)
            rol = f"destinatario {lado}" if par.tipo == "recíproco" else ("quien enseña" if lado == "A" else "quien aprende")
            print(f"[{par.tipo} · {rol}]")
            print(f"Asunto: {asunto}\n")
            print(cuerpo)
    print("=" * 72)
    print("Demo con datos ficticios: no se ha enviado nada.")


if __name__ == "__main__":
    main()

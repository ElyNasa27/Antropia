"""Agente de match por CURSOS (2026-11-22). Solo calcula: no escribe ni envía nada.

Empareja personas teniendo en cuenta ÚNICAMENTE sus cursos (temas), leídos de los
perfiles con la misma lectura que la base Cursos (temas_formulario: un tema por
línea; una sola línea con la separación anterior; como máximo 7). No mira idioma,
horario, minutos, zona ni modalidad.

Tipos de match (decisión del usuario: los dos, por separado):
  - Recíproco: A ofrece un curso que B quiere aprender Y B ofrece uno que A quiere.
  - En una dirección: solo una de las dos enseña algo a la otra.

Los cursos coinciden si son el mismo texto sin distinguir mayúsculas, tildes ni
espacios (igual que en Cursos). Temas parecidos («Soporte computadoras» /
«Soporte computadores») NO coinciden: no se fusiona ni se interpreta nada.

Protecciones (elegidas por el usuario):
  - Solo perfiles con «Autorización para participar» marcada (decisión del
    2026-11-22: se exige).
  - Solo perfiles con correo válido y único (duplicados comprobados entre TODAS las
    filas leídas, también las que no autorizan). Nunca se unen registros.
  - Dos filas con el mismo alias no se emparejan (posible misma persona).
  - Un campo con más de 7 temas no se usa (requiere aclaración).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from . import a2_match
from .automatico import Persona, marcar_correos_duplicados, problema_de_correo
from .cursos import MOTIVO_SIN_AUTORIZACION, clave_tema, referencia
from .temas_formulario import leer_temas_formulario

RECIPROCO = "recíproco"
UNA_DIRECCION = "en una dirección"


@dataclass(frozen=True)
class Coincidencia:
    curso: str          # el curso tal como lo escribió quien lo ofrece
    pidio: str          # tal como lo escribió quien quiere aprenderlo


@dataclass(frozen=True)
class ParCursos:
    tipo: str
    a: str                                   # id de la fila A
    b: str
    ref_a: str                               # «fila #N» (nunca alias ni correo)
    ref_b: str
    a_ensena: tuple[Coincidencia, ...]       # cursos que A puede enseñar a B
    b_ensena: tuple[Coincidencia, ...]

    @property
    def total(self) -> int:
        return len(self.a_ensena) + len(self.b_ensena)


@dataclass
class ResultadoCursos:
    reciprocos: list[ParCursos] = field(default_factory=list)
    una_direccion: list[ParCursos] = field(default_factory=list)
    perfiles: int = 0
    considerados: int = 0
    excluidos: dict[str, int] = field(default_factory=dict)
    pares_mismo_alias: int = 0               # pares con cursos en común, no emparejados
    campos_con_demasiados: int = 0


def _cursos(texto: str | None) -> tuple[dict[str, str], bool]:
    """{clave: texto} y si había más de 7 (entonces no se usa ninguno)."""
    temas, demasiados = leer_temas_formulario(texto)
    if demasiados:
        return {}, True
    res: dict[str, str] = {}
    for t in temas:
        res.setdefault(clave_tema(t), t)
    return res, False


def _coincidencias(ofrece: dict[str, str], busca: dict[str, str]) -> tuple[Coincidencia, ...]:
    return tuple(Coincidencia(ofrece[k], busca[k]) for k in sorted(set(ofrece) & set(busca), key=lambda k: ofrece[k]))


def emparejar_por_cursos(personas: list[Persona]) -> ResultadoCursos:
    r = ResultadoCursos(perfiles=len(personas))
    marcar_correos_duplicados(personas)
    candidatos = []
    for p in personas:
        problema = MOTIVO_SIN_AUTORIZACION if p.autoriza is not True else problema_de_correo(p)
        if problema:
            r.excluidos[problema] = r.excluidos.get(problema, 0) + 1
            continue
        ofrece, d1 = _cursos(p.ofrece)
        busca, d2 = _cursos(p.quiere_aprender)
        r.campos_con_demasiados += d1 + d2
        candidatos.append((p, ofrece, busca))
    r.considerados = len(candidatos)

    orden = sorted(candidatos, key=lambda c: (c[0].id_consecutivo is None, c[0].id_consecutivo or 0, c[0].id))
    for (pa, oa, ba), (pb, ob, bb) in combinations(orden, 2):
        a_ensena, b_ensena = _coincidencias(oa, bb), _coincidencias(ob, ba)
        if not a_ensena and not b_ensena:
            continue
        if a2_match._normalizar(pa.alias or "") and \
                a2_match._normalizar(pa.alias or "") == a2_match._normalizar(pb.alias or ""):
            r.pares_mismo_alias += 1
            continue
        if not a_ensena:                      # en una dirección: A es siempre quien enseña
            pa, pb, a_ensena, b_ensena = pb, pa, b_ensena, a_ensena
        par = ParCursos(RECIPROCO if b_ensena else UNA_DIRECCION, pa.id, pb.id,
                        referencia(pa, pa.id), referencia(pb, pb.id), a_ensena, b_ensena)
        (r.reciprocos if b_ensena else r.una_direccion).append(par)
    clave = lambda par: (-par.total, par.ref_a, par.ref_b)  # noqa: E731
    r.reciprocos.sort(key=clave)
    r.una_direccion.sort(key=clave)
    return r


def _lista(cs: tuple[Coincidencia, ...]) -> str:
    return "; ".join(c.curso if c.curso == c.pidio else f"{c.curso} (pidió: {c.pidio})" for c in cs)


def recuentos(r: ResultadoCursos) -> list[str]:
    """Solo números y etiquetas fijas: sin cursos, filas, alias ni correos."""
    lineas = [
        "Agente de match por cursos (solo cálculo: no se ha escrito nada ni enviado correos).",
        f"Perfiles leídos: {r.perfiles} · considerados: {r.considerados}",
    ]
    lineas += [f"Excluidos · {m}: {n}" for m, n in sorted(r.excluidos.items())]
    lineas += [
        f"Matches recíprocos: {len(r.reciprocos)} · en una dirección: {len(r.una_direccion)}",
        f"Pares con cursos en común no emparejados por tener el mismo alias: {r.pares_mismo_alias}",
        f"Campos con más de 7 temas (no se usan): {r.campos_con_demasiados}",
    ]
    return lineas


def informe(r: ResultadoCursos) -> list[str]:
    """Con cursos y «fila #N»; nunca alias ni correos."""
    lineas = recuentos(r)
    for titulo, pares in (("Recíprocos", r.reciprocos), ("En una dirección", r.una_direccion)):
        lineas.append(f"{titulo}:")
        if not pares:
            lineas.append("  (ninguno)")
        for p in pares:
            if p.tipo == RECIPROCO:
                lineas.append(f"  {p.ref_a} ↔ {p.ref_b} · {p.ref_a} enseña: {_lista(p.a_ensena)} · "
                              f"{p.ref_b} enseña: {_lista(p.b_ensena)}")
            else:
                lineas.append(f"  {p.ref_a} → {p.ref_b} · enseña: {_lista(p.a_ensena)}")
    return lineas

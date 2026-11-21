"""Autorización SIMULADA: personas ficticias (Ana, Luis, Marta) con roles.

Estas pruebas comprueban las REGLAS de roles dentro del programa. No prueban
ninguna autenticación: no existe. Nadie verifica quién es cada persona.
"""
import dataclasses
import json
import unittest
from pathlib import Path

from encuentros import autorizacion_simulada as az
from encuentros.autorizacion_simulada import (
    PERMISOS, Accion, DirectorioSimulado, PersonaSimulada, Rol, cargar_directorio_json,
)
from encuentros.canal import BandejaBorradores
from encuentros.coordinacion import Coordinacion
from encuentros.modelos import EstadoPacto, OperacionNoPermitida, TipoRespuesta as T
from encuentros.repositorio import RepositorioMemoria
from tests.apoyo import (
    COORDINADORA, DESDE, DIRECTORIO, ENLACE_PRUEBA, REGISTRO, REVISORA, RUTA_PERSONAS,
    aceptan_y_se_revisa, hasta_invitaciones, nuevo_escenario, responder, revisar_respuestas,
)

RAIZ = Path(__file__).resolve().parent.parent

# Tabla esperada, escrita a mano: si alguien cambia PERMISOS, esta prueba lo detecta.
ESPERADO = {
    "rev-ana": {Accion.REVISAR_RESPALDO, Accion.REVISAR_MINUTOS,
                Accion.APROBAR_PROPUESTA, Accion.RECHAZAR_PROPUESTA},
    "coord-luis": {Accion.REVISAR_PACTO, Accion.REGISTRAR_RESPUESTA, Accion.REVISAR_RESPUESTA,
                   Accion.CONFIRMAR_PACTO, Accion.APROBAR_BORRADOR},
    "reg-marta": {Accion.REGISTRAR_RESPUESTA},
}


def _directorio(*extra: PersonaSimulada) -> DirectorioSimulado:
    """Copia del directorio ficticio con personas adicionales (también ficticias)."""
    return DirectorioSimulado(DIRECTORIO.personas() + list(extra))


def _pacto_con_invitaciones(coord):
    return hasta_invitaciones(coord)


class TestDirectorioSimulado(unittest.TestCase):
    def test_personas_ficticias_ana_luis_marta(self):
        personas = {p.id: p for p in DIRECTORIO.personas()}
        self.assertEqual(set(personas), {"rev-ana", "coord-luis", "reg-marta"})
        self.assertEqual(personas["rev-ana"].nombre, "Ana (ficticia)")
        self.assertEqual(personas["coord-luis"].roles, frozenset({Rol.COORDINADORA}))
        self.assertEqual(personas["reg-marta"].roles, frozenset({Rol.REGISTRO_RESPUESTAS}))
        self.assertTrue(all(p.activa for p in personas.values()))

    def test_un_agente_no_puede_ser_persona(self):
        for persona in (PersonaSimulada("A2", "Agente", frozenset({Rol.REVISORA})),
                        PersonaSimulada("x", " a3 ", frozenset({Rol.COORDINADORA}))):
            with self.assertRaises(ValueError):
                _directorio(persona)

    def test_ids_repetidos_o_vacios(self):
        with self.assertRaises(ValueError):
            _directorio(PersonaSimulada("rev-ana", "Otra Ana", frozenset()))
        with self.assertRaises(ValueError):
            _directorio(PersonaSimulada(" ", "Sin id", frozenset()))

    def test_persona_desconocida(self):
        with self.assertRaises(OperacionNoPermitida):
            DIRECTORIO.actuar_como("alguien")

    def test_personas_y_actores_no_se_modifican(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            DIRECTORIO.personas()[0].roles = frozenset(Rol)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            REVISORA.persona_id = "coord-luis"


class TestMatrizDePermisos(unittest.TestCase):
    def test_cada_persona_solo_puede_lo_de_su_rol(self):
        for persona_id, permitidas in ESPERADO.items():
            actor = DIRECTORIO.actuar_como(persona_id)
            for accion in Accion:
                with self.subTest(persona=persona_id, accion=accion.name):
                    if accion in permitidas:
                        self.assertEqual(DIRECTORIO.autorizar(actor, accion).id, persona_id)
                    else:
                        with self.assertRaises(OperacionNoPermitida):
                            DIRECTORIO.autorizar(actor, accion)

    def test_todas_las_acciones_tienen_permisos(self):
        self.assertEqual(set(PERMISOS), set(Accion))

    def test_la_coordinadora_tambien_registra_respuestas(self):
        self.assertIn(Rol.COORDINADORA, PERMISOS[Accion.REGISTRAR_RESPUESTA])


class TestUnNombreEscritoNoBasta(unittest.TestCase):
    def test_textos_rechazados_en_cada_paso(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        for texto in ("Ana (ficticia)", "rev-ana", "Coordinadora del piloto", "", None):
            with self.assertRaises(OperacionNoPermitida) as ctx:
                coord.aprobar_match(m.id, texto, evidencia_revisada=True)
            self.assertIn("un nombre escrito no basta", str(ctx.exception))
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_pacto(pacto.id, "Luis (ficticio)")

    def test_actor_de_otro_directorio(self):
        otro = cargar_directorio_json(RUTA_PERSONAS)   # mismas personas, otro directorio
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.aprobar_match(m.id, otro.actuar_como("rev-ana"), evidencia_revisada=True)
        self.assertIn("otro directorio", str(ctx.exception))

    def test_sin_directorio_no_hay_pasos_humanos(self):
        coord = Coordinacion(RepositorioMemoria(), BandejaBorradores())
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_respaldo_declarado("alba", REVISORA, "Aprobada")


class TestRolesEnElFlujo(unittest.TestCase):
    def test_solo_la_revisora_aprueba_propuestas(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        for actor in (COORDINADORA, REGISTRO):
            with self.assertRaises(OperacionNoPermitida):
                coord.aprobar_match(m.id, actor, evidencia_revisada=True)
        with self.assertRaises(OperacionNoPermitida):
            coord.revisar_respaldo_declarado("alba", COORDINADORA, "Aprobada")

    def test_solo_la_coordinadora_revisa_y_confirma(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        pacto = coord.proponer_pacto(m.id, DESDE, "p1")
        for actor in (REVISORA, REGISTRO):
            with self.assertRaises(OperacionNoPermitida):
                coord.revisar_pacto(pacto.id, actor)
        coord.revisar_pacto(pacto.id, COORDINADORA)
        aceptan_y_se_revisa(coord, pacto)
        for actor in (REVISORA, REGISTRO):
            with self.assertRaises(OperacionNoPermitida):
                coord.confirmar_pacto(pacto.id, actor, ENLACE_PRUEBA)
        coord.confirmar_pacto(pacto.id, COORDINADORA, ENLACE_PRUEBA)
        # Quien revisó el pacto puede confirmarlo.
        self.assertEqual((pacto.revisado_por, pacto.confirmado_por), ("coord-luis", "coord-luis"))

    def test_registran_respuestas_marta_y_luis_pero_no_ana(self):
        coord = nuevo_escenario()
        pacto = _pacto_con_invitaciones(coord)
        with self.assertRaises(OperacionNoPermitida):
            responder(coord, pacto, "alba", T.ACEPTA, registrado_por=REVISORA)
        responder(coord, pacto, "alba", T.ACEPTA, registrado_por=REGISTRO)
        responder(coord, pacto, "bruno", T.ACEPTA, registrado_por=COORDINADORA)
        self.assertEqual(pacto.respuestas["alba"].registrado_por, "reg-marta")
        self.assertEqual(pacto.respuestas["bruno"].registrado_por, "coord-luis")

    def test_persona_inactiva(self):
        baja = PersonaSimulada("rev-baja", "Revisora de baja (ficticia)", frozenset({Rol.REVISORA}), activa=False)
        d = _directorio(baja)
        coord = nuevo_escenario(directorio=d, revisora=d.actuar_como("rev-ana"))
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.aprobar_match(m.id, d.actuar_como("rev-baja"), evidencia_revisada=True)
        self.assertIn("inactiva", str(ctx.exception))


class TestCuatroOjos(unittest.TestCase):
    """Quien confirma el pacto debe ser distinta de quien aprobó la propuesta."""

    def setUp(self):
        dos_roles = PersonaSimulada("rev-coord", "Persona con dos roles (ficticia)",
                                    frozenset({Rol.REVISORA, Rol.COORDINADORA}))
        self.d = _directorio(dos_roles)
        self.ambos = self.d.actuar_como("rev-coord")
        self.luis = self.d.actuar_como("coord-luis")
        marta = self.d.actuar_como("reg-marta")
        self.coord = nuevo_escenario(directorio=self.d, revisora=self.ambos)
        self.pacto = hasta_invitaciones(self.coord, revisora=self.ambos, coordinadora=self.ambos)
        for pid in self.pacto.participantes:
            responder(self.coord, self.pacto, pid, T.ACEPTA, registrado_por=marta)
        revisar_respuestas(self.coord, self.pacto, revisor=self.luis)

    def test_quien_aprobo_la_propuesta_no_confirma(self):
        with self.assertRaises(OperacionNoPermitida) as ctx:
            self.coord.confirmar_pacto(self.pacto.id, self.ambos, ENLACE_PRUEBA)
        self.assertIn("debe confirmarlo otra persona", str(ctx.exception))
        self.assertEqual(self.pacto.estado, EstadoPacto.LISTO_PARA_CONFIRMAR)
        self.assertEqual(self.coord.bandeja.para("alba", "confirmación"), [])

    def test_otra_persona_si_confirma(self):
        self.coord.confirmar_pacto(self.pacto.id, self.luis, ENLACE_PRUEBA)
        self.assertEqual(self.pacto.estado, EstadoPacto.CONFIRMADO)
        m = self.coord.repo.matches[self.pacto.match_id]
        self.assertEqual((m.decidido_por, self.pacto.confirmado_por), ("rev-coord", "coord-luis"))


class TestRevisionHumanaDeLasRespuestas(unittest.TestCase):
    def setUp(self):
        self.coord = nuevo_escenario()
        self.pacto = _pacto_con_invitaciones(self.coord)

    def _revisar(self, pid, version=1, revisor=COORDINADORA):
        return self.coord.revisar_respuesta(self.pacto.id, pid, revisor, version)

    def test_dos_aceptaciones_sin_revisar_no_permiten_confirmar(self):
        responder(self.coord, self.pacto, "alba", T.ACEPTA)
        responder(self.coord, self.pacto, "bruno", T.ACEPTA)
        self.assertEqual(self.pacto.estado, EstadoPacto.RESPUESTAS_POR_REVISAR)
        with self.assertRaises(OperacionNoPermitida):
            self.coord.confirmar_pacto(self.pacto.id, COORDINADORA, ENLACE_PRUEBA)
        self._revisar("alba")
        self.assertEqual(self.pacto.estado, EstadoPacto.RESPUESTAS_POR_REVISAR)
        with self.assertRaises(OperacionNoPermitida):   # falta la de Bruno
            self.coord.confirmar_pacto(self.pacto.id, COORDINADORA, ENLACE_PRUEBA)
        self._revisar("bruno")
        self.assertEqual(self.pacto.estado, EstadoPacto.LISTO_PARA_CONFIRMAR)
        self.coord.confirmar_pacto(self.pacto.id, COORDINADORA, ENLACE_PRUEBA)
        self.assertEqual(self.pacto.estado, EstadoPacto.CONFIRMADO)

    def test_la_revision_queda_ligada_a_la_version_vigente(self):
        responder(self.coord, self.pacto, "alba", T.ACEPTA)
        with self.assertRaises(OperacionNoPermitida):
            self._revisar("alba", version=2)
        self._revisar("alba", version=1)
        r = self.pacto.respuestas["alba"]
        self.assertEqual((r.version, r.revisada_por, r.version_revisada), (1, "coord-luis", 1))

    def test_solo_se_revisan_aceptaciones_ya_registradas(self):
        with self.assertRaises(OperacionNoPermitida) as ctx:
            self._revisar("alba")                          # aún no respondió
        self.assertIn("No hay una aceptación", str(ctx.exception))
        responder(self.coord, self.pacto, "alba", T.ACEPTA)
        self._revisar("alba")
        with self.assertRaises(OperacionNoPermitida):     # ya revisada
            self._revisar("alba")
        with self.assertRaises(OperacionNoPermitida):     # no participa
            self._revisar("dani")

    def test_revisar_antes_de_que_responda_la_otra_persona(self):
        responder(self.coord, self.pacto, "alba", T.ACEPTA)
        self._revisar("alba")
        self.assertEqual(self.pacto.estado, EstadoPacto.INVITACIONES_PREPARADAS)
        responder(self.coord, self.pacto, "bruno", T.ACEPTA)
        self.assertEqual(self.pacto.estado, EstadoPacto.RESPUESTAS_POR_REVISAR)

    def test_solo_la_coordinadora_revisa_respuestas(self):
        responder(self.coord, self.pacto, "alba", T.ACEPTA)
        for actor in (REVISORA, REGISTRO, "Luis (ficticio)"):
            with self.assertRaises(OperacionNoPermitida):
                self._revisar("alba", revisor=actor)

    def test_quien_registra_no_puede_revisar_su_propio_registro(self):
        otra = PersonaSimulada("coord-otra", "Otra coordinadora (ficticia)", frozenset({Rol.COORDINADORA}))
        d = _directorio(otra)
        luis, otra = d.actuar_como("coord-luis"), d.actuar_como("coord-otra")
        coord = nuevo_escenario(directorio=d, revisora=d.actuar_como("rev-ana"))
        pacto = hasta_invitaciones(coord, revisora=d.actuar_como("rev-ana"), coordinadora=luis)
        responder(coord, pacto, "alba", T.ACEPTA, registrado_por=luis)   # Luis registra
        with self.assertRaises(OperacionNoPermitida) as ctx:
            coord.revisar_respuesta(pacto.id, "alba", luis, 1)           # y no puede revisar
        self.assertIn("debe revisarla otra persona", str(ctx.exception))
        self.assertIsNone(pacto.respuestas["alba"].revisada_por)
        coord.revisar_respuesta(pacto.id, "alba", otra, 1)               # otra persona sí
        self.assertEqual(pacto.respuestas["alba"].revisada_por, "coord-otra")

    def test_una_version_nueva_anula_las_revisiones(self):
        responder(self.coord, self.pacto, "alba", T.ACEPTA)
        self._revisar("alba")
        responder(self.coord, self.pacto, "bruno", T.CAMBIOS, comentario="el lunes no puedo")
        self.coord.proponer_nueva_version(self.pacto.id, DESDE)
        self.coord.revisar_pacto(self.pacto.id, COORDINADORA)
        self.assertEqual(self.pacto.version_actual.numero, 2)
        self.assertTrue(all(r.revisada_por is None for r in self.pacto.respuestas.values()))
        aceptan_y_se_revisa(self.coord, self.pacto)
        self.assertTrue(all(r.version_revisada == 2 for r in self.pacto.respuestas.values()))
        self.coord.confirmar_pacto(self.pacto.id, COORDINADORA, ENLACE_PRUEBA)
        self.assertEqual(self.pacto.estado, EstadoPacto.CONFIRMADO)


class TestTransparenciaDeLaSimulacion(unittest.TestCase):
    def test_la_bitacora_registra_id_y_rol_simulado(self):
        coord = nuevo_escenario()
        pacto = _pacto_con_invitaciones(coord)
        aceptan_y_se_revisa(coord, pacto)
        coord.confirmar_pacto(pacto.id, COORDINADORA, ENLACE_PRUEBA)
        actores = [e.actor for e in coord.repo.bitacora]
        self.assertIn("Ana (ficticia) [rev-ana] · rol «revisora» (simulado: no verifica identidades reales)", actores)
        self.assertTrue(any("[coord-luis] · rol «coordinadora»" in a for a in actores))
        self.assertTrue(any("[reg-marta] · rol «registro_respuestas»" in a for a in actores))
        humanos = [e for e in coord.repo.bitacora if e.actor not in ("A2", "A3", "sistema", "Alba", "Bruno")]
        self.assertTrue(humanos and all("simulado" in e.actor for e in humanos))

    def test_la_bitacora_es_modificable_no_es_una_prueba(self):
        # Limitación documentada: cualquiera con acceso al programa puede alterarla.
        coord = nuevo_escenario()
        self.assertTrue(coord.repo.bitacora)
        coord.repo.bitacora.clear()
        self.assertEqual(coord.repo.bitacora, [])

    def test_codigo_y_documentacion_avisan_que_no_es_autenticacion(self):
        self.assertIn("NO ES AUTENTICACIÓN", az.__doc__)
        self.assertIn("No verifica identidades reales", az.__doc__)
        self.assertIn("bitácora", az.__doc__)
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        self.assertIn("no es autenticación", readme.lower())
        self.assertIn("bitácora", readme)
        nota = json.loads(RUTA_PERSONAS.read_text(encoding="utf-8"))["_nota"]
        self.assertIn("FICTICIAS", nota)
        self.assertIn("no verifican identidades", nota)


if __name__ == "__main__":
    unittest.main()

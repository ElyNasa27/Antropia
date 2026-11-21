"""Máximo de tres propuestas por solicitud y clave de ejecución contra duplicados.

Para superar el límite se generan candidatos FICTICIOS copiando los datos de
Bruno («Candidato ficticio N»).
"""
import copy
import unittest
from datetime import UTC, datetime, time

from encuentros.a2_match import MAX_CANDIDATOS_POR_SOLICITUD
from encuentros.modelos import Franja, OperacionNoPermitida
from tests.apoyo import DESDE, REVISORA, nuevo_escenario

MIERCOLES = [Franja("miércoles", time(12), time(13, 30))]   # CDMX; coincide con Alba los miércoles


def con_candidatos(n, lunes_para=None):
    """Añade n copias de Bruno. Todas solo los miércoles, salvo `lunes_para`."""
    def modificar(ps, ss):
        for i in range(1, n + 1):
            pid, sid = f"cand{i}", f"sol-cand{i}"
            p = copy.deepcopy(ps["bruno"])
            p.id, p.nombre = pid, f"Candidato ficticio {i}"
            s = copy.deepcopy(ss["sol-bruno"])
            s.id, s.participante_id = sid, pid
            if i != lunes_para:
                s.disponibilidad = list(MIERCOLES)
            ps[pid], ss[sid] = p, s
        del ps["bruno"], ss["sol-bruno"]
    return modificar


def activas_de(coord, sid):
    return [m for m in coord.repo.matches.values()
            if m.activa and sid in (m.solicitud_origen, m.solicitud_candidata)]


class TestMaximoTresPorSolicitud(unittest.TestCase):
    def test_el_limite_es_tres(self):
        self.assertEqual(MAX_CANDIDATOS_POR_SOLICITUD, 3)

    def test_cinco_candidatos_validos_solo_tres_propuestas(self):
        coord = nuevo_escenario(modificar=con_candidatos(5))
        res = coord.proponer_matches(DESDE, "e1")
        self.assertEqual(len(activas_de(coord, "sol-alba")), 3)
        resumen = res.por_solicitud["sol-alba"]
        self.assertEqual(len(resumen.propuestas), 3)
        self.assertEqual(len(resumen.omitidas_por_limite), 2)
        # Empate en horario -> orden estable por identificador de solicitud
        self.assertEqual([m.solicitud_candidata for m in res.propuestas],
                         ["sol-cand1", "sol-cand2", "sol-cand3"])

    def test_se_prefiere_el_horario_comun_mas_temprano(self):
        coord = nuevo_escenario(modificar=con_candidatos(5, lunes_para=5))
        res = coord.proponer_matches(DESDE, "e1")
        candidatas = [m.solicitud_candidata for m in res.propuestas]
        self.assertEqual(candidatas[0], "sol-cand5")   # lunes 30-nov va antes que miércoles 2-dic
        self.assertEqual(len(candidatas), 3)

    def test_las_omitidas_por_el_limite_no_reciben_propuesta_desde_su_solicitud(self):
        coord = nuevo_escenario(modificar=con_candidatos(5))
        res = coord.proponer_matches(DESDE, "e1")
        for sid in ("sol-cand4", "sol-cand5"):
            self.assertEqual(activas_de(coord, sid), [])
            self.assertIn("sol-alba", res.por_solicitud[sid].omitidas_por_limite)

    def test_rechazar_una_libera_un_hueco_en_otra_ejecucion(self):
        coord = nuevo_escenario(modificar=con_candidatos(5))
        res = coord.proponer_matches(DESDE, "e1")
        coord.rechazar_match(res.propuestas[0].id, REVISORA, "no encaja")
        self.assertEqual(len(activas_de(coord, "sol-alba")), 2)
        res2 = coord.proponer_matches(DESDE, "e2")
        self.assertEqual(len(res2.propuestas), 1)
        self.assertEqual(len(activas_de(coord, "sol-alba")), 3)

    def test_el_limite_tambien_cuenta_como_candidata(self):
        # Una Alba con 4 copias que buscan lo que ella ofrece: Alba aparece en <= 3.
        coord = nuevo_escenario(modificar=con_candidatos(4))
        coord.proponer_matches(DESDE, "e1")
        for m in coord.repo.matches.values():
            self.assertLessEqual(len(activas_de(coord, m.solicitud_origen)), 3)
            self.assertLessEqual(len(activas_de(coord, m.solicitud_candidata)), 3)


class TestClaveDeEjecucion(unittest.TestCase):
    def test_a2_requiere_clave(self):
        coord = nuevo_escenario()
        for clave in (None, "", "  "):
            with self.assertRaises(OperacionNoPermitida):
                coord.proponer_matches(DESDE, clave)

    def test_misma_clave_no_duplica_propuestas(self):
        coord = nuevo_escenario(modificar=con_candidatos(5))
        r1 = coord.proponer_matches(DESDE, "e1")
        r2 = coord.proponer_matches(DESDE, "e1")
        self.assertIs(r1, r2)
        self.assertEqual(len(coord.repo.matches), 3)

    def test_misma_clave_de_pacto_no_duplica_pactos(self):
        coord = nuevo_escenario()
        [m] = coord.proponer_matches(DESDE, "e1").propuestas
        coord.aprobar_match(m.id, REVISORA, evidencia_revisada=True)
        p1 = coord.proponer_pacto(m.id, DESDE, "p1")
        p2 = coord.proponer_pacto(m.id, DESDE, "p1")
        self.assertIs(p1, p2)
        self.assertEqual(len(coord.repo.pactos), 1)
        with self.assertRaises(OperacionNoPermitida):   # otra clave, mismo match abierto
            coord.proponer_pacto(m.id, DESDE, "p2")


if __name__ == "__main__":
    unittest.main()

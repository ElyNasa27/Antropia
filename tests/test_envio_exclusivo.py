"""Envío exclusivo con resultados inmutables. Servicios SIMULADOS: sin red ni correos.

Las ejecuciones simultáneas se prueban con hilos reales y un planificador que fija el
orden exacto de sus operaciones; se recorren TODAS las intercalaciones posibles.
"""
import itertools
import threading
import unittest

from encuentros.correo import ErrorEnvioDudoso, ErrorEnvioSeguro
from encuentros.envio_exclusivo import (
    ABANDONADO, CANCELADO, EN_CURSO, ESTADO_ENVIADO, PENDIENTE, POR_REVISAR, TERMINADA, Ejecucion,
    enviar_automatico, estado_de, reenviar_por_decision_humana, vista, vista_permite_primer_envio,
)

BASE = "antropia-correos/huella-ficticia-a"


class Planificador:
    """Hace que los hilos ejecuten sus operaciones exactamente en el orden `orden`
    (lista de nombres de hilo). Un hilo conserva el turno hasta su siguiente operación."""

    def __init__(self, orden):
        self.orden, self.pos, self.actual = list(orden), 0, None
        self.cv = threading.Condition()
        self.vivos = set()

    def _saltar_terminados(self):
        while self.pos < len(self.orden) and self.orden[self.pos] not in self.vivos:
            self.pos += 1

    def paso(self):
        yo = threading.current_thread().name
        if yo not in self.vivos:
            return                                        # llamada desde el hilo principal
        with self.cv:
            if self.actual == yo:
                self.pos += 1
                self.actual = None
                self.cv.notify_all()
            while True:
                self._saltar_terminados()
                if self.pos >= len(self.orden) or self.orden[self.pos] == yo:
                    self.actual = yo
                    return
                if not self.cv.wait(timeout=5):
                    raise RuntimeError("planificador bloqueado")

    def ejecutar(self, funciones):
        resultados, errores = {}, []

        def envoltura(nombre, f):
            try:
                resultados[nombre] = f()
            except Exception as e:                        # pragma: no cover - fallo de la prueba
                errores.append(e)
            finally:
                with self.cv:
                    if self.actual == nombre:
                        self.pos += 1
                        self.actual = None
                    self.vivos.discard(nombre)
                    self.cv.notify_all()

        self.vivos = set(funciones)
        hilos = [threading.Thread(target=envoltura, args=(n, f), name=n) for n, f in funciones.items()]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
        if errores:
            raise errores[0]
        return resultados


class RegistroSimulado:
    """«Crear solo si no existe» ATÓMICO. Nada se modifica ni se borra."""

    def __init__(self, planificador=None):
        self.datos, self._lock, self.p = {}, threading.Lock(), planificador
        self.perder_respuesta = set()                     # nombres cuya creación «no responde»
        self.caido = False

    def _paso(self):
        if self.p:
            self.p.paso()

    def crear(self, nombre, contenido):
        self._paso()
        if self.caido:
            return None
        with self._lock:
            creado = nombre not in self.datos
            if creado:
                self.datos[nombre] = contenido
        return None if nombre in self.perder_respuesta else creado

    def leer(self, nombre):
        self._paso()
        if self.caido:
            raise ConnectionError("registro no disponible (simulado)")
        with self._lock:
            return self.datos.get(nombre)


class RegistroTrazado(RegistroSimulado):
    """Anota cada operación (hilo, operación, resultado) para comprobar el orden real."""

    def __init__(self, planificador=None):
        super().__init__(planificador)
        self.traza = []

    def crear(self, nombre, contenido):
        r = super().crear(nombre, contenido)
        self.traza.append((threading.current_thread().name, "crear " + nombre.rsplit("/", 1)[1], r))
        return r

    def leer(self, nombre):
        r = super().leer(nombre)
        quien = threading.current_thread().name
        valor = "ninguna" if r is None else ("propia" if f"nonce-{quien}" in r else "ajena")
        self.traza.append((quien, "leer " + nombre.rsplit("/", 1)[1], valor))
        return r


class RegistroNoAtomico(RegistroSimulado):
    """Contraejemplo: «comprobar y luego escribir» en dos pasos. Muestra por qué la
    atomicidad del registro real tiene que verificarse antes de activar nada."""

    def crear(self, nombre, contenido):
        self._paso()
        existe = nombre in self.datos
        self._paso()                                      # otra ejecución puede colarse aquí
        if existe:
            return False
        self.datos[nombre] = contenido                    # sobrescribe sin comprobar
        return True


class Envios:
    """SMTP simulado: registra cada envío; nunca sale nada."""

    def __init__(self, planificador=None, fallo=None):
        self.hechos, self.p, self.fallo = [], planificador, fallo
        self._lock = threading.Lock()

    def para(self, quien):
        def enviar(n):
            if self.p:
                self.p.paso()
            if self.fallo:
                raise self.fallo
            with self._lock:
                self.hechos.append((quien, n))
        return enviar


def ID(n, lado="a"):
    """Identificador completo de un intento (formato del agente; sin datos personales)."""
    return f"<antropia-cursos.huella-ficticia.{lado}.{n}@antropia.invalid>"


def reenviar_h(registro, base, ejecucion, inicio, enviar, consulta, id_confirmado=None, **kw):
    """Reenvío humano. Por defecto la persona indica el identificador EXACTO del último
    intento según el registro; las pruebas de identificadores pasan otros."""
    if id_confirmado is None:
        try:
            id_confirmado = ID(estado_de(registro, base, consulta).intento)
        except Exception:
            id_confirmado = ""
    return reenviar_por_decision_humana(registro, base, ejecucion, inicio, enviar, consulta,
                                        id_confirmado, ID, **kw)


def ej(nombre):
    return Ejecucion(nombre, "1", "nonce-" + nombre)


def terminadas(*ids):
    return lambda ejecucion, reintento: TERMINADA if ejecucion in ids else "in_progress"


def intercalaciones(a, b, pasos=6):
    for pos in itertools.combinations(range(2 * pasos), pasos):
        orden = [b] * (2 * pasos)
        for i in pos:
            orden[i] = a
        yield orden


class TestSimultaneas(unittest.TestCase):
    def test_dos_ejecuciones_automaticas_en_todas_las_intercalaciones(self):
        casos = 0
        for orden in intercalaciones("A", "B"):
            p = Planificador(orden)
            reg, envios = RegistroSimulado(p), Envios(p)
            p.ejecutar({q: (lambda q=q: enviar_automatico(reg, BASE, ej(q), "t0", envios.para(q)))
                        for q in ("A", "B")})
            self.assertEqual(len(envios.hechos), 1, orden)
            casos += 1
        self.assertEqual(casos, 924)

    def test_segunda_reserva_despues_de_la_relectura_de_la_primera(self):
        # B lee ANTES de que A reserve (no ve nada: lectura atrasada). Después A lee, crea su
        # reserva y la RELEE (es suya). Solo entonces B intenta crear la misma reserva.
        orden = ["B", "A", "A", "A", "B", "B", "A", "A", "B", "B"]
        p = Planificador(orden)
        reg = RegistroTrazado(p)
        envios = Envios(p)
        r = p.ejecutar({q: (lambda q=q: enviar_automatico(reg, BASE, ej(q), "t0", envios.para(q)))
                        for q in ("A", "B")})
        self.assertEqual(reg.traza[:5], [
            ("B", "leer reserva-1", "ninguna"),
            ("A", "leer reserva-1", "ninguna"),
            ("A", "crear reserva-1", True),
            ("A", "leer reserva-1", "propia"),
            ("B", "crear reserva-1", False),           # B reserva DESPUÉS de la relectura de A
        ])
        self.assertEqual(envios.hechos, [("A", 1)])
        self.assertFalse(r["B"].enviado)

    def test_misma_situacion_con_un_registro_no_atomico_duplica(self):
        # Contraejemplo: si el registro real no fuera atómico, habría duplicados.
        duplicados = 0
        for orden in intercalaciones("A", "B"):
            p = Planificador(orden)
            reg, envios = RegistroNoAtomico(p), Envios(p)
            p.ejecutar({q: (lambda q=q: enviar_automatico(reg, BASE, ej(q), "t0", envios.para(q)))
                        for q in ("A", "B")})
            duplicados += len(envios.hechos) > 1
        self.assertGreater(duplicados, 0)

    def test_dos_reenvios_humanos_a_la_vez_envian_una_sola_vez(self):
        for orden in intercalaciones("H1", "H2", pasos=7):
            p = Planificador(orden)
            reg = RegistroSimulado(p)
            reg.datos[f"{BASE}/reserva-1"] = ej("vieja").texto("t0")     # interrumpido
            envios = Envios(p)
            p.ejecutar({h: (lambda h=h: reenviar_h(
                reg, BASE, ej(h), "t1", envios.para(h), terminadas("vieja"))) for h in ("H1", "H2")})
            self.assertEqual(len(envios.hechos), 1, orden)


class TestResultadosInmutables(unittest.TestCase):
    def test_un_enviado_no_se_puede_sobrescribir(self):
        reg, envios = RegistroSimulado(), Envios()
        enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"))
        self.assertFalse(reg.crear(f"{BASE}/cierre-1", '{"resultado": "abandonado"}'))
        e = estado_de(reg, BASE, terminadas("A"))
        self.assertEqual(e.estado, ESTADO_ENVIADO)
        r = reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"), terminadas("A"))
        self.assertFalse(r.enviado)
        self.assertEqual(envios.hechos, [("A", 1)])

    def test_cierre_tardio_tras_abandono_queda_como_posible_duplicado(self):
        # Solo podría pasar si GitHub informara «completed» de una ejecución que sigue
        # viva (no debería). Aun así nada se sobrescribe y queda señalado.
        # A reserva, comprueba y llega a enviar (4 pasos) y se queda ANTES de cerrar. H hace
        # su reenvío completo (turnos de sobra). Después A cierra: ya está cerrado.
        orden = ["A", "A", "A", "A"] + ["H"] * 40 + ["A"] * 4
        p = Planificador(orden)
        reg, envios = RegistroTrazado(p), Envios(p)
        p.ejecutar({
            "A": lambda: enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A")),
            "H": lambda: reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"),
                                                      terminadas("A")),
        })
        e = estado_de(reg, BASE, terminadas("A", "H"))
        # Orden real: H abandona el intento 1 ANTES de que A intente cerrarlo.
        ops = [(q, op) for q, op, _ in reg.traza if op.startswith("crear cierre-1")]
        self.assertEqual(ops, [("H", "crear cierre-1"), ("A", "crear cierre-1")])
        self.assertEqual(envios.hechos, [("A", 1), ("H", 2)])     # el duplicado que se señala
        self.assertIn(ABANDONADO, reg.datos[f"{BASE}/cierre-1"])
        self.assertIn(f"{BASE}/tardio-1", reg.datos)
        self.assertTrue(e.posible_duplicado)
        self.assertIn("posible duplicado", vista(e)[1])

    def test_vista_atrasada_en_notion_no_decide_nada(self):
        reg, envios = RegistroSimulado(), Envios()
        notion = {}
        vista_vieja = vista(estado_de(reg, BASE, terminadas()))             # «Pendiente»
        enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"))
        notion["Correo a A"] = vista(estado_de(reg, BASE, terminadas("A")))[0]   # «Enviado»
        notion["Correo a A"] = "Por revisar"            # escritura tardía de otro proceso
        self.assertEqual(vista_vieja[0], PENDIENTE)
        # Las decisiones leen el registro, no Notion: no hay reenvío posible.
        r = reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"), terminadas("A"))
        self.assertFalse(r.enviado)
        self.assertFalse(enviar_automatico(reg, BASE, ej("B"), "t2", envios.para("B")).enviado)
        self.assertEqual(vista(estado_de(reg, BASE, terminadas("A")))[0], ESTADO_ENVIADO)   # se corrige
        self.assertEqual(len(envios.hechos), 1)


class TestActividadSinPlazos(unittest.TestCase):
    def preparar(self):
        reg = RegistroSimulado()
        reg.datos[f"{BASE}/reserva-1"] = ej("A").texto("2020-01-01T00:00:00+00:00")   # muy antigua
        return reg

    def test_muy_antiguo_pero_en_curso_sigue_activo(self):
        reg, envios = self.preparar(), Envios()
        en_curso = lambda e, r: "in_progress"  # noqa: E731
        self.assertEqual(estado_de(reg, BASE, en_curso).estado, EN_CURSO)
        self.assertFalse(reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"), en_curso).enviado)
        self.assertFalse(enviar_automatico(reg, BASE, ej("B"), "t1", envios.para("B")).enviado)
        self.assertEqual(envios.hechos, [])

    def test_si_no_se_puede_saber_cuenta_como_activo(self):
        reg, envios = self.preparar(), Envios()

        def falla(e, r):
            raise ConnectionError("API no disponible (simulada)")
        for consulta in (lambda e, r: None, lambda e, r: "queued", falla):
            self.assertEqual(estado_de(reg, BASE, consulta).estado, EN_CURSO)
            self.assertFalse(reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"),
                                                          consulta).enviado)
        self.assertEqual(envios.hechos, [])

    def test_solo_con_prueba_positiva_queda_por_revisar(self):
        reg, envios = self.preparar(), Envios()
        e = estado_de(reg, BASE, terminadas("A"))
        self.assertEqual((e.estado, e.intento), (POR_REVISAR, 1))
        self.assertIn("interrumpido", e.detalle)
        self.assertFalse(enviar_automatico(reg, BASE, ej("B"), "t1", envios.para("B")).enviado)   # nunca solo
        r = reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"), terminadas("A"))
        self.assertTrue(r.enviado)
        self.assertEqual(envios.hechos, [("H", 2)])
        self.assertIn(ABANDONADO, reg.datos[f"{BASE}/cierre-1"])
        self.assertEqual(estado_de(reg, BASE, terminadas("A", "H")).estado, ESTADO_ENVIADO)


class TestFallos(unittest.TestCase):
    def test_fallo_seguro_y_duda_no_se_reintentan_solos(self):
        for error, detalle in ((ErrorEnvioSeguro("x"), "no salió"), (ErrorEnvioDudoso("x"), "duda")):
            reg = RegistroSimulado()
            enviar_automatico(reg, BASE, ej("A"), "t0", Envios(fallo=error).para("A"))
            e = estado_de(reg, BASE, terminadas("A"))
            self.assertEqual((e.estado, e.detalle), (POR_REVISAR, detalle))
            otra = Envios()
            self.assertFalse(enviar_automatico(reg, BASE, ej("B"), "t1", otra.para("B")).enviado)
            self.assertEqual(otra.hechos, [])
            # Solo una decisión humana lo reenvía (nueva reserva).
            self.assertTrue(reenviar_h(reg, BASE, ej("H"), "t2", otra.para("H"),
                                                         terminadas("A")).enviado)
            self.assertEqual(otra.hechos, [("H", 2)])

    def test_respuesta_perdida_al_reservar_no_envia(self):
        reg, envios = RegistroSimulado(), Envios()
        reg.perder_respuesta.add(f"{BASE}/reserva-1")
        self.assertFalse(enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A")).enviado)
        self.assertEqual(envios.hechos, [])
        self.assertEqual(estado_de(reg, BASE, lambda e, r: "in_progress").estado, EN_CURSO)
        self.assertEqual(estado_de(reg, BASE, terminadas("A")).estado, POR_REVISAR)

    def test_registro_caido_no_envia(self):
        reg, envios = RegistroSimulado(), Envios()
        reg.caido = True
        self.assertFalse(enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A")).enviado)
        self.assertFalse(reenviar_h(reg, BASE, ej("H"), "t0", envios.para("H"),
                                                      terminadas()).enviado)
        self.assertEqual(envios.hechos, [])

    def test_fallo_al_cerrar_queda_en_curso_hasta_prueba_positiva(self):
        reg, envios = RegistroSimulado(), Envios()
        reg.perder_respuesta.add(f"{BASE}/cierre-1")        # no se sabe si el cierre quedó
        original_crear = reg.crear

        def crear_sin_cierre(nombre, contenido):
            if nombre.endswith("cierre-1"):
                return None                                 # el cierre no llega a escribirse
            return original_crear(nombre, contenido)
        reg.crear = crear_sin_cierre
        self.assertTrue(enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A")).enviado)
        self.assertEqual(estado_de(reg, BASE, lambda e, r: "in_progress").estado, EN_CURSO)
        self.assertEqual(estado_de(reg, BASE, terminadas("A")).estado, POR_REVISAR)
        self.assertEqual(envios.hechos, [("A", 1)])          # y nada se reenvía solo

    def test_el_registro_no_guarda_datos_personales(self):
        reg = RegistroSimulado()
        enviar_automatico(reg, BASE, ej("A"), "t0", Envios().para("A"))
        texto = " ".join(reg.datos) + " ".join(reg.datos.values())
        self.assertNotIn("@", texto)


class TestIdentificadorExacto(unittest.TestCase):
    """El reenvío exige el identificador COMPLETO y EXACTO del ÚLTIMO intento."""

    def preparar(self):
        reg = RegistroSimulado()
        reg.datos[f"{BASE}/reserva-1"] = ej("vieja").texto("t0")
        reg.datos[f"{BASE}/cierre-1"] = '{"resultado": "duda", "ejecucion": "vieja"}'
        return reg

    def intentar(self, reg, identificador):
        envios, antes = Envios(), dict(reg.datos)
        r = reenviar_por_decision_humana(reg, BASE, ej("H"), "t1", envios.para("H"),
                                         terminadas("vieja", "H", "H1"), identificador, ID)
        return r, envios, antes

    def test_identificadores_no_validos_no_reenvian_ni_reservan(self):
        exacto = ID(1)
        malos = {
            "vacío": "",
            "incompleto (sin el final)": exacto[:-5],
            "incompleto (solo el comienzo)": "<antropia-cursos.huella-ficticia.a.",
            "sin los signos < >": exacto[1:-1],
            "con espacios": " " + exacto + " ",
            "en mayúsculas": exacto.upper(),
            "del otro lado (B)": ID(1, "b"),
            "de otro correo": exacto.replace("huella-ficticia", "otra-huella"),
            "de un intento futuro": ID(2),
            "no es texto": None,
        }
        for caso, identificador in malos.items():
            reg = self.preparar()
            r, envios, antes = self.intentar(reg, identificador)
            self.assertFalse(r.enviado, caso)
            self.assertEqual(envios.hechos, [], caso)
            self.assertEqual(reg.datos, antes, caso)            # ni reserva nueva ni abandono
            self.assertIn("identificador", r.motivo, caso)

    def test_el_exacto_si_reenvia(self):
        reg = self.preparar()
        r, envios, _ = self.intentar(reg, ID(1))
        self.assertTrue(r.enviado)
        self.assertEqual(envios.hechos, [("H", 2)])

    def test_identificador_de_un_intento_anterior_no_vale(self):
        reg = self.preparar()
        # Un reenvío (intento 2) que vuelve a quedar en duda.
        reenviar_por_decision_humana(reg, BASE, ej("H1"), "t1", Envios(fallo=ErrorEnvioDudoso("x")).para("H1"),
                                     terminadas("vieja", "H1"), ID(1), ID)
        self.assertEqual(estado_de(reg, BASE, terminadas("vieja", "H1")).intento, 2)
        r, envios, antes = self.intentar(reg, ID(1))            # el del intento ANTERIOR
        self.assertFalse(r.enviado)
        self.assertEqual((envios.hechos, reg.datos), ([], antes))
        r, envios, _ = self.intentar(reg, ID(2))                # el del último: sí
        self.assertTrue(r.enviado)
        self.assertEqual(envios.hechos, [("H", 3)])


class TestDatosVigentes(unittest.TestCase):
    """La autorización (y lo demás que compruebe el agente) se revisa antes de reservar
    y otra vez justo antes de enviar."""

    def test_autorizacion_retirada_antes_de_reservar(self):
        reg, envios = RegistroSimulado(), Envios()
        r = enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"),
                              comprobar=lambda: "sin autorización para participar")
        self.assertFalse(r.enviado)
        self.assertEqual(r.motivo, "sin autorización para participar")
        self.assertEqual((reg.datos, envios.hechos), ({}, []))      # no se gastó ninguna reserva
        self.assertEqual(estado_de(reg, BASE, terminadas()).estado, PENDIENTE)

    def test_autorizacion_retirada_entre_la_reserva_y_el_envio(self):
        respuestas = iter([None, "sin autorización para participar"])
        reg, envios = RegistroSimulado(), Envios()
        r = enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"), comprobar=lambda: next(respuestas))
        self.assertFalse(r.enviado)
        self.assertEqual(envios.hechos, [])
        e = estado_de(reg, BASE, terminadas("A"))
        self.assertEqual((e.estado, e.detalle), (POR_REVISAR, CANCELADO))
        # Nunca se reintenta solo, aunque la autorización vuelva.
        self.assertFalse(enviar_automatico(reg, BASE, ej("B"), "t1", envios.para("B")).enviado)
        self.assertEqual(envios.hechos, [])

    def test_si_la_comprobacion_falla_no_se_envia(self):
        reg, envios = RegistroSimulado(), Envios()

        def falla():
            raise ConnectionError("Notion no responde (simulado)")
        r = enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"), comprobar=falla)
        self.assertFalse(r.enviado)
        self.assertEqual((reg.datos, envios.hechos), ({}, []))

    def test_el_reenvio_tambien_comprueba(self):
        reg = RegistroSimulado()
        reg.datos[f"{BASE}/reserva-1"] = ej("vieja").texto("t0")
        reg.datos[f"{BASE}/cierre-1"] = '{"resultado": "duda", "ejecucion": "vieja"}'
        envios = Envios()
        r = reenviar_h(reg, BASE, ej("H"), "t1", envios.para("H"), terminadas("vieja"),
                       comprobar=lambda: "el correo cambió desde la lectura")
        self.assertFalse(r.enviado)
        self.assertEqual(envios.hechos, [])
        self.assertNotIn(f"{BASE}/reserva-2", reg.datos)


class TestVistaSoloPuedeImpedir(unittest.TestCase):
    """La vista de Notion puede impedir un envío, nunca autorizarlo."""

    def test_valores_de_la_vista(self):
        for valor in (None, "", PENDIENTE):
            self.assertTrue(vista_permite_primer_envio(valor), valor)
        for valor in (ESTADO_ENVIADO, POR_REVISAR, EN_CURSO, "otra cosa"):
            self.assertFalse(vista_permite_primer_envio(valor), valor)

    def test_vista_incoherente_impide_el_envio_sin_reservar(self):
        for valor in (ESTADO_ENVIADO, POR_REVISAR, EN_CURSO):
            reg, envios = RegistroSimulado(), Envios()
            r = enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"), estado_en_notion=valor)
            self.assertFalse(r.enviado, valor)
            self.assertEqual((reg.datos, envios.hechos), ({}, []), valor)

    def test_vista_pendiente_no_autoriza_si_el_registro_ya_lo_tiene(self):
        reg, envios = RegistroSimulado(), Envios()
        enviar_automatico(reg, BASE, ej("A"), "t0", envios.para("A"))
        r = enviar_automatico(reg, BASE, ej("B"), "t1", envios.para("B"), estado_en_notion=PENDIENTE)
        self.assertFalse(r.enviado)                              # decide el registro
        self.assertEqual(envios.hechos, [("A", 1)])


if __name__ == "__main__":
    unittest.main()

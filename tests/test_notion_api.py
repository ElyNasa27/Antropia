"""Cliente y almacén de Notion con respuestas HTTP simuladas (nunca se conecta a Notion)."""
import io
import json
import unittest
import urllib.error
from datetime import UTC, datetime

from encuentros.automatico import FilaMatch
from encuentros.notion_api import (
    DS_MATCHES, DS_PARTICIPANTES, AlmacenNotion, AlmacenSoloLectura, ClienteNotion,
)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class HttpFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.pedidos = []

    def __call__(self, req, timeout=None):
        cuerpo = json.loads(req.data) if req.data else None
        self.pedidos.append((req.get_method(), req.full_url, dict(req.header_items()), cuerpo))
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Resp(json.dumps(r).encode())


def t(texto, tipo="rich_text"):
    return {"type": tipo, tipo: [{"plain_text": texto}] if texto else []}


def sel(n):
    return {"type": "select", "select": {"name": n} if n else None}


FILA_PARTICIPANTE = {"id": "aaaa-1111", "properties": {
    "Alias": t("Alba", "title"), "Correo electrónico": {"type": "email", "email": "alba@example.org"},
    "Autorización para participar": {"type": "checkbox", "checkbox": True},
    "Aptitud": sel("Apto"), "Revisión humana del respaldo": sel("No requerida"),
    "Respaldo declarado": t(None), "Idioma": sel("Español"), "Modalidad": sel("Virtual"),
    "Acepta videollamada": sel(None), "Ofrece": t("Fotografía"), "Quiere aprender": t("Inglés"),
    "Disponibilidad + zona horaria": t("lunes 18:00-20:00"), "Zona horaria": t("Europe/Madrid"),
    "Minutos disponibles": {"type": "number", "number": 30},
}}


class TestCliente(unittest.TestCase):
    def test_cabeceras_paginacion_y_token_oculto(self):
        http = HttpFalso([
            {"results": [FILA_PARTICIPANTE], "has_more": True, "next_cursor": "c2"},
            {"results": [], "has_more": False},
        ])
        c = ClienteNotion("secreto-123", abrir=http)
        [p] = AlmacenNotion(c).personas()
        self.assertEqual((p.id, p.alias, p.correo, p.minutos, p.zona_horaria),
                         ("aaaa1111", "Alba", "alba@example.org", 30, "Europe/Madrid"))
        self.assertTrue(p.autoriza)
        metodo, url, cab, cuerpo = http.pedidos[1]
        self.assertEqual(url, f"https://api.notion.com/v1/data_sources/{DS_PARTICIPANTES}/query")
        self.assertEqual(cuerpo["start_cursor"], "c2")
        self.assertEqual(cab["Authorization"], "Bearer secreto-123")
        self.assertIn("Notion-version", cab)
        self.assertNotIn("secreto", repr(c))

    def test_reintenta_si_notion_limita(self):
        limite = urllib.error.HTTPError("u", 429, "lento", {"Retry-After": "0"}, io.BytesIO(b""))
        http = HttpFalso([limite, {"results": [], "has_more": False}])
        esperas = []
        ClienteNotion("x", abrir=http, esperar=esperas.append).consultar("ds")
        self.assertEqual(esperas, [0.0])


class TestAlmacen(unittest.TestCase):
    def fila(self):
        return FilaMatch(id="m1", a="aaaa1111", b="bbbb2222", alias_a="Alba", alias_b="Bruno",
                         a_ensena=["fotografía"], b_ensena=["inglés"],
                         inicio_utc=datetime(2026, 11, 30, 17, tzinfo=UTC), minutos_a=30, minutos_b=45,
                         huella_a="h" * 64, aviso_a=True)

    def test_crear_match_y_leerlo_de_vuelta(self):
        http = HttpFalso([{"id": "m-1"}])
        alm = AlmacenNotion(ClienteNotion("x", abrir=http))
        self.assertEqual(alm.crear_match(self.fila()), "m1")
        _, url, _, cuerpo = http.pedidos[0]
        self.assertEqual(cuerpo["parent"], {"type": "data_source_id", "data_source_id": DS_MATCHES})
        props = cuerpo["properties"]
        self.assertEqual(props["Duración total (min)"], {"number": 75})
        self.assertEqual(props["Estado"], {"select": {"name": "Esperando respuestas"}})

        # Lectura: convertir lo escrito al formato que devuelve Notion
        def leido(p):
            tipo = next(iter(p))
            v = p[tipo]
            if tipo in ("title", "rich_text"):
                return {"type": tipo, tipo: [{"plain_text": x["text"]["content"]} for x in v]}
            if tipo == "relation":
                return {"type": tipo, tipo: v}
            return {"type": tipo, tipo: v}
        pagina = {"id": "m-1", "properties": {k: leido(v) for k, v in props.items()}}
        http2 = HttpFalso([{"results": [pagina], "has_more": False}])
        [f] = AlmacenNotion(ClienteNotion("x", abrir=http2)).matches()
        esperado = self.fila()
        esperado.id = "m1"
        self.assertEqual(f, esperado)

    def test_solo_lectura_no_escribe(self):
        http = HttpFalso([])
        alm = AlmacenSoloLectura(AlmacenNotion(ClienteNotion("x", abrir=http)))
        alm.crear_match(self.fila())
        alm.guardar_match(self.fila())
        alm.marcar_respuesta("r1", "Aplicada", "m1")
        self.assertEqual(http.pedidos, [])
        self.assertEqual(len(alm.escrituras), 3)


if __name__ == "__main__":
    unittest.main()

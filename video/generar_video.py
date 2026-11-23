"""Genera el video de presentación de Antropia (MP4 1920x1080, H.264 + AAC, apto para YouTube).

  - Narración: voz de Windows «Microsoft Sabina» (es-MX), sin servicios de pago ni conexión.
  - Fotogramas: dibujados con Pillow. Las pantallas de Notion y del correo son RECREACIONES
    con personas FICTICIAS (el video es público).
  - Salida: video/antropia_pitch.mp4 y video/antropia_pitch.srt (subtítulos para YouTube).

Uso:  .venv\\Scripts\\python.exe video\\generar_video.py
"""
from __future__ import annotations

import math
import subprocess
import sys
import wave
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guion import ESCENAS  # noqa: E402

AQUI = Path(__file__).resolve().parent
TMP = AQUI / "tmp"
SALIDA = AQUI / "antropia_pitch.mp4"
SRT = AQUI / "antropia_pitch.srt"
W, H, FPS = 1920, 1080, 30
VOZ = "Microsoft Sabina Desktop"
PAUSA = 0.7                                   # segundos de silencio al final de cada escena

# Paleta
FONDO = (246, 247, 244)
TINTA = (29, 36, 32)
SUAVE = (93, 106, 99)
LINEA = (215, 221, 216)
BLANCO = (255, 255, 255)
VERDE = (47, 111, 94)
VERDE_CLARO = (226, 239, 233)
AMARILLO = (242, 193, 78)
AMARILLO_CLARO = (255, 244, 214)
AZUL = (60, 110, 170)
AZUL_CLARO = (224, 234, 247)
GRIS_CHIP = (232, 234, 232)
ROJO = (180, 73, 47)
OSCURO = (22, 30, 27)

FUENTES = Path("C:/Windows/Fonts")


def fuente(nombre: str, tam: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FUENTES / nombre), tam)
    except OSError:
        return ImageFont.load_default(size=tam)


def F(tam, peso="normal"):
    return fuente({"normal": "segoeui.ttf", "semi": "seguisb.ttf", "negrita": "segoeuib.ttf",
                   "mono": "consola.ttf"}[peso], tam)


# ---------------------------------------------------------------------------
# Narración
# ---------------------------------------------------------------------------
def sintetizar(texto: str, destino: Path) -> float:
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{VOZ}');"
        "$s.Rate = 1;"
        f"$s.SetOutputToWaveFile('{destino}');"
        "$s.Speak([Console]::In.ReadToEnd());"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], input=texto.encode("utf-8"),
                   check=True, capture_output=True)
    with wave.open(str(destino)) as w:
        return w.getnframes() / w.getframerate()


def unir_audio(partes: list[tuple[Path, float]], destino: Path) -> None:
    """Concatena los WAV, rellenando cada escena con silencio hasta su duración."""
    with wave.open(str(partes[0][0])) as w0:
        params = w0.getparams()
    with wave.open(str(destino), "wb") as out:
        out.setparams(params)
        for ruta, duracion in partes:
            with wave.open(str(ruta)) as w:
                datos = w.readframes(w.getnframes())
            out.writeframes(datos)
            faltan = int(duracion * params.framerate) - len(datos) // (params.sampwidth * params.nchannels)
            if faltan > 0:
                out.writeframes(b"\x00" * faltan * params.sampwidth * params.nchannels)


# ---------------------------------------------------------------------------
# Utilidades de dibujo
# ---------------------------------------------------------------------------
def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def aparece(t: float, inicio: float, dur: float = 0.5) -> float:
    return ease((t - inicio) / dur)


def mezclar(c1, c2, a):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * a) for i in range(3))


def caja(d: ImageDraw.ImageDraw, xy, fill, radio=18, borde=None, ancho=2):
    d.rounded_rectangle(xy, radius=radio, fill=fill, outline=borde, width=ancho if borde else 0)


def texto(d, xy, s, f, fill=TINTA, ancla="la"):
    d.text(xy, s, font=f, fill=fill, anchor=ancla)


def envolver(s: str, f, ancho: int) -> list[str]:
    lineas, actual = [], ""
    for palabra in s.split():
        prueba = (actual + " " + palabra).strip()
        if f.getlength(prueba) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def chip(d, x, y, s, fondo, tinta, f=None):
    f = f or F(24, "semi")
    ancho = int(f.getlength(s)) + 28
    caja(d, (x, y, x + ancho, y + 40), fondo, radio=20)
    texto(d, (x + 14, y + 20), s, f, tinta, "lm")
    return ancho


def persona(d, cx, cy, r, color, inicial):
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    texto(d, (cx, cy), inicial, F(int(r * 1.0), "negrita"), BLANCO, "mm")


def marco_ventana(d, x0, y0, x1, y1, titulo):
    """Ventana genérica (sin logotipos): barra superior con título."""
    caja(d, (x0, y0, x1, y1), BLANCO, radio=16, borde=LINEA)
    d.rounded_rectangle((x0, y0, x1, y0 + 52), radius=16, fill=(236, 239, 236))
    d.rectangle((x0, y0 + 30, x1, y0 + 52), fill=(236, 239, 236))
    for i, c in enumerate(((225, 120, 100), (230, 190, 90), (120, 180, 120))):
        d.ellipse((x0 + 20 + i * 26, y0 + 18, x0 + 36 + i * 26, y0 + 34), fill=c)
    texto(d, (x0 + 110, y0 + 26), titulo, F(22, "semi"), SUAVE, "lm")


ETAPAS = [("P", "Problema"), ("I", "Insight"), ("B", "Big Idea"), ("E", "Execution"), ("R", "Results")]


def cabecera(d, escena):
    if not escena["etapa"]:
        return
    x = 110
    for letra, nombre in ETAPAS:
        activa = letra == escena["etapa"]
        r = 30
        d.ellipse((x, 58, x + 2 * r, 58 + 2 * r), fill=VERDE if activa else BLANCO,
                  outline=VERDE if activa else LINEA, width=3)
        texto(d, (x + r, 58 + r), letra, F(30, "negrita"), BLANCO if activa else SUAVE, "mm")
        if activa:
            texto(d, (x + 2 * r + 14, 58 + r), nombre, F(28, "semi"), VERDE, "lm")
            x += 2 * r + 34 + int(F(28, "semi").getlength(nombre))
        else:
            x += 2 * r + 18
    texto(d, (W - 110, 88), "Antropia · proyecto final", F(24), SUAVE, "rm")
    texto(d, (110, 158), escena["titulo"], F(60, "negrita"), TINTA)


def subtitulo(d, s: str):
    if not s:
        return
    f = F(34, "semi")
    lineas = envolver(s, f, W - 360)[:2]
    alto = 54 * len(lineas) + 30
    y0 = H - 70 - alto
    caja(d, (150, y0, W - 150, H - 70), (22, 30, 27), radio=14)
    for i, l in enumerate(lineas):
        texto(d, (W // 2, y0 + 15 + 27 + i * 54), l, f, BLANCO, "mm")


# ---------------------------------------------------------------------------
# Escenas (t = segundos desde el inicio de la escena, dur = duración)
# ---------------------------------------------------------------------------
def esc_portada(d, t, dur):
    a = aparece(t, 0.1, 0.8)
    texto(d, (W // 2, 400), "Antropia", F(150, "negrita"), mezclar(FONDO, VERDE, a), "mm")
    b = aparece(t, 0.6, 0.8)
    texto(d, (W // 2, 520), "Comparte lo que sabes, aprende lo que sueñas", F(48, "semi"), mezclar(FONDO, TINTA, b), "mm")
    c = aparece(t, 1.2, 0.8)
    texto(d, (W // 2, 610), "Proyecto final · Agente de intercambio de conocimiento", F(32), mezclar(FONDO, SUAVE, c), "mm")


def esc_problema(d, t, dur):
    sabe = [("L", "Lucía", "sabe guitarra", (217, 120, 90)), ("V", "Valeria", "sabe fotografía", (120, 110, 190))]
    quiere = [("M", "Mateo", "quiere aprender guitarra", (70, 140, 120)), ("T", "Tomás", "quiere aprender fotografía", (200, 150, 60))]
    for i, (ini, nombre, frase, color) in enumerate(sabe):
        a = aparece(t, 0.3 + i * 0.3)
        y = 360 + i * 170
        caja(d, (150, y, 700, y + 130), mezclar(FONDO, BLANCO, a), borde=LINEA if a > 0.5 else None)
        if a > 0.05:
            persona(d, 225, y + 65, 42, color, ini)
            texto(d, (290, y + 46), nombre, F(36, "negrita"), TINTA, "lm")
            texto(d, (290, y + 92), frase, F(28), SUAVE, "lm")
    for i, (ini, nombre, frase, color) in enumerate(quiere):
        a = aparece(t, 0.9 + i * 0.3)
        y = 360 + i * 170
        caja(d, (1220, y, 1770, y + 130), mezclar(FONDO, BLANCO, a), borde=LINEA if a > 0.5 else None)
        if a > 0.05:
            persona(d, 1295, y + 65, 42, color, ini)
            texto(d, (1360, y + 46), nombre, F(36, "negrita"), TINTA, "lm")
            texto(d, (1360, y + 92), frase, F(26), SUAVE, "lm")
    a = aparece(t, 1.8, 0.6)
    if a > 0:
        for i in range(2):
            y = 425 + i * 170
            for x in range(720, 1200, 34):
                d.line((x, y, x + 16, y), fill=mezclar(FONDO, LINEA, a), width=5)
        texto(d, (W // 2, 510), "?", F(150, "negrita"), mezclar(FONDO, ROJO, a), "mm")
    b = aparece(t, dur * 0.55, 0.6)
    if b > 0:
        caja(d, (560, 720, 1360, 800), mezclar(FONDO, AMARILLO_CLARO, b), radio=14)
        texto(d, (W // 2, 760), "Emparejar a mano: lento y con personas sin respuesta", F(30, "semi"), mezclar(FONDO, TINTA, b), "mm")


def tarjeta_form(d, x, y, nombre, color, ofrece, quiere, resaltar=0.0):
    caja(d, (x, y, x + 620, y + 330), BLANCO, borde=LINEA)
    persona(d, x + 60, y + 60, 34, color, nombre[0])
    texto(d, (x + 110, y + 60), nombre, F(34, "negrita"), TINTA, "lm")
    for j, (etq, val) in enumerate((("Ofrece", ofrece), ("Quiere aprender", quiere))):
        yy = y + 120 + j * 100
        fondo = mezclar(BLANCO, AMARILLO_CLARO, resaltar)
        caja(d, (x + 30, yy, x + 590, yy + 80), fondo, radio=10, borde=mezclar(LINEA, AMARILLO, resaltar))
        texto(d, (x + 50, yy + 22), etq.upper(), F(18, "semi"), SUAVE)
        texto(d, (x + 50, yy + 48), val, F(28, "semi"), TINTA)


def esc_insight(d, t, dur):
    r = aparece(t, 1.2, 0.8)
    tarjeta_form(d, 200, 340, "Lucía", (217, 120, 90), "Guitarra", "Inglés", r)
    tarjeta_form(d, 1100, 340, "Mateo", (70, 140, 120), "Inglés", "Guitarra", r)
    a = aparece(t, dur * 0.5, 0.8)
    if a > 0:
        # Líneas que cruzan: lo que ofrece uno es lo que quiere el otro.
        for (x0, y0, x1, y1) in ((790, 500, 1130, 600), (790, 600, 1130, 500)):
            xe = x0 + (x1 - x0) * a
            ye = y0 + (y1 - y0) * a
            d.line((x0, y0, xe, ye), fill=VERDE, width=8)
            if a > 0.95:
                d.ellipse((xe - 12, ye - 12, xe + 12, ye + 12), fill=VERDE)
    b = aparece(t, dur * 0.75, 0.6)
    if b > 0:
        caja(d, (650, 720, 1270, 800), mezclar(FONDO, VERDE_CLARO, b), radio=14)
        texto(d, (W // 2, 760), "La coincidencia ya está en el formulario", F(32, "semi"), mezclar(FONDO, VERDE, b), "mm")


def esc_idea(d, t, dur):
    pasos = [("Formulario", "lo que ofreces\ny lo que quieres"), ("Agente", "encuentra\ncoincidencias"), ("Correo", "avisa a cada\npersona")]
    for i, (tit, sub) in enumerate(pasos):
        a = aparece(t, 0.4 + i * 0.9, 0.6)
        x = 210 + i * 560
        if a <= 0:
            continue
        caja(d, (x, 360 - int(20 * (1 - a)), x + 420, 620 - int(20 * (1 - a))),
             mezclar(FONDO, VERDE if i == 1 else BLANCO, a), borde=LINEA if i != 1 else None)
        col = BLANCO if i == 1 else TINTA
        texto(d, (x + 210, 440), tit, F(48, "negrita"), mezclar(FONDO, col, a), "mm")
        for k, linea in enumerate(sub.split("\n")):
            texto(d, (x + 210, 515 + k * 40), linea, F(30), mezclar(FONDO, BLANCO if i == 1 else SUAVE, a), "mm")
        if i < 2:
            b = aparece(t, 0.9 + i * 0.9, 0.5)
            if b > 0:
                x0, x1 = x + 440, x + 440 + int(100 * b)
                d.line((x0, 490, x1, 490), fill=VERDE, width=8)
                if b > 0.9:
                    d.polygon([(x1, 470), (x1 + 26, 490), (x1, 510)], fill=VERDE)
    sellos = ["Una sola vez", "Con autorización", "Cuidando la privacidad"]
    x = 540
    for i, s in enumerate(sellos):
        a = aparece(t, dur * 0.55 + i * 0.35, 0.5)
        if a > 0:
            x += chip(d, x, 700, s, mezclar(FONDO, AMARILLO_CLARO, a), mezclar(FONDO, TINTA, a), F(30, "semi")) + 24


def tabla(d, x0, y0, columnas, filas, anchos, aparicion, alto_fila=78, f=None):
    f = f or F(26)
    caja(d, (x0, y0, x0 + sum(anchos), y0 + 64 + alto_fila * len(filas)), BLANCO, radio=12, borde=LINEA)
    x = x0
    for c, a in zip(columnas, anchos):
        texto(d, (x + 18, y0 + 32), c, F(22, "semi"), SUAVE, "lm")
        x += a
    d.line((x0, y0 + 64, x0 + sum(anchos), y0 + 64), fill=LINEA, width=2)
    for i, fila in enumerate(filas):
        a = aparicion[i] if i < len(aparicion) else 1
        if a <= 0:
            continue
        y = y0 + 64 + i * alto_fila
        x = x0
        for celda, ancho in zip(fila, anchos):
            if isinstance(celda, tuple):                     # chip: (texto, fondo, tinta)
                chip(d, x + 14, y + 19, celda[0], mezclar(BLANCO, celda[1], a), mezclar(BLANCO, celda[2], a),
                     F(22, "semi"))
            else:
                texto(d, (x + 18, y + alto_fila // 2), celda, f, mezclar(BLANCO, TINTA, a), "lm")
            x += ancho
        if i < len(filas) - 1:
            d.line((x0 + 10, y + alto_fila, x0 + sum(anchos) - 10, y + alto_fila), fill=(236, 239, 236), width=2)


def esc_ingreso(d, t, dur):
    # Formulario (izquierda), con escritura progresiva
    marco_ventana(d, 110, 270, 800, 860, "Formulario de ingreso (recreación)")
    campos = [("Alias", "Lucía"), ("Ofrece", "Guitarra"), ("Quiere aprender", "Inglés"),
              ("Idiomas", "Español"), ("Disponibilidad", "Lunes 18:00–19:00"),
              ("Correo electrónico", "lucia@ejemplo.com"), ("Autorización para participar", "Sí")]
    escribir = max(0.0, (t - 0.5) / (dur * 0.5))
    total = sum(len(v) for _, v in campos)
    restantes = int(total * min(1, escribir))
    for i, (etq, val) in enumerate(campos):
        y = 340 + i * 66
        texto(d, (150, y), etq, F(20, "semi"), SUAVE)
        caja(d, (150, y + 24, 760, y + 60), (247, 248, 247), radio=8, borde=LINEA)
        mostrar = val[:max(0, restantes)]
        restantes -= len(val)
        texto(d, (166, y + 42), mostrar, F(23), TINTA, "lm")
    b = aparece(t, dur * 0.55, 0.4)
    if b > 0:
        caja(d, (560, 812, 760, 848), mezclar(BLANCO, VERDE, b), radio=10)
        texto(d, (660, 830), "Enviar", F(22, "semi"), mezclar(BLANCO, BLANCO, b), "mm")
    # Flecha
    a = aparece(t, dur * 0.62, 0.4)
    if a > 0:
        d.line((830, 600, 830 + int(70 * a), 600), fill=VERDE, width=8)
        if a > 0.9:
            d.polygon([(900, 580), (926, 600), (900, 620)], fill=VERDE)
    # Base Participantes (derecha)
    marco_ventana(d, 950, 270, 1810, 860, "Notion · base Participantes (recreación)")
    filas = [
        ["Mateo", "Inglés", "Guitarra", ("Sí", VERDE_CLARO, VERDE)],
        ["Valeria", "Fotografía", "Cocina", ("Sí", VERDE_CLARO, VERDE)],
        ["Tomás", "Cocina", "Fotografía", ("Sí", VERDE_CLARO, VERDE)],
        ["Lucía", "Guitarra", "Inglés", ("Sí", VERDE_CLARO, VERDE)],
    ]
    apar = [1, 1, 1, aparece(t, dur * 0.68, 0.5)]
    tabla(d, 980, 350, ["Alias", "Ofrece", "Quiere aprender", "Autoriza"], filas, [200, 210, 260, 130], apar)
    if apar[3] > 0.5:
        y = 350 + 64 + 3 * 78
        d.rounded_rectangle((976, y + 2, 980 + 800 + 4, y + 76), radius=10, outline=AMARILLO, width=4)


def esc_match(d, t, dur):
    marco_ventana(d, 110, 270, 1810, 860, "Notion · base Matches por cursos (recreación)")
    filas = [
        ["Lucía ↔ Mateo", ("Recíproco", VERDE_CLARO, VERDE), "Guitarra", "Inglés", ("Pendiente", GRIS_CHIP, SUAVE), ("Pendiente", GRIS_CHIP, SUAVE)],
        ["Valeria → Tomás", ("En una dirección", AZUL_CLARO, AZUL), "Fotografía", "—", ("Pendiente", GRIS_CHIP, SUAVE), ("Pendiente", GRIS_CHIP, SUAVE)],
        ["Tomás → Valeria", ("En una dirección", AZUL_CLARO, AZUL), "Cocina", "—", ("Pendiente", GRIS_CHIP, SUAVE), ("Pendiente", GRIS_CHIP, SUAVE)],
    ]
    apar = [aparece(t, 0.6 + i * 0.7, 0.5) for i in range(3)]
    tabla(d, 140, 350, ["Match", "Tipo", "A enseña", "B enseña", "Correo a A", "Correo a B"], filas,
          [300, 300, 260, 220, 280, 280], apar, alto_fila=92)
    comprobaciones = ["Autorización verificada", "Correo válido y único", "Alias distintos"]
    x = 260
    for i, s in enumerate(comprobaciones):
        a = aparece(t, dur * 0.6 + i * 0.4, 0.4)
        if a > 0:
            x += chip(d, x, 730, s, mezclar(BLANCO, VERDE_CLARO, a), mezclar(BLANCO, VERDE, a), F(28, "semi")) + 24


def esc_correo(d, t, dur):
    marco_ventana(d, 110, 270, 1180, 860, "Correo (recreación)")
    texto(d, (150, 345), "De: Comunidad Antropia", F(24), SUAVE)
    texto(d, (150, 383), "Para: lucia@ejemplo.com", F(24), SUAVE)
    texto(d, (150, 430), "Lucía, tienes una posible oportunidad de intercambio", F(30, "negrita"))
    d.line((150, 478, 1140, 478), fill=LINEA, width=2)
    cuerpo = [("Hola, Lucía:", F(26)), ("Encontramos una posible oportunidad de intercambio con Mateo.", F(26)),
              ("Lo que podrías aprender: Inglés", F(26, "semi")), ("Lo que podrías compartir: Guitarra", F(26, "semi")),
              ("Solo comparamos los cursos: idioma y horario se acuerdan después.", F(24)),
              ("¿Te interesa? Responde a este correo.", F(26))]
    for i, (s, f) in enumerate(cuerpo):
        a = aparece(t, 0.4 + i * 0.35, 0.4)
        texto(d, (150, 505 + i * 54), s, f, mezclar(BLANCO, TINTA, a))
    # Fila de Notion que pasa a «Enviado»
    marco_ventana(d, 1240, 270, 1810, 860, "Notion · el match (recreación)")
    texto(d, (1280, 360), "Lucía ↔ Mateo", F(32, "negrita"))
    cambio = aparece(t, dur * 0.65, 0.5)
    for k, lado in enumerate(("Correo a A", "Correo a B")):
        y = 430 + k * 110
        texto(d, (1280, y), lado, F(22, "semi"), SUAVE)
        if cambio < 0.5:
            chip(d, 1280, y + 34, "Pendiente", GRIS_CHIP, SUAVE, F(26, "semi"))
        else:
            chip(d, 1280, y + 34, "Enviado", VERDE_CLARO, VERDE, F(26, "semi"))
    if cambio > 0.5:
        texto(d, (1280, 665), "Id correo", F(22, "semi"), SUAVE)
        texto(d, (1280, 700), "<antropia-cursos.4f1c…a.1>", F(22, "mono"), TINTA)
        caja(d, (1280, 765, 1770, 825), AMARILLO_CLARO, radio=10)
        texto(d, (1525, 795), "Nunca se envía dos veces", F(24, "semi"), TINTA, "mm")


def esc_resultados(d, t, dur):
    datos = [("3", "matches detectados", "en el piloto"), ("6", "correos listos", "con la plantilla"),
             ("0", "duplicados", "registro de envíos"), ("599", "pruebas automáticas", "respaldan cada regla")]
    for i, (num, etq, sub) in enumerate(datos):
        a = aparece(t, 0.4 + i * 0.7, 0.6)
        x = 150 + i * 420
        if a <= 0:
            continue
        caja(d, (x, 360, x + 380, 700), mezclar(FONDO, BLANCO, a), borde=LINEA)
        valor = int(num)
        mostrado = str(int(round(valor * ease((t - (0.4 + i * 0.7)) / 1.2)))) if valor > 9 else num
        texto(d, (x + 190, 480), mostrado, F(120, "negrita"), mezclar(FONDO, VERDE, a), "mm")
        texto(d, (x + 190, 590), etq, F(32, "semi"), mezclar(FONDO, TINTA, a), "mm")
        texto(d, (x + 190, 640), sub, F(26), mezclar(FONDO, SUAVE, a), "mm")


def esc_cierre(d, t, dur):
    a = aparece(t, 0.1, 0.8)
    texto(d, (W // 2, 400), "Antropia", F(140, "negrita"), mezclar(FONDO, VERDE, a), "mm")
    b = aparece(t, 0.6, 0.8)
    texto(d, (W // 2, 520), "Conectamos lo que sabes con quien quiere aprenderlo", F(46, "semi"), mezclar(FONDO, TINTA, b), "mm")
    c = aparece(t, 1.2, 0.8)
    texto(d, (W // 2, 610), "Notion · Python · GitHub Actions · Gmail", F(30), mezclar(FONDO, SUAVE, c), "mm")
    texto(d, (W // 2, 660), "Personas y datos del video: ficticios", F(24), mezclar(FONDO, SUAVE, c), "mm")


DIBUJAR = {"portada": esc_portada, "problema": esc_problema, "insight": esc_insight, "idea": esc_idea,
           "ingreso": esc_ingreso, "match": esc_match, "correo": esc_correo, "resultados": esc_resultados,
           "cierre": esc_cierre}


# ---------------------------------------------------------------------------
# Subtítulos
# ---------------------------------------------------------------------------
def trozos(narracion: str) -> list[str]:
    res = []
    for frase in narracion.replace(": ", ". ").split(". "):
        frase = frase.strip().rstrip(".")
        if not frase:
            continue
        if len(frase) > 95 and ", " in frase:
            partes = frase.split(", ")
            mitad = len(partes) // 2
            res += [", ".join(partes[:mitad]) + ",", ", ".join(partes[mitad:]) + "."]
        else:
            res.append(frase + ".")
    return res


def tiempos_subtitulos(narracion: str, voz: float) -> list[tuple[float, float, str]]:
    ts = trozos(narracion)
    total = sum(len(x) for x in ts)
    t, res = 0.0, []
    for x in ts:
        d = voz * len(x) / total
        res.append((t, t + d, x))
        t += d
    return res


def srt_tiempo(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


# ---------------------------------------------------------------------------
def main() -> int:
    TMP.mkdir(exist_ok=True)
    plan, inicio = [], 0.0
    for e in ESCENAS:
        wav = TMP / f"{e['id']}.wav"
        voz = sintetizar(e["narracion"], wav)
        dur = max(voz + PAUSA, 3.0)
        plan.append(dict(e, wav=wav, voz=voz, dur=dur, inicio=inicio, subs=tiempos_subtitulos(e["narracion"], voz)))
        inicio += dur
        print(f"  {e['id']:<11} voz {voz:5.1f} s · escena {dur:5.1f} s")
    total = inicio
    print(f"Duración total: {total:.1f} s")

    audio = TMP / "narracion.wav"
    unir_audio([(p["wav"], p["dur"]) for p in plan], audio)

    with open(SRT, "w", encoding="utf-8") as f:
        n = 1
        for p in plan:
            for a, b, s in p["subs"]:
                f.write(f"{n}\n{srt_tiempo(p['inicio'] + a)} --> {srt_tiempo(p['inicio'] + b)}\n{s}\n\n")
                n += 1

    mudo = TMP / "video_mudo.mp4"
    escritor = imageio_ffmpeg.write_frames(str(mudo), (W, H), fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
                                           output_params=["-crf", "20", "-preset", "medium"], macro_block_size=8)
    escritor.send(None)
    for p in plan:
        cuadros = int(round(p["dur"] * FPS))
        for k in range(cuadros):
            t = k / FPS
            img = Image.new("RGB", (W, H), FONDO)
            d = ImageDraw.Draw(img)
            cabecera(d, p)
            DIBUJAR[p["id"]](d, t, p["dur"])
            actual = next((s for a, b, s in p["subs"] if a <= t < b + 0.25), "")
            subtitulo(d, actual)
            if t < 0.35:                                     # entrada suave de cada escena
                img = Image.blend(Image.new("RGB", (W, H), FONDO), img, t / 0.35)
            escritor.send(img.tobytes())
    escritor.close()

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mudo), "-i", str(audio), "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest",
                    str(SALIDA)], check=True)
    print(f"Video: {SALIDA}")
    print(f"Subtítulos: {SRT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Antropia · Coordinación de encuentros (piloto local)

Módulo para coordinar encuentros de intercambio de conocimiento. Es un piloto:
usa **solo datos ficticios**, **no envía mensajes**, **no crea reuniones** y
**no escribe en Notion**. Las bases de Notion se han leído solo para alinear
los nombres de los campos (ver `encuentros/notion_mapa.py`).

## Flujo

1. Cada participante aporta sus datos y su solicitud por separado.
2. **Revisión humana 1 · respaldo declarado** (`revisar_respaldo_declarado`):
   - «Aprobada»: solo si hay respaldo declarado; queda registrada la persona revisora.
   - «No requerida»: permite continuar **sin aprobar** nada, y solo si no hay
     ninguna afirmación de respaldo. Si la hay, es una contradicción: se pide
     revisión humana y no se aprueba automáticamente.
   - La revisión nunca viene en los datos de la propia persona y se anula si la
     persona cambia su respaldo.
3. **A2** propone candidatos para cada solicitud. Requisitos:
   - Persona: «Autorización para participar», «Aptitud» = Apto, respaldo resuelto.
   - Solicitud: «Estado» = Lista.
   - Par: reciprocidad, mismo idioma, modalidad compatible con videollamada
     (Virtual, o Mixta **con aceptación explícita**; si no consta, se pide
     aclaración) y horario común real en UTC durante **toda** la duración
     (ver «Tiempo de cada encuentro»).
   - **Máximo 3 propuestas activas por solicitud** (como origen o candidata);
     se prefieren los horarios comunes más tempranos. Las rechazadas no cuentan.
   - Resultado por par: «Propuesta», «Sin coincidencia» o «Bloqueada».
   - **Clave de ejecución** obligatoria: repetir una ejecución no crea duplicados.
4. **Revisión humana 2 · evidencia de la propuesta** (`aprobar_match` con
   `evidencia_revisada=True`). Al aprobar, se vuelven a comprobar los criterios.
   Si los aportes de minutos son distintos, además hace falta
   `aportes_distintos_revisados=True`.
   Esta revisión es independiente de la del respaldo: ninguna sustituye a la otra.
5. **A3** sugiere el pacto (objetivos, modalidad, fecha, zonas, minutos de cada
   persona y duración total) solo con datos disponibles; si falta algo, queda en
   «falta información». También usa clave de ejecución.
6. Una persona revisa el pacto; se prepara una invitación para cada participante.
7. Cada persona responde por separado (acepta / rechaza / cambios), ligado a la
   versión vigente. Un cambio genera otra versión y anula las respuestas previas.
8. Con las dos aceptaciones explícitas, una persona confirma y escribe el enlace https.
9. Se prepara una confirmación para cada participante.

Todos los mensajes quedan en una bandeja de borradores. No existe función de envío.

## Tiempo de cada encuentro

«Minutos por sesión» = **minutos que esa persona ofrece enseñar** (su aporte).

- **Duración total = suma de ambos aportes.** Ejemplo: Alba 30 + Bruno 30 = 60 min,
  lunes 30-nov-2026 18:00–19:00 en Madrid y 11:00–12:00 en Ciudad de México.
- **Disponibilidad completa:** ambas personas deben estar disponibles desde el
  inicio hasta el final, dentro de una misma franja de cada una (dos franjas
  contiguas no se unen). Se comprueba en A2 y A3 y se vuelve a comprobar al
  revisar y al confirmar el pacto.
- **Aportes distintos** (p. ej. 30 y 45 → 75 min): se permiten, pero la propuesta
  queda marcada y la persona que la aprueba debe revisarlos expresamente.
- **Pacto y mensajes** muestran los minutos de cada persona y la duración total:
  «30 min enseñas tú · 45 min enseña Bruno · duración total: 75 min».
  La invitación aclara que aceptar incluye ese reparto. Pedir otro reparto es un
  «cambio», no una aceptación.
- **Cambios de minutos** después de una revisión humana anulan esa revisión: A2
  no aprueba, A3 no propone y el pacto no se revisa ni se confirma.
- **Valores existentes en Notion:** algunos podrían ser la duración total. No se
  convierten nunca. La futura integración debe cargarlos con
  `minutos_requieren_revision=True`; quedan «Bloqueada» hasta que una persona
  escriba el aporte con `revisar_minutos_por_sesion(solicitud, revisora, minutos)`.
  En los JSON ficticios, `"minutos_requieren_revision": true` simula ese caso.

## Estructura

| Archivo | Función |
|---|---|
| `encuentros/modelos.py` | Participante, Solicitud, PropuestaMatch, Pacto, Respuesta, Mensaje |
| `encuentros/a2_match.py` | A2: requisitos, criterios del par, límite de 3, resultados |
| `encuentros/a3_pacto.py` | A3: primera franja común en UTC que cubre la duración total, o lo que falta |
| `encuentros/coordinacion.py` | Flujo y reglas: las dos revisiones humanas, claves, confirmación |
| `encuentros/mensajes.py` | Mensajes en la hora local de cada persona |
| `encuentros/canal.py` | Bandeja de borradores (sin envío) |
| `encuentros/repositorio.py` | Almacenamiento en memoria y carga desde JSON |
| `encuentros/zonas.py` | Zonas horarias reales (zoneinfo + tzdata). Sin tabla simulada |
| `encuentros/notion_mapa.py` | Columnas y opciones reales de Notion; carencias detectadas |
| `datos/*.json` | Datos ficticios |
| `tests/test_minutos.py` | Reglas del tiempo: suma, disponibilidad completa, aportes distintos, valores sin revisar |
| `tests/zonas_simuladas.py` | Tabla simulada, **solo** para pruebas sin tzdata |
| `requirements.txt` | `tzdata==2026.6`, solo para `.venv` |

## Ejecutar (con el entorno virtual del proyecto)

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe demo_piloto.py
```

Recrear el entorno: `py -3.14 -m venv .venv` y
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

### Zonas horarias

- El código del módulo solo usa la base IANA real. La tabla simulada vive en
  `tests/` y `Coordinacion` la rechaza salvo `permitir_zonas_simuladas=True`.
- La demo se niega a ejecutarse sin tzdata.
- Con `.venv`, `TestZonasReales` valida noviembre de 2026 y el cambio de hora en
  Madrid del 28-mar-2027. Con el Python global esas 5 pruebas se omiten.

## Datos de prueba

- `piloto_alba_bruno.json`: Alba (fotografía ↔ inglés conversacional) y Bruno.
- `piloto_original.json`: Alba (Excel ↔ inglés), Bruno (inglés ↔ Excel),
  Dani (inglés ↔ Excel, **sin autorización**) y Cora (fotografía ↔ Excel, sin reciprocidad).

## Supuestos pendientes de confirmar

- «Franja y zona horaria» es texto libre en Notion; aquí se usa estructurada.
- Confirmado el 2026-11-21: «Minutos por sesión» = minutos que esa persona
  enseña; la duración es la suma (ver «Tiempo de cada encuentro»).
- Ver `SIN_COLUMNA_EN_NOTION` en `notion_mapa.py` para los datos sin columna.

## Privacidad

El teléfono solo existe en la ficha de su dueño. Los mensajes reciben únicamente
el nombre de la otra persona; las pruebas verifican que ningún mensaje ni entrada
de la bitácora contiene teléfonos.

# Antropia · Coordinación de encuentros (piloto local)

Módulo para coordinar encuentros de intercambio de conocimiento. Es un piloto:
usa **solo datos ficticios**, **no crea reuniones** y **no escribe en Notion**.
La única salida automática es el **aviso de match por correo** (ver «Aviso de
match por correo»); en las pruebas y la demo ese envío es simulado. Las bases de Notion se han leído solo para alinear
los nombres de los campos (ver `encuentros/notion_mapa.py`).

> **Las personas que revisan son ficticias y sus roles son simulados.** Esto
> no es autenticación: no se verifica ninguna identidad real y la bitácora es
> modificable. Ver «Autorización simulada».

## Modo automático en Notion (producción)

Decisión del 2026-11-21: todo automático, sin revisiones humanas de match,
pacto, respuestas ni confirmación. Las únicas decisiones humanas que se
mantienen son «Aptitud» y «Revisión humana del respaldo» en Participantes.
Lo ejecuta **GitHub Actions cada 30 minutos** (`.github/workflows/ciclo-automatico.yml`
→ `ciclo_automatico.py` → `encuentros/automatico.py`).

1. Las personas llenan el «Formulario de ingreso Antropia» (base Participantes).
   No hay base Solicitudes en este modo: la solicitud de cada persona se deriva
   en memoria de su fila de Participantes (no se escribe en Notion).
2. **A1 automático** (`validar_a1_automatico`) comprueba temas, idioma, modalidad,
   disponibilidad legible, zona IANA, «Minutos disponibles» y correo. Quien no los
   tiene queda fuera y el registro solo dice qué columnas faltan. Es una
   comprobación automática: no escribe «Aptitud» ni sustituye a las decisiones
   humanas. «Tipo de perfil» es de selección múltiple y no interviene en el match.
3. A2 empareja a quienes tienen autorización, Aptitud = Apto y respaldo resuelto.
   **Temas** (`encuentros/temas.py`, comparación local y conservadora): se separan
   por comas, «;», «/» o « y » y cuentan si son iguales («Clases de inglés» /
   «ingles»), sinónimos de la lista `SINONIMOS` («inglés» / «English») o el mismo
   tema de `TEMAS_DEFINIDOS` («crear tablas en Excel para controlar gastos» /
   «organizar gastos usando Excel»). Si el nivel o el alcance es incierto
   («Excel» / «Excel avanzado», «inglés avanzado» / «inglés básico», «Excel» /
   «Excel para controlar gastos») o parece una errata, el par queda **«requiere
   aclaración»** y NO se crea el match. Compartir solo una categoría amplia
   («cocina italiana» / «cocina mexicana») no es coincidencia. Hace falta
   coincidencia clara **en las dos direcciones**. Disponibilidad: texto como
   «lunes 18:00–20:00» (`encuentros/disponibilidad.py`); lo ilegible no se adivina.
   Los minutos de enseñanza se leen de «Minutos disponibles».
4. Cada par se escribe en **Matches [PRUEBA]** y cada persona recibe un correo con
   la fecha y hora en su zona (al menos 24 h después), los minutos, el enlace del
   formulario **«Responder a tu match»** y su **código personal**. En Notion solo
   queda la huella HMAC del código.
5. Las respuestas del formulario (base **Respuestas al match [PRUEBA]**) se
   aplican por la huella y se marcan: Aplicada, Código no válido, Ya respondida,
   Caducada o Sin respuesta. Cada código es de UNA persona y UNA versión del
   horario: al proponer otro horario se generan códigos nuevos y los anteriores
   dejan de valer.
6. Con dos «Acepto» de la misma versión y el horario aún válido, el match queda
   «Confirmado». **El sistema no inventa enlaces**: la confirmación (con enlace y
   `.ics`) se envía solo cuando hay un enlace https real, el que crea Jitsi Meet según
   `ANTROPIA_SALAS`, o el que una persona escribe en «Enlace Jitsi». Con
   `jitsi-prueba` (primera fase del piloto) las salas llevan «AntropiaPRUEBA» en el
   nombre y el correo y el `.ics` dicen que es un enlace de prueba; con `jitsi`
   son para encuentros reales. En los dos casos cada pareja recibe una sala
   distinta con 128 bits aleatorios en el nombre, que se crea y se envía solo
   después de que ambas personas aceptan la misma versión. Quien tenga acceso a la
   base «Matches [PRUEBA]» puede ver el enlace.
7. Si la hora llega sin las dos aceptaciones, choca con otro encuentro confirmado
   o alguien dejó de ser elegible, se propone otro horario con códigos nuevos
   (máximo 3 horarios). «No me interesa» cierra el match y avisa a la otra persona.

### Puesta en marcha (lo hace la persona responsable)

1. **Notion:** crear una integración interna (notion.so/profile/integrations),
   conectarla a la página «Piloto - Intercambio de Conocimiento» y copiar su token.
   En el formulario «Responder a tu match», añadir la pregunta «Respuesta»
   (obligatoria) y publicarlo con enlace público.
2. **Gmail:** activar la verificación en dos pasos y crear una contraseña de aplicación.
3. **GitHub → Settings → Secrets and variables → Actions:**
   - Secretos: `NOTION_TOKEN`, `ANTROPIA_SMTP_USUARIO`, `ANTROPIA_SMTP_CLAVE`,
     `ANTROPIA_CLAVE_CODIGOS` (≥ 32 caracteres aleatorios; si cambia, los códigos
     ya enviados dejan de valer).
   - Variables: `ANTROPIA_FORMULARIO_URL` (enlace público del formulario),
     `ANTROPIA_SALAS` = `jitsi-prueba` primero, y `jitsi` para encuentros reales
     (opcional; vacío = una persona escribe el enlace) y
     `ANTROPIA_ACTIVO` = `si` para activar la ejecución cada 30 minutos.
4. Probar primero en la pestaña **Actions → Ciclo automático → Run workflow →
   simulacion**: lee Notion, no escribe y no envía correos.

Para pausarlo: `ANTROPIA_ACTIVO` distinto de `si`, o desactivar el workflow.
Sin `ANTROPIA_ACTIVO` = `si` el **modo real no se ejecuta nunca**, ni programado ni
lanzado a mano: `ciclo_automatico.py` se detiene (código de salida 4) antes de leer o
escribir en Notion y de enviar correos. La simulación manual funciona siempre y no
necesita las credenciales de Gmail.

## Flujo del piloto local (con revisiones humanas simuladas)

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
   - **Aviso automático por correo**: cada «Propuesta» envía al instante un aviso
     a las dos personas, sin aprobación manual (ver «Aviso de match por correo»).
4. **Revisión humana 2 · evidencia de la propuesta** (`aprobar_match` con
   `evidencia_revisada=True`). Al aprobar, se vuelven a comprobar los criterios.
   Si los aportes de minutos son distintos, además hace falta
   `aportes_distintos_revisados=True`.
   Esta revisión es independiente de la del respaldo: ninguna sustituye a la otra.
5. **A3** sugiere el pacto (objetivos, modalidad, fecha, zonas, minutos de cada
   persona y duración total) solo con datos disponibles; si falta algo, queda en
   «falta información». También usa clave de ejecución.
6. Una persona (coordinadora) revisa el pacto; se prepara una invitación para cada participante.
7. Cada persona responde por separado (acepta / rechaza / cambios), ligado a la
   versión vigente; la registra Marta o Luis. Un cambio genera otra versión y
   anula las respuestas y revisiones previas.
8. **Revisión humana de las respuestas** (`revisar_respuesta`): la coordinadora
   revisa cada una de las dos aceptaciones, indicando la versión; la revisión
   queda ligada a esa versión, que debe ser la vigente.
9. Con las dos aceptaciones explícitas y revisadas, la coordinadora confirma y
   escribe el enlace https. **Debe ser una persona distinta de quien aprobó la
   propuesta**; quien revisó el pacto sí puede confirmarlo.
10. Se prepara una confirmación para cada participante.

Los mensajes del pacto (invitaciones y confirmaciones) quedan en una bandeja de
borradores y no se envían. El aviso de match por correo sí se envía solo.

## Aviso de match por correo (automático)

Decisión del 2026-11-21: **en cuanto A2 detecta que dos personas son compatibles**
(resultado «Propuesta»), el sistema redacta y **envía automáticamente** un aviso a
cada una, al «Correo electrónico» que dejaron en el formulario. No hay revisión
humana antes del envío. Código: `encuentros/correo.py`.

- **Contenido (solo aviso):** nombre de la otra persona y los temas que cada una
  comparte. Ningún dato de contacto de la otra persona.
- **Las dos o ninguna:** si a una de las dos le falta el correo, no se envía a
  ninguna; `reintentar_avisos_pendientes()` lo envía cuando llega el dato.
- **Sin duplicados:** cada aviso (propuesta + persona) se envía una sola vez,
  aunque se repita la ejecución o el reintento.
- **Fallos:** si el servidor falla, queda en la bitácora como pendiente y el
  reintento solo envía a quien aún no lo recibió.
- **Bitácora:** registra el envío con el id de la persona, nunca la dirección.
- Como A2 puede proponer hasta 3 candidatos por solicitud, una persona puede
  recibir hasta 3 avisos. Si la revisora rechaza después una propuesta, el aviso
  ya se envió.

Envío real con **Gmail SMTP** (`EnvioGmailSMTP`, smtp.gmail.com:587 con STARTTLS),
usando una contraseña de aplicación de Google. Las credenciales se leen de
variables de entorno y nunca se escriben en el código ni en Git:

| Variable | Contenido |
|---|---|
| `ANTROPIA_SMTP_USUARIO` | cuenta de Gmail que envía |
| `ANTROPIA_SMTP_CLAVE` | contraseña de aplicación (16 caracteres) |
| `ANTROPIA_SMTP_NOMBRE` | nombre del remitente (opcional; «Comunidad Antropia») |

Las pruebas usan `EnvioSimulado` y nunca se conectan a Gmail. Para activarlo:
`Coordinacion(..., notificador=NotificadorMatch(AgendaCorreos({...}), EnvioGmailSMTP()))`.

## Formulario y A1 (informe local)

El formulario «Antropia: comparte lo que sabes, aprende lo que sueñas» es una
vista nativa de Notion sobre **Participantes**: cada respuesta crea una fila.
`encuentros/formulario.py` representa esa fila tal como llega (columnas en
`notion_mapa.COLUMNAS_FORMULARIO`), ignora campos internos (Aptitud, Revisión
humana del respaldo, Faltantes, ID, Minutos disponibles) y rechaza teléfonos.
El correo es privado y sirve para el aviso automático de match.

**A1** (`encuentros/a1_revision.py`) prepara un **informe local** para la persona
revisora: autorización, datos obligatorios que faltan, valores no reconocidos,
zona IANA, minutos, Mixta sin aclarar, respaldo (pendiente de revisión humana)
y si hay correo (sin mostrarlo). **A1 no escribe ni sugiere nada en Notion**, no
marca Apto ni Lista, no aprueba respaldos y no inventa datos.

```powershell
.\.venv\Scripts\python.exe demo_a1.py   # informes de las respuestas ficticias
```

Todavía no hay lectura automática desde Notion: los datos de prueba están en
`datos/formulario_ficticio.json`.

## Autorización simulada (no es autenticación)

`encuentros/autorizacion_simulada.py` y `datos/personas_simuladas.json`.

**Qué es:** una simulación para probar qué rol puede hacer cada paso humano,
con personas **ficticias**. **Qué no es:** autenticación.

- No verifica identidades reales: nadie inicia sesión. Cualquiera que ejecute el
  código puede «actuar como» cualquier persona con `directorio.actuar_como(...)`,
  y cualquiera que edite el JSON puede cambiar personas y roles.
- La **bitácora es una lista en memoria y se puede modificar**: sirve para
  seguir el flujo, no como prueba de quién hizo qué.
- Lo que sí comprueba, dentro del programa: un nombre escrito ya no basta (hace
  falta un actor del directorio que usa la coordinación), la persona debe estar
  activa y tener el rol, y los agentes A2/A3 no pueden ser personas.

| Persona ficticia | id | Rol simulado |
|---|---|---|
| Ana (ficticia) | `rev-ana` | `revisora` |
| Luis (ficticio) | `coord-luis` | `coordinadora` |
| Marta (ficticia) | `reg-marta` | `registro_respuestas` |

| Acción | Roles que la permiten |
|---|---|
| Revisar respaldo · revisar minutos · aprobar o rechazar propuesta | revisora |
| Revisar el pacto · revisar respuestas · confirmar el pacto · aprobar borradores | coordinadora |
| Registrar respuestas | coordinadora, registro_respuestas |

Reglas adicionales: quien confirma el pacto ≠ quien aprobó la propuesta; las
dos aceptaciones deben estar revisadas para la versión vigente; quien registró
una respuesta no puede revisarla. En la bitácora
y en los campos `*_por` queda el id de la persona simulada y el rol usado.

La autenticación real se diseñará aparte (p. ej. usuarios verificados de Notion,
con cada decisión ligada a la versión exacta).

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
| `encuentros/formulario.py` | Respuestas del formulario de Participantes (sin campos internos ni teléfonos) |
| `encuentros/a1_revision.py` | A1: informe local para la persona revisora (no escribe en Notion) |
| `demo_a1.py` · `datos/formulario_ficticio.json` | Demo de A1 con 5 respuestas ficticias |
| `encuentros/autorizacion_simulada.py` | Personas ficticias y roles **simulados** (no es autenticación) |
| `datos/personas_simuladas.json` | Ana, Luis y Marta (ficticias) |
| `encuentros/coordinacion.py` | Flujo y reglas: revisiones humanas (simuladas), claves, revisión de respuestas, confirmación |
| `encuentros/mensajes.py` | Mensajes en la hora local de cada persona |
| `encuentros/canal.py` | Bandeja de borradores del pacto (sin envío) |
| `encuentros/automatico.py` | Ciclo automático: A1 automático, match, códigos, respuestas, confirmación, reprogramación |
| `encuentros/notion_api.py` | API de Notion (biblioteca estándar) y almacén de Matches/Respuestas [PRUEBA] |
| `encuentros/disponibilidad.py` | Lectura del texto libre: franjas, zona y temas |
| `encuentros/temas.py` | Comparación conservadora de temas: igual, sinónimo, tema definido o «requiere aclaración» |
| `ciclo_automatico.py` · `.github/workflows/ciclo-automatico.yml` | Ejecución cada 30 min en GitHub Actions |
| `encuentros/correo.py` | Aviso automático de match: agenda privada, redacción, envío simulado y Gmail SMTP |
| `tests/test_correo.py` | Envío automático a las dos personas, privacidad, sin duplicados, fallos y reintento |
| `encuentros/repositorio.py` | Almacenamiento en memoria y carga desde JSON |
| `encuentros/zonas.py` | Zonas horarias reales (zoneinfo + tzdata). Sin tabla simulada |
| `encuentros/notion_mapa.py` | Columnas y opciones reales de Notion; carencias detectadas |
| `datos/*.json` | Datos ficticios |
| `tests/test_formulario.py` · `tests/test_a1.py` | Columnas reales, campos internos, privacidad y A1 |
| `tests/test_autorizacion_simulada.py` | Roles simulados, cuatro ojos, revisión de respuestas por versión |
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

El sistema **no guarda teléfonos**: el modelo `Participante` no tiene ese campo y
el cargador de datos rechaza cualquier registro que incluya `telefono`, `phone`,
`celular` o `whatsapp`. Los mensajes reciben únicamente el nombre de la otra
persona; las pruebas verifican que ningún mensaje ni entrada de la bitácora
contiene teléfonos ni correos.

El correo del formulario es privado: vive solo en `AgendaCorreos`, se usa para
el aviso de match y no se copia a mensajes, a la bitácora ni a la otra persona.

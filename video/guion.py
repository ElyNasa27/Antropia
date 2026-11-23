"""Guion del video de presentación (método P·I·B·E·R, formato elevator pitch, ~80 s).

Cada escena tiene: id, etiqueta P/I/B/E/R, título en pantalla y el texto que narra la voz.
Todas las personas que aparecen en pantalla son FICTICIAS (el video es público).
"""

ESCENAS = [
    dict(id="portada", etapa="", titulo="Antropia",
         narracion="Antropia: comparte lo que sabes, aprende lo que sueñas."),
    dict(id="problema", etapa="P", titulo="Problema",
         narracion="Mucha gente sabe algo que otra persona quiere aprender, pero no se encuentran. "
                   "Emparejarlas a mano es lento y deja a personas sin respuesta."),
    dict(id="insight", etapa="I", titulo="Insight",
         narracion="La información ya existe: en el formulario, cada persona escribe lo que ofrece "
                   "y lo que quiere aprender. Solo falta cruzarla."),
    dict(id="idea", etapa="B", titulo="Big Idea",
         narracion="Creamos un agente que encuentra coincidencias de cursos y avisa por correo, "
                   "una sola vez y cuidando la privacidad."),
    dict(id="ingreso", etapa="E", titulo="Execution · 1. Ingreso de datos",
         narracion="Todo empieza en el formulario de Notion: lo que ofreces, lo que quieres aprender, "
                   "tu correo y tu autorización. Cada respuesta es una fila en la base Participantes."),
    dict(id="match", etapa="E", titulo="Execution · 2. El match en Notion",
         narracion="El agente compara los cursos y registra cada match en Notion: quién enseña, quién aprende "
                   "y si es recíproco. Antes, verifica la autorización y que el correo sea único."),
    dict(id="correo", etapa="E", titulo="Execution · 3. El aviso por correo",
         narracion="Cada persona recibe un aviso: una posibilidad, no un encuentro confirmado, con solo el alias "
                   "y los cursos. En Notion queda como Enviado y nunca se repite."),
    dict(id="resultados", etapa="R", titulo="Results",
         narracion="En el piloto: tres matches, seis correos listos, cero duplicados "
                   "y casi seiscientas pruebas automáticas."),
    dict(id="cierre", etapa="", titulo="Antropia",
         narracion="Antropia: conectamos lo que sabes con quien quiere aprenderlo."),
]

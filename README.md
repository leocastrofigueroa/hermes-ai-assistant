# Hermes

Hermes es un asistente personal de inteligencia artificial que estoy desarrollando en Python.

El objetivo del proyecto es construir un asistente local capaz de conversar, recordar información de forma permanente, organizar tareas y utilizar distintos modelos según la complejidad de cada consulta.

## Funcionalidades actuales

- Ejecución local con Ollama
- Modelo rápido con Qwen 3 1.7B
- Modelo profundo con Qwen 3 4B
- Memoria permanente con SQLite
- Actualización inteligente de recuerdos
- Evita recuerdos duplicados
- Arquitectura preparada para gestión de tareas

## Tecnologías

- Python
- Ollama
- Qwen
- SQLite
- Requests

## Objetivo

Hermes busca evolucionar hacia un asistente personal completo con:

- tareas y agenda
- notas
- acceso a archivos
- herramientas
- búsqueda web
- voz
- automatizaciones
- control seguro de aplicaciones

## Estado

Proyecto en desarrollo activo.

## Automatizaciones (28.4)

La consola permite crear, listar y ver automatizaciones. El motor existente
`python recordatorios.py` las revisa cada 15 segundos junto con los servicios
anteriores. Debe estar en ejecución; abrir solamente `hermes.py` no lo inicia.
Ejecutar desde la carpeta del proyecto para usar la misma `hermes.db`.

Ejemplos en Hermes (reemplazar el horario por uno próximo):

```text
Creá una automatización llamada "Tareas diarias" todos los días a las 18:30: Mostrame las tareas pendientes.
Creá una automatización llamada "Agenda semanal" cada lunes a las 09:00: Consultar eventos.
Listá las automatizaciones
Ver automatización 1
```

Capacidades permitidas: `Mostrar resumen diario`, `Mostrar tareas pendientes`,
`Consultar eventos`, `Consultar notas` y `Mostrame los eventos de hoy`. También se admite `Mostrame`, acentos y
puntuación final. Las instrucciones compuestas, destructivas o no reconocidas
se rechazan. No se usa Ollama, web, shell ni el despachador general de Hermes.
Las automatizaciones guardadas en 28.1 también quedan sujetas a esta lista.

El horario es local, diario o semanal, con hasta 5 minutos de tolerancia
(incluso al cruzar medianoche). Fuera de esa ventana no se recuperan ejecuciones
perdidas. Una reserva SQLite atómica por ID y fecha programada impide duplicados
entre ciclos, reinicios y procesos concurrentes. Desde 28.3, cambiar la
frecuencia, el día o la hora crea una nueva versión de programación, con su
propia ventana; puede ejecutarse nuevamente ese día al llegar el nuevo horario.
El historial de versiones anteriores se conserva.

Los resultados completos quedan en `ejecuciones_automatizaciones` y se imprimen
en la salida del motor, sin notificaciones adicionales. `ultimo_disparo` guarda
la clave de la ocurrencia solo después de guardar correctamente el resultado.
Los rechazos y fallos quedan con estado `error`, y se registran también por
stderr; no interrumpen las demás automatizaciones. No se reintentan en la misma
ventana. Una caída tras reservar puede dejar `en_curso`; tampoco se reintenta
para evitar duplicados. Si SQLite no permite registrar el error, se informa por
stderr. La recuperación de ejecuciones interrumpidas queda para etapas posteriores.

Consulta local de resultados y errores, sin modificar datos:

```bash
sqlite3 -readonly -header -column hermes.db 'SELECT automatizacion_id, ventana, estado, inicio, fin, resultado, error FROM ejecuciones_automatizaciones ORDER BY inicio DESC;'
```

Los resultados pueden contener notas y tareas privadas y no tienen limpieza
automática en esta etapa. Las pruebas usan SQLite temporal y no envían
notificaciones ni hacen consultas a Ollama:

```bash
python -m py_compile hermes.py memoria.py recordatorios.py
python -m unittest discover -s tests -v
```


### Gestión de automatizaciones (28.3)

Reiniciar el motor y la consola para cargar 28.3 antes de usar la gestión.
La migración agrega `fecha_eliminacion` y `version_programacion` sin reconstruir
la tabla ni cambiar los registros existentes. La eliminación es lógica:
internamente queda pausada y marcada con fecha de eliminación; Hermes muestra
`eliminada`. No aparece en el listado normal, pero sigue visible por ID con
su configuración e historial. No se puede editar ni reanudar una eliminada.

```text
Pausá la automatización 3
Reanudá la automatización 3
Cambiá la hora de la automatización 3 a las 09:30
Cambiá el nombre de la automatización 3 a "Resumen de mañana"
Cambiá la instrucción de la automatización 3 a: Mostrame los eventos de hoy.
Cambiá la frecuencia de la automatización 3 a semanal los lunes
Cambiá el día semanal de la automatización 3 a miércoles
Cambiá la frecuencia de la automatización 3 a diaria
Mostrame el estado de la automatización 3
Ver automatización 3
Eliminá la automatización 3
```

Al pasar de diaria a semanal se debe indicar el día en la misma orden; al pasar
a diaria se limpia el día semanal. No se aceptan horas fuera de rango, nombres
o instrucciones vacíos ni IDs inexistentes. Las instrucciones se almacenan como
texto y siguen sujetas a la lista segura del motor; editarlas no las ejecuta.

Cambiar frecuencia, día u hora reinicia `ultimo_disparo` para la nueva versión,
sin borrar reservas anteriores. Una edición que deja el mismo horario no crea
versión. Renombrar, editar la instrucción, pausar y reanudar no habilitan un
segundo disparo de una ventana ya reservada. No hay fecha individual editable:
las frecuencias disponibles siguen siendo diaria y semanal.

El motor comprueba estado, eliminación y configuración de nuevo después de
reservar. La consulta y su finalización se serializan con la gestión mediante
una transacción SQLite: una pausa o eliminación completada impide comenzar una
consulta posterior. Si la consulta ya empezó, la gestión espera a que termine;
no puede deshacer una consulta ya realizada. Las reservas obsoletas se registran
como error. Las consultas grandes pueden retrasar brevemente otras escrituras.


### Auditoría y seguridad (28.4)

Reiniciar consola y motor para cargar los controles nuevos. En Hermes:

```text
Auditá las automatizaciones
```

El comando es local, sin Ollama, y abre SQLite en modo de solo lectura sobre una
instantánea consistente. No ejecuta instrucciones, repara registros, elimina
historial ni reintenta reservas. Verifica columnas, tipos, nulabilidad, valores
por defecto, claves y restricciones CHECK; configuración, estados, horarios,
eliminación lógica, versiones, ventanas, referencias, fechas y coherencia de
`ultimo_disparo`, resultados y errores. Informa configuraciones activas con la
misma consulta y horario: son advertencias, ya que IDs distintos pueden ser
intencionales. No existe UID externo en este subsistema.

La auditoría y el motor comparten una única lista de consultas permitidas.
Instrucciones destructivas, shell, web o instrucciones compuestas se rechazan
antes de consultar datos. El rechazo queda registrado como error al llegar su
horario; durante la auditoría solo se informa. Cada fallo se aísla para permitir
que continúen las demás automatizaciones. Los errores sin mensaje guardan el
nombre de la excepción. Una ejecución correcta exige resultado de texto; una
fallida exige descripción y no admite resultado simultáneo.

El motor verifica la clave primaria compuesta que impide duplicar reservas
antes de reservar y de ejecutar; si falta, bloquea la ejecución y registra el
problema en stderr. Pausadas y eliminadas siguen bloqueadas. Las reservas
`en_curso` mayores a cinco minutos se señalan como posibles interrupciones, sin
modificarlas. La auditoría no prueba si el proceso del motor está encendido ni
puede reconstruir instrucciones/configuraciones históricas que no se guardaron
como instantáneas. Los resultados permanecen locales y no se purgan.

### Punto 29 — Voz local

Hermes usa **whisper.cpp para STT** y **Supertonic para TTS**, con voz **M2**,
idioma **español (`es`)** y velocidad **1.15**. La transcripción pasa al mismo
`procesar_turno_texto` que el teclado: dispatcher, seguridad, confirmaciones,
contexto, memoria y tareas no tienen un flujo alternativo.

#### Instalación y rutas

Supertonic está instalado separadamente en `/Users/leocast/supertonic-test`.
Se verificó el ejecutable `/Users/leocast/supertonic-test/.venv/bin/supertonic` y
su CLI `tts`. Hermes no depende del PATH ni de activar ese entorno manualmente.
El equivalente de la configuración elegida es:

```bash
/Users/leocast/supertonic-test/.venv/bin/supertonic tts "Hola Leo." --voice M2 --lang es --speed 1.15 -o salida.wav
```

Hermes usa la **misma API Python de esa CLI** mediante el Python absoluto
`/Users/leocast/supertonic-test/.venv/bin/python`, con `voz_tts_worker.py` del
repositorio. Crea `TTS(model="supertonic-3", auto_download=False)` con el directorio
de caché local, obtiene `get_voice_style("M2")` y llama a
`synthesize(text=..., voice_style=..., lang="es", speed=1.15, total_steps=8)`.
`supertonic-3` y los 8 pasos son los valores predeterminados de la CLI instalada.
El resultado se guarda con `save_audio` y se reproduce con `/usr/bin/afplay`.

El TTS funciona **100% local**, sin servidor HTTP ni descargas automáticas.
Los modelos deben estar instalados previamente en `~/.cache/supertonic3`:
los cuatro archivos ONNX, `tts.json`, `unicode_indexer.json` y
`voice_styles/M2.json`. Si faltan, se informa el fallo y permanece el texto.
La carga usa `auto_download=False`, `HF_HUB_OFFLINE=1` y telemetría de Hugging Face
deshabilitada. La instalación externa y sus modelos no se modifican desde Hermes.

En el entorno de Hermes sólo se necesita la dependencia opcional de captura:

```bash
python -m pip install -r requirements-voz.txt
```

`sounddevice` utiliza PortAudio. La instalación separada de Supertonic conserva
sus propias dependencias; no se instalan ONNX ni bibliotecas TTS en Hermes.
Las rutas STT siguen configurándose como antes. En este equipo se validaron:

```bash
export HERMES_WHISPER_BIN=/opt/homebrew/bin/whisper-cli
export HERMES_WHISPER_MODEL=/Users/leocast/hermes-models/whisper/ggml-base.bin
```

Las opciones `HERMES_SUPERTONIC_DIR` y `SUPERTONIC_CACHE_DIR` permiten cambiar la
instalación y la caché respectivamente. No colocar modelos ni audios en el repo.

#### Captura, reproducción y memoria

`Escuchame` abre una sola captura. El VAD local RMS termina tras aproximadamente
0,8 segundos de silencio continuo después de detectar voz, con máximo de
8 segundos. Espera el comienzo del habla; las pausas breves no terminan la
captura. Sin voz vuelve al prompt. Lee sólo frames disponibles para evitar
bloquear esperando audio; convierte el buffer CFFI a PCM int16 correctamente.
El WAV es mono de 16 kHz. Ctrl+C cierra el stream y cancela la operación.

Obligatoriamente antes de fragmentar y sintetizar, sólo para la salida hablada,
Hermes normaliza enteros, dinero en pesos (formato
argentino), porcentajes, horas, fechas y decimales a palabras en español. El texto
visible y el historial permanecen intactos. Conserva identificadores técnicos,
URLs y formatos ambiguos; usa Python estándar sin dependencias adicionales.

La respuesta escrita aparece antes del TTS. Se divide por oraciones y unidades
naturales con un objetivo de 80–110 caracteres, priorizando punto, punto y coma,
coma, conectores y espacios. No corta palabras, importes ni fechas naturalizadas.
Una palabra o expresión indivisible más larga puede superar ese límite.
Se genera y reproduce el primer fragmento antes de continuar con el siguiente,
sin audios superpuestos. Se conserva este tamaño para favorecer el primer audio;
no se afirma una mejora de latencia medida sin la validación manual.
Sólo en la copia hablada se adaptan formas claras como «puedes» → «podés»,
«quieres» → «querés» y «tienes» → «tenés». «Tú» cambia a «vos» cuando acompaña
a esos verbos. Citas, código, URLs, rutas e identificadores se conservan.

Hay **un solo worker persistente** y una sola instancia Supertonic, cargada al
primer uso. Modelo y estilo M2 se reutilizan entre fragmentos y turnos. No hay
servidor ni hilos adicionales de síntesis. Un bloqueo impide cargar otra copia
con la misma instalación desde otra consola Hermes. Desactivar modo voz, salir,
error, timeout o Ctrl+C libera el worker. El timeout TTS es de 600 segundos por
fragmento, configurable en `ConfigVoz`.

Con voz activa, las consultas a Ollama usan `qwen3:1.7b` y `keep_alive: 0` para
liberar el cerebro al terminar; Supertonic permanece caliente. TTS directo y
comandos locales no requieren Ollama. Con voz inactiva, una consulta textual
puede elegir el cerebro profundo habitual y libera antes el worker TTS.
No se aplica la antigua heurística de memoria de Qwen/MLX ni se detienen modelos
de otras aplicaciones. No se promete un consumo máximo de RAM.

Qwen-TTS dejó de formar parte del flujo. `voz_tts_worker.py` se conserva y ahora
adapta Supertonic. No hay fallback automático a Qwen ni dependencias MLX.
`Modo voz rápido` y `Modo voz calidad` se reconocen como comandos antiguos y
explican que Supertonic usa la configuración única M2/es/1.15. Las carpetas y
modelos externos de Qwen permanecen intactos.

#### Comandos y diagnóstico

- `Activá modo voz` / `Desactivá modo voz`: estado de sesión, inicialmente inactivo.
- `Estado de voz`: estado, motor Supertonic, voz M2, idioma y velocidad.
- `Escuchame`: una captura; con modo activo se imprime y reproduce la respuesta.
- `Decime esto en voz alta: ...` / `Leé esto en voz alta: ...`: lectura explícita;
  su contenido no se ejecuta como orden.
- `Diagnóstico de voz`: motor, voz, idioma, velocidad y tiempos del último turno.
- `Auditá la voz`: micrófono, STT, ejecutable y caché TTS, worker y errores recientes.

Diagnóstico y auditoría no sintetizan audio ni cargan modelos. Los tiempos
incluyen captura, STT, procesamiento Hermes, primer audio y TTS total. «Primer
audio» mide hasta entregar el primer WAV a `afplay`, no hasta la primera palabra
acústica; «TTS total» incluye generación y reproducción. Las etapas no ejecutadas
muestran «sin medición». `Estado de voz` no pisa el diagnóstico del último turno.

Ante fallo TTS se conserva la respuesta escrita, se muestra un mensaje breve y
se registran los últimos cinco errores en RAM. Comprobar `Auditá la voz` y las
rutas si faltan dependencias o modelos. La próxima lectura puede reiniciar el
worker. No se guardan logs de audio ni texto TTS en la instalación externa.
Captura, texto auxiliar STT y WAV TTS usan temporales privados que se eliminan
al terminar, fallar o cancelar. Una terminación forzada (`kill -9`) puede impedir
esa limpieza. La transcripción y respuesta procesadas siguen formando parte del
historial normal de Hermes. No hay cambios en SQLite ni en sus esquemas.

#### Una prueba manual

Con las rutas STT anteriores configuradas, iniciar Hermes en su entorno:

```bash
cd /Users/leocast/hermes
source .venv/bin/activate
python hermes.py
```

Ingresar `Activá modo voz`, luego `Escuchame` y decir **«Mostrame mis tareas»**.
Comprobar que termina la captura al callar, muestra la transcripción y respuesta,
y reproduce esa misma respuesta con M2. Finalmente ingresar `Diagnóstico de voz`
para verificar Supertonic, español, velocidad 1.15 y tiempos; terminar con `salir`.

Verificaciones automatizadas sin micrófono, Internet, modelos ni síntesis real:

```bash
python -m py_compile hermes.py memoria.py recordatorios.py voz.py voz_tts_worker.py
python -m unittest discover -s tests -q
git diff --check
```

No incluir `hermes.db`, `recordatorios.log` ni `hermes-calendario.ics` en commits.
Los archivos del sistema de voz siguen protegidos por la seguridad de Hermes.

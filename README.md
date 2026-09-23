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

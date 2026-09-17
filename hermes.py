import json
import re
import unicodedata
from datetime import date, datetime, timedelta

import requests

from memoria import (
    crear_base,
    guardar_recuerdo,
    obtener_recuerdos,
    crear_tarea,
    obtener_tareas_pendientes,
    obtener_tareas_por_fecha,
    obtener_tareas_entre_fechas,
    completar_tarea,
    obtener_tarea_por_id,
    crear_evento,
    obtener_eventos_activos,
    obtener_eventos_por_fecha,
    obtener_eventos_entre_fechas,
    cancelar_evento,
    obtener_evento_por_id,
)

from recordatorios import (
    crear_tabla_recordatorios,
    crear_recordatorio,
    obtener_recordatorios_pendientes,
)

OLLAMA_URL = "http://localhost:11434/api/generate"

MODELO_RAPIDO = "qwen3:1.7b"
MODELO_PROFUNDO = "qwen3:4b"

crear_base()
crear_tabla_recordatorios()


PROMPT_SISTEMA = """
Tu nombre es Hermes.

Sos el asistente personal de inteligencia artificial de Leo.

Tu función es ayudarlo a organizar su vida, proyectos,
trabajo, estudios, tareas, agenda, eventos, recordatorios,
ideas y preferencias.

Hablá siempre en español salvo que Leo solicite otro idioma.

Tu estilo debe ser natural, claro, directo, amistoso y conciso.

Nunca hables como si fueras Leo.
No inventes emociones ni agregues frases decorativas innecesarias.

Nunca digas que sos Qwen ni menciones Alibaba Cloud,
salvo que Leo pregunte específicamente por el modelo técnico.

Tenés memoria permanente sobre Leo.

Una TAREA es algo pendiente por hacer.

Un EVENTO ocupa un momento determinado de la agenda.

Un RECORDATORIO debe avisarle activamente a Leo
en una fecha y hora determinadas.

Los recordatorios se procesan directamente con Python.

No guardes tareas, eventos o recordatorios también
como recuerdos personales.
"""


# ==========================================================
# TEXTO
# ==========================================================

def normalizar_texto(texto):
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)

    return "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )


# ==========================================================
# FECHAS
# ==========================================================

DIAS_SEMANA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}


def convertir_fecha(texto_fecha):
    if not texto_fecha:
        return None

    original = texto_fecha.strip()

    if not original:
        return None

    texto = normalizar_texto(original)
    hoy = date.today()

    if texto in ("hoy", "para hoy"):
        return hoy.isoformat()

    if texto in ("manana", "para manana"):
        return (
            hoy
            + timedelta(days=1)
        ).isoformat()

    if texto in (
        "pasado manana",
        "para pasado manana",
    ):
        return (
            hoy
            + timedelta(days=2)
        ).isoformat()

    for nombre_dia, numero_dia in DIAS_SEMANA.items():

        if nombre_dia in texto:

            diferencia = (
                numero_dia
                - hoy.weekday()
            ) % 7

            if diferencia == 0:
                diferencia = 7

            return (
                hoy
                + timedelta(
                    days=diferencia
                )
            ).isoformat()

    formatos = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    )

    for formato in formatos:

        try:
            fecha = datetime.strptime(
                original,
                formato
            ).date()

            return fecha.isoformat()

        except ValueError:
            pass

    return None


def extraer_fecha_del_mensaje(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    if "pasado manana" in texto:
        return convertir_fecha(
            "pasado mañana"
        )

    if "manana" in texto:
        return convertir_fecha(
            "mañana"
        )

    if re.search(
        r"\bhoy\b",
        texto
    ):
        return convertir_fecha(
            "hoy"
        )

    for nombre_dia in DIAS_SEMANA:

        if re.search(
            rf"\b{nombre_dia}\b",
            texto
        ):
            return convertir_fecha(
                nombre_dia
            )

    coincidencia = re.search(
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        mensaje
    )

    if coincidencia:
        return convertir_fecha(
            coincidencia.group(0)
        )

    coincidencia = re.search(
        r"\b\d{4}-\d{2}-\d{2}\b",
        mensaje
    )

    if coincidencia:
        return convertir_fecha(
            coincidencia.group(0)
        )

    return None


def fecha_para_mostrar(fecha_iso):
    if not fecha_iso:
        return ""

    try:
        fecha = datetime.strptime(
            fecha_iso,
            "%Y-%m-%d"
        ).date()

    except ValueError:
        return fecha_iso

    hoy = date.today()

    if fecha == hoy:
        return "hoy"

    if fecha == (
        hoy + timedelta(days=1)
    ):
        return "mañana"

    if fecha == (
        hoy + timedelta(days=2)
    ):
        return "pasado mañana"

    return fecha.strftime(
        "%d/%m/%Y"
    )


# ==========================================================
# HORAS
# ==========================================================

def extraer_horas_del_mensaje(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    rango = re.search(
        r"(?:de|desde)\s+"
        r"(\d{1,2})(?::(\d{2}))?"
        r"\s+(?:a|hasta)\s+"
        r"(\d{1,2})(?::(\d{2}))?",
        texto
    )

    if rango:

        h1 = int(
            rango.group(1)
        )

        m1 = int(
            rango.group(2) or 0
        )

        h2 = int(
            rango.group(3)
        )

        m2 = int(
            rango.group(4) or 0
        )

        return (
            f"{h1:02d}:{m1:02d}",
            f"{h2:02d}:{m2:02d}",
        )

    simple = re.search(
        r"(?:a las|a la)\s+"
        r"(\d{1,2})(?::(\d{2}))?",
        texto
    )

    if simple:

        hora = int(
            simple.group(1)
        )

        minuto = int(
            simple.group(2) or 0
        )

        return (
            f"{hora:02d}:{minuto:02d}",
            None,
        )

    return None, None


# ==========================================================
# RECORDATORIOS
# ==========================================================

def es_orden_recordatorio(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    palabras = (
        "recordame",
        "recuerdame",
        "avisame",
        "avisa me",
    )

    return any(
        palabra in texto
        for palabra in palabras
    )


def extraer_titulo_recordatorio(mensaje):
    texto = mensaje.strip()

    texto = re.sub(
        r"^(recordame|recordáme|recuérdame|avisame|avísame)\s+",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(pasado mañana|mañana|hoy)\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(el\s+)?"
        r"(lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)"
        r"\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\ba\s+las?\s+\d{1,2}(?::\d{2})?\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        "",
        texto
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    ).strip(" .,-")

    if not texto:
        return "Recordatorio de Hermes"

    return texto[0].upper() + texto[1:]


def crear_recordatorio_desde_mensaje(
    mensaje
):
    fecha = extraer_fecha_del_mensaje(
        mensaje
    )

    hora_inicio, _ = (
        extraer_horas_del_mensaje(
            mensaje
        )
    )

    if fecha is None:
        return (
            "Necesito saber qué día querés "
            "que te lo recuerde."
        )

    if hora_inicio is None:
        return (
            "Necesito saber a qué hora querés "
            "que te lo recuerde."
        )

    try:
        momento = datetime.fromisoformat(
            f"{fecha}T{hora_inicio}:00"
        )

    except ValueError:
        return (
            "No pude interpretar correctamente "
            "la fecha o la hora."
        )

    if momento <= datetime.now():
        return (
            "Ese momento ya pasó. Indicame "
            "una fecha u hora futura."
        )

    titulo = extraer_titulo_recordatorio(
        mensaje
    )

    estado, recordatorio_id = crear_recordatorio(
        titulo=titulo,
        fecha_hora=momento.isoformat(),
        mensaje=titulo
    )

    if estado == "duplicado":
        return (
            f"Ya tenés ese recordatorio "
            f"programado como #{recordatorio_id}: "
            f"{titulo} para "
            f"{fecha_para_mostrar(fecha)} "
            f"a las {hora_inicio}."
        )

    return (
        f"Listo. Creé el recordatorio "
        f"#{recordatorio_id}: {titulo} "
        f"para {fecha_para_mostrar(fecha)} "
        f"a las {hora_inicio}."
    )


def mostrar_recordatorios():
    recordatorios = (
        obtener_recordatorios_pendientes()
    )

    if not recordatorios:
        return (
            "No tenés recordatorios pendientes."
        )

    lineas = [
        "Tus recordatorios pendientes son:"
    ]

    for (
        recordatorio_id,
        titulo,
        mensaje,
        fecha_hora
    ) in recordatorios:

        try:
            momento = datetime.fromisoformat(
                fecha_hora
            )

            fecha = fecha_para_mostrar(
                momento.date().isoformat()
            )

            hora = momento.strftime(
                "%H:%M"
            )

            lineas.append(
                f"{recordatorio_id}. "
                f"{titulo} — "
                f"{fecha} a las {hora}"
            )

        except ValueError:
            lineas.append(
                f"{recordatorio_id}. {titulo}"
            )

    return "\n".join(
        lineas
    )


def es_consulta_recordatorios(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        "que recordatorios tengo",
        "mis recordatorios",
        "recordatorios pendientes",
        "mostrar recordatorios",
        "listar recordatorios",
    )

    return any(
        patron in texto
        for patron in patrones
    )


# ==========================================================
# MEMORIA
# ==========================================================

def obtener_texto_memoria():
    recuerdos = obtener_recuerdos()

    if not recuerdos:
        return (
            "No hay recuerdos permanentes "
            "guardados todavía."
        )

    return "\n".join(
        f"- [{categoria}] "
        f"{clave}: {valor}"
        for categoria, clave, valor
        in recuerdos
    )


# ==========================================================
# TAREAS
# ==========================================================

def obtener_texto_tareas():
    tareas = (
        obtener_tareas_pendientes()
    )

    if not tareas:
        return (
            "No hay tareas pendientes."
        )

    lineas = []

    for (
        tarea_id,
        titulo,
        descripcion,
        fecha,
        estado,
    ) in tareas:

        texto = (
            f"- ID {tarea_id}: "
            f"{titulo}"
        )

        if fecha:
            texto += (
                f" | fecha: "
                f"{fecha_para_mostrar(fecha)}"
            )

        if descripcion:
            texto += (
                f" | detalle: "
                f"{descripcion}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


def formatear_tareas(
    tareas,
    encabezado
):
    if not tareas:
        return (
            "No encontré tareas pendientes "
            "para ese período."
        )

    lineas = [
        encabezado
    ]

    for (
        tarea_id,
        titulo,
        descripcion,
        fecha,
        estado,
    ) in tareas:

        texto = (
            f"{tarea_id}. "
            f"{titulo}"
        )

        if fecha:
            texto += (
                f" — "
                f"{fecha_para_mostrar(fecha)}"
            )

        if descripcion:
            texto += (
                f" — {descripcion}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


def mostrar_tareas_pendientes():
    return formatear_tareas(
        obtener_tareas_pendientes(),
        "Tus tareas pendientes son:"
    )


# ==========================================================
# EVENTOS
# ==========================================================

def obtener_texto_eventos():
    eventos = (
        obtener_eventos_activos()
    )

    if not eventos:
        return (
            "No hay eventos próximos."
        )

    lineas = []

    for (
        evento_id,
        titulo,
        descripcion,
        fecha,
        hora_inicio,
        hora_fin,
        estado,
    ) in eventos:

        texto = (
            f"- ID {evento_id}: "
            f"{titulo}"
        )

        if fecha:
            texto += (
                f" | fecha: "
                f"{fecha_para_mostrar(fecha)}"
            )

        if hora_inicio:
            texto += (
                f" | hora: "
                f"{hora_inicio}"
            )

        if hora_fin:
            texto += (
                f" a {hora_fin}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


def mostrar_eventos():
    eventos = (
        obtener_eventos_activos()
    )

    if not eventos:
        return (
            "No tenés eventos próximos."
        )

    lineas = [
        "Tus próximos eventos son:"
    ]

    for (
        evento_id,
        titulo,
        descripcion,
        fecha,
        hora_inicio,
        hora_fin,
        estado,
    ) in eventos:

        texto = (
            f"{evento_id}. "
            f"{titulo} — "
            f"{fecha_para_mostrar(fecha)}"
        )

        if hora_inicio:
            texto += (
                f" — {hora_inicio}"
            )

        if hora_fin:
            texto += (
                f" a {hora_fin}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


# ==========================================================
# AGENDA
# ==========================================================

def agenda_para_fecha(
    fecha_iso,
    nombre
):
    tareas = (
        obtener_tareas_por_fecha(
            fecha_iso
        )
    )

    eventos = (
        obtener_eventos_por_fecha(
            fecha_iso
        )
    )

    if not tareas and not eventos:
        return (
            f"No tenés tareas ni eventos "
            f"para {nombre}."
        )

    lineas = [
        f"Tu agenda para {nombre}:"
    ]

    if eventos:
        lineas.append("")
        lineas.append("Eventos:")

        for (
            evento_id,
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado,
        ) in eventos:

            texto = (
                f"- #{evento_id} "
                f"{titulo}"
            )

            if hora_inicio:
                texto += (
                    f" — {hora_inicio}"
                )

            if hora_fin:
                texto += (
                    f" a {hora_fin}"
                )

            lineas.append(
                texto
            )

    if tareas:
        lineas.append("")
        lineas.append("Tareas:")

        for (
            tarea_id,
            titulo,
            descripcion,
            fecha,
            estado,
        ) in tareas:

            lineas.append(
                f"- #{tarea_id} "
                f"{titulo}"
            )

    return "\n".join(
        lineas
    )


def agenda_hoy():
    return agenda_para_fecha(
        date.today().isoformat(),
        "hoy"
    )


def agenda_manana():
    fecha = (
        date.today()
        + timedelta(days=1)
    ).isoformat()

    return agenda_para_fecha(
        fecha,
        "mañana"
    )


def agenda_semana():
    hoy = date.today()

    fin = (
        hoy
        + timedelta(
            days=6 - hoy.weekday()
        )
    )

    tareas = (
        obtener_tareas_entre_fechas(
            hoy.isoformat(),
            fin.isoformat()
        )
    )

    eventos = (
        obtener_eventos_entre_fechas(
            hoy.isoformat(),
            fin.isoformat()
        )
    )

    if not tareas and not eventos:
        return (
            "No tenés tareas ni eventos "
            "para esta semana."
        )

    lineas = [
        "Tu agenda para esta semana:"
    ]

    if eventos:
        lineas.append("")
        lineas.append("Eventos:")

        for (
            evento_id,
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado,
        ) in eventos:

            texto = (
                f"- "
                f"{fecha_para_mostrar(fecha)}: "
                f"#{evento_id} "
                f"{titulo}"
            )

            if hora_inicio:
                texto += (
                    f" — {hora_inicio}"
                )

            if hora_fin:
                texto += (
                    f" a {hora_fin}"
                )

            lineas.append(
                texto
            )

    if tareas:
        lineas.append("")
        lineas.append("Tareas:")

        for (
            tarea_id,
            titulo,
            descripcion,
            fecha,
            estado,
        ) in tareas:

            lineas.append(
                f"- "
                f"{fecha_para_mostrar(fecha)}: "
                f"#{tarea_id} "
                f"{titulo}"
            )

    return "\n".join(
        lineas
    )


# ==========================================================
# COMANDOS LOCALES
# ==========================================================

def procesar_comandos_directos(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if es_consulta_recordatorios(
        mensaje
    ):
        return mostrar_recordatorios()

    if es_orden_recordatorio(
        mensaje
    ):
        return crear_recordatorio_desde_mensaje(
            mensaje
        )

    if any(
        patron in texto
        for patron in (
            "que tengo hoy",
            "que tengo para hoy",
            "agenda de hoy",
        )
    ):
        return agenda_hoy()

    if any(
        patron in texto
        for patron in (
            "que tengo manana",
            "que tengo para manana",
            "agenda de manana",
        )
    ):
        return agenda_manana()

    if any(
        patron in texto
        for patron in (
            "que tengo esta semana",
            "agenda de esta semana",
        )
    ):
        return agenda_semana()

    if any(
        patron in texto
        for patron in (
            "que tareas tengo",
            "mis tareas",
            "tareas pendientes",
        )
    ):
        return mostrar_tareas_pendientes()

    if any(
        patron in texto
        for patron in (
            "que eventos tengo",
            "mis eventos",
            "proximos eventos",
        )
    ):
        return mostrar_eventos()

    if any(
        palabra in texto
        for palabra in (
            "completar",
            "complete",
            "termine",
            "marcar como hecha",
        )
    ):
        coincidencia = re.search(
            r"(?:tarea\s*)?#?\s*(\d+)",
            texto
        )

        if coincidencia:
            tarea_id = int(
                coincidencia.group(1)
            )

            tarea = (
                obtener_tarea_por_id(
                    tarea_id
                )
            )

            if not tarea:
                return (
                    f"No encontré la tarea "
                    f"#{tarea_id}."
                )

            if tarea[4] == "completada":
                return (
                    f"La tarea #{tarea_id} "
                    f"ya estaba completada."
                )

            if completar_tarea(
                tarea_id
            ):
                return (
                    f"Listo. Completé la tarea "
                    f"#{tarea_id}: "
                    f"{tarea[1]}."
                )

    return None


# ==========================================================
# MODELOS
# ==========================================================

def necesita_modo_profundo(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if texto.startswith(
        "profundo:"
    ):
        return True

    palabras = (
        "analiza en profundidad",
        "estrategia",
        "arquitectura",
        "investiga",
        "programa",
        "debug",
        "contrato",
    )

    if any(
        palabra in texto
        for palabra in palabras
    ):
        return True

    return len(mensaje) > 1200


def elegir_modelo(mensaje):
    if necesita_modo_profundo(
        mensaje
    ):
        return (
            MODELO_PROFUNDO,
            "🧠 profundo"
        )

    return (
        MODELO_RAPIDO,
        "⚡ rápido"
    )


# ==========================================================
# IA
# ==========================================================

def consultar_hermes(
    mensaje
):
    comando = (
        procesar_comandos_directos(
            mensaje
        )
    )

    if comando is not None:
        print(
            "Hermes ⚡ comando local..."
        )
        return comando

    modelo, modo = elegir_modelo(
        mensaje
    )

    memoria = (
        obtener_texto_memoria()
    )

    tareas = (
        obtener_texto_tareas()
    )

    eventos = (
        obtener_texto_eventos()
    )

    prompt = f"""
{PROMPT_SISTEMA}

FECHA ACTUAL:
{date.today().isoformat()}

MEMORIA:
{memoria}

TAREAS:
{tareas}

EVENTOS:
{eventos}

MENSAJE DE LEO:
{mensaje}

Respondé solamente con JSON válido:

{{
    "respuesta": "respuesta natural",
    "accion": "ninguna",
    "guardar_memoria": false,
    "categoria": "",
    "clave": "",
    "valor": "",
    "tarea_titulo": "",
    "tarea_descripcion": "",
    "evento_titulo": "",
    "evento_descripcion": ""
}}

Acciones posibles:

"ninguna"
"crear_tarea"
"crear_evento"

Elegí crear_evento para citas,
reuniones, turnos o clases.

Elegí crear_tarea para pendientes.

No escribas nada fuera del JSON.
"""

    datos = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "num_ctx": 4096,
        },
    }

    print(
        f"Hermes {modo}...",
        flush=True
    )

    respuesta_http = requests.post(
        OLLAMA_URL,
        json=datos,
        timeout=120
    )

    respuesta_http.raise_for_status()

    texto = (
        respuesta_http
        .json()["response"]
        .strip()
    )

    try:
        resultado = json.loads(
            texto
        )

    except json.JSONDecodeError:
        return texto

    accion = resultado.get(
        "accion",
        "ninguna"
    )

    respuesta = resultado.get(
        "respuesta",
        "No pude generar una respuesta."
    )

    if accion == "crear_tarea":
        titulo = str(
            resultado.get(
                "tarea_titulo",
                ""
            )
        ).strip()

        descripcion = str(
            resultado.get(
                "tarea_descripcion",
                ""
            )
        ).strip()

        fecha = (
            extraer_fecha_del_mensaje(
                mensaje
            )
        )

        if titulo:
            tarea_id = crear_tarea(
                titulo,
                descripcion,
                fecha
            )

            print(
                f"✅ Tarea creada "
                f"#{tarea_id}: "
                f"{titulo}"
            )

            respuesta = (
                f"Listo. Agregué la tarea "
                f"#{tarea_id}: "
                f"{titulo}."
            )

    elif accion == "crear_evento":
        titulo = str(
            resultado.get(
                "evento_titulo",
                ""
            )
        ).strip()

        descripcion = str(
            resultado.get(
                "evento_descripcion",
                ""
            )
        ).strip()

        fecha = (
            extraer_fecha_del_mensaje(
                mensaje
            )
        )

        hora_inicio, hora_fin = (
            extraer_horas_del_mensaje(
                mensaje
            )
        )

        if not fecha:
            respuesta = (
                "Necesito una fecha "
                "para crear el evento."
            )

        elif titulo:
            evento_id = crear_evento(
                titulo=titulo,
                fecha=fecha,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                descripcion=descripcion,
            )

            print(
                f"📅 Evento creado "
                f"#{evento_id}: "
                f"{titulo}"
            )

            respuesta = (
                f"Listo. Agregué el evento "
                f"#{evento_id}: "
                f"{titulo} para "
                f"{fecha_para_mostrar(fecha)}"
            )

            if hora_inicio:
                respuesta += (
                    f" a las "
                    f"{hora_inicio}"
                )

            respuesta += "."

    if resultado.get(
        "guardar_memoria"
    ) is True:
        categoria = str(
            resultado.get(
                "categoria",
                "otro"
            )
        ).strip()

        clave = str(
            resultado.get(
                "clave",
                ""
            )
        ).strip().lower()

        valor = str(
            resultado.get(
                "valor",
                ""
            )
        ).strip()

        if clave and valor:
            estado = guardar_recuerdo(
                categoria,
                clave,
                valor
            )

            if estado == "creado":
                print(
                    f"🧠 Hermes recordó: "
                    f"{valor}"
                )

            elif estado == "actualizado":
                print(
                    f"🧠 Hermes actualizó: "
                    f"{valor}"
                )

    return respuesta


# ==========================================================
# INICIO
# ==========================================================

print()
print(
    "════════════════════════════════"
)
print(
    "            HERMES"
)
print(
    "════════════════════════════════"
)
print()
print(
    "⚡ Cerebro rápido: qwen3:1.7b"
)
print(
    "🧠 Cerebro profundo: qwen3:4b"
)
print(
    "🧠 Memoria permanente: activa"
)
print(
    "✅ Gestión de tareas: activa"
)
print(
    "📅 Fechas inteligentes: activas"
)
print(
    "🗓️ Agenda y eventos: activos"
)
print(
    "🔔 Recordatorios: activos"
)
print()
print(
    "Escribí 'salir' para terminar."
)
print()


while True:
    mensaje = input(
        "Vos: "
    ).strip()

    if not mensaje:
        continue

    if mensaje.lower() == "salir":
        print()
        print(
            "Hermes: Hasta luego, Leo."
        )
        break

    try:
        respuesta = consultar_hermes(
            mensaje
        )

        print()
        print(
            f"Hermes: {respuesta}"
        )
        print()

    except requests.exceptions.RequestException as error:
        print()
        print(
            "Hermes: Tuve un problema "
            "comunicándome con mi "
            "modelo local."
        )

        print(
            f"Error técnico: "
            f"{error}"
        )
        print()

    except Exception as error:
        print()
        print(
            "Hermes: Ocurrió un error."
        )

        print(
            f"Error técnico: "
            f"{error}"
        )
        print()

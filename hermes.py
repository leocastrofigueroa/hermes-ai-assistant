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
)

from recordatorios import (
    crear_tabla_recordatorios,
    crear_recordatorio,
    obtener_recordatorios_pendientes,
    obtener_recordatorio_por_id,
    modificar_recordatorio,
    cancelar_recordatorio,
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
No inventes emociones.

Tenés memoria permanente.

Una TAREA es algo pendiente por hacer.
Un EVENTO ocupa un momento determinado de la agenda.
Un RECORDATORIO avisa activamente en una fecha y hora.

No guardes tareas, eventos ni recordatorios
como recuerdos personales.
"""


# ==========================================================
# TEXTO
# ==========================================================

def normalizar_texto(texto):
    texto = texto.lower().strip()

    texto = unicodedata.normalize(
        "NFD",
        texto
    )

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
    texto = normalizar_texto(original)
    hoy = date.today()

    if texto in (
        "hoy",
        "para hoy"
    ):
        return hoy.isoformat()

    if texto in (
        "manana",
        "para manana"
    ):
        return (
            hoy
            + timedelta(days=1)
        ).isoformat()

    if texto in (
        "pasado manana",
        "para pasado manana"
    ):
        return (
            hoy
            + timedelta(days=2)
        ).isoformat()

    for nombre, numero in DIAS_SEMANA.items():

        if nombre in texto:

            diferencia = (
                numero
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

    for formato in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ):

        try:
            return datetime.strptime(
                original,
                formato
            ).date().isoformat()

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

    for dia in DIAS_SEMANA:

        if re.search(
            rf"\b{dia}\b",
            texto
        ):
            return convertir_fecha(
                dia
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
    try:
        fecha = datetime.strptime(
            fecha_iso,
            "%Y-%m-%d"
        ).date()

    except (ValueError, TypeError):
        return fecha_iso or ""

    hoy = date.today()

    if fecha == hoy:
        return "hoy"

    if fecha == hoy + timedelta(days=1):
        return "mañana"

    if fecha == hoy + timedelta(days=2):
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

        h1 = int(rango.group(1))
        m1 = int(rango.group(2) or 0)

        h2 = int(rango.group(3))
        m2 = int(rango.group(4) or 0)

        return (
            f"{h1:02d}:{m1:02d}",
            f"{h2:02d}:{m2:02d}"
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
            None
        )

    return None, None


# ==========================================================
# RECORDATORIOS
# ==========================================================

def es_consulta_recordatorios(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        patron in texto
        for patron in (
            "que recordatorios tengo",
            "mis recordatorios",
            "recordatorios pendientes",
            "mostrar recordatorios",
            "listar recordatorios",
        )
    )


def es_orden_recordatorio(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        palabra in texto
        for palabra in (
            "recordame",
            "recuerdame",
            "avisame",
        )
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
        r"\s+",
        " ",
        texto
    ).strip(" .,-")

    if not texto:
        return "Recordatorio de Hermes"

    return (
        texto[0].upper()
        + texto[1:]
    )


def crear_recordatorio_desde_mensaje(
    mensaje
):
    fecha = extraer_fecha_del_mensaje(
        mensaje
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    if not fecha:
        return (
            "Necesito saber qué día querés "
            "que te lo recuerde."
        )

    if not hora:
        return (
            "Necesito saber a qué hora querés "
            "que te lo recuerde."
        )

    try:
        momento = datetime.fromisoformat(
            f"{fecha}T{hora}:00"
        )

    except ValueError:
        return (
            "No pude interpretar la fecha "
            "o la hora."
        )

    if momento <= datetime.now():
        return (
            "Ese momento ya pasó."
        )

    titulo = extraer_titulo_recordatorio(
        mensaje
    )

    estado, recordatorio_id = (
        crear_recordatorio(
            titulo,
            momento.isoformat(),
            titulo
        )
    )

    if estado == "duplicado":
        return (
            f"Ya tenés ese recordatorio "
            f"programado como #{recordatorio_id}."
        )

    return (
        f"Listo. Creé el recordatorio "
        f"#{recordatorio_id}: {titulo} "
        f"para {fecha_para_mostrar(fecha)} "
        f"a las {hora}."
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
                f"{recordatorio_id}. "
                f"{titulo}"
            )

    return "\n".join(
        lineas
    )


# ==========================================================
# CANCELAR RECORDATORIO
# ==========================================================

def es_cancelacion_recordatorio(mensaje):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "recordatorio" in texto
        and any(
            palabra in texto
            for palabra in (
                "cancela",
                "cancelar",
                "elimina",
                "eliminar",
                "borra",
                "borrar",
            )
        )
    )


def cancelar_recordatorio_desde_mensaje(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    coincidencia = re.search(
        r"recordatorio\s*#?\s*(\d+)",
        texto
    )

    if not coincidencia:
        return (
            "Decime el número del recordatorio "
            "que querés cancelar."
        )

    recordatorio_id = int(
        coincidencia.group(1)
    )

    recordatorio = (
        obtener_recordatorio_por_id(
            recordatorio_id
        )
    )

    if not recordatorio:
        return (
            f"No encontré el recordatorio "
            f"#{recordatorio_id}."
        )

    estado, _ = cancelar_recordatorio(
        recordatorio_id
    )

    if estado == "ya_cancelado":
        return (
            f"El recordatorio "
            f"#{recordatorio_id} "
            f"ya estaba cancelado."
        )

    if estado == "ya_disparado":
        return (
            f"El recordatorio "
            f"#{recordatorio_id} "
            f"ya fue disparado."
        )

    return (
        f"Listo. Cancelé el recordatorio "
        f"#{recordatorio_id}: "
        f"{recordatorio[1]}."
    )


# ==========================================================
# MODIFICAR RECORDATORIO
# ==========================================================

def es_modificacion_recordatorio(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "recordatorio" in texto
        and any(
            palabra in texto
            for palabra in (
                "cambia",
                "cambiar",
                "cambialo",
                "modifica",
                "modificar",
                "mueve",
                "mover",
                "pasa",
                "pasalo",
            )
        )
    )


def buscar_recordatorio_por_texto(
    mensaje
):
    recordatorios = (
        obtener_recordatorios_pendientes()
    )

    texto = normalizar_texto(
        mensaje
    )

    mejores = []

    for recordatorio in recordatorios:

        recordatorio_id = recordatorio[0]
        titulo = recordatorio[1]

        titulo_normalizado = (
            normalizar_texto(
                titulo
            )
        )

        palabras = [
            palabra
            for palabra in titulo_normalizado.split()
            if len(palabra) >= 4
        ]

        coincidencias = sum(
            1
            for palabra in palabras
            if palabra in texto
        )

        if coincidencias > 0:
            mejores.append(
                (
                    coincidencias,
                    recordatorio_id
                )
            )

    if not mejores:
        return None

    mejores.sort(
        reverse=True
    )

    return mejores[0][1]


def modificar_recordatorio_desde_mensaje(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    coincidencia = re.search(
        r"recordatorio\s*#?\s*(\d+)",
        texto
    )

    if coincidencia:

        recordatorio_id = int(
            coincidencia.group(1)
        )

    else:

        recordatorio_id = (
            buscar_recordatorio_por_texto(
                mensaje
            )
        )

    if not recordatorio_id:
        return (
            "No pude identificar qué "
            "recordatorio querés modificar."
        )

    actual = obtener_recordatorio_por_id(
        recordatorio_id
    )

    if not actual:
        return (
            f"No encontré el recordatorio "
            f"#{recordatorio_id}."
        )

    fecha_nueva = (
        extraer_fecha_del_mensaje(
            mensaje
        )
    )

    hora_nueva, _ = (
        extraer_horas_del_mensaje(
            mensaje
        )
    )

    try:
        momento_actual = datetime.fromisoformat(
            actual[3]
        )

    except ValueError:
        return (
            "El recordatorio tiene una fecha "
            "inválida en la base de datos."
        )

    if fecha_nueva:
        fecha_final = fecha_nueva

    else:
        fecha_final = (
            momento_actual
            .date()
            .isoformat()
        )

    if hora_nueva:
        hora_final = hora_nueva

    else:
        hora_final = (
            momento_actual
            .strftime("%H:%M")
        )

    momento_nuevo = datetime.fromisoformat(
        f"{fecha_final}T{hora_final}:00"
    )

    if momento_nuevo <= datetime.now():
        return (
            "La nueva fecha y hora "
            "ya pasaron."
        )

    estado, resultado_id = (
        modificar_recordatorio(
            recordatorio_id,
            momento_nuevo.isoformat()
        )
    )

    if estado == "duplicado":
        return (
            f"Ya existe un recordatorio "
            f"igual como #{resultado_id}."
        )

    if estado == "no_pendiente":
        return (
            f"El recordatorio "
            f"#{recordatorio_id} "
            f"ya no está pendiente."
        )

    return (
        f"Listo. Cambié el recordatorio "
        f"#{recordatorio_id}: "
        f"{actual[1]} para "
        f"{fecha_para_mostrar(fecha_final)} "
        f"a las {hora_final}."
    )


# ==========================================================
# RECORDATORIOS ANTES DE EVENTOS
# ==========================================================

def es_recordatorio_relativo_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        es_orden_recordatorio(mensaje)
        and (
            "antes de" in texto
            or "antes del" in texto
        )
    )


def extraer_minutos_anticipacion(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if "media hora antes" in texto:
        return 30, "30 minutos"

    if re.search(
        r"\b(?:una|un)\s+hora\s+antes\b",
        texto
    ):
        return 60, "1 hora"

    coincidencia = re.search(
        r"\b(\d+)\s*"
        r"(minuto|minutos|hora|horas|dia|dias)"
        r"\s+antes\b",
        texto
    )

    if not coincidencia:
        return None, None

    cantidad = int(
        coincidencia.group(1)
    )

    unidad = coincidencia.group(2)

    if unidad.startswith("minuto"):
        return (
            cantidad,
            f"{cantidad} minutos"
        )

    if unidad.startswith("hora"):
        return (
            cantidad * 60,
            f"{cantidad} horas"
        )

    return (
        cantidad * 1440,
        f"{cantidad} días"
    )


def extraer_referencia_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    coincidencia = re.search(
        r"antes\s+(?:de|del)\s+(.+)$",
        texto
    )

    if not coincidencia:
        return ""

    return (
        coincidencia
        .group(1)
        .strip(" .,!¿?¡")
    )


def buscar_evento_por_referencia(
    referencia
):
    eventos = obtener_eventos_activos()

    referencia = normalizar_texto(
        referencia
    )

    candidatos = []

    for evento in eventos:

        titulo = normalizar_texto(
            evento[1]
        )

        puntuacion = 0

        if referencia in titulo:
            puntuacion += 50

        for palabra in referencia.split():

            if (
                len(palabra) >= 4
                and palabra in titulo
            ):
                puntuacion += 10

        if puntuacion:
            candidatos.append(
                (
                    puntuacion,
                    evento
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda elemento: elemento[0],
        reverse=True
    )

    return candidatos[0][1]


def crear_recordatorio_antes_evento(
    mensaje
):
    minutos, descripcion = (
        extraer_minutos_anticipacion(
            mensaje
        )
    )

    if minutos is None:
        return (
            "Necesito saber cuánto tiempo "
            "antes querés que te avise."
        )

    referencia = (
        extraer_referencia_evento(
            mensaje
        )
    )

    evento = (
        buscar_evento_por_referencia(
            referencia
        )
    )

    if not evento:
        return (
            f"No encontré un evento "
            f"relacionado con '{referencia}'."
        )

    (
        evento_id,
        titulo,
        descripcion_evento,
        fecha,
        hora_inicio,
        hora_fin,
        estado_evento,
    ) = evento

    if not hora_inicio:
        return (
            f"El evento {titulo} "
            f"no tiene hora."
        )

    momento_evento = datetime.fromisoformat(
        f"{fecha}T{hora_inicio}:00"
    )

    momento_aviso = (
        momento_evento
        - timedelta(
            minutes=minutos
        )
    )

    if momento_aviso <= datetime.now():
        return (
            "El momento para ese aviso "
            "ya pasó."
        )

    mensaje_recordatorio = (
        f"En {descripcion} "
        f"tenés {titulo}."
    )

    estado, recordatorio_id = (
        crear_recordatorio(
            titulo,
            momento_aviso.isoformat(),
            mensaje_recordatorio
        )
    )

    if estado == "duplicado":
        return (
            f"Ya tenés ese aviso "
            f"programado como "
            f"#{recordatorio_id}."
        )

    return (
        f"Listo. Creé el recordatorio "
        f"#{recordatorio_id}. "
        f"Te voy a avisar "
        f"{descripcion} antes de "
        f"{titulo}, "
        f"{fecha_para_mostrar(momento_aviso.date().isoformat())} "
        f"a las "
        f"{momento_aviso.strftime('%H:%M')}."
    )


# ==========================================================
# MEMORIA / TAREAS / EVENTOS
# ==========================================================

def obtener_texto_memoria():
    recuerdos = obtener_recuerdos()

    if not recuerdos:
        return "Sin recuerdos guardados."

    return "\n".join(
        f"- [{categoria}] "
        f"{clave}: {valor}"
        for categoria, clave, valor
        in recuerdos
    )


def obtener_texto_tareas():
    tareas = obtener_tareas_pendientes()

    if not tareas:
        return "Sin tareas pendientes."

    return "\n".join(
        f"- ID {tarea[0]}: "
        f"{tarea[1]} | "
        f"{tarea[3] or 'sin fecha'}"
        for tarea in tareas
    )


def obtener_texto_eventos():
    eventos = obtener_eventos_activos()

    if not eventos:
        return "Sin eventos próximos."

    return "\n".join(
        f"- ID {evento[0]}: "
        f"{evento[1]} | "
        f"{evento[3]} | "
        f"{evento[4] or 'sin hora'}"
        for evento in eventos
    )


def mostrar_tareas_pendientes():
    tareas = obtener_tareas_pendientes()

    if not tareas:
        return "No tenés tareas pendientes."

    lineas = [
        "Tus tareas pendientes son:"
    ]

    for tarea in tareas:

        texto = (
            f"{tarea[0]}. "
            f"{tarea[1]}"
        )

        if tarea[3]:
            texto += (
                f" — "
                f"{fecha_para_mostrar(tarea[3])}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


def mostrar_eventos():
    eventos = obtener_eventos_activos()

    if not eventos:
        return "No tenés eventos próximos."

    lineas = [
        "Tus próximos eventos son:"
    ]

    for evento in eventos:

        texto = (
            f"{evento[0]}. "
            f"{evento[1]} — "
            f"{fecha_para_mostrar(evento[3])}"
        )

        if evento[4]:
            texto += (
                f" — {evento[4]}"
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
    tareas = obtener_tareas_por_fecha(
        fecha_iso
    )

    eventos = obtener_eventos_por_fecha(
        fecha_iso
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

        for evento in eventos:

            texto = (
                f"- #{evento[0]} "
                f"{evento[1]}"
            )

            if evento[4]:
                texto += (
                    f" — {evento[4]}"
                )

            lineas.append(
                texto
            )

    if tareas:
        lineas.append("")
        lineas.append("Tareas:")

        for tarea in tareas:

            lineas.append(
                f"- #{tarea[0]} "
                f"{tarea[1]}"
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
    return agenda_para_fecha(
        (
            date.today()
            + timedelta(days=1)
        ).isoformat(),
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

    tareas = obtener_tareas_entre_fechas(
        hoy.isoformat(),
        fin.isoformat()
    )

    eventos = obtener_eventos_entre_fechas(
        hoy.isoformat(),
        fin.isoformat()
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

        for evento in eventos:

            lineas.append(
                f"- "
                f"{fecha_para_mostrar(evento[3])}: "
                f"#{evento[0]} "
                f"{evento[1]}"
                + (
                    f" — {evento[4]}"
                    if evento[4]
                    else ""
                )
            )

    if tareas:
        lineas.append("")
        lineas.append("Tareas:")

        for tarea in tareas:

            lineas.append(
                f"- "
                f"{fecha_para_mostrar(tarea[3])}: "
                f"#{tarea[0]} "
                f"{tarea[1]}"
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

    if es_cancelacion_recordatorio(
        mensaje
    ):
        return cancelar_recordatorio_desde_mensaje(
            mensaje
        )

    if es_modificacion_recordatorio(
        mensaje
    ):
        return modificar_recordatorio_desde_mensaje(
            mensaje
        )

    if es_recordatorio_relativo_evento(
        mensaje
    ):
        return crear_recordatorio_antes_evento(
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

            tarea = obtener_tarea_por_id(
                tarea_id
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

            completar_tarea(
                tarea_id
            )

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

    return (
        any(
            palabra in texto
            for palabra in palabras
        )
        or len(mensaje) > 1200
    )


def elegir_modelo(
    mensaje
):
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
    comando = procesar_comandos_directos(
        mensaje
    )

    if comando is not None:

        print(
            "Hermes ⚡ comando local..."
        )

        return comando

    modelo, modo = elegir_modelo(
        mensaje
    )

    prompt = f"""
{PROMPT_SISTEMA}

FECHA ACTUAL:
{date.today().isoformat()}

MEMORIA:
{obtener_texto_memoria()}

TAREAS:
{obtener_texto_tareas()}

EVENTOS:
{obtener_texto_eventos()}

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

Acciones:
"ninguna"
"crear_tarea"
"crear_evento"

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

    respuesta = resultado.get(
        "respuesta",
        "No pude generar una respuesta."
    )

    accion = resultado.get(
        "accion",
        "ninguna"
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

        fecha = extraer_fecha_del_mensaje(
            mensaje
        )

        if titulo:

            tarea_id = crear_tarea(
                titulo,
                descripcion,
                fecha
            )

            respuesta = (
                f"Listo. Agregué la tarea "
                f"#{tarea_id}: {titulo}."
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

        fecha = extraer_fecha_del_mensaje(
            mensaje
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

            respuesta = (
                f"Listo. Agregué el evento "
                f"#{evento_id}: "
                f"{titulo} para "
                f"{fecha_para_mostrar(fecha)}"
            )

            if hora_inicio:
                respuesta += (
                    f" a las {hora_inicio}"
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

            guardar_recuerdo(
                categoria,
                clave,
                valor
            )

    return respuesta


# ==========================================================
# INICIO
# ==========================================================

print()
print("════════════════════════════════")
print("            HERMES")
print("════════════════════════════════")
print()
print("⚡ Cerebro rápido: qwen3:1.7b")
print("🧠 Cerebro profundo: qwen3:4b")
print("🧠 Memoria permanente: activa")
print("✅ Gestión de tareas: activa")
print("🗓️ Agenda y eventos: activos")
print("🔔 Recordatorios: activos")
print("⏰ Avisos previos a eventos: activos")
print("✏️ Modificación de recordatorios: activa")
print("🗑️ Cancelación de recordatorios: activa")
print()
print("Escribí 'salir' para terminar.")
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
            f"Error técnico: {error}"
        )
        print()

    except Exception as error:

        print()
        print(
            "Hermes: Ocurrió un error."
        )

        print(
            f"Error técnico: {error}"
        )
        print()

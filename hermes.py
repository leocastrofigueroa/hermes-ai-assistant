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
    obtener_evento_por_id,
    modificar_evento,
    cancelar_evento,
)

from recordatorios import (
    crear_tabla_recordatorios,
    crear_recordatorio,
    obtener_recordatorios_pendientes,
    obtener_recordatorio_por_id,
    obtener_recordatorios_de_evento,
    modificar_recordatorio,
    actualizar_recordatorio_vinculado,
    cancelar_recordatorio,
    reprogramar_recordatorios_de_evento,
    cancelar_recordatorios_de_evento,
)


OLLAMA_URL = "http://localhost:11434/api/generate"

MODELO_RAPIDO = "qwen3:1.7b"
MODELO_PROFUNDO = "qwen3:4b"


crear_base()
crear_tabla_recordatorios()


confirmacion_pendiente = None
ultimo_contexto_edicion = None


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

Los recordatorios pueden estar vinculados a eventos.

Si existen varios elementos posibles para una acción,
no elijas uno arbitrariamente.

No interpretes respuestas aisladas dependientes de contexto
como nuevas tareas o eventos.

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
# SEGURIDAD CONVERSACIONAL
# ==========================================================

def es_respuesta_dependiente_sin_contexto(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if not texto:
        return False

    patrones = (
        r"^(el|la|los|las)\s+de\b",
        r"^(el|la)\s+(primero|primera|segundo|segunda|tercero|tercera|ultimo|ultima)\b",
        r"^(ese|esa|esos|esas|este|esta|estos|estas)$",
        r"^(ese|esa|este|esta)\s+",
        r"^(el|la)\s+#?\d+\s*$",
        r"^(el|la)\s+recordatorio\s+#?\d+\s*$",
        r"^(?:ahora|despues|luego)\s+(?:dejalo|dejala|correlo|correla|movelo|movela|muevelo|muevela|cambialo|cambiala|pasalo|pasala)\b",
        r"^(?:ahora|despues|luego)\s+(?:ese|esa|eso|este|esta)\b",
    )

    for patron in patrones:

        if re.search(
            patron,
            texto
        ):
            return True

    respuestas_dependientes = {
        "agregalo",
        "agregala",
        "agrega",
        "sumalo",
        "sumala",
        "reemplazalo",
        "reemplazala",
        "reemplaza",
        "cambialo",
        "cambiala",
        "cancelalo",
        "cancelala",
        "dejalo",
        "dejala",
        "ese",
        "esa",
        "este",
        "esta",
        "el primero",
        "el segundo",
        "el tercero",
        "la primera",
        "la segunda",
        "la tercera",
    }

    return texto in respuestas_dependientes


def respuesta_contexto_faltante(
    mensaje
):
    return (
        f"No tengo una acción pendiente a la que pueda "
        f"asociar “{mensaje.strip()}”. "
        f"Decime a qué te referís."
    )


def guardar_contexto_edicion(
    tipo,
    elemento_id
):
    global ultimo_contexto_edicion

    ultimo_contexto_edicion = {
        "tipo": tipo,
        "id": elemento_id,
    }


def limpiar_contexto_edicion():
    global ultimo_contexto_edicion
    ultimo_contexto_edicion = None


def es_edicion_contextual(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    pronombres_accion = (
        "dejalo",
        "dejala",
        "correlo",
        "correla",
        "movelo",
        "movela",
        "muevelo",
        "muevela",
        "cambialo",
        "cambiala",
        "pasalo",
        "pasala",
        "adelantalo",
        "adelantala",
        "retrasalo",
        "retrasala",
    )

    if any(
        re.search(
            rf"\b{re.escape(palabra)}\b",
            texto
        )
        for palabra in pronombres_accion
    ):
        return True

    if re.search(
        r"^(?:ahora|despues|luego)\s+"
        r"(?:ese|esa|eso|este|esta)\b",
        texto
    ):
        return True

    if re.search(
        r"^(?:ese|esa|eso|este|esta)\b",
        texto
    ):
        return True

    # También aceptamos una acción seguida de un pronombre contextual.
    # Ejemplos: "Mové eso al viernes a las 18" o
    # "Cambiá ese para mañana".
    if re.search(
        r"^(?:move|mover|cambia|cambiar|pasa|pasar|"
        r"corre|correr|adelanta|adelantar|retrasa|retrasar)\s+"
        r"(?:ese|esa|eso|este|esta)\b",
        texto
    ):
        return True

    return False


def procesar_edicion_contextual(
    mensaje
):
    global ultimo_contexto_edicion

    if ultimo_contexto_edicion is None:
        return respuesta_contexto_faltante(
            mensaje
        )

    tipo = ultimo_contexto_edicion.get(
        "tipo"
    )

    elemento_id = ultimo_contexto_edicion.get(
        "id"
    )

    if tipo == "evento":
        evento = obtener_evento_por_id(
            elemento_id
        )

        if not evento or evento[6] != "activo":
            limpiar_contexto_edicion()
            return (
                "El evento al que te referías "
                "ya no está disponible."
            )

        desplazamiento = extraer_desplazamiento_evento_minutos(
            mensaje
        )

        if desplazamiento is not None:
            mensaje_completo = (
                f"{mensaje} {evento[1]}"
            )

            respuesta = mover_evento_relativamente_desde_mensaje(
                mensaje_completo
            )

            if respuesta.startswith("Listo."):
                guardar_contexto_edicion(
                    "evento",
                    evento[0]
                )

            return respuesta

        fecha_nueva = extraer_fecha_del_mensaje(
            mensaje
        )

        hora_nueva, hora_fin_nueva = extraer_horas_del_mensaje(
            mensaje
        )

        if fecha_nueva or hora_nueva:
            respuesta = aplicar_modificacion_evento(
                evento=evento,
                fecha_nueva=fecha_nueva,
                hora_nueva=hora_nueva,
                hora_fin_nueva=hora_fin_nueva,
            )

            if respuesta.startswith("Listo."):
                guardar_contexto_edicion(
                    "evento",
                    evento[0]
                )

            return respuesta

        return (
            f"Entiendo que te referís a {evento[1]}, "
            f"pero necesito que me digas qué cambio querés hacer."
        )

    if tipo == "recordatorio":
        recordatorio = obtener_recordatorio_por_id(
            elemento_id
        )

        if not recordatorio or recordatorio[4] != "pendiente":
            limpiar_contexto_edicion()
            return (
                "El recordatorio al que te referías "
                "ya no está pendiente."
            )

        mensaje_completo = (
            f"{mensaje} recordatorio #{recordatorio[0]}"
        )

        desplazamiento = extraer_desplazamiento_recordatorio_minutos(
            mensaje_completo
        )

        if desplazamiento is not None:
            respuesta = mover_recordatorio_relativamente_desde_mensaje(
                mensaje_completo
            )

            if respuesta.startswith("Listo."):
                guardar_contexto_edicion(
                    "recordatorio",
                    recordatorio[0]
                )

            return respuesta

        fecha_nueva = extraer_fecha_del_mensaje(
            mensaje
        )

        hora_nueva, _ = extraer_horas_del_mensaje(
            mensaje
        )

        if fecha_nueva or hora_nueva:
            mensaje_completo = (
                f"Cambiá el recordatorio #{recordatorio[0]} "
                f"{mensaje}"
            )

            respuesta = modificar_recordatorio_desde_mensaje(
                mensaje_completo
            )

            if respuesta.startswith("Listo."):
                guardar_contexto_edicion(
                    "recordatorio",
                    recordatorio[0]
                )

            return respuesta

        return (
            f"Entiendo que te referís al recordatorio "
            f"#{recordatorio[0]}: {recordatorio[1]}, "
            f"pero necesito que me digas qué cambio querés hacer."
        )

    limpiar_contexto_edicion()

    return respuesta_contexto_faltante(
        mensaje
    )


def autoriza_creacion_tarea_desde_modelo(
    mensaje
):
    """
    Permite que el modelo cree una tarea solamente cuando
    el propio mensaje de Leo contiene una intención clara
    de agregar algo pendiente.

    Esto evita que frases descriptivas o respuestas copiadas
    se conviertan accidentalmente en tareas.
    """

    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"\btengo que\b",
        r"\bdebo\b",
        r"\bnecesito\b",
        r"\bme falta\b",
        r"\bpendiente\b",
        r"\bagrega(?:me)?(?: una)? tarea\b",
        r"\banota(?:me)?(?: esto)? como tarea\b",
        r"\bcrea(?:me)?(?: una)? tarea\b",
        r"\bpon(?:e|eme)?(?: esto)? como tarea\b",
    )

    return any(
        re.search(
            patron,
            texto
        )
        for patron in patrones
    )


def autoriza_creacion_evento_desde_modelo(
    mensaje
):
    """
    Permite crear eventos desde el modelo solo cuando el
    mensaje expresa claramente que hay que agendar algo.
    """

    texto = normalizar_texto(
        mensaje
    )

    patrones_explicitos = (
        r"\bagrega(?:me)?(?: un)? evento\b",
        r"\banota(?:me)?(?: esto)? como evento\b",
        r"\bcrea(?:me)?(?: un)? evento\b",
        r"\bagenda(?:me)?\b",
        r"\bprograma(?:me)?\b",
    )

    if any(
        re.search(
            patron,
            texto
        )
        for patron in patrones_explicitos
    ):
        return True

    # También permitimos expresiones naturales del tipo
    # "mañana a las 10 tengo dentista".
    tiene_fecha = (
        extraer_fecha_del_mensaje(
            mensaje
        )
        is not None
    )

    tiene_hora = (
        extraer_horas_del_mensaje(
            mensaje
        )[0]
        is not None
    )

    habla_de_compromiso = bool(
        re.search(
            r"\b(tengo|tenemos)\b",
            texto
        )
    )

    return (
        tiene_fecha
        and tiene_hora
        and habla_de_compromiso
    )


# ==========================================================
# COMPRENSIÓN TEMPORAL AVANZADA — DESPLAZAMIENTOS RELATIVOS
# ==========================================================
NUMEROS_TEMPORALES = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
}


def convertir_cantidad_temporal(
    valor
):
    if valor is None:
        return None

    valor_normalizado = normalizar_texto(
        str(valor)
    )

    if valor_normalizado.isdigit():
        return int(
            valor_normalizado
        )

    return NUMEROS_TEMPORALES.get(
        valor_normalizado
    )


def extraer_momento_relativo(
    mensaje
):
    """
    Interpreta expresiones como:
    - dentro de 3 días
    - en dos días
    - de acá a 4 días
    - dentro de 2 horas
    - en 30 minutos

    Devuelve un datetime futuro o None.
    """

    texto = normalizar_texto(
        mensaje
    )

    patron = re.search(
        r"\b(?:dentro\s+de|en|de\s+aca\s+a)\s+"
        r"(\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|"
        r"nueve|diez|once|doce|trece|catorce|quince|veinte|treinta|"
        r"cuarenta|cincuenta|sesenta)\s+"
        r"(minuto|minutos|hora|horas|dia|dias)\b",
        texto
    )

    if not patron:
        return None

    cantidad = convertir_cantidad_temporal(
        patron.group(1)
    )

    if cantidad is None:
        return None

    unidad = patron.group(2)

    ahora = datetime.now()

    if unidad.startswith(
        "minuto"
    ):
        return (
            ahora
            + timedelta(
                minutes=cantidad
            )
        )

    if unidad.startswith(
        "hora"
    ):
        return (
            ahora
            + timedelta(
                hours=cantidad
            )
        )

    return (
        ahora
        + timedelta(
            days=cantidad
        )
    )


def extraer_fecha_relativa_avanzada(
    mensaje
):
    momento = extraer_momento_relativo(
        mensaje
    )

    if momento is None:
        return None

    return momento.date().isoformat()


def extraer_hora_relativa_avanzada(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    momento = extraer_momento_relativo(
        mensaje
    )

    if momento is None:
        return None

    # Para expresiones en días, si además Leo dice una hora explícita,
    # dejamos que la lógica normal de "a las HH:MM" decida la hora.
    if re.search(
        r"\b(?:dentro\s+de|en|de\s+aca\s+a)\s+"
        r"(?:\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|"
        r"nueve|diez|once|doce|trece|catorce|quince|veinte|treinta|"
        r"cuarenta|cincuenta|sesenta)\s+"
        r"(?:dia|dias)\b",
        texto
    ):
        return None

    return momento.strftime(
        "%H:%M"
    )


# ==========================================================
# COMPRENSIÓN TEMPORAL AVANZADA — DÍAS NATURALES
# ==========================================================

def proxima_fecha_dia_mes(
    dia_objetivo
):
    """
    Devuelve la próxima fecha futura cuyo día del mes coincide
    con dia_objetivo. Si ya pasó este mes, busca en el siguiente.
    """

    hoy = date.today()

    anio = hoy.year
    mes = hoy.month

    for _ in range(24):

        try:
            candidata = date(
                anio,
                mes,
                dia_objetivo,
            )

            if candidata >= hoy:
                return candidata.isoformat()

        except ValueError:
            pass

        mes += 1

        if mes > 12:
            mes = 1
            anio += 1

    return None


def proximo_dia_semana_natural(
    numero_dia,
    incluir_hoy=False,
):
    hoy = date.today()

    diferencia = (
        numero_dia
        - hoy.weekday()
    ) % 7

    if diferencia == 0 and not incluir_hoy:
        diferencia = 7

    return (
        hoy
        + timedelta(
            days=diferencia
        )
    ).isoformat()


def extraer_fecha_natural_avanzada(
    mensaje
):
    """
    Interpreta expresiones como:
    - el lunes que viene
    - el próximo viernes
    - este sábado
    - el fin de semana
    - el 15
    """

    texto = normalizar_texto(
        mensaje
    )

    # "el próximo viernes" / "el viernes que viene"
    for nombre, numero in DIAS_SEMANA.items():

        if re.search(
            rf"\b(?:el\s+)?proximo\s+{nombre}\b",
            texto
        ):

            return proximo_dia_semana_natural(
                numero,
                incluir_hoy=False,
            )

        if re.search(
            rf"\b(?:el\s+)?{nombre}\s+que\s+viene\b",
            texto
        ):

            return proximo_dia_semana_natural(
                numero,
                incluir_hoy=False,
            )

        # "este sábado": si hoy es sábado, interpreta hoy.
        if re.search(
            rf"\beste\s+{nombre}\b",
            texto
        ):

            return proximo_dia_semana_natural(
                numero,
                incluir_hoy=True,
            )

    # Para Hermes, "el fin de semana" se interpreta como
    # el sábado más próximo.
    if re.search(
        r"\b(?:el\s+)?fin\s+de\s+semana\b",
        texto
    ):

        return proximo_dia_semana_natural(
            DIAS_SEMANA["sabado"],
            incluir_hoy=True,
        )

    # "el 15", "para el 22", etc.
    coincidencia = re.search(
        r"\b(?:para\s+)?el\s+(\d{1,2})\b",
        texto
    )

    if coincidencia:

        dia_objetivo = int(
            coincidencia.group(1)
        )

        if 1 <= dia_objetivo <= 31:

            return proxima_fecha_dia_mes(
                dia_objetivo
            )

    return None


# ==========================================================
# COMPRENSIÓN TEMPORAL AVANZADA — PERÍODOS NATURALES
# ==========================================================

def primer_dia_mes_siguiente(
    referencia=None
):
    referencia = referencia or date.today()

    if referencia.month == 12:
        return date(
            referencia.year + 1,
            1,
            1,
        )

    return date(
        referencia.year,
        referencia.month + 1,
        1,
    )


def ultimo_dia_mes(
    referencia=None
):
    referencia = referencia or date.today()

    siguiente = primer_dia_mes_siguiente(
        referencia
    )

    return (
        siguiente
        - timedelta(
            days=1
        )
    )


def fecha_mitad_mes_futura():
    hoy = date.today()

    candidata = date(
        hoy.year,
        hoy.month,
        15,
    )

    if candidata >= hoy:
        return candidata.isoformat()

    siguiente = primer_dia_mes_siguiente(
        hoy
    )

    return date(
        siguiente.year,
        siguiente.month,
        15,
    ).isoformat()


def fecha_principio_mes_futura():
    hoy = date.today()

    if hoy.day == 1:
        return hoy.isoformat()

    return primer_dia_mes_siguiente(
        hoy
    ).isoformat()


def fecha_fin_mes_actual():
    return ultimo_dia_mes(
        date.today()
    ).isoformat()


def fecha_semana_que_viene():
    hoy = date.today()

    dias_hasta_lunes = (
        7 - hoy.weekday()
    )

    return (
        hoy
        + timedelta(
            days=dias_hasta_lunes
        )
    ).isoformat()


def fecha_mes_que_viene():
    """
    Interpreta "el mes que viene" como el mismo número de día
    del mes siguiente. Si ese día no existe, usa el último día
    válido del mes siguiente.
    """

    hoy = date.today()
    inicio_siguiente = primer_dia_mes_siguiente(
        hoy
    )

    anio = inicio_siguiente.year
    mes = inicio_siguiente.month
    dia = hoy.day

    while dia >= 1:

        try:
            return date(
                anio,
                mes,
                dia,
            ).isoformat()

        except ValueError:
            dia -= 1

    return inicio_siguiente.isoformat()


def extraer_fecha_periodo_natural(
    mensaje
):
    """
    Interpreta:
    - a principio de mes
    - a mitad de mes
    - a fin de mes
    - la semana que viene / la semana próxima
    - el mes que viene / el próximo mes
    """

    texto = normalizar_texto(
        mensaje
    )

    if re.search(
        r"\b(?:a\s+)?principio\s+de\s+mes\b",
        texto
    ):
        return fecha_principio_mes_futura()

    if re.search(
        r"\b(?:a\s+)?mitad\s+de\s+mes\b",
        texto
    ):
        return fecha_mitad_mes_futura()

    if re.search(
        r"\b(?:a\s+)?fin\s+de\s+mes\b",
        texto
    ):
        return fecha_fin_mes_actual()

    if re.search(
        r"\b(?:la\s+)?semana\s+que\s+viene\b"
        r"|\b(?:la\s+)?semana\s+proxima\b",
        texto
    ):
        return fecha_semana_que_viene()

    if re.search(
        r"\b(?:el\s+)?mes\s+que\s+viene\b"
        r"|\b(?:el\s+)?proximo\s+mes\b",
        texto
    ):
        return fecha_mes_que_viene()

    return None


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
    texto = normalizar_texto(
        original
    )

    hoy = date.today()

    if texto in (
        "hoy",
        "para hoy",
    ):
        return hoy.isoformat()

    if texto in (
        "manana",
        "para manana",
    ):
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


def extraer_fecha_del_mensaje(
    mensaje
):
    fecha_relativa = extraer_fecha_relativa_avanzada(
        mensaje
    )

    if fecha_relativa:
        return fecha_relativa

    fecha_periodo = extraer_fecha_periodo_natural(
        mensaje
    )

    if fecha_periodo:
        return fecha_periodo

    fecha_natural = extraer_fecha_natural_avanzada(
        mensaje
    )

    if fecha_natural:
        return fecha_natural

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


def fecha_para_mostrar(
    fecha_iso
):
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
# COMPRENSIÓN TEMPORAL AVANZADA — PARTES DEL DÍA
# ==========================================================
HORAS_PARTES_DIA = {
    "manana": "09:00",
    "mediodia": "12:00",
    "tarde": "17:00",
    "noche": "21:00",
}


def extraer_hora_parte_dia(
    mensaje
):
    """
    Interpreta expresiones vagas de hora usando valores
    predeterminados consistentes:

    - mañana / por la mañana -> 09:00
    - mediodía -> 12:00
    - tarde / por la tarde -> 17:00
    - noche / por la noche -> 21:00

    La palabra "mañana" como fecha no se confunde con
    "a la mañana" o "por la mañana".
    """

    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        (
            r"\b(?:a\s+la|por\s+la)\s+manana\b",
            HORAS_PARTES_DIA["manana"],
        ),
        (
            r"\b(?:al|a\s+el|por\s+el)\s+mediodia\b"
            r"|\bmediodia\b",
            HORAS_PARTES_DIA["mediodia"],
        ),
        (
            r"\b(?:a\s+la|por\s+la|esta)\s+tarde\b",
            HORAS_PARTES_DIA["tarde"],
        ),
        (
            r"\b(?:a\s+la|por\s+la|esta)\s+noche\b",
            HORAS_PARTES_DIA["noche"],
        ),
    )

    for patron, hora in patrones:

        if re.search(
            patron,
            texto
        ):
            return hora

    return None


# ==========================================================
# HORAS
# ==========================================================

def extraer_horas_del_mensaje(
    mensaje
):
    hora_relativa = extraer_hora_relativa_avanzada(
        mensaje
    )

    if hora_relativa:
        return (
            hora_relativa,
            None,
        )

    hora_parte_dia = extraer_hora_parte_dia(
        mensaje
    )

    if hora_parte_dia:
        return (
            hora_parte_dia,
            None,
        )

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

        if not (
            0 <= h1 <= 23
            and 0 <= h2 <= 23
            and 0 <= m1 <= 59
            and 0 <= m2 <= 59
        ):
            return None, None

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

        if not (
            0 <= hora <= 23
            and 0 <= minuto <= 59
        ):
            return None, None

        return (
            f"{hora:02d}:{minuto:02d}",
            None,
        )

    return None, None


# ==========================================================
# BÚSQUEDA
# ==========================================================

PALABRAS_VACIAS = {
    "a",
    "al",
    "antes",
    "aviso",
    "avisos",
    "avisame",
    "cambia",
    "cambiar",
    "cambialo",
    "cambiala",
    "cancela",
    "cancelar",
    "con",
    "de",
    "del",
    "el",
    "en",
    "evento",
    "hora",
    "horas",
    "la",
    "las",
    "los",
    "mi",
    "minuto",
    "minutos",
    "modifica",
    "modificar",
    "move",
    "mover",
    "muevelo",
    "muevela",
    "para",
    "pasa",
    "pasalo",
    "pasala",
    "recordame",
    "recordatorio",
    "recordatorios",
    "recuerdame",
    "saca",
    "sacar",
    "solo",
    "dejame",
}


def palabras_importantes(
    texto
):
    texto = normalizar_texto(
        texto
    )

    palabras = re.findall(
        r"[a-z0-9]+",
        texto
    )

    return {
        palabra
        for palabra in palabras
        if palabra not in PALABRAS_VACIAS
        and palabra not in DIAS_SEMANA
        and len(palabra) >= 3
        and not palabra.isdigit()
    }


def puntuacion_coincidencia(
    mensaje,
    titulo
):
    mensaje_normalizado = normalizar_texto(
        mensaje
    )

    titulo_normalizado = normalizar_texto(
        titulo
    )

    puntuacion = 0

    if titulo_normalizado in mensaje_normalizado:

        puntuacion += 100

    palabras_titulo = palabras_importantes(
        titulo
    )

    palabras_mensaje = palabras_importantes(
        mensaje
    )

    puntuacion += (
        len(
            palabras_titulo
            & palabras_mensaje
        )
        * 20
    )

    return puntuacion


# ==========================================================
# ANTICIPACIÓN
# ==========================================================

def descripcion_anticipacion(
    minutos
):
    if minutos is None:

        return (
            "anticipación desconocida"
        )

    if minutos % 1440 == 0:

        dias = minutos // 1440

        return (
            f"{dias} "
            f"{'día' if dias == 1 else 'días'}"
        )

    if minutos % 60 == 0:

        horas = minutos // 60

        return (
            f"{horas} "
            f"{'hora' if horas == 1 else 'horas'}"
        )

    return (
        f"{minutos} "
        f"{'minuto' if minutos == 1 else 'minutos'}"
    )


def extraer_anticipacion_simple(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if "media hora" in texto:
        return 30

    if re.search(
        r"\b(?:una|un)\s+hora\b",
        texto
    ):
        return 60

    if re.search(
        r"\b(?:un|una)\s+dia\b",
        texto
    ):
        return 1440

    coincidencia = re.search(
        r"\b(\d+)\s*"
        r"(minuto|minutos|hora|horas|dia|dias)\b",
        texto
    )

    if not coincidencia:
        return None

    cantidad = int(
        coincidencia.group(1)
    )

    unidad = coincidencia.group(2)

    if unidad.startswith(
        "minuto"
    ):
        return cantidad

    if unidad.startswith(
        "hora"
    ):
        return cantidad * 60

    return cantidad * 1440


def extraer_todas_las_anticipaciones(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    resultados = []

    patrones_especiales = [
        (
            r"\bmedia\s+hora\b",
            30,
        ),
        (
            r"\b(?:una|un)\s+hora\b",
            60,
        ),
        (
            r"\b(?:un|una)\s+dia\b",
            1440,
        ),
    ]

    ocupados = []

    for patron, minutos in patrones_especiales:

        for coincidencia in re.finditer(
            patron,
            texto
        ):

            resultados.append(
                (
                    coincidencia.start(),
                    minutos,
                )
            )

            ocupados.append(
                (
                    coincidencia.start(),
                    coincidencia.end(),
                )
            )

    patron_numerico = re.compile(
        r"\b(\d+)\s*"
        r"(minuto|minutos|hora|horas|dia|dias)\b"
    )

    for coincidencia in patron_numerico.finditer(
        texto
    ):

        inicio = coincidencia.start()
        fin = coincidencia.end()

        solapa = any(
            inicio < fin_ocupado
            and fin > inicio_ocupado
            for inicio_ocupado, fin_ocupado
            in ocupados
        )

        if solapa:
            continue

        cantidad = int(
            coincidencia.group(1)
        )

        unidad = coincidencia.group(2)

        if unidad.startswith(
            "minuto"
        ):
            minutos = cantidad

        elif unidad.startswith(
            "hora"
        ):
            minutos = cantidad * 60

        else:
            minutos = cantidad * 1440

        resultados.append(
            (
                inicio,
                minutos,
            )
        )

    resultados.sort(
        key=lambda elemento: elemento[0]
    )

    return [
        minutos
        for _, minutos
        in resultados
    ]


def es_creacion_evento_natural(
    mensaje
):
    """
    Detecta compromisos expresados de forma natural, por ejemplo:
    "Dentro de 3 días a las 16 tengo una reunión".
    """

    texto = normalizar_texto(
        mensaje
    )

    # "Tengo que..." se reserva para tareas, no para eventos.
    if re.search(
        r"\btengo\s+que\b",
        texto
    ):
        return False

    habla_de_compromiso = bool(
        re.search(
            r"\b(?:tengo|tenemos)\b",
            texto
        )
    )

    if not habla_de_compromiso:
        return False

    fecha = extraer_fecha_del_mensaje(
        mensaje
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    return (
        fecha is not None
        and hora is not None
    )


def extraer_titulo_evento_natural(
    mensaje
):
    texto = mensaje.strip()

    coincidencia = re.search(
        r"\b(?:tengo|tenemos)\b\s+(.*)$",
        texto,
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return None

    titulo = coincidencia.group(1).strip()

    titulo = re.sub(
        r"^(?:un|una|el|la)\s+",
        "",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\b(?:dura|durante|por)\s+media\s+hora\b",
        "",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\b(?:dura|durante|por)\s+(?:una|un)\s+hora\b",
        "",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\b(?:dura|durante|por)\s+\d+\s*"
        r"(?:minuto|minutos|hora|horas)\b",
        "",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\s+",
        " ",
        titulo,
    ).strip(" .,-")

    if not titulo:
        return None

    return (
        titulo[0].upper()
        + titulo[1:]
    )


def crear_evento_natural_desde_mensaje(
    mensaje
):
    fecha = extraer_fecha_del_mensaje(
        mensaje
    )

    hora_inicio, hora_fin = extraer_horas_del_mensaje(
        mensaje
    )

    duracion_minutos = extraer_duracion_evento_minutos(
        mensaje
    )

    if (
        hora_inicio
        and hora_fin is None
        and duracion_minutos is not None
    ):
        hora_fin = calcular_hora_fin_por_duracion(
            fecha,
            hora_inicio,
            duracion_minutos,
        )

    titulo = extraer_titulo_evento_natural(
        mensaje
    )

    if not fecha:
        return (
            "Necesito una fecha para crear el evento."
        )

    if not hora_inicio:
        return (
            "Necesito una hora para crear el evento."
        )

    if not titulo:
        return (
            "Entendí cuándo es el evento, pero no qué evento querés agendar."
        )

    momento = datetime.fromisoformat(
        f"{fecha}T{hora_inicio}:00"
    )

    if momento <= datetime.now():
        return (
            "Ese momento ya pasó."
        )

    evento_id = crear_evento(
        titulo=titulo,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        descripcion="",
    )

    respuesta = (
        f"Listo. Agregué el evento "
        f"#{evento_id}: {titulo} para "
        f"{fecha_para_mostrar(fecha)} "
        f"a las {hora_inicio}"
    )

    if hora_fin:
        respuesta += (
            f" hasta las {hora_fin}"
        )

    respuesta += "."

    return respuesta


# ==========================================================
# DURACIÓN DE EVENTOS — DURACIÓN NATURAL
# ==========================================================

def extraer_duracion_evento_minutos(
    mensaje
):
    """
    Interpreta duraciones naturales como:
    - por 2 horas
    - durante 90 minutos
    - dura una hora
    - dura media hora
    """

    texto = normalizar_texto(
        mensaje
    )

    if re.search(
        r"\b(?:dura|durante|por)\s+media\s+hora\b",
        texto
    ):
        return 30

    if re.search(
        r"\b(?:dura|durante|por)\s+(?:una|un)\s+hora\b",
        texto
    ):
        return 60

    coincidencia = re.search(
        r"\b(?:dura|durante|por)\s+"
        r"(\d+)\s*"
        r"(minuto|minutos|hora|horas)\b",
        texto
    )

    if not coincidencia:
        return None

    cantidad = int(
        coincidencia.group(1)
    )

    unidad = coincidencia.group(2)

    if unidad.startswith(
        "hora"
    ):
        return cantidad * 60

    return cantidad


def calcular_hora_fin_por_duracion(
    fecha_iso,
    hora_inicio,
    duracion_minutos,
):
    if not fecha_iso or not hora_inicio or duracion_minutos is None:
        return None

    inicio = datetime.fromisoformat(
        f"{fecha_iso}T{hora_inicio}:00"
    )

    fin = (
        inicio
        + timedelta(
            minutes=duracion_minutos
        )
    )

    return fin.strftime(
        "%H:%M"
    )


# ==========================================================
# EVENTOS
# ==========================================================

def buscar_evento_desde_mensaje(
    mensaje
):
    eventos = obtener_eventos_activos()

    candidatos = []

    for evento in eventos:

        puntuacion = puntuacion_coincidencia(
            mensaje,
            evento[1]
        )

        if puntuacion > 0:

            candidatos.append(
                (
                    puntuacion,
                    evento,
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda elemento: (
            -elemento[0],
            elemento[1][3],
            elemento[1][4] or "99:99",
        )
    )

    return candidatos[0][1]


# ==========================================================
# CONSULTAR AVISOS DE UN EVENTO
# ==========================================================

def es_consulta_avisos_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    tiene_aviso = (
        "aviso" in texto
        or "avisos" in texto
        or "recordatorio" in texto
        or "recordatorios" in texto
    )

    return (
        tiene_aviso
        and any(
            patron in texto
            for patron in (
                "que aviso",
                "que avisos",
                "que recordatorio",
                "que recordatorios",
                "avisos tiene",
                "recordatorios tiene",
            )
        )
    )


def mostrar_avisos_de_evento(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar "
            "de qué evento querés "
            "ver los avisos."
        )

    recordatorios = obtener_recordatorios_de_evento(
        evento[0]
    )

    if not recordatorios:

        return (
            f"{evento[1]} no tiene "
            f"avisos pendientes."
        )

    lineas = [
        f"Los avisos de {evento[1]} son:"
    ]

    for recordatorio in recordatorios:

        lineas.append(
            f"- #{recordatorio[0]}: "
            f"{descripcion_anticipacion(recordatorio[6])} antes"
        )

    return "\n".join(
        lineas
    )


# ==========================================================
# SACAR AVISO DE UN EVENTO
# ==========================================================

def es_eliminar_aviso_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    tiene_aviso = (
        "aviso" in texto
        or "recordatorio" in texto
    )

    accion = any(
        palabra in texto
        for palabra in (
            "saca",
            "sacar",
            "elimina",
            "eliminar",
            "borra",
            "borrar",
            "quita",
            "quitar",
        )
    )

    return (
        tiene_aviso
        and accion
    )


def eliminar_aviso_evento_desde_mensaje(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar "
            "de qué evento querés "
            "sacar el aviso."
        )

    anticipacion = extraer_anticipacion_simple(
        mensaje
    )

    recordatorios = obtener_recordatorios_de_evento(
        evento[0]
    )

    if not recordatorios:

        return (
            f"{evento[1]} no tiene "
            f"avisos pendientes."
        )

    if anticipacion is None:

        if len(recordatorios) == 1:

            recordatorio = recordatorios[0]

            cancelar_recordatorio(
                recordatorio[0]
            )

            return (
                f"Listo. Saqué el aviso "
                f"#{recordatorio[0]} de "
                f"{evento[1]}."
            )

        opciones = ", ".join(
            descripcion_anticipacion(
                recordatorio[6]
            )
            for recordatorio in recordatorios
        )

        return (
            f"{evento[1]} tiene varios avisos: "
            f"{opciones}. "
            f"Decime cuál querés sacar."
        )

    coincidencias = [
        recordatorio
        for recordatorio in recordatorios
        if recordatorio[6] == anticipacion
    ]

    if not coincidencias:

        return (
            f"{evento[1]} no tiene "
            f"un aviso de "
            f"{descripcion_anticipacion(anticipacion)}."
        )

    if len(coincidencias) > 1:

        ids = ", ".join(
            f"#{recordatorio[0]}"
            for recordatorio in coincidencias
        )

        return (
            f"Encontré más de un aviso "
            f"de {descripcion_anticipacion(anticipacion)}: "
            f"{ids}. "
            f"Decime cuál querés eliminar."
        )

    recordatorio = coincidencias[0]

    cancelar_recordatorio(
        recordatorio[0]
    )

    return (
        f"Listo. Saqué el aviso "
        f"#{recordatorio[0]} de "
        f"{descripcion_anticipacion(anticipacion)} "
        f"antes de {evento[1]}."
    )


# ==========================================================
# CAMBIAR ANTICIPACIÓN DE UN AVISO
# ==========================================================

def es_cambio_anticipacion_aviso(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    tiene_aviso = (
        "aviso" in texto
        or "recordatorio" in texto
    )

    accion = any(
        palabra in texto
        for palabra in (
            "cambia",
            "cambiar",
            "cambialo",
            "modifica",
            "modificar",
            "reemplaza",
            "reemplazar",
        )
    )

    return (
        tiene_aviso
        and accion
        and len(
            extraer_todas_las_anticipaciones(
                mensaje
            )
        ) >= 2
    )


def cambiar_anticipacion_aviso_desde_mensaje(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar "
            "de qué evento querés "
            "cambiar el aviso."
        )

    anticipaciones = extraer_todas_las_anticipaciones(
        mensaje
    )

    if len(anticipaciones) < 2:

        return (
            "Necesito saber la anticipación "
            "actual y la nueva. "
            "Por ejemplo: "
            "'Cambiá el aviso de 15 minutos "
            "por uno de 30 minutos'."
        )

    anterior = anticipaciones[0]
    nueva = anticipaciones[1]

    if anterior == nueva:

        return (
            "La anticipación nueva "
            "es igual a la actual."
        )

    recordatorios = obtener_recordatorios_de_evento(
        evento[0]
    )

    coincidencias = [
        recordatorio
        for recordatorio in recordatorios
        if recordatorio[6] == anterior
    ]

    if not coincidencias:

        return (
            f"{evento[1]} no tiene "
            f"un aviso de "
            f"{descripcion_anticipacion(anterior)}."
        )

    if len(coincidencias) > 1:

        return (
            f"Hay más de un aviso de "
            f"{descripcion_anticipacion(anterior)}. "
            f"Necesito que me indiques "
            f"el número del recordatorio."
        )

    for recordatorio in recordatorios:

        if (
            recordatorio[6] == nueva
            and recordatorio[0]
            != coincidencias[0][0]
        ):

            return (
                f"Ya existe un aviso de "
                f"{descripcion_anticipacion(nueva)} "
                f"para {evento[1]}."
            )

    momento_evento = datetime.fromisoformat(
        f"{evento[3]}T{evento[4]}:00"
    )

    momento_aviso = (
        momento_evento
        - timedelta(
            minutes=nueva
        )
    )

    if momento_aviso <= datetime.now():

        return (
            "Ese nuevo aviso quedaría "
            "en un momento que ya pasó."
        )

    recordatorio = coincidencias[0]

    mensaje_recordatorio = (
        f"En {descripcion_anticipacion(nueva)} "
        f"tenés {evento[1]}."
    )

    estado, resultado_id = (
        actualizar_recordatorio_vinculado(
            recordatorio_id=recordatorio[0],
            nueva_fecha_hora=(
                momento_aviso
                .replace(microsecond=0)
                .isoformat()
            ),
            anticipacion_minutos=nueva,
            nuevo_mensaje=mensaje_recordatorio,
        )
    )

    if estado == "duplicado":

        return (
            f"Ya existe ese aviso "
            f"como #{resultado_id}."
        )

    if estado != "actualizado":

        return (
            "No pude modificar "
            "ese aviso."
        )

    return (
        f"Listo. Cambié el aviso "
        f"#{recordatorio[0]} de "
        f"{descripcion_anticipacion(anterior)} "
        f"a {descripcion_anticipacion(nueva)} "
        f"antes de {evento[1]}."
    )


# ==========================================================
# DEJAR SOLO UN AVISO
# ==========================================================

def es_dejar_solo_aviso(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        (
            "dejame solo" in texto
            or "deja solo" in texto
            or "dejar solo" in texto
            or "dejame solamente" in texto
        )
        and (
            "aviso" in texto
            or "recordatorio" in texto
        )
    )


def dejar_solo_aviso_desde_mensaje(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar "
            "de qué evento estás hablando."
        )

    anticipacion = extraer_anticipacion_simple(
        mensaje
    )

    if anticipacion is None:

        return (
            "Necesito saber cuál aviso "
            "querés conservar."
        )

    recordatorios = obtener_recordatorios_de_evento(
        evento[0]
    )

    if not recordatorios:

        return (
            f"{evento[1]} no tiene "
            f"avisos pendientes."
        )

    conservar = [
        recordatorio
        for recordatorio in recordatorios
        if recordatorio[6] == anticipacion
    ]

    if not conservar:

        return (
            f"{evento[1]} no tiene "
            f"un aviso de "
            f"{descripcion_anticipacion(anticipacion)}."
        )

    if len(conservar) > 1:

        return (
            f"Hay más de un aviso de "
            f"{descripcion_anticipacion(anticipacion)}. "
            f"Necesito que me indiques "
            f"cuál querés conservar."
        )

    conservado_id = conservar[0][0]
    cancelados = 0

    for recordatorio in recordatorios:

        if recordatorio[0] == conservado_id:
            continue

        estado, _ = cancelar_recordatorio(
            recordatorio[0]
        )

        if estado == "cancelado":
            cancelados += 1

    return (
        f"Listo. Dejé solamente "
        f"el aviso #{conservado_id} de "
        f"{descripcion_anticipacion(anticipacion)} "
        f"antes de {evento[1]}. "
        f"Cancelé {cancelados} "
        f"{'aviso' if cancelados == 1 else 'avisos'} adicional"
        f"{'' if cancelados == 1 else 'es'}."
    )


# ==========================================================
# RECORDATORIOS NORMALES
# ==========================================================

def es_consulta_recordatorios(
    mensaje
):
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


def es_orden_recordatorio(
    mensaje
):
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


def extraer_titulo_recordatorio(
    mensaje
):
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
        r"\b(?:dentro\s+de|en|de\s+acá\s+a)\s+"
        r"(?:\d+|un|una|uno|dos|tres|cuatro|cinco|seis|siete|ocho|"
        r"nueve|diez|once|doce|trece|catorce|quince|veinte|treinta|"
        r"cuarenta|cincuenta|sesenta)\s+"
        r"(?:minuto|minutos|hora|horas|día|dias|días)\b",
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
        r"\b(?:el\s+)?próximo\s+"
        r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:el\s+)?"
        r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)"
        r"\s+que\s+viene\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\beste\s+"
        r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:el\s+)?fin\s+de\s+semana\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:para\s+)?el\s+\d{1,2}\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:a\s+)?(?:principio|mitad|fin)\s+de\s+mes\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:la\s+)?semana\s+(?:que\s+viene|próxima|proxima)\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:el\s+)?(?:mes\s+que\s+viene|próximo\s+mes|proximo\s+mes)\b",
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
        r"\b(?:a\s+la|por\s+la)\s+mañana\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:al|a\s+el|por\s+el)?\s*mediodía\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:a\s+la|por\s+la|esta)\s+tarde\b",
        "",
        texto,
        flags=re.IGNORECASE
    )

    texto = re.sub(
        r"\b(?:a\s+la|por\s+la|esta)\s+noche\b",
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

        return (
            "Recordatorio de Hermes"
        )

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

    momento = datetime.fromisoformat(
        f"{fecha}T{hora}:00"
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
            titulo,
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
    recordatorios = obtener_recordatorios_pendientes()

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
        fecha_hora,
    ) in recordatorios:

        try:

            momento = datetime.fromisoformat(
                fecha_hora
            )

            lineas.append(
                f"{recordatorio_id}. "
                f"{titulo} — "
                f"{fecha_para_mostrar(momento.date().isoformat())} "
                f"a las {momento.strftime('%H:%M')}"
            )

        except ValueError:

            lineas.append(
                f"{recordatorio_id}. "
                f"{titulo}"
            )

    return "\n".join(
        lineas
    )


def buscar_recordatorios_candidatos(
    mensaje
):
    recordatorios = obtener_recordatorios_pendientes()

    candidatos = []

    for recordatorio in recordatorios:

        puntuacion = puntuacion_coincidencia(
            mensaje,
            recordatorio[1]
        )

        if puntuacion <= 0:
            continue

        completo = obtener_recordatorio_por_id(
            recordatorio[0]
        )

        if completo:

            candidatos.append(
                (
                    puntuacion,
                    completo,
                )
            )

    if not candidatos:
        return []

    puntuacion_maxima = max(
        candidato[0]
        for candidato in candidatos
    )

    mejores = [
        candidato[1]
        for candidato in candidatos
        if candidato[0] == puntuacion_maxima
    ]

    mejores.sort(
        key=lambda recordatorio: (
            recordatorio[3],
            recordatorio[0],
        )
    )

    return mejores


def buscar_recordatorio_desde_mensaje(
    mensaje
):
    candidatos = buscar_recordatorios_candidatos(
        mensaje
    )

    if not candidatos:
        return None

    recordatorio = candidatos[0]

    return (
        recordatorio[0],
        recordatorio[1],
        recordatorio[2],
        recordatorio[3],
    )


# ==========================================================
# CANCELAR RECORDATORIOS
# ==========================================================

def es_cancelacion_recordatorio(
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
                "cancela",
                "cancelar",
                "elimina",
                "eliminar",
                "borra",
                "borrar",
            )
        )
    )


def cancelar_un_recordatorio(
    recordatorio
):
    recordatorio_id = recordatorio[0]

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

    if estado == "no_existe":

        return (
            f"No encontré el recordatorio "
            f"#{recordatorio_id}."
        )

    return (
        f"Listo. Cancelé el recordatorio "
        f"#{recordatorio_id}: "
        f"{recordatorio[1]}."
    )


def cancelar_recordatorio_desde_mensaje(
    mensaje
):
    global confirmacion_pendiente

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

        recordatorio = obtener_recordatorio_por_id(
            recordatorio_id
        )

        if not recordatorio:

            return (
                f"No encontré el recordatorio "
                f"#{recordatorio_id}."
            )

        return cancelar_un_recordatorio(
            recordatorio
        )

    candidatos = buscar_recordatorios_candidatos(
        mensaje
    )

    if not candidatos:

        return (
            "No pude identificar qué "
            "recordatorio querés cancelar."
        )

    if len(candidatos) == 1:

        return cancelar_un_recordatorio(
            candidatos[0]
        )

    confirmacion_pendiente = {
        "tipo": "cancelar_recordatorio_ambiguo",
        "recordatorios": candidatos,
    }

    titulo = candidatos[0][1]

    lineas = [
        f"Tenés varios recordatorios "
        f"para {titulo}:"
    ]

    for recordatorio in candidatos:

        anticipacion = recordatorio[6]

        if anticipacion is not None:

            detalle = (
                f"{descripcion_anticipacion(anticipacion)} "
                f"antes"
            )

        else:

            try:

                momento = datetime.fromisoformat(
                    recordatorio[3]
                )

                detalle = (
                    f"{fecha_para_mostrar(momento.date().isoformat())} "
                    f"a las {momento.strftime('%H:%M')}"
                )

            except ValueError:

                detalle = recordatorio[3]

        lineas.append(
            f"- #{recordatorio[0]}: "
            f"{detalle}"
        )

    lineas.append("")
    lineas.append(
        "¿Cuál querés cancelar?"
    )

    return "\n".join(
        lineas
    )


def procesar_cancelacion_recordatorio_ambiguo(
    mensaje,
    pendiente
):
    global confirmacion_pendiente

    texto = normalizar_texto(
        mensaje
    )

    recordatorios = pendiente[
        "recordatorios"
    ]

    if any(
        expresion in texto
        for expresion in (
            "ninguno",
            "ninguna",
            "dejalo",
            "dejala",
            "deja",
            "olvidalo",
            "olvidala",
            "olvida",
            "no importa",
            "no gracias",
        )
    ):

        confirmacion_pendiente = None

        return (
            "Perfecto. No cancelé ninguno."
        )

    anticipacion = extraer_anticipacion_simple(
        mensaje
    )

    if anticipacion is not None:

        coincidencias = [
            recordatorio
            for recordatorio in recordatorios
            if recordatorio[6] == anticipacion
        ]

        if len(coincidencias) == 1:

            confirmacion_pendiente = None

            return cancelar_un_recordatorio(
                coincidencias[0]
            )

        if len(coincidencias) > 1:

            opciones = ", ".join(
                f"#{recordatorio[0]}"
                for recordatorio in coincidencias
            )

            return (
                f"Hay más de un aviso con "
                f"{descripcion_anticipacion(anticipacion)} "
                f"de anticipación: "
                f"{opciones}. "
                f"Decime el número."
            )

        return (
            f"No encontré entre esas opciones "
            f"un aviso de "
            f"{descripcion_anticipacion(anticipacion)}."
        )

    coincidencia_id = re.fullmatch(
        r"\s*(?:"
        r"recordatorio\s*#?\s*"
        r"|#\s*"
        r")?(\d+)\s*",
        texto
    )

    if not coincidencia_id:

        coincidencia_id = re.search(
            r"\brecordatorio\s*#?\s*(\d+)\b",
            texto
        )

    if not coincidencia_id:

        coincidencia_id = re.search(
            r"#\s*(\d+)\b",
            texto
        )

    if coincidencia_id:

        recordatorio_id = int(
            coincidencia_id.group(1)
        )

        for recordatorio in recordatorios:

            if recordatorio[0] == recordatorio_id:

                confirmacion_pendiente = None

                return cancelar_un_recordatorio(
                    recordatorio
                )

        opciones = ", ".join(
            f"#{recordatorio[0]}"
            for recordatorio in recordatorios
        )

        return (
            f"Ese no es uno de los "
            f"recordatorios que estaba "
            f"comparando. "
            f"Las opciones son: "
            f"{opciones}."
        )

    return (
        "No pude saber cuál elegiste. "
        "Podés decir, por ejemplo, "
        "'el de 15 minutos', "
        "'el de una hora', "
        "'el recordatorio 8' o '#8'."
    )


# ==========================================================
# MODIFICAR RECORDATORIOS NORMALES
# ==========================================================

def extraer_desplazamiento_recordatorio_minutos(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if "recordatorio" not in texto:
        return None

    acciones = (
        "mover",
        "mueve",
        "move",
        "muevelo",
        "muevela",
        "pasalo",
        "pasala",
        "pasa",
        "correr",
        "corre",
        "correlo",
        "correla",
        "retrasa",
        "retrasalo",
        "retrasala",
        "adelanta",
        "adelantalo",
        "adelantala",
    )

    if not any(
        accion in texto
        for accion in acciones
    ):
        return None

    minutos = None

    if "media hora" in texto:
        minutos = 30

    elif re.search(
        r"\b(?:una|un)\s+hora\b",
        texto
    ):
        minutos = 60

    else:
        coincidencia = re.search(
            r"\b(\d+)\s*"
            r"(minuto|minutos|hora|horas)\b",
            texto
        )

        if coincidencia:
            cantidad = int(
                coincidencia.group(1)
            )

            unidad = coincidencia.group(2)

            if unidad.startswith(
                "hora"
            ):
                minutos = cantidad * 60

            else:
                minutos = cantidad

    if minutos is None:
        return None

    hacia_antes = any(
        expresion in texto
        for expresion in (
            " mas temprano",
            " antes",
            "adelanta",
            "adelantalo",
            "adelantala",
        )
    )

    hacia_despues = any(
        expresion in texto
        for expresion in (
            " mas tarde",
            " despues",
            "retrasa",
            "retrasalo",
            "retrasala",
        )
    )

    if hacia_antes:
        return -minutos

    if hacia_despues:
        return minutos

    if any(
        accion in texto
        for accion in (
            "correr",
            "corre",
            "correlo",
            "correla",
        )
    ):
        return minutos

    return None


def es_desplazamiento_relativo_recordatorio(
    mensaje
):
    return (
        extraer_desplazamiento_recordatorio_minutos(
            mensaje
        )
        is not None
    )


def obtener_recordatorio_objetivo_para_edicion(
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

        actual = obtener_recordatorio_por_id(
            recordatorio_id
        )

        if actual:
            return actual, None

        return None, (
            f"No encontré el recordatorio "
            f"#{recordatorio_id}."
        )

    candidatos = buscar_recordatorios_candidatos(
        mensaje
    )

    if not candidatos:
        return None, (
            "No pude identificar qué "
            "recordatorio querés modificar."
        )

    if len(candidatos) > 1:
        opciones = []

        for recordatorio in candidatos:
            try:
                momento = datetime.fromisoformat(
                    recordatorio[3]
                )
                detalle = (
                    f"{fecha_para_mostrar(momento.date().isoformat())} "
                    f"a las {momento.strftime('%H:%M')}"
                )
            except ValueError:
                detalle = recordatorio[3]

            opciones.append(
                f"#{recordatorio[0]} ({detalle})"
            )

        return None, (
            "Encontré varios recordatorios posibles: "
            + ", ".join(opciones)
            + ". Decime el número del que querés modificar."
        )

    return candidatos[0], None


def validar_recordatorio_editable_independientemente(
    recordatorio
):
    evento_id = recordatorio[5]

    if evento_id is None:
        return None

    evento = obtener_evento_por_id(
        evento_id
    )

    if evento:
        return (
            f"Ese recordatorio está vinculado al evento "
            f"{evento[1]}. Para mantenerlos sincronizados, "
            f"mové el evento o cambiá la anticipación del aviso."
        )

    return (
        "Ese recordatorio está vinculado a un evento. "
        "Para mantener la sincronización, modificá el evento "
        "o la anticipación del aviso."
    )


def mover_recordatorio_relativamente_desde_mensaje(
    mensaje
):
    actual, error = obtener_recordatorio_objetivo_para_edicion(
        mensaje
    )

    if error:
        return error

    bloqueo = validar_recordatorio_editable_independientemente(
        actual
    )

    if bloqueo:
        return bloqueo

    desplazamiento = extraer_desplazamiento_recordatorio_minutos(
        mensaje
    )

    if desplazamiento is None:
        return (
            "No pude interpretar cuánto tiempo "
            "querés mover el recordatorio."
        )

    momento_actual = datetime.fromisoformat(
        actual[3]
    )

    momento_nuevo = (
        momento_actual
        + timedelta(
            minutes=desplazamiento
        )
    )

    if momento_nuevo <= datetime.now():
        return (
            "El nuevo momento del recordatorio "
            "ya pasó."
        )

    estado, resultado_id = modificar_recordatorio(
        actual[0],
        momento_nuevo.replace(
            microsecond=0
        ).isoformat()
    )

    if estado == "duplicado":
        return (
            f"Ya existe un recordatorio "
            f"igual como #{resultado_id}."
        )

    if estado == "no_pendiente":
        return (
            f"El recordatorio #{actual[0]} "
            f"ya no está pendiente."
        )

    cantidad = abs(
        desplazamiento
    )

    direccion = (
        "más tarde"
        if desplazamiento > 0
        else "más temprano"
    )

    return (
        f"Listo. Moví el recordatorio "
        f"#{actual[0]}: {actual[1]} a "
        f"{fecha_para_mostrar(momento_nuevo.date().isoformat())} "
        f"a las {momento_nuevo.strftime('%H:%M')}. "
        f"Lo moví {descripcion_anticipacion(cantidad)} "
        f"{direccion}."
    )


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
                "move",
                "mover",
                "pasa",
                "pasalo",
                "pasala",
                "corre",
                "correr",
                "correlo",
                "correla",
            )
        )
    )


def modificar_recordatorio_desde_mensaje(
    mensaje
):
    actual, error = obtener_recordatorio_objetivo_para_edicion(
        mensaje
    )

    if error:
        return error

    bloqueo = validar_recordatorio_editable_independientemente(
        actual
    )

    if bloqueo:
        return bloqueo

    recordatorio_id = actual[0]

    fecha_nueva = extraer_fecha_del_mensaje(
        mensaje
    )

    hora_nueva, _ = extraer_horas_del_mensaje(
        mensaje
    )

    momento_actual = datetime.fromisoformat(
        actual[3]
    )

    fecha_final = (
        fecha_nueva
        if fecha_nueva
        else momento_actual.date().isoformat()
    )

    hora_final = (
        hora_nueva
        if hora_nueva
        else momento_actual.strftime("%H:%M")
    )

    momento_nuevo = datetime.fromisoformat(
        f"{fecha_final}T{hora_final}:00"
    )

    if momento_nuevo <= datetime.now():

        return (
            "La nueva fecha y hora "
            "ya pasaron."
        )

    estado, resultado_id = modificar_recordatorio(
        recordatorio_id,
        momento_nuevo.isoformat()
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
# AVISO RELATIVO A EVENTO
# ==========================================================

def es_recordatorio_relativo_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        es_orden_recordatorio(
            mensaje
        )
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
        return 30

    if re.search(
        r"\b(?:una|un)\s+hora\s+antes\b",
        texto
    ):
        return 60

    coincidencia = re.search(
        r"\b(\d+)\s*"
        r"(minuto|minutos|hora|horas|dia|dias)"
        r"\s+antes\b",
        texto
    )

    if not coincidencia:
        return None

    cantidad = int(
        coincidencia.group(1)
    )

    unidad = coincidencia.group(2)

    if unidad.startswith(
        "minuto"
    ):
        return cantidad

    if unidad.startswith(
        "hora"
    ):
        return cantidad * 60

    return cantidad * 1440


def calcular_momento_aviso(
    evento,
    minutos
):
    if not evento[3] or not evento[4]:
        return None

    momento_evento = datetime.fromisoformat(
        f"{evento[3]}T{evento[4]}:00"
    )

    return (
        momento_evento
        - timedelta(
            minutes=minutos
        )
    )


def crear_aviso_vinculado(
    evento,
    minutos
):
    momento_aviso = calcular_momento_aviso(
        evento,
        minutos
    )

    if momento_aviso is None:

        return (
            "El evento no tiene fecha "
            "u hora suficiente."
        )

    if momento_aviso <= datetime.now():

        return (
            "El momento para ese aviso "
            "ya pasó."
        )

    descripcion = descripcion_anticipacion(
        minutos
    )

    mensaje_recordatorio = (
        f"En {descripcion} "
        f"tenés {evento[1]}."
    )

    estado, recordatorio_id = crear_recordatorio(
        titulo=evento[1],
        fecha_hora=(
            momento_aviso
            .replace(microsecond=0)
            .isoformat()
        ),
        mensaje=mensaje_recordatorio,
        evento_id=evento[0],
        anticipacion_minutos=minutos,
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
        f"{evento[1]}, "
        f"{fecha_para_mostrar(momento_aviso.date().isoformat())} "
        f"a las {momento_aviso.strftime('%H:%M')}."
    )


def crear_recordatorio_antes_evento(
    mensaje
):
    global confirmacion_pendiente

    minutos = extraer_minutos_anticipacion(
        mensaje
    )

    if minutos is None:

        return (
            "Necesito saber cuánto tiempo "
            "antes querés que te avise."
        )

    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar el evento "
            "al que te referís."
        )

    existentes = obtener_recordatorios_de_evento(
        evento[0]
    )

    for recordatorio in existentes:

        if recordatorio[6] == minutos:

            return (
                f"Ya tenés el recordatorio "
                f"#{recordatorio[0]} "
                f"programado "
                f"{descripcion_anticipacion(minutos)} "
                f"antes de {evento[1]}."
            )

    if existentes:

        confirmacion_pendiente = {
            "tipo": "nuevo_aviso_evento",
            "evento": evento,
            "minutos": minutos,
            "recordatorios_existentes": existentes,
        }

        lineas = [
            f"Ya tenés "
            f"{'un aviso' if len(existentes) == 1 else 'avisos'} "
            f"para {evento[1]}:"
        ]

        for recordatorio in existentes:

            lineas.append(
                f"- #{recordatorio[0]}: "
                f"{descripcion_anticipacion(recordatorio[6])} "
                f"antes"
            )

        lineas.append("")

        lineas.append(
            f"El nuevo sería "
            f"{descripcion_anticipacion(minutos)} antes. "
            f"Podés decir 'agregalo' o "
            f"'reemplazá el recordatorio "
            f"{existentes[0][0]}'."
        )

        return "\n".join(
            lineas
        )

    return crear_aviso_vinculado(
        evento,
        minutos
    )


def procesar_confirmacion_aviso(
    mensaje,
    pendiente
):
    global confirmacion_pendiente

    texto = normalizar_texto(
        mensaje
    )

    evento = pendiente["evento"]
    minutos = pendiente["minutos"]

    existentes = pendiente[
        "recordatorios_existentes"
    ]

    quiere_agregar = any(
        expresion in texto
        for expresion in (
            "agregalo",
            "agregala",
            "agrega",
            "agregar",
            "sumalo",
            "sumala",
            "suma",
            "sumar",
            "otro aviso",
        )
    )

    if quiere_agregar:

        confirmacion_pendiente = None

        return crear_aviso_vinculado(
            evento,
            minutos
        )

    quiere_cancelar = any(
        expresion in texto
        for expresion in (
            "dejalo",
            "dejala",
            "deja",
            "olvidalo",
            "olvidala",
            "no gracias",
        )
    )

    if quiere_cancelar:

        confirmacion_pendiente = None

        return (
            "Perfecto. No hice ningún cambio."
        )

    quiere_reemplazar = any(
        expresion in texto
        for expresion in (
            "reemplaza",
            "reemplazalo",
            "reemplazala",
            "reemplazar",
            "cambia",
            "cambialo",
            "cambiala",
        )
    )

    coincidencia_id = re.search(
        r"(?:recordatorio\s*)?#?\s*(\d+)",
        texto
    )

    if quiere_reemplazar:

        if coincidencia_id:

            objetivo_id = int(
                coincidencia_id.group(1)
            )

        elif len(existentes) == 1:

            objetivo_id = existentes[0][0]

        else:

            opciones = ", ".join(
                f"#{recordatorio[0]}"
                for recordatorio in existentes
            )

            return (
                f"Tenés varios avisos: "
                f"{opciones}. "
                f"Decime cuál querés reemplazar."
            )

        ids_validos = {
            recordatorio[0]
            for recordatorio in existentes
        }

        if objetivo_id not in ids_validos:

            return (
                "Ese recordatorio no pertenece "
                "a los avisos que estaba comparando."
            )

        momento_aviso = calcular_momento_aviso(
            evento,
            minutos
        )

        if (
            momento_aviso is None
            or momento_aviso <= datetime.now()
        ):

            confirmacion_pendiente = None

            return (
                "No puedo crear ese aviso "
                "porque el momento ya pasó."
            )

        descripcion = descripcion_anticipacion(
            minutos
        )

        estado, resultado_id = (
            actualizar_recordatorio_vinculado(
                recordatorio_id=objetivo_id,
                nueva_fecha_hora=(
                    momento_aviso
                    .replace(microsecond=0)
                    .isoformat()
                ),
                anticipacion_minutos=minutos,
                nuevo_mensaje=(
                    f"En {descripcion} "
                    f"tenés {evento[1]}."
                ),
            )
        )

        if estado == "duplicado":

            confirmacion_pendiente = None

            return (
                f"Ya existe ese aviso "
                f"como #{resultado_id}."
            )

        if estado != "actualizado":

            confirmacion_pendiente = None

            return (
                "No pude modificar "
                "ese recordatorio."
            )

        confirmacion_pendiente = None

        return (
            f"Listo. Reemplacé el aviso "
            f"#{objetivo_id}. "
            f"Ahora te voy a avisar "
            f"{descripcion} antes de "
            f"{evento[1]}."
        )

    return (
        "Tengo pendiente decidir qué hacer "
        "con ese nuevo aviso. "
        "Decime 'agregalo', "
        "'reemplazá el recordatorio X' "
        "o 'dejalo'."
    )


# ==========================================================
# DURACIÓN DE EVENTOS — CAMBIAR DURACIÓN
# ==========================================================

def es_cambio_duracion_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if "duracion" not in texto:
        return False

    accion = any(
        palabra in texto
        for palabra in (
            "cambia",
            "cambiar",
            "modifica",
            "modificar",
            "pone",
            "poner",
            "deja",
            "dejar",
        )
    )

    return accion


def extraer_nueva_duracion_evento_minutos(
    mensaje
):
    """
    Interpreta la duración objetivo en frases como:
    "Cambiá la duración de la reunión a 3 horas"
    "Poné la duración de la llamada en 45 minutos"
    """

    texto = normalizar_texto(
        mensaje
    )

    if re.search(
        r"\b(?:a|en)\s+media\s+hora\b",
        texto
    ):
        return 30

    if re.search(
        r"\b(?:a|en)\s+(?:una|un)\s+hora\b",
        texto
    ):
        return 60

    coincidencia = re.search(
        r"\b(?:a|en)\s+"
        r"(\d+)\s*"
        r"(minuto|minutos|hora|horas)\b",
        texto
    )

    if not coincidencia:
        return None

    cantidad = int(
        coincidencia.group(1)
    )

    unidad = coincidencia.group(2)

    if unidad.startswith(
        "hora"
    ):
        return cantidad * 60

    return cantidad


def cambiar_duracion_evento_desde_mensaje(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:
        return (
            "No pude identificar de qué evento "
            "querés cambiar la duración."
        )

    if not evento[3] or not evento[4]:
        return (
            f"El evento {evento[1]} no tiene fecha "
            f"u hora de inicio suficiente."
        )

    duracion_minutos = extraer_nueva_duracion_evento_minutos(
        mensaje
    )

    if duracion_minutos is None:
        return (
            "Necesito saber la nueva duración. "
            "Por ejemplo: 'Cambiá la duración "
            "de la reunión a 90 minutos'."
        )

    inicio = datetime.fromisoformat(
        f"{evento[3]}T{evento[4]}:00"
    )

    fin = (
        inicio
        + timedelta(
            minutes=duracion_minutos
        )
    )

    hora_fin_nueva = fin.strftime(
        "%H:%M"
    )

    estado_modificacion, _ = modificar_evento(
        evento_id=evento[0],
        fecha=evento[3],
        hora_inicio=evento[4],
        hora_fin=hora_fin_nueva,
    )

    if estado_modificacion == "no_existe":
        return (
            f"No encontré el evento #{evento[0]}."
        )

    if estado_modificacion == "no_activo":
        return (
            f"El evento #{evento[0]} ya no está activo."
        )

    return (
        f"Listo. Cambié la duración de "
        f"#{evento[0]}: {evento[1]} a "
        f"{descripcion_anticipacion(duracion_minutos)}. "
        f"Ahora va de {evento[4]} a {hora_fin_nueva}."
    )


# ==========================================================
# MODIFICAR EVENTOS
# ==========================================================

def extraer_desplazamiento_evento_minutos(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if (
        "recordatorio" in texto
        or "aviso" in texto
    ):
        return None

    acciones = (
        "mover",
        "move",
        "muevelo",
        "muevela",
        "pasalo",
        "pasala",
        "pasa",
        "correr",
        "corre",
        "correlo",
        "correla",
        "retrasa",
        "retrasalo",
        "retrasala",
        "adelanta",
        "adelantalo",
        "adelantala",
    )

    if not any(
        accion in texto
        for accion in acciones
    ):
        return None

    minutos = None

    if "media hora" in texto:
        minutos = 30

    elif re.search(
        r"\b(?:una|un)\s+hora\b",
        texto
    ):
        minutos = 60

    else:
        coincidencia = re.search(
            r"\b(\d+)\s*"
            r"(minuto|minutos|hora|horas)\b",
            texto
        )

        if coincidencia:
            cantidad = int(
                coincidencia.group(1)
            )

            unidad = coincidencia.group(2)

            if unidad.startswith(
                "hora"
            ):
                minutos = cantidad * 60

            else:
                minutos = cantidad

    if minutos is None:
        return None

    hacia_antes = any(
        expresion in texto
        for expresion in (
            " mas temprano",
            " antes",
            "adelanta",
            "adelantalo",
            "adelantala",
        )
    )

    hacia_despues = any(
        expresion in texto
        for expresion in (
            " mas tarde",
            " despues",
            "retrasa",
            "retrasalo",
            "retrasala",
        )
    )

    if hacia_antes:
        return -minutos

    if hacia_despues:
        return minutos

    # En frases como "Corré el dentista 30 minutos",
    # interpretamos "correr" como desplazarlo hacia adelante.
    if any(
        accion in texto
        for accion in (
            "correr",
            "corre",
            "correlo",
            "correla",
        )
    ):
        return minutos

    return None


def es_desplazamiento_relativo_evento(
    mensaje
):
    return (
        extraer_desplazamiento_evento_minutos(
            mensaje
        )
        is not None
    )


def mover_evento_relativamente_desde_mensaje(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:
        return (
            "No pude identificar qué "
            "evento querés mover."
        )

    if not evento[3] or not evento[4]:
        return (
            f"El evento {evento[1]} "
            f"no tiene fecha u hora suficiente "
            f"para moverlo de forma relativa."
        )

    desplazamiento = extraer_desplazamiento_evento_minutos(
        mensaje
    )

    if desplazamiento is None:
        return (
            "No pude interpretar cuánto tiempo "
            "querés mover el evento."
        )

    momento_actual = datetime.fromisoformat(
        f"{evento[3]}T{evento[4]}:00"
    )

    momento_nuevo = (
        momento_actual
        + timedelta(
            minutes=desplazamiento
        )
    )

    hora_fin_nueva = None

    if evento[5]:
        momento_fin_actual = datetime.fromisoformat(
            f"{evento[3]}T{evento[5]}:00"
        )

        if momento_fin_actual < momento_actual:
            momento_fin_actual += timedelta(
                days=1
            )

        momento_fin_nuevo = (
            momento_fin_actual
            + timedelta(
                minutes=desplazamiento
            )
        )

        hora_fin_nueva = momento_fin_nuevo.strftime(
            "%H:%M"
        )

    respuesta = aplicar_modificacion_evento(
        evento=evento,
        fecha_nueva=momento_nuevo.date().isoformat(),
        hora_nueva=momento_nuevo.strftime("%H:%M"),
        hora_fin_nueva=hora_fin_nueva,
    )

    if respuesta.startswith(
        "Listo."
    ):
        cantidad = abs(
            desplazamiento
        )

        direccion = (
            "más tarde"
            if desplazamiento > 0
            else "más temprano"
        )

        return (
            respuesta
            + f" Lo moví {descripcion_anticipacion(cantidad)} "
            + f"{direccion}."
        )

    return respuesta


def es_modificacion_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if (
        "recordatorio" in texto
        or "aviso" in texto
    ):
        return False

    return any(
        palabra in texto
        for palabra in (
            "mover",
            "move",
            "muevelo",
            "muevela",
            "cambiar",
            "cambia",
            "cambialo",
            "cambiala",
            "pasa",
            "pasar",
            "pasalo",
            "pasala",
        )
    )


def es_cancelacion_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if (
        "recordatorio" in texto
        or "aviso" in texto
    ):
        return False

    return any(
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


def reprogramar_avisos_evento_seguro(
    evento_id,
    fecha_evento,
    hora_evento,
):
    """
    Reprograma los avisos pendientes vinculados a un evento.

    Los avisos cuyo nuevo horario continúa en el futuro se actualizan.
    Los avisos cuyo nuevo horario ya quedó en el pasado se cancelan.
    Conserva evento_id y anticipacion_minutos.
    """

    recordatorios = obtener_recordatorios_de_evento(
        evento_id
    )

    if not recordatorios:
        return 0, 0

    momento_evento = datetime.fromisoformat(
        f"{fecha_evento}T{hora_evento}:00"
    )

    ahora = datetime.now()
    actualizados = 0
    cancelados_pasado = 0

    for recordatorio in recordatorios:

        recordatorio_id = recordatorio[0]
        titulo = recordatorio[1]
        anticipacion = recordatorio[6]

        if anticipacion is None:
            continue

        nuevo_momento = (
            momento_evento
            - timedelta(
                minutes=anticipacion
            )
        )

        if nuevo_momento <= ahora:

            estado, _ = cancelar_recordatorio(
                recordatorio_id
            )

            if estado == "cancelado":
                cancelados_pasado += 1

            continue

        mensaje_recordatorio = (
            f"En {descripcion_anticipacion(anticipacion)} "
            f"tenés {titulo}."
        )

        estado, _ = actualizar_recordatorio_vinculado(
            recordatorio_id=recordatorio_id,
            nueva_fecha_hora=(
                nuevo_momento
                .replace(microsecond=0)
                .isoformat()
            ),
            anticipacion_minutos=anticipacion,
            nuevo_mensaje=mensaje_recordatorio,
        )

        if estado == "actualizado":
            actualizados += 1

    return actualizados, cancelados_pasado


def aplicar_modificacion_evento(
    evento,
    fecha_nueva=None,
    hora_nueva=None,
    hora_fin_nueva=None,
):
    (
        evento_id,
        titulo,
        descripcion,
        fecha_actual,
        hora_actual,
        hora_fin_actual,
        estado,
    ) = evento

    fecha_final = (
        fecha_nueva
        if fecha_nueva
        else fecha_actual
    )

    hora_final = (
        hora_nueva
        if hora_nueva
        else hora_actual
    )

    hora_fin_final = (
        hora_fin_nueva
        if hora_fin_nueva
        else hora_fin_actual
    )

    # Si cambia la hora de inicio y no se indicó una nueva hora de fin,
    # conservamos la duración original del evento.
    if (
        hora_nueva
        and hora_fin_nueva is None
        and hora_actual
        and hora_fin_actual
    ):
        inicio_actual = datetime.fromisoformat(
            f"{fecha_actual}T{hora_actual}:00"
        )

        fin_actual = datetime.fromisoformat(
            f"{fecha_actual}T{hora_fin_actual}:00"
        )

        if fin_actual < inicio_actual:
            fin_actual += timedelta(
                days=1
            )

        duracion_original = (
            fin_actual
            - inicio_actual
        )

        nuevo_inicio = datetime.fromisoformat(
            f"{fecha_final}T{hora_final}:00"
        )

        nuevo_fin = (
            nuevo_inicio
            + duracion_original
        )

        hora_fin_final = nuevo_fin.strftime(
            "%H:%M"
        )

    if hora_final:

        momento_nuevo = datetime.fromisoformat(
            f"{fecha_final}T{hora_final}:00"
        )

        if momento_nuevo <= datetime.now():

            return (
                "La nueva fecha y hora "
                "ya pasaron."
            )

    estado_modificacion, _ = modificar_evento(
        evento_id=evento_id,
        fecha=fecha_final,
        hora_inicio=hora_final,
        hora_fin=hora_fin_final,
    )

    if estado_modificacion == "no_existe":

        return (
            f"No encontré el evento "
            f"#{evento_id}."
        )

    if estado_modificacion == "no_activo":

        return (
            f"El evento #{evento_id} "
            f"ya no está activo."
        )

    cantidad_reprogramada = 0
    cantidad_cancelada_por_pasado = 0

    if hora_final:

        (
            cantidad_reprogramada,
            cantidad_cancelada_por_pasado,
        ) = reprogramar_avisos_evento_seguro(
            evento_id,
            fecha_final,
            hora_final,
        )

    respuesta = (
        f"Listo. Moví el evento "
        f"#{evento_id}: {titulo} "
        f"al {fecha_para_mostrar(fecha_final)}"
    )

    if hora_final:

        respuesta += (
            f" a las {hora_final}"
        )

    respuesta += "."

    if cantidad_reprogramada == 1:

        respuesta += (
            " También actualicé "
            "1 recordatorio asociado."
        )

    elif cantidad_reprogramada > 1:

        respuesta += (
            f" También actualicé "
            f"{cantidad_reprogramada} "
            f"recordatorios asociados."
        )

    if cantidad_cancelada_por_pasado == 1:

        respuesta += (
            " Cancelé 1 aviso asociado "
            "porque su nuevo horario ya había pasado."
        )

    elif cantidad_cancelada_por_pasado > 1:

        respuesta += (
            f" Cancelé "
            f"{cantidad_cancelada_por_pasado} "
            f"avisos asociados porque sus nuevos horarios "
            f"ya habían pasado."
        )

    return respuesta


def modificar_evento_desde_mensaje(
    mensaje
):
    global confirmacion_pendiente

    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué "
            "evento querés modificar."
        )

    fecha_nueva = extraer_fecha_del_mensaje(
        mensaje
    )

    hora_nueva, hora_fin_nueva = extraer_horas_del_mensaje(
        mensaje
    )

    if not fecha_nueva and not hora_nueva:

        confirmacion_pendiente = {
            "tipo": "completar_modificacion_evento",
            "evento": evento,
        }

        return (
            f"Encontré el evento "
            f"#{evento[0]}: {evento[1]}. "
            f"¿A qué día y hora querés moverlo?"
        )

    return aplicar_modificacion_evento(
        evento=evento,
        fecha_nueva=fecha_nueva,
        hora_nueva=hora_nueva,
        hora_fin_nueva=hora_fin_nueva,
    )


def procesar_confirmacion_modificacion_evento(
    mensaje,
    pendiente
):
    global confirmacion_pendiente

    texto = normalizar_texto(
        mensaje
    )

    evento = pendiente["evento"]

    if any(
        expresion in texto
        for expresion in (
            "dejalo",
            "dejala",
            "deja",
            "olvidalo",
            "olvidala",
            "no importa",
        )
    ):

        confirmacion_pendiente = None

        return (
            "Perfecto. Dejé el evento como estaba."
        )

    fecha_nueva = extraer_fecha_del_mensaje(
        mensaje
    )

    hora_nueva, hora_fin_nueva = extraer_horas_del_mensaje(
        mensaje
    )

    if not fecha_nueva and not hora_nueva:

        return (
            f"Tengo pendiente mover "
            f"{evento[1]}. "
            f"Decime una nueva fecha, "
            f"una nueva hora o ambas."
        )

    confirmacion_pendiente = None

    return aplicar_modificacion_evento(
        evento=evento,
        fecha_nueva=fecha_nueva,
        hora_nueva=hora_nueva,
        hora_fin_nueva=hora_fin_nueva,
    )


# ==========================================================
# CANCELAR EVENTOS
# ==========================================================

def cancelar_evento_desde_mensaje(
    mensaje
):
    evento = buscar_evento_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué "
            "evento querés cancelar."
        )

    estado_cancelacion, _ = cancelar_evento(
        evento[0]
    )

    if estado_cancelacion == "ya_cancelado":

        return (
            f"El evento #{evento[0]} "
            f"ya estaba cancelado."
        )

    cantidad_cancelada = cancelar_recordatorios_de_evento(
        evento[0]
    )

    respuesta = (
        f"Listo. Cancelé el evento "
        f"#{evento[0]}: "
        f"{evento[1]}."
    )

    if cantidad_cancelada == 1:

        respuesta += (
            " También cancelé "
            "1 recordatorio asociado."
        )

    elif cantidad_cancelada > 1:

        respuesta += (
            f" También cancelé "
            f"{cantidad_cancelada} "
            f"recordatorios asociados."
        )

    return respuesta


# ==========================================================
# CONFIRMACIONES
# ==========================================================

def procesar_confirmacion_pendiente(
    mensaje
):
    global confirmacion_pendiente

    if confirmacion_pendiente is None:
        return None

    pendiente = confirmacion_pendiente

    tipo = pendiente.get(
        "tipo"
    )

    if tipo == "nuevo_aviso_evento":

        return procesar_confirmacion_aviso(
            mensaje,
            pendiente,
        )

    if tipo == "completar_modificacion_evento":

        return procesar_confirmacion_modificacion_evento(
            mensaje,
            pendiente,
        )

    if tipo == "cancelar_recordatorio_ambiguo":

        return procesar_cancelacion_recordatorio_ambiguo(
            mensaje,
            pendiente,
        )

    confirmacion_pendiente = None

    return None


# ==========================================================
# MEMORIA
# ==========================================================

def obtener_texto_memoria():
    recuerdos = obtener_recuerdos()

    if not recuerdos:

        return (
            "Sin recuerdos guardados."
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
    tareas = obtener_tareas_pendientes()

    if not tareas:

        return (
            "Sin tareas pendientes."
        )

    return "\n".join(
        f"- ID {tarea[0]}: "
        f"{tarea[1]} | "
        f"{tarea[3] or 'sin fecha'}"
        for tarea in tareas
    )


def mostrar_tareas_pendientes():
    tareas = obtener_tareas_pendientes()

    if not tareas:

        return (
            "No tenés tareas pendientes."
        )

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


# ==========================================================
# EVENTOS / AGENDA
# ==========================================================

def obtener_texto_eventos():
    eventos = obtener_eventos_activos()

    if not eventos:

        return (
            "Sin eventos próximos."
        )

    return "\n".join(
        f"- ID {evento[0]}: "
        f"{evento[1]} | "
        f"{evento[3]} | "
        f"{evento[4] or 'sin hora'}"
        for evento in eventos
    )


def mostrar_eventos():
    eventos = obtener_eventos_activos()

    if not eventos:

        return (
            "No tenés eventos próximos."
        )

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

        if evento[5]:

            texto += (
                f" a {evento[5]}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


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
        lineas.append(
            "Eventos:"
        )

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
        lineas.append(
            "Tareas:"
        )

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
        "hoy",
    )


def agenda_manana():
    return agenda_para_fecha(
        (
            date.today()
            + timedelta(days=1)
        ).isoformat(),
        "mañana",
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
        fin.isoformat(),
    )

    eventos = obtener_eventos_entre_fechas(
        hoy.isoformat(),
        fin.isoformat(),
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
        lineas.append(
            "Eventos:"
        )

        for evento in eventos:

            texto = (
                f"- "
                f"{fecha_para_mostrar(evento[3])}: "
                f"#{evento[0]} "
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
        lineas.append(
            "Tareas:"
        )

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
# AUDITORÍA DE SINCRONIZACIÓN EVENTO ↔ RECORDATORIOS
# ==========================================================

def es_auditoria_sincronizacion(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_sincronizacion = any(
        expresion in texto
        for expresion in (
            "sincronizacion",
            "sincronizados",
            "sincronizado",
            "desfasados",
            "desfasado",
        )
    )

    accion_revision = any(
        expresion in texto
        for expresion in (
            "revisa",
            "revisar",
            "verifica",
            "verificar",
            "audita",
            "auditar",
            "controla",
            "controlar",
            "comproba",
            "comprobar",
        )
    )

    habla_de_eventos = (
        "evento" in texto
        or "eventos" in texto
        or "recordatorio" in texto
        or "recordatorios" in texto
        or "aviso" in texto
        or "avisos" in texto
    )

    return (
        menciona_sincronizacion
        and accion_revision
        and habla_de_eventos
    )


def revisar_sincronizacion_eventos():
    """
    Revisa todos los recordatorios pendientes vinculados a eventos.

    Detecta:
    - vínculos a eventos inexistentes;
    - vínculos a eventos ya no activos;
    - datos de vínculo incompletos;
    - fecha/hora de aviso desfasada respecto del evento
      y su anticipación guardada.

    Esta función solo audita: no modifica datos.
    """

    pendientes = obtener_recordatorios_pendientes()

    vinculados = []
    problemas = []

    for pendiente in pendientes:

        recordatorio_id = pendiente[0]

        recordatorio = obtener_recordatorio_por_id(
            recordatorio_id
        )

        if not recordatorio:
            continue

        evento_id = recordatorio[5]
        anticipacion = recordatorio[6]

        if evento_id is None:
            continue

        vinculados.append(
            recordatorio
        )

        evento = obtener_evento_por_id(
            evento_id
        )

        if not evento:

            problemas.append(
                (
                    recordatorio_id,
                    "huérfano",
                    (
                        f"está vinculado al evento #{evento_id}, "
                        f"pero ese evento no existe"
                    ),
                )
            )

            continue

        if evento[6] != "activo":

            problemas.append(
                (
                    recordatorio_id,
                    "evento no activo",
                    (
                        f"está vinculado a {evento[1]} "
                        f"(evento #{evento_id}), "
                        f"pero el evento está {evento[6]}"
                    ),
                )
            )

            continue

        if not evento[3] or not evento[4]:

            problemas.append(
                (
                    recordatorio_id,
                    "evento incompleto",
                    (
                        f"{evento[1]} no tiene fecha "
                        f"u hora suficiente"
                    ),
                )
            )

            continue

        if anticipacion is None:

            problemas.append(
                (
                    recordatorio_id,
                    "anticipación faltante",
                    (
                        f"está vinculado a {evento[1]}, "
                        f"pero no tiene anticipación guardada"
                    ),
                )
            )

            continue

        try:

            momento_evento = datetime.fromisoformat(
                f"{evento[3]}T{evento[4]}:00"
            )

            momento_esperado = (
                momento_evento
                - timedelta(
                    minutes=anticipacion
                )
            ).replace(
                microsecond=0
            )

            momento_actual = datetime.fromisoformat(
                recordatorio[3]
            ).replace(
                microsecond=0
            )

        except (TypeError, ValueError):

            problemas.append(
                (
                    recordatorio_id,
                    "fecha inválida",
                    (
                        f"no pude interpretar la fecha/hora "
                        f"del aviso o del evento {evento[1]}"
                    ),
                )
            )

            continue

        if momento_actual != momento_esperado:

            problemas.append(
                (
                    recordatorio_id,
                    "desfasado",
                    (
                        f"{evento[1]} debería avisar "
                        f"{descripcion_anticipacion(anticipacion)} antes, "
                        f"el "
                        f"{fecha_para_mostrar(momento_esperado.date().isoformat())} "
                        f"a las {momento_esperado.strftime('%H:%M')}, "
                        f"pero está programado para "
                        f"{fecha_para_mostrar(momento_actual.date().isoformat())} "
                        f"a las {momento_actual.strftime('%H:%M')}"
                    ),
                )
            )

    if not vinculados:

        return (
            "No hay recordatorios pendientes vinculados a eventos "
            "para revisar."
        )

    if not problemas:

        cantidad = len(
            vinculados
        )

        return (
            f"Sincronización correcta. Revisé "
            f"{cantidad} "
            f"{'aviso vinculado' if cantidad == 1 else 'avisos vinculados'} "
            f"y no encontré desfasajes ni vínculos huérfanos."
        )

    lineas = [
        (
            f"Encontré {len(problemas)} "
            f"{'problema' if len(problemas) == 1 else 'problemas'} "
            f"de sincronización:"
        )
    ]

    for recordatorio_id, tipo, detalle in problemas:

        lineas.append(
            f"- Recordatorio #{recordatorio_id} "
            f"({tipo}): {detalle}."
        )

    lineas.append("")
    lineas.append(
        "No modifiqué nada; esto fue solamente una auditoría."
    )

    return "\n".join(
        lineas
    )


# ==========================================================
# CONSULTAS INDEPENDIENTES
# ==========================================================

def es_consulta_independiente(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        "que recordatorios tengo",
        "mis recordatorios",
        "recordatorios pendientes",
        "que tareas tengo",
        "mis tareas",
        "tareas pendientes",
        "que eventos tengo",
        "mis eventos",
        "proximos eventos",
        "que tengo hoy",
        "agenda de hoy",
        "que tengo manana",
        "agenda de manana",
        "que tengo esta semana",
        "agenda de esta semana",
    )

    return any(
        patron in texto
        for patron in patrones
    )


# ==========================================================
# COMANDOS LOCALES
# ==========================================================

def procesar_comandos_directos(
    mensaje
):
    global confirmacion_pendiente
    global ultimo_contexto_edicion

    texto = normalizar_texto(
        mensaje
    )

    if es_edicion_contextual(
        mensaje
    ):
        return procesar_edicion_contextual(
            mensaje
        )

    # El contexto de edición sirve para el seguimiento inmediato.
    # Si Leo inicia otra orden distinta, dejamos de arrastrarlo.
    ultimo_contexto_edicion = None

    if (
        confirmacion_pendiente is not None
        and es_consulta_independiente(
            mensaje
        )
    ):

        confirmacion_pendiente = None

    if (
        confirmacion_pendiente is not None
        and es_cambio_duracion_evento(
            mensaje
        )
    ):
        confirmacion_pendiente = None

        return cambiar_duracion_evento_desde_mensaje(
            mensaje
        )

    if confirmacion_pendiente is not None:

        return procesar_confirmacion_pendiente(
            mensaje
        )

    if es_respuesta_dependiente_sin_contexto(
        mensaje
    ):

        return respuesta_contexto_faltante(
            mensaje
        )

    if es_auditoria_sincronizacion(
        mensaje
    ):

        return revisar_sincronizacion_eventos()

    # ======================================================
    # GESTIÓN AVANZADA DE AVISOS
    # Orden importante: estas reglas van antes de las
    # reglas generales de recordatorios.
    # ======================================================

    if es_dejar_solo_aviso(
        mensaje
    ):

        return dejar_solo_aviso_desde_mensaje(
            mensaje
        )

    if es_cambio_anticipacion_aviso(
        mensaje
    ):

        return cambiar_anticipacion_aviso_desde_mensaje(
            mensaje
        )

    if es_eliminar_aviso_evento(
        mensaje
    ):

        return eliminar_aviso_evento_desde_mensaje(
            mensaje
        )

    if es_consulta_avisos_evento(
        mensaje
    ):

        evento = buscar_evento_desde_mensaje(
            mensaje
        )

        if evento:

            return mostrar_avisos_de_evento(
                mensaje
            )

    # RECORDATORIOS GENERALES

    if es_cancelacion_recordatorio(
        mensaje
    ):

        return cancelar_recordatorio_desde_mensaje(
            mensaje
        )

    if es_desplazamiento_relativo_recordatorio(
        mensaje
    ):
        actual, _ = obtener_recordatorio_objetivo_para_edicion(
            mensaje
        )

        respuesta = mover_recordatorio_relativamente_desde_mensaje(
            mensaje
        )

        if (
            actual
            and respuesta.startswith("Listo.")
        ):
            guardar_contexto_edicion(
                "recordatorio",
                actual[0]
            )

        return respuesta

    if es_modificacion_recordatorio(
        mensaje
    ):
        actual, _ = obtener_recordatorio_objetivo_para_edicion(
            mensaje
        )

        respuesta = modificar_recordatorio_desde_mensaje(
            mensaje
        )

        if (
            actual
            and respuesta.startswith("Listo.")
        ):
            guardar_contexto_edicion(
                "recordatorio",
                actual[0]
            )

        return respuesta

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

    # EVENTOS

    if es_cambio_duracion_evento(
        mensaje
    ):

        evento = buscar_evento_desde_mensaje(
            mensaje
        )

        respuesta = cambiar_duracion_evento_desde_mensaje(
            mensaje
        )

        if (
            evento
            and respuesta.startswith("Listo.")
        ):
            guardar_contexto_edicion(
                "evento",
                evento[0]
            )

        return respuesta

    if es_creacion_evento_natural(
        mensaje
    ):

        return crear_evento_natural_desde_mensaje(
            mensaje
        )

    if es_desplazamiento_relativo_evento(
        mensaje
    ):

        evento = buscar_evento_desde_mensaje(
            mensaje
        )

        if evento:
            respuesta = mover_evento_relativamente_desde_mensaje(
                mensaje
            )

            if respuesta.startswith("Listo."):
                guardar_contexto_edicion(
                    "evento",
                    evento[0]
                )

            return respuesta

    if es_modificacion_evento(
        mensaje
    ):

        evento = buscar_evento_desde_mensaje(
            mensaje
        )

        if evento:
            respuesta = modificar_evento_desde_mensaje(
                mensaje
            )

            if respuesta.startswith("Listo."):
                guardar_contexto_edicion(
                    "evento",
                    evento[0]
                )

            return respuesta

    if es_cancelacion_evento(
        mensaje
    ):

        evento = buscar_evento_desde_mensaje(
            mensaje
        )

        if evento:

            return cancelar_evento_desde_mensaje(
                mensaje
            )

    # AGENDA

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

    # TAREAS

    if any(
        patron in texto
        for patron in (
            "que tareas tengo",
            "mis tareas",
            "tareas pendientes",
        )
    ):

        return mostrar_tareas_pendientes()

    # EVENTOS

    if any(
        patron in texto
        for patron in (
            "que eventos tengo",
            "mis eventos",
            "proximos eventos",
        )
    ):

        return mostrar_eventos()

    # COMPLETAR TAREA

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
            "🧠 profundo",
        )

    return (
        MODELO_RAPIDO,
        "⚡ rápido",
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

No inventes una tarea o evento a partir de una respuesta
corta que dependa de una conversación anterior.

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
        timeout=120,
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
        "No pude generar una respuesta.",
    )

    accion = resultado.get(
        "accion",
        "ninguna",
    )

    if (
        accion == "crear_tarea"
        and not autoriza_creacion_tarea_desde_modelo(
            mensaje
        )
    ):

        return (
            "No veo una solicitud explícita para crear "
            "una tarea, así que no guardé nada."
        )

    if (
        accion == "crear_evento"
        and not autoriza_creacion_evento_desde_modelo(
            mensaje
        )
    ):

        return (
            "No veo una solicitud explícita para crear "
            "un evento, así que no guardé nada."
        )

    if accion == "crear_tarea":

        titulo = str(
            resultado.get(
                "tarea_titulo",
                "",
            )
        ).strip()

        descripcion = str(
            resultado.get(
                "tarea_descripcion",
                "",
            )
        ).strip()

        fecha = extraer_fecha_del_mensaje(
            mensaje
        )

        if titulo:

            tarea_id = crear_tarea(
                titulo,
                descripcion,
                fecha,
            )

            respuesta = (
                f"Listo. Agregué la tarea "
                f"#{tarea_id}: {titulo}."
            )

    elif accion == "crear_evento":

        titulo = str(
            resultado.get(
                "evento_titulo",
                "",
            )
        ).strip()

        descripcion = str(
            resultado.get(
                "evento_descripcion",
                "",
            )
        ).strip()

        fecha = extraer_fecha_del_mensaje(
            mensaje
        )

        hora_inicio, hora_fin = extraer_horas_del_mensaje(
            mensaje
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
                "otro",
            )
        ).strip()

        clave = str(
            resultado.get(
                "clave",
                "",
            )
        ).strip().lower()

        valor = str(
            resultado.get(
                "valor",
                "",
            )
        ).strip()

        if clave and valor:

            guardar_recuerdo(
                categoria,
                clave,
                valor,
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
print("🔗 Vínculo evento-recordatorio: activo")
print("🔔 Múltiples avisos por evento: activos")
print("💬 Confirmaciones conversacionales: activas")
print("🧩 Datos faltantes de eventos: activos")
print("🔀 Resolución de ambigüedades: activa")
print("🛡️ Seguridad conversacional: activa")
print("🎛️ Gestión avanzada de avisos: activa")
print("🔗 Referencias contextuales de edición: activas")
print("⏱️ Edición natural de recordatorios: activa")
print("↔️ Edición relativa de eventos: activa")
print("🔄 Sincronización segura evento-aviso: activa")
print("🧪 Auditoría evento-recordatorios: activa")
print("🕒 Comprensión temporal relativa: activa")
print("📅 Creación natural de eventos temporales: activa")
print("🗓️ Fechas naturales avanzadas: activas")
print("🌅 Partes del día: activas")
print("📆 Períodos naturales: activos")
print("⏳ Duración natural de eventos: activa")
print("🕐 Edición de duración de eventos: activa")
print("🧭 Conservación automática de duración al mover eventos: activa")
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

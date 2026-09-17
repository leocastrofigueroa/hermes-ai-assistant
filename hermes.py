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
)

OLLAMA_URL = "http://localhost:11434/api/generate"

MODELO_RAPIDO = "qwen3:1.7b"
MODELO_PROFUNDO = "qwen3:4b"

crear_base()


PROMPT_SISTEMA = """
Tu nombre es Hermes.

Sos el asistente personal de inteligencia artificial de Leo.

Tu función es ayudarlo a organizar su vida, proyectos,
trabajo, estudios, tareas, eventos, ideas y preferencias.

Hablá siempre en español salvo que Leo solicite otro idioma.

Tu estilo debe ser natural, claro, directo, amistoso y conciso.

Nunca hables como si fueras Leo.
No inventes emociones ni agregues frases decorativas innecesarias.

Nunca digas que sos Qwen ni menciones Alibaba Cloud,
salvo que Leo pregunte específicamente por el modelo técnico.

Tenés memoria permanente sobre Leo.

También podés detectar cuando Leo expresa una NUEVA tarea.

Ejemplos:
- mañana tengo que llamar a Juan
- el viernes tengo que pagar la tarjeta
- tengo que comprar tinta
- agregá como tarea enviar el presupuesto

IMPORTANTE:

El campo tarea_descripcion debe contener solamente
detalles adicionales reales de la tarea.

No pongas en tarea_descripcion expresiones de fecha como:
- hoy
- mañana
- pasado mañana
- lunes
- martes
- miércoles
- jueves
- viernes
- sábado
- domingo
- el viernes
- el sábado

Las fechas son procesadas por Python.

Las consultas y operaciones simples sobre tareas
son procesadas directamente por Python.
"""


def normalizar_texto(texto):
    texto = texto.lower().strip()

    texto = unicodedata.normalize("NFD", texto)

    texto = "".join(
        caracter
        for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )

    return texto


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

    texto_original = texto_fecha.strip()

    if not texto_original:
        return None

    texto = normalizar_texto(texto_original)
    hoy = date.today()

    if texto in ("hoy", "para hoy"):
        return hoy.isoformat()

    if texto in ("manana", "para manana"):
        return (
            hoy + timedelta(days=1)
        ).isoformat()

    if texto in (
        "pasado manana",
        "para pasado manana",
    ):
        return (
            hoy + timedelta(days=2)
        ).isoformat()

    for nombre_dia, numero_dia in DIAS_SEMANA.items():
        if nombre_dia in texto:
            diferencia = (
                numero_dia - hoy.weekday()
            ) % 7

            if diferencia == 0:
                diferencia = 7

            return (
                hoy + timedelta(days=diferencia)
            ).isoformat()

    formatos = (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
    )

    for formato in formatos:
        try:
            fecha = datetime.strptime(
                texto_original,
                formato
            ).date()

            return fecha.isoformat()

        except ValueError:
            pass

    return None


def extraer_fecha_del_mensaje(mensaje):
    texto = normalizar_texto(mensaje)

    if "pasado manana" in texto:
        return convertir_fecha("pasado mañana")

    if "manana" in texto:
        return convertir_fecha("mañana")

    if re.search(r"\bhoy\b", texto):
        return convertir_fecha("hoy")

    for nombre_dia in DIAS_SEMANA:
        if re.search(
            rf"\b{nombre_dia}\b",
            texto
        ):
            return convertir_fecha(nombre_dia)

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


def descripcion_es_solo_fecha(descripcion):
    if not descripcion:
        return False

    texto = normalizar_texto(descripcion)

    expresiones = {
        "hoy",
        "para hoy",
        "manana",
        "para manana",
        "pasado manana",
        "para pasado manana",
        "lunes",
        "el lunes",
        "martes",
        "el martes",
        "miercoles",
        "el miercoles",
        "jueves",
        "el jueves",
        "viernes",
        "el viernes",
        "sabado",
        "el sabado",
        "domingo",
        "el domingo",
    }

    if texto in expresiones:
        return True

    if re.fullmatch(
        r"\d{1,2}/\d{1,2}/\d{4}",
        texto
    ):
        return True

    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}",
        texto
    ):
        return True

    return False


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

    if fecha == hoy + timedelta(days=1):
        return "mañana"

    if fecha == hoy + timedelta(days=2):
        return "pasado mañana"

    return fecha.strftime("%d/%m/%Y")


def obtener_texto_memoria():
    recuerdos = obtener_recuerdos()

    if not recuerdos:
        return (
            "No hay recuerdos permanentes "
            "guardados todavía."
        )

    lineas = []

    for categoria, clave, valor in recuerdos:
        lineas.append(
            f"- [{categoria}] {clave}: {valor}"
        )

    return "\n".join(lineas)


def obtener_texto_tareas():
    tareas = obtener_tareas_pendientes()

    if not tareas:
        return "No hay tareas pendientes."

    lineas = []

    for (
        tarea_id,
        titulo,
        descripcion,
        fecha,
        estado,
    ) in tareas:

        texto = f"- ID {tarea_id}: {titulo}"

        if fecha:
            texto += (
                f" | fecha: "
                f"{fecha_para_mostrar(fecha)}"
            )

        if descripcion:
            texto += (
                f" | detalle: {descripcion}"
            )

        lineas.append(texto)

    return "\n".join(lineas)


def formatear_lista_tareas(
    tareas,
    encabezado
):
    if not tareas:
        return (
            "No encontré tareas pendientes "
            "para ese período."
        )

    lineas = [encabezado]

    for (
        tarea_id,
        titulo,
        descripcion,
        fecha,
        estado,
    ) in tareas:

        texto = f"{tarea_id}. {titulo}"

        if fecha:
            texto += (
                f" — {fecha_para_mostrar(fecha)}"
            )

        if descripcion:
            texto += (
                f" — {descripcion}"
            )

        lineas.append(texto)

    return "\n".join(lineas)


def mostrar_todas_las_tareas():
    return formatear_lista_tareas(
        obtener_tareas_pendientes(),
        "Tus tareas pendientes son:"
    )


def mostrar_tareas_hoy():
    tareas = obtener_tareas_por_fecha(
        date.today().isoformat()
    )

    return formatear_lista_tareas(
        tareas,
        "Tus tareas para hoy son:"
    )


def mostrar_tareas_manana():
    fecha_manana = (
        date.today()
        + timedelta(days=1)
    ).isoformat()

    tareas = obtener_tareas_por_fecha(
        fecha_manana
    )

    return formatear_lista_tareas(
        tareas,
        "Tus tareas para mañana son:"
    )


def mostrar_tareas_semana():
    hoy = date.today()

    fin_semana = (
        hoy
        + timedelta(
            days=6 - hoy.weekday()
        )
    )

    tareas = obtener_tareas_entre_fechas(
        hoy.isoformat(),
        fin_semana.isoformat()
    )

    return formatear_lista_tareas(
        tareas,
        "Tus tareas para esta semana son:"
    )


def es_consulta_tareas_hoy(mensaje):
    texto = normalizar_texto(mensaje)

    patrones = (
        "que tengo para hoy",
        "tareas para hoy",
        "tareas de hoy",
        "que tareas tengo hoy",
    )

    return any(
        patron in texto
        for patron in patrones
    )


def es_consulta_tareas_manana(mensaje):
    texto = normalizar_texto(mensaje)

    patrones = (
        "que tengo para manana",
        "tareas para manana",
        "tareas de manana",
        "que tareas tengo manana",
    )

    return any(
        patron in texto
        for patron in patrones
    )


def es_consulta_tareas_semana(mensaje):
    texto = normalizar_texto(mensaje)

    patrones = (
        "que tengo esta semana",
        "tareas de esta semana",
        "tareas para esta semana",
        "que tareas tengo esta semana",
    )

    return any(
        patron in texto
        for patron in patrones
    )


def es_consulta_de_tareas(mensaje):
    texto = normalizar_texto(mensaje)

    patrones = (
        "que tareas tengo",
        "mis tareas",
        "tareas pendientes",
        "mostrame las tareas",
        "mostrame mis tareas",
        "mostrar tareas",
        "listar tareas",
        "lista de tareas",
    )

    return any(
        patron in texto
        for patron in patrones
    )


def es_orden_de_completar(mensaje):
    texto = normalizar_texto(mensaje)

    palabras = (
        "completar",
        "completada",
        "complete",
        "termine",
        "hecha",
        "finalizar",
        "finalice",
        "marcar",
    )

    return any(
        palabra in texto
        for palabra in palabras
    )


def extraer_id_tarea(mensaje):
    coincidencia = re.search(
        r"(?:tarea\s*)?#?\s*(\d+)",
        normalizar_texto(mensaje)
    )

    if coincidencia:
        return int(
            coincidencia.group(1)
        )

    return None


def procesar_comandos_directos(mensaje):
    if es_consulta_tareas_hoy(mensaje):
        return mostrar_tareas_hoy()

    if es_consulta_tareas_manana(mensaje):
        return mostrar_tareas_manana()

    if es_consulta_tareas_semana(mensaje):
        return mostrar_tareas_semana()

    if es_consulta_de_tareas(mensaje):
        return mostrar_todas_las_tareas()

    if es_orden_de_completar(mensaje):
        tarea_id = extraer_id_tarea(mensaje)

        if tarea_id is None:
            tareas = obtener_tareas_pendientes()

            if not tareas:
                return (
                    "No tenés tareas pendientes "
                    "para completar."
                )

            return (
                "Indicame el número de la tarea "
                "que querés completar.\n\n"
                + mostrar_todas_las_tareas()
            )

        tarea = obtener_tarea_por_id(
            tarea_id
        )

        if not tarea:
            return (
                f"No encontré una tarea "
                f"con ID {tarea_id}."
            )

        if tarea[4] == "completada":
            return (
                f"La tarea #{tarea_id} ya estaba "
                f"completada: {tarea[1]}."
            )

        if completar_tarea(tarea_id):
            return (
                f"Listo. Marqué como completada "
                f"la tarea #{tarea_id}: "
                f"{tarea[1]}."
            )

    return None


def necesita_modo_profundo(mensaje):
    texto = normalizar_texto(mensaje)

    if texto.startswith("profundo:"):
        return True

    if texto.startswith("modo profundo:"):
        return True

    palabras_complejas = (
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
        for palabra in palabras_complejas
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


def limpiar_comando_profundo(mensaje):
    texto = mensaje.strip()

    normalizado = normalizar_texto(
        texto
    )

    if normalizado.startswith(
        "profundo:"
    ):
        return texto.split(
            ":",
            1
        )[1].strip()

    if normalizado.startswith(
        "modo profundo:"
    ):
        return texto.split(
            ":",
            1
        )[1].strip()

    return texto


def consultar_hermes(mensaje):
    comando_directo = (
        procesar_comandos_directos(
            mensaje
        )
    )

    if comando_directo is not None:
        print(
            "Hermes ⚡ comando local..."
        )

        return comando_directo

    memoria = obtener_texto_memoria()
    tareas = obtener_texto_tareas()

    modelo, modo = elegir_modelo(
        mensaje
    )

    mensaje_limpio = (
        limpiar_comando_profundo(
            mensaje
        )
    )

    prompt = f"""
{PROMPT_SISTEMA}

FECHA ACTUAL:
{date.today().isoformat()}

MEMORIA PERMANENTE DE LEO:
{memoria}

TAREAS PENDIENTES:
{tareas}

MENSAJE ACTUAL DE LEO:
{mensaje_limpio}

Respondé SOLAMENTE con JSON válido.

Usá exactamente esta estructura:

{{
    "respuesta": "respuesta natural de Hermes",
    "accion": "ninguna",
    "guardar_memoria": false,
    "categoria": "",
    "clave": "",
    "valor": "",
    "tarea_titulo": "",
    "tarea_descripcion": "",
    "tarea_fecha": ""
}}

Las únicas acciones posibles son:

"ninguna"
"crear_tarea"

Usá "crear_tarea" solamente cuando Leo
exprese una NUEVA obligación o pendiente.

No crees tareas a partir de tareas existentes
que aparezcan en el contexto.

No guardes una tarea también como recuerdo.

No uses expresiones de fecha como descripción
de una tarea.

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
            "num_ctx": 4096
        }
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

    texto = respuesta_http.json()[
        "response"
    ].strip()

    try:
        resultado = json.loads(texto)

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

        if descripcion_es_solo_fecha(
            descripcion
        ):
            descripcion = ""

        fecha_texto = str(
            resultado.get(
                "tarea_fecha",
                ""
            )
        ).strip()

        fecha_iso = (
            extraer_fecha_del_mensaje(
                mensaje_limpio
            )
        )

        if fecha_iso is None:
            fecha_iso = convertir_fecha(
                fecha_texto
            )

        if titulo:
            tarea_id = crear_tarea(
                titulo,
                descripcion,
                fecha_iso
            )

            print(
                f"✅ Tarea creada "
                f"#{tarea_id}: {titulo}"
            )

            if fecha_iso:
                respuesta = (
                    f"Listo. Agregué la tarea "
                    f"#{tarea_id}: {titulo} "
                    f"para "
                    f"{fecha_para_mostrar(fecha_iso)}."
                )

            else:
                respuesta = (
                    f"Listo. Agregué la tarea "
                    f"#{tarea_id}: {titulo}."
                )

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
                    f"🧠 Hermes recordó: {valor}"
                )

            elif estado == "actualizado":
                print(
                    f"🧠 Hermes actualizó: {valor}"
                )

    return respuesta


print()
print("════════════════════════════════")
print("            HERMES")
print("════════════════════════════════")
print()
print("⚡ Cerebro rápido: qwen3:1.7b")
print("🧠 Cerebro profundo: qwen3:4b")
print("🧠 Memoria permanente: activa")
print("✅ Gestión de tareas: activa")
print("📅 Fechas inteligentes: activas")
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
            "comunicándome con mi modelo local."
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

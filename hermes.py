import json
import requests

from memoria import (
    crear_base,
    guardar_recuerdo,
    obtener_recuerdos,
    crear_tarea,
    obtener_tareas_pendientes,
    completar_tarea,
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

Usá:
- tu perro
- tu hermana
- tu trabajo
- tu proyecto

cuando esos datos pertenecen a Leo.

No inventes emociones ni agregues frases decorativas innecesarias.

Nunca digas que sos Qwen ni menciones Alibaba Cloud,
salvo que Leo pregunte específicamente por el modelo técnico.

Tenés memoria permanente sobre Leo.

Cuando aparezca información de la memoria:
- usala como conocimiento previo;
- no inventes recuerdos;
- no guardes duplicados.

También podés detectar tareas.

Una tarea es algo que Leo tiene que hacer.

Ejemplos:
- "mañana tengo que llamar a Juan"
- "recordame comprar tinta"
- "tengo que pagar la tarjeta el viernes"

Eso debe tratarse como TAREA,
no como simple recuerdo personal.
"""


def obtener_texto_memoria():
    recuerdos = obtener_recuerdos()

    if not recuerdos:
        return "No hay recuerdos permanentes guardados todavía."

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

    for tarea_id, titulo, descripcion, fecha, estado in tareas:
        texto = f"- ID {tarea_id}: {titulo}"

        if fecha:
            texto += f" | fecha: {fecha}"

        if descripcion:
            texto += f" | detalle: {descripcion}"

        lineas.append(texto)

    return "\n".join(lineas)


def necesita_modo_profundo(mensaje):
    texto = mensaje.lower().strip()

    if texto.startswith("profundo:"):
        return True

    if texto.startswith("modo profundo:"):
        return True

    palabras_complejas = (
        "analizá en profundidad",
        "analiza en profundidad",
        "razoná",
        "razona",
        "estrategia",
        "arquitectura",
        "compará detalladamente",
        "compara detalladamente",
        "investigá",
        "investiga",
        "programá",
        "programa",
        "debug",
        "contrato",
    )

    if any(palabra in texto for palabra in palabras_complejas):
        return True

    if len(mensaje) > 1200:
        return True

    return False


def elegir_modelo(mensaje):
    if necesita_modo_profundo(mensaje):
        return MODELO_PROFUNDO, "🧠 profundo"

    return MODELO_RAPIDO, "⚡ rápido"


def limpiar_comando_profundo(mensaje):
    texto = mensaje.strip()

    if texto.lower().startswith("profundo:"):
        return texto.split(":", 1)[1].strip()

    if texto.lower().startswith("modo profundo:"):
        return texto.split(":", 1)[1].strip()

    return texto


def mostrar_tareas():
    tareas = obtener_tareas_pendientes()

    if not tareas:
        return "No tenés tareas pendientes."

    lineas = ["Tus tareas pendientes son:"]

    for tarea_id, titulo, descripcion, fecha, estado in tareas:
        texto = f"{tarea_id}. {titulo}"

        if fecha:
            texto += f" — {fecha}"

        if descripcion:
            texto += f" — {descripcion}"

        lineas.append(texto)

    return "\n".join(lineas)


def consultar_hermes(mensaje):
    memoria = obtener_texto_memoria()
    tareas = obtener_texto_tareas()

    modelo, modo = elegir_modelo(mensaje)
    mensaje_limpio = limpiar_comando_profundo(mensaje)

    prompt = f"""
{PROMPT_SISTEMA}

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

El campo "accion" puede ser:

- "ninguna"
- "crear_tarea"
- "listar_tareas"
- "completar_tarea"

Si Leo dice algo que tiene que hacer:
accion = "crear_tarea"

Ejemplo:

Mensaje:
"Mañana tengo que llamar a Juan"

Respuesta JSON:

{{
    "respuesta": "Listo, agregué la tarea de llamar a Juan.",
    "accion": "crear_tarea",
    "guardar_memoria": false,
    "categoria": "",
    "clave": "",
    "valor": "",
    "tarea_titulo": "Llamar a Juan",
    "tarea_descripcion": "",
    "tarea_fecha": "mañana"
}}

Si Leo pide ver sus tareas:
accion = "listar_tareas"

Si Leo proporciona un dato personal importante:
guardar_memoria = true

No guardes una tarea también como recuerdo personal.

No escribas nada fuera del JSON.
"""

    datos = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.15,
            "num_ctx": 4096
        }
    }

    print(f"Hermes {modo}...", flush=True)

    respuesta_http = requests.post(
        OLLAMA_URL,
        json=datos,
        timeout=120
    )

    respuesta_http.raise_for_status()

    texto = respuesta_http.json()["response"].strip()

    try:
        resultado = json.loads(texto)

    except json.JSONDecodeError:
        return texto

    accion = resultado.get("accion", "ninguna")
    respuesta = resultado.get(
        "respuesta",
        "No pude generar una respuesta."
    )

    if accion == "crear_tarea":
        titulo = str(
            resultado.get("tarea_titulo", "")
        ).strip()

        descripcion = str(
            resultado.get("tarea_descripcion", "")
        ).strip()

        fecha = str(
            resultado.get("tarea_fecha", "")
        ).strip()

        if fecha == "":
            fecha = None

        if titulo:
            tarea_id = crear_tarea(
                titulo,
                descripcion,
                fecha
            )

            print(
                f"✅ Tarea creada #{tarea_id}: {titulo}"
            )

    elif accion == "listar_tareas":
        respuesta = mostrar_tareas()

    elif accion == "completar_tarea":
        pass

    if resultado.get("guardar_memoria") is True:
        categoria = str(
            resultado.get("categoria", "otro")
        ).strip()

        clave = str(
            resultado.get("clave", "")
        ).strip().lower()

        valor = str(
            resultado.get("valor", "")
        ).strip()

        if clave and valor:
            estado = guardar_recuerdo(
                categoria,
                clave,
                valor
            )

            if estado == "creado":
                print(f"🧠 Hermes recordó: {valor}")

            elif estado == "actualizado":
                print(f"🧠 Hermes actualizó: {valor}")

    return respuesta


print()
print("════════════════════════════════")
print("            HERMES")
print("════════════════════════════════")
print()
print("⚡ Cerebro rápido: qwen3:1.7b")
print("🧠 Cerebro profundo: qwen3:4b")
print("🧠 Memoria permanente: activa")
print("✅ Tareas: activas")
print()
print("Escribí 'salir' para terminar.")
print()


while True:

    mensaje = input("Vos: ").strip()

    if not mensaje:
        continue

    if mensaje.lower() == "salir":
        print()
        print("Hermes: Hasta luego, Leo.")
        break

    try:
        respuesta = consultar_hermes(mensaje)

        print()
        print(f"Hermes: {respuesta}")
        print()

    except requests.exceptions.RequestException as error:
        print()
        print(
            "Hermes: Tuve un problema comunicándome "
            "con mi modelo local."
        )
        print(f"Error técnico: {error}")
        print()

    except Exception as error:
        print()
        print("Hermes: Ocurrió un error.")
        print(f"Error técnico: {error}")
        print()

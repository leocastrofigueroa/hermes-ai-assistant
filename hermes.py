import json
import ipaddress
import socket
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import requests

from memoria import (
    crear_base,
    guardar_recuerdo,
    obtener_recuerdos,
    buscar_recuerdos,
    guardar_mensaje_conversacion,
    obtener_historial_conversacion,
    limpiar_historial_conversacion,
    contar_historial_conversacion,
    obtener_historial_antiguo,
    eliminar_historial_hasta,
    obtener_resumen_contexto,
    actualizar_resumen_contexto,
    limpiar_resumen_contexto,
    auditar_contexto_conversacional_db,
    reparar_contexto_conversacional_db,
    crear_nota,
    obtener_notas_activas,
    obtener_nota_por_id,
    modificar_nota,
    eliminar_nota,
    obtener_categorias_notas,
    auditar_notas_db,
    limpiar_notas_db,
    buscar_notas,
    auditar_busqueda_local_db,
    crear_tarea,
    obtener_tareas_pendientes,
    obtener_tareas_por_fecha,
    obtener_tareas_entre_fechas,
    obtener_tareas_completadas_en_fecha,
    completar_tarea,
    obtener_tarea_por_id,
    modificar_tarea,
    crear_rutina,
    obtener_rutinas,
    obtener_rutinas_activas,
    obtener_rutina_por_id,
    modificar_rutina,
    cambiar_estado_rutina,
    eliminar_rutina,
    crear_evento_recurrente,
    obtener_eventos_recurrentes,
    obtener_eventos_recurrentes_activos,
    obtener_evento_recurrente_por_id,
    modificar_evento_recurrente,
    cambiar_estado_evento_recurrente,
    eliminar_evento_recurrente,
    auditar_y_limpiar_eventos_recurrentes,
    crear_evento,
    obtener_eventos_activos,
    obtener_eventos_por_fecha,
    obtener_eventos_entre_fechas,
    obtener_evento_por_id,
    obtener_evento_por_external_uid,
    asignar_external_uid_evento,
    actualizar_evento_desde_calendario,
    auditar_integracion_calendario_db,
    modificar_evento,
    cancelar_evento,
)

from recordatorios import (
    crear_tabla_recordatorios,
    crear_recordatorio,
    obtener_recordatorios_pendientes,
    obtener_recordatorio_por_id,
    obtener_recordatorios_de_evento,
    obtener_recordatorios_de_tarea,
    reprogramar_recordatorios_de_tarea,
    modificar_recordatorio,
    actualizar_recordatorio_vinculado,
    cancelar_recordatorio,
    reprogramar_recordatorios_de_evento,
    cancelar_recordatorios_de_evento,
    cancelar_recordatorios_de_tarea,
    obtener_configuracion_resumen_diario,
    configurar_hora_resumen_diario,
    obtener_hora_resumen_diario,
    auditar_configuracion_resumen_diario,
    obtener_configuracion_resumen_nocturno,
    configurar_hora_resumen_nocturno,
    obtener_hora_resumen_nocturno,
    auditar_configuracion_resumen_nocturno,
)


OLLAMA_URL = "http://localhost:11434/api/generate"

MODELO_RAPIDO = "qwen3:1.7b"
MODELO_PROFUNDO = "qwen3:4b"


crear_base()
crear_tabla_recordatorios()


confirmacion_pendiente = None
ultimo_contexto_edicion = None
ultima_pagina_web = None


MAX_MENSAJES_CONTEXTO = 8
MAX_HISTORIAL_SIN_COMPACTAR = 24
MENSAJES_A_CONSERVAR = 10
MAX_CARACTERES_RESUMEN_CONTEXTO = 6000


def obtener_texto_resumen_contexto():
    contenido, mensajes_compactados, _fecha = obtener_resumen_contexto()

    if not contenido:
        return "Sin resumen anterior."

    return (
        f"{contenido}\n"
        f"[{mensajes_compactados} mensajes anteriores compactados]"
    )


def construir_resumen_extractivo(
    mensajes
):
    lineas = []

    for (
        _mensaje_id,
        rol,
        contenido,
        _fecha_creacion,
    ) in mensajes:
        contenido = re.sub(
            r"\s+",
            " ",
            str(contenido or ""),
        ).strip()

        if not contenido:
            continue

        if len(contenido) > 220:
            contenido = (
                contenido[:217].rstrip()
                + "..."
            )

        etiqueta = (
            "Leo"
            if rol == "usuario"
            else "Hermes"
        )

        lineas.append(
            f"- {etiqueta}: {contenido}"
        )

    return "\n".join(lineas)


def compactar_contexto_conversacional(
    forzar=False
):
    cantidad = contar_historial_conversacion()

    if not forzar and cantidad <= MAX_HISTORIAL_SIN_COMPACTAR:
        return None

    cantidad_compactar = max(
        0,
        cantidad - MENSAJES_A_CONSERVAR,
    )

    if cantidad_compactar <= 0:
        return (
            "No hay suficiente historial para compactar."
            if forzar
            else None
        )

    antiguos = obtener_historial_antiguo(
        cantidad_compactar
    )

    if not antiguos:
        return (
            "No hay historial para compactar."
            if forzar
            else None
        )

    bloque = construir_resumen_extractivo(
        antiguos
    )

    resumen_actual, _total, _fecha = obtener_resumen_contexto()

    partes = [
        parte.strip()
        for parte in (
            resumen_actual,
            bloque,
        )
        if parte and parte.strip()
    ]

    resumen_nuevo = "\n".join(
        partes
    )

    if len(resumen_nuevo) > MAX_CARACTERES_RESUMEN_CONTEXTO:
        resumen_nuevo = resumen_nuevo[
            -MAX_CARACTERES_RESUMEN_CONTEXTO:
        ]

        primer_salto = resumen_nuevo.find(
            "\n"
        )

        if primer_salto >= 0:
            resumen_nuevo = resumen_nuevo[
                primer_salto + 1:
            ]

    ultimo_id = antiguos[-1][0]

    actualizar_resumen_contexto(
        resumen_nuevo,
        len(antiguos),
    )

    eliminar_historial_hasta(
        ultimo_id
    )

    if forzar:
        return (
            f"Listo. Compacté {len(antiguos)} mensajes "
            f"y conservé los {contar_historial_conversacion()} "
            f"más recientes."
        )

    return None


def mostrar_estado_contexto():
    recientes = contar_historial_conversacion()
    _contenido, compactados, _fecha = obtener_resumen_contexto()

    return (
        f"Contexto: {recientes} mensajes recientes "
        f"y {compactados} mensajes compactados."
    )


def es_comando_compactar_contexto(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "compacta el contexto",
            "compactar el contexto",
            "comprime el contexto",
            "comprimir el contexto",
        )
    )


def es_consulta_estado_contexto(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "estado del contexto",
            "como esta el contexto",
            "cuanto contexto",
        )
    )


def es_auditoria_contexto_conversacional(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "audita el contexto",
            "auditar el contexto",
            "audita el contexto conversacional",
            "revisa el contexto conversacional",
            "revisar el contexto conversacional",
        )
    )


def es_reparacion_contexto_conversacional(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "repara el contexto",
            "reparar el contexto",
            "limpia errores del contexto",
            "corrige el contexto",
            "corregir el contexto",
        )
    )


def auditar_contexto_conversacional():
    datos = auditar_contexto_conversacional_db()

    problemas = []

    if datos["roles_invalidos"]:
        problemas.append(
            f'{datos["roles_invalidos"]} roles inválidos'
        )

    if datos["mensajes_vacios"]:
        problemas.append(
            f'{datos["mensajes_vacios"]} mensajes vacíos'
        )

    if datos["resumen_faltante"]:
        problemas.append(
            "falta el registro de resumen"
        )

    if datos["resumen_demasiado_largo"]:
        problemas.append(
            "el resumen supera el límite"
        )

    if datos["compactados_invalidos"]:
        problemas.append(
            "el contador de compactados es inválido"
        )

    if datos["total_recientes"] > MAX_HISTORIAL_SIN_COMPACTAR:
        problemas.append(
            "hay demasiados mensajes recientes sin compactar"
        )

    if not problemas:
        return (
            "El contexto está correcto. "
            f'Recientes: {datos["total_recientes"]}. '
            f'Compactados: {datos["mensajes_compactados"]}.'
        )

    return (
        "Encontré problemas en el contexto: "
        + "; ".join(problemas)
        + "."
    )


def reparar_contexto_conversacional():
    resultado = reparar_contexto_conversacional_db()

    compactacion = compactar_contexto_conversacional()

    auditoria = auditar_contexto_conversacional_db()

    correcto = (
        auditoria["roles_invalidos"] == 0
        and auditoria["mensajes_vacios"] == 0
        and not auditoria["resumen_faltante"]
        and not auditoria["resumen_demasiado_largo"]
        and not auditoria["compactados_invalidos"]
        and auditoria["total_recientes"]
        <= MAX_HISTORIAL_SIN_COMPACTAR
    )

    if correcto:
        return (
            "Listo. El contexto quedó limpio y consistente. "
            f'Recientes: {auditoria["total_recientes"]}. '
            f'Compactados: {auditoria["mensajes_compactados"]}.'
        )

    return (
        "La reparación terminó, pero todavía hay "
        "inconsistencias. Ejecutá: Auditá el contexto."
    )


def es_comando_mantenimiento_contexto(
    mensaje
):
    return (
        es_limpieza_contexto_conversacional(
            mensaje
        )
        or es_comando_compactar_contexto(
            mensaje
        )
        or es_consulta_estado_contexto(
            mensaje
        )
        or es_auditoria_contexto_conversacional(
            mensaje
        )
        or es_reparacion_contexto_conversacional(
            mensaje
        )
    )


def obtener_texto_contexto_conversacional():
    historial = obtener_historial_conversacion(
        MAX_MENSAJES_CONTEXTO
    )

    if not historial:
        return (
            "Sin conversación reciente."
        )

    lineas = []

    for (
        _mensaje_id,
        rol,
        contenido,
        _fecha_creacion,
    ) in historial:

        etiqueta = (
            "Leo"
            if rol == "usuario"
            else "Hermes"
        )

        lineas.append(
            f"{etiqueta}: {contenido}"
        )

    return "\\n".join(
        lineas
    )


def obtener_referente_conversacional_reciente():
    historial = obtener_historial_conversacion(
        20
    )

    for (
        _mensaje_id,
        rol,
        contenido,
        _fecha_creacion,
    ) in reversed(historial):
        if rol != "usuario":
            continue

        contenido = str(
            contenido or ""
        ).strip()

        if not contenido:
            continue

        texto = normalizar_texto(
            contenido
        )

        texto_limpio = re.sub(
            r"[^a-z0-9ñü\s]",
            " ",
            texto,
        )

        texto_limpio = re.sub(
            r"\s+",
            " ",
            texto_limpio,
        ).strip()

        if texto_limpio in (
            "y cuando",
            "cuando",
            "y donde",
            "donde",
            "y con quien",
            "con quien",
            "y cual",
            "cual",
        ):
            continue

        if (
            "que te dije" in texto_limpio
            or "que estaba pensando" in texto_limpio
        ):
            continue

        return contenido

    return None


def es_referencia_natural_corta(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    texto = re.sub(
        r"[^a-z0-9ñü\\s]",
        " ",
        texto,
    )

    texto = re.sub(
        r"\\s+",
        " ",
        texto,
    ).strip()

    return texto in (
        "y cuando",
        "cuando",
        "y donde",
        "donde",
        "y con quien",
        "con quien",
        "y cual",
        "cual",
    )


def resolver_referencia_natural_corta(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    texto = re.sub(
        r"[^a-z0-9ñü\s]",
        " ",
        texto,
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto,
    ).strip()

    referente = obtener_referente_conversacional_reciente()

    if not referente:
        return (
            "No tengo suficiente contexto reciente "
            "para saber a qué te referís."
        )

    referente_normalizado = normalizar_texto(
        referente
    )

    if texto in (
        "y cuando",
        "cuando",
    ):
        pares_tiempo = (
            ("el mes que viene", "El mes que viene."),
            ("el proximo mes", "El próximo mes."),
            ("la semana que viene", "La semana que viene."),
            ("la proxima semana", "La próxima semana."),
            ("pasado manana", "Pasado mañana."),
            ("manana", "Mañana."),
            ("hoy", "Hoy."),
            ("esta semana", "Esta semana."),
            ("este mes", "Este mes."),
        )

        for expresion, respuesta in pares_tiempo:
            if expresion in referente_normalizado:
                return respuesta

        return (
            "En ese mensaje no habías especificado cuándo."
        )

    if texto in (
        "y donde",
        "donde",
    ):
        patrones = (
            r"\bviaj(?:ar|o|ando)\s+a\s+([^,.]+)",
            r"\b(?:ir|voy|yendo)\s+a\s+([^,.]+)",
            r"\b(?:volver|vuelvo)\s+a\s+([^,.]+)",
            r"\b(?:mudarme|mudarse)\s+a\s+([^,.]+)",
        )

        for patron in patrones:
            coincidencia = re.search(
                patron,
                referente,
                flags=re.IGNORECASE,
            )

            if not coincidencia:
                continue

            lugar = coincidencia.group(1).strip()

            cortes = (
                " el mes que viene",
                " el próximo mes",
                " el proximo mes",
                " la semana que viene",
                " la próxima semana",
                " la proxima semana",
                " mañana",
                " manana",
                " pasado mañana",
                " pasado manana",
                " hoy",
            )

            lugar_normalizado = normalizar_texto(
                lugar
            )

            posiciones = []

            for corte in cortes:
                pos = lugar_normalizado.find(
                    normalizar_texto(corte)
                )

                if pos >= 0:
                    posiciones.append(pos)

            if posiciones:
                lugar = lugar[
                    :min(posiciones)
                ].strip()

            lugar = lugar.strip(
                " .,-"
            )

            if lugar:
                return f"En {lugar}."

        return (
            "En ese mensaje no habías especificado dónde."
        )

    if texto in (
        "y con quien",
        "con quien",
    ):
        coincidencia = re.search(
            r"\bcon\s+([^,.]+)",
            referente,
            flags=re.IGNORECASE,
        )

        if coincidencia:
            persona = coincidencia.group(1).strip(
                " .,-"
            )

            return f"Con {persona}."

        return (
            "En ese mensaje no habías especificado con quién."
        )

    return None


def es_limpieza_contexto_conversacional(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "olvida esta conversacion",
        "olvidate de esta conversacion",
        "borra el contexto de esta conversacion",
        "limpia el contexto de esta conversacion",
        "limpia la conversacion reciente",
        "reinicia el contexto conversacional",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def limpiar_contexto_conversacional_desde_hermes():
    cantidad = limpiar_historial_conversacion()
    limpiar_resumen_contexto()

    return (
        "Listo. Limpié el contexto conversacional reciente "
        f"({cantidad} mensajes). La memoria permanente no fue modificada."
    )


# ==========================================================
# NOTAS
# ==========================================================

def es_creacion_nota(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        "anota ",
        "anota que ",
        "crea una nota ",
        "crea una nota que ",
        "guarda una nota ",
        "guardame una nota ",
        "guardá una nota ",
        "nota: ",
    )

    return any(
        texto.startswith(
            normalizar_texto(patron)
        )
        for patron in patrones
    )


def extraer_contenido_nota(
    mensaje
):
    texto_original = str(
        mensaje or ""
    ).strip()

    patrones = (
        r"^\s*anot[áa]\s+(?:que\s+)?",
        r"^\s*cre[áa]\s+una\s+nota\s+(?:que\s+)?",
        r"^\s*guard[áa](?:me)?\s+una\s+nota\s+(?:que\s+)?",
        r"^\s*nota\s*:\s*",
    )

    contenido = texto_original

    for patron in patrones:
        nuevo = re.sub(
            patron,
            "",
            contenido,
            count=1,
            flags=re.IGNORECASE,
        )

        if nuevo != contenido:
            contenido = nuevo.strip()
            break

    return contenido.strip()


def extraer_categoria_nota(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    coincidencia = re.search(
        r"\b(?:en|categoria|categoría)\s+"
        r"(?:la\s+categoria\s+|la\s+categoría\s+)?"
        r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_-]+)\s*$",
        texto,
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return "general"

    categoria = coincidencia.group(1).strip().lower()

    return categoria or "general"


def quitar_categoria_del_contenido(
    contenido
):
    return re.sub(
        r"\s+\b(?:en|categoria|categoría)\s+"
        r"(?:la\s+categoria\s+|la\s+categoría\s+)?"
        r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_-]+\s*$",
        "",
        str(contenido),
        flags=re.IGNORECASE,
    ).strip()


def crear_nota_desde_mensaje(
    mensaje
):
    categoria = extraer_categoria_nota(
        mensaje
    )

    contenido = extraer_contenido_nota(
        mensaje
    )

    contenido = quitar_categoria_del_contenido(
        contenido
    )

    if not contenido:
        return (
            "Decime qué querés anotar."
        )

    titulo = contenido

    if len(titulo) > 70:
        titulo = titulo[:67].rstrip() + "..."

    nota_id = crear_nota(
        titulo,
        contenido,
        categoria,
    )

    return (
        f"Listo. Guardé la nota #{nota_id} "
        f"en la categoría {categoria}: {titulo}"
    )


def es_edicion_nota(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"\b(?:edita|editar|modifica|modificar|cambia|cambiar)\s+"
        r"(?:la\s+)?nota\s+#?\d+\b",
    )

    return any(
        re.search(
            patron,
            texto
        )
        for patron in patrones
    )


def editar_nota_desde_mensaje(
    mensaje
):
    coincidencia_id = re.search(
        r"\bnota\s+#?(\d+)\b",
        normalizar_texto(
            mensaje
        ),
    )

    if not coincidencia_id:
        return (
            "Decime qué nota querés editar."
        )

    nota_id = int(
        coincidencia_id.group(1)
    )

    nota = obtener_nota_por_id(
        nota_id
    )

    if not nota or nota[3] != "activa":
        return (
            f"No encontré una nota activa #{nota_id}."
        )

    contenido_nuevo = re.sub(
        r"^.*?\bnota\s+#?\d+\b",
        "",
        str(mensaje),
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    contenido_nuevo = re.sub(
        r"^(?:por|a|como|que\s+diga|y\s+pone|y\s+poné|y\s+pon)\s+",
        "",
        contenido_nuevo,
        flags=re.IGNORECASE,
    ).strip()

    if not contenido_nuevo:
        return (
            "Decime cuál querés que sea el nuevo contenido."
        )

    titulo_nuevo = contenido_nuevo

    if len(titulo_nuevo) > 70:
        titulo_nuevo = (
            titulo_nuevo[:67].rstrip()
            + "..."
        )

    estado, _ = modificar_nota(
        nota_id,
        titulo=titulo_nuevo,
        contenido=contenido_nuevo,
    )

    if estado == "actualizada":
        return (
            f"Listo. Actualicé la nota #{nota_id}: "
            f"{titulo_nuevo}"
        )

    return (
        f"No pude actualizar la nota #{nota_id}."
    )


def es_eliminacion_nota(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"\b(?:elimina|eliminar|borra|borrar|quita|quitar)\s+"
        r"(?:la\s+)?nota\s+#?\d+\b",
    )

    return any(
        re.search(
            patron,
            texto
        )
        for patron in patrones
    )


def eliminar_nota_desde_mensaje(
    mensaje
):
    coincidencia = re.search(
        r"\bnota\s+#?(\d+)\b",
        normalizar_texto(
            mensaje
        ),
    )

    if not coincidencia:
        return (
            "Decime qué nota querés eliminar."
        )

    nota_id = int(
        coincidencia.group(1)
    )

    estado, _ = eliminar_nota(
        nota_id
    )

    if estado == "eliminada":
        return (
            f"Listo. Eliminé la nota #{nota_id}."
        )

    if estado == "ya_eliminada":
        return (
            f"La nota #{nota_id} ya estaba eliminada."
        )

    return (
        f"No encontré la nota #{nota_id}."
    )




def es_cambio_categoria_nota(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"\b(?:move|mover|pasa|pasar|cambia|cambiar)\s+"
            r"(?:la\s+)?nota\s+#?\d+\b.*\b(?:categoria|categoría|a)\b",
            texto
        )
    )


def cambiar_categoria_nota_desde_mensaje(
    mensaje
):
    coincidencia_id = re.search(
        r"\bnota\s+#?(\d+)\b",
        normalizar_texto(
            mensaje
        ),
    )

    if not coincidencia_id:
        return "Decime qué nota querés mover."

    nota_id = int(
        coincidencia_id.group(1)
    )

    nota = obtener_nota_por_id(
        nota_id
    )

    if not nota or nota[3] != "activa":
        return f"No encontré una nota activa #{nota_id}."

    coincidencia_categoria = re.search(
        r"\b(?:categoria|categoría|a)\s+"
        r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_-]+)\s*$",
        str(mensaje),
        flags=re.IGNORECASE,
    )

    if not coincidencia_categoria:
        return "Decime a qué categoría querés moverla."

    categoria = coincidencia_categoria.group(1).strip().lower()

    modificar_nota(
        nota_id,
        categoria=categoria,
    )

    return (
        f"Listo. Moví la nota #{nota_id} "
        f"a la categoría {categoria}."
    )


def es_consulta_categorias_notas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        expresion in texto
        for expresion in (
            "categorias de notas",
            "categorias de mis notas",
            "que categorias tengo",
            "que categorias de notas tengo",
        )
    )


def mostrar_categorias_notas():
    categorias = obtener_categorias_notas()

    if not categorias:
        return "No tenés categorías de notas activas."

    lineas = [
        "Categorías de notas:"
    ]

    for categoria, cantidad in categorias:
        lineas.append(
            f"- {categoria}: {cantidad}"
        )

    return "\n".join(
        lineas
    )


def es_consulta_notas_por_categoria(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"\bnotas\s+(?:de|en)\s+"
            r"[a-z0-9ñü_-]+\b",
            texto
        )
    )


def mostrar_notas_por_categoria_desde_mensaje(
    mensaje
):
    coincidencia = re.search(
        r"\bnotas\s+(?:de|en)\s+"
        r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_-]+)\b",
        str(mensaje),
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return None

    categoria = coincidencia.group(1).strip().lower()

    notas = obtener_notas_activas(
        categoria=categoria
    )

    if not notas:
        return (
            f"No tenés notas activas en la categoría {categoria}."
        )

    lineas = [
        f"Notas en {categoria}:"
    ]

    for nota in notas:
        lineas.append(
            f"#{nota[0]} — {nota[1]}"
        )

    return "\n".join(
        lineas
    )




def es_busqueda_notas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"^(?:busca|buscar|buscame|búscame)\s+(?:en\s+)?(?:mis\s+)?notas\b",
        r"^(?:busca|buscar|buscame|búscame)\s+notas\b",
        r"^(?:encontra|encontrá|encontrar)\s+(?:en\s+)?(?:mis\s+)?notas\b",
    )

    return any(
        re.search(
            patron,
            texto
        )
        for patron in patrones
    )


def extraer_termino_busqueda_notas(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    patrones = (
        r"^\s*busc[áa](?:me)?\s+en\s+mis\s+notas\s+",
        r"^\s*busc[áa](?:me)?\s+notas\s+",
        r"^\s*buscar\s+en\s+mis\s+notas\s+",
        r"^\s*buscar\s+notas\s+",
        r"^\s*encontr[áa]\s+en\s+mis\s+notas\s+",
        r"^\s*encontrar\s+en\s+mis\s+notas\s+",
    )

    termino = texto

    for patron in patrones:
        nuevo = re.sub(
            patron,
            "",
            termino,
            count=1,
            flags=re.IGNORECASE,
        )

        if nuevo != termino:
            termino = nuevo.strip()
            break

    termino = re.sub(
        r"^(?:sobre|de|con|que\s+digan|que\s+tengan)\s+",
        "",
        termino,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    return termino.strip(
        " .,:;-"
    )


def buscar_notas_desde_mensaje(
    mensaje
):
    termino = extraer_termino_busqueda_notas(
        mensaje
    )

    if not termino:
        return (
            "Decime qué querés buscar en tus notas."
        )

    resultados = buscar_notas(
        termino
    )

    if not resultados:
        return (
            f'No encontré notas que coincidan con "{termino}".'
        )

    lineas = [
        f'Resultados para "{termino}":'
    ]

    for nota in resultados:
        categoria = (
            nota[6]
            if len(nota) > 6 and nota[6]
            else "general"
        )

        lineas.append(
            f"#{nota[0]} [{categoria}] — {nota[1]}"
        )

    return "\n".join(
        lineas
    )




def es_auditoria_notas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "audita las notas",
            "auditar las notas",
            "revisa las notas",
            "revisar las notas",
            "audita el sistema de notas",
        )
    )


def auditar_notas():
    datos = auditar_notas_db()

    problemas = []

    if datos["estados_invalidos"]:
        problemas.append(
            f'{datos["estados_invalidos"]} estados inválidos'
        )

    if datos["titulos_vacios"]:
        problemas.append(
            f'{datos["titulos_vacios"]} títulos vacíos'
        )

    if datos["categorias_vacias"]:
        problemas.append(
            f'{datos["categorias_vacias"]} categorías vacías'
        )

    if not problemas:
        return (
            "Las notas están correctas. "
            f'Activas: {datos["activas"]}. '
            f'Eliminadas: {datos["eliminadas"]}.'
        )

    return (
        "Encontré problemas en las notas: "
        + "; ".join(problemas)
        + "."
    )


def es_limpieza_notas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "limpia las notas",
            "limpiar las notas",
            "repara las notas",
            "reparar las notas",
            "corrige las notas",
            "corregir las notas",
        )
    )


def limpiar_notas():
    limpiar_notas_db()

    datos = auditar_notas_db()

    correcto = (
        datos["estados_invalidos"] == 0
        and datos["titulos_vacios"] == 0
        and datos["categorias_vacias"] == 0
    )

    if correcto:
        return (
            "Listo. El sistema de notas quedó limpio y consistente. "
            f'Activas: {datos["activas"]}. '
            f'Eliminadas: {datos["eliminadas"]}.'
        )

    return (
        "La limpieza terminó, pero todavía hay inconsistencias. "
        "Ejecutá: Auditá las notas."
    )




def es_consulta_notas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "mis notas",
        "mostra mis notas",
        "mostrar mis notas",
        "lista mis notas",
        "listar mis notas",
        "que notas tengo",
        "que tengo anotado",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def mostrar_notas():
    notas = obtener_notas_activas()

    if not notas:
        return "No tenés notas guardadas."

    lineas = [
        "Notas:"
    ]

    for nota in notas:
        nota_id = nota[0]
        titulo = nota[1]
        categoria = (
            nota[6]
            if len(nota) > 6 and nota[6]
            else "general"
        )

        lineas.append(
            f"#{nota_id} [{categoria}] — {titulo}"
        )

    return "\n".join(
        lineas
    )


def es_consulta_nota_por_id(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"\bnota\s+#?\d+\b",
            texto
        )
    )


def mostrar_nota_por_id_desde_mensaje(
    mensaje
):
    coincidencia = re.search(
        r"\bnota\s+#?(\d+)\b",
        normalizar_texto(
            mensaje
        ),
    )

    if not coincidencia:
        return None

    nota_id = int(
        coincidencia.group(1)
    )

    nota = obtener_nota_por_id(
        nota_id
    )

    if not nota or nota[3] != "activa":
        return (
            f"No encontré una nota activa #{nota_id}."
        )

    categoria = (
        nota[6]
        if len(nota) > 6 and nota[6]
        else "general"
    )

    return (
        f"Nota #{nota[0]} [{categoria}] — {nota[1]}\n"
        f"{nota[2]}"
    )




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
Una RUTINA es una acción o recordatorio que se repite
con una frecuencia definida, por ejemplo todos los días
o todos los lunes.

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

    return crear_evento_con_control_conflictos(
        titulo=titulo,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        descripcion="",
    )


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

    texto = normalizar_texto(
        mensaje
    )

    # Si Leo menciona un ID explícito, ese ID manda.
    coincidencia_id = re.search(
        r"\b(?:evento\s*)?#\s*(\d+)\b",
        texto
    )

    if not coincidencia_id:
        coincidencia_id = re.search(
            r"\bevento\s+(\d+)\b",
            texto
        )

    if coincidencia_id:
        evento_id = int(
            coincidencia_id.group(1)
        )

        for evento in eventos:
            if evento[0] == evento_id:
                return evento

        return None

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
# CAMBIO COMBINADO DE PRIORIDAD + FECHA DE TAREA
# ==========================================================

def es_cambio_combinado_tarea(
    mensaje
):
    prioridad = extraer_prioridad_tarea(
        mensaje
    )

    fecha_nueva = extraer_fecha_del_mensaje(
        mensaje
    )

    if not prioridad or not fecha_nueva:
        return False

    texto = normalizar_texto(
        mensaje
    )

    menciona_tarea = (
        "tarea" in texto
        or bool(
            re.search(
                r"\btarea\s*#?\s*\d+\b",
                texto
            )
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "pone prioridad",
            "pon prioridad",
            "cambia la prioridad",
            "cambiar la prioridad",
            "marca como urgente",
            "marcar como urgente",
            "es urgente",
            "pasa",
            "pasala",
            "pasalo",
            "pasar",
            "move",
            "mover",
            "reprograma",
            "reprogramar",
            "corre",
            "correr",
        )
    )

    return (
        prioridad is not None
        and fecha_nueva is not None
        and (
            menciona_tarea
            or accion
        )
    )


def cambiar_prioridad_y_fecha_tarea_desde_mensaje(
    mensaje
):
    prioridad = extraer_prioridad_tarea(
        mensaje
    )

    fecha_nueva = extraer_fecha_del_mensaje(
        mensaje
    )

    if not prioridad:

        return (
            "No pude identificar la prioridad. "
            "Podés usar alta, media o baja."
        )

    if not fecha_nueva:

        return (
            "No pude identificar la nueva fecha "
            "de la tarea."
        )

    tarea = obtener_tarea_objetivo_para_edicion(
        mensaje
    )

    if not tarea:

        return (
            "No pude identificar qué tarea "
            "querés modificar."
        )

    fecha_anterior = tarea[3]

    estado, _ = modificar_tarea(
        tarea[0],
        fecha=fecha_nueva,
        prioridad=prioridad
    )

    if estado != "actualizado":

        return (
            "No pude actualizar esa tarea."
        )

    actualizados = 0
    cancelados = 0

    if (
        fecha_anterior
        and fecha_anterior != fecha_nueva
    ):

        (
            actualizados,
            cancelados
        ) = reprogramar_recordatorios_de_tarea(
            tarea[0],
            fecha_anterior,
            fecha_nueva
        )

    respuesta = (
        f"Listo. La tarea #{tarea[0]}: "
        f"{tarea[1]} quedó con prioridad "
        f"{prioridad} y fecha "
        f"{fecha_para_mostrar(fecha_nueva)}."
    )

    if actualizados == 1:

        respuesta += (
            " También reprogramé 1 recordatorio "
            "vinculado."
        )

    elif actualizados > 1:

        respuesta += (
            f" También reprogramé "
            f"{actualizados} recordatorios "
            f"vinculados."
        )

    if cancelados == 1:

        respuesta += (
            " Cancelé 1 recordatorio vinculado "
            "porque su nuevo horario ya había pasado."
        )

    elif cancelados > 1:

        respuesta += (
            f" Cancelé {cancelados} recordatorios "
            f"vinculados porque sus nuevos horarios "
            f"ya habían pasado."
        )

    return respuesta


# ==========================================================
# PRIORIDADES DE TAREAS
# ==========================================================

def extraer_prioridad_tarea(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if any(
        expresion in texto
        for expresion in (
            "urgente",
            "prioridad alta",
            "prioridad maxima",
            "muy importante",
        )
    ):
        return "alta"

    if any(
        expresion in texto
        for expresion in (
            "prioridad baja",
            "poca prioridad",
            "no es urgente",
            "cuando pueda",
        )
    ):
        return "baja"

    if any(
        expresion in texto
        for expresion in (
            "prioridad media",
            "prioridad normal",
            "prioridad intermedia",
        )
    ):
        return "media"

    return None


def etiqueta_prioridad(
    prioridad
):
    valor = (
        prioridad
        or "media"
    ).lower()

    if valor == "alta":
        return "ALTA"

    if valor == "baja":
        return "BAJA"

    return "MEDIA"


def es_cambio_prioridad_tarea(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    prioridad = extraer_prioridad_tarea(
        mensaje
    )

    if not prioridad:
        return False

    menciona_tarea = (
        "tarea" in texto
        or bool(
            re.search(
                r"\btarea\s*#?\s*\d+\b",
                texto
            )
        )
    )

    accion_explicita = any(
        expresion in texto
        for expresion in (
            "pone prioridad",
            "pon prioridad",
            "cambia la prioridad",
            "cambiar la prioridad",
            "marca como urgente",
            "marcar como urgente",
            "es urgente",
            "prioridad alta",
            "prioridad media",
            "prioridad normal",
            "prioridad baja",
        )
    )

    return (
        prioridad is not None
        and (
            menciona_tarea
            or accion_explicita
        )
    )


def cambiar_prioridad_tarea_desde_mensaje(
    mensaje
):
    prioridad = extraer_prioridad_tarea(
        mensaje
    )

    if not prioridad:
        return (
            "No pude identificar la prioridad. "
            "Podés usar alta, media o baja."
        )

    tarea = obtener_tarea_objetivo_para_edicion(
        mensaje
    )

    if not tarea:

        return (
            "No pude identificar qué tarea "
            "querés priorizar."
        )

    estado, _ = modificar_tarea(
        tarea[0],
        prioridad=prioridad
    )

    if estado != "actualizado":

        return (
            "No pude cambiar la prioridad "
            "de esa tarea."
        )

    return (
        f"Listo. La tarea #{tarea[0]}: "
        f"{tarea[1]} quedó con prioridad "
        f"{prioridad}."
    )


# ==========================================================
# CAMBIO DE HORARIO DE AVISO DE TAREAS
# ==========================================================

def es_cambio_horario_aviso_tarea(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_tarea = (
        "tarea" in texto
    )

    menciona_aviso = any(
        palabra in texto
        for palabra in (
            "aviso",
            "recordatorio",
            "recordame",
            "recuerdo",
        )
    )

    accion = any(
        palabra in texto
        for palabra in (
            "cambia",
            "cambiar",
            "pasa",
            "pasar",
            "move",
            "mover",
            "reprograma",
            "reprogramar",
            "corre",
            "correr",
        )
    )

    menciona_hora = bool(
        re.search(
            r"\b(?:a\s+las?|para\s+las?)\s+"
            r"\d{1,2}(?::\d{2})?\b",
            texto
        )
    )

    return (
        menciona_tarea
        and menciona_aviso
        and accion
        and menciona_hora
    )


def cambiar_horario_aviso_tarea_desde_mensaje(
    mensaje
):
    tarea = obtener_tarea_objetivo_para_edicion(
        mensaje
    )

    if not tarea:

        return (
            "No pude identificar a qué tarea "
            "pertenece el aviso que querés cambiar."
        )

    recordatorios = obtener_recordatorios_de_tarea(
        tarea[0]
    )

    if not recordatorios:

        return (
            f"La tarea #{tarea[0]}: {tarea[1]} "
            f"no tiene recordatorios vinculados pendientes."
        )

    hora_nueva, _ = extraer_horas_del_mensaje(
        mensaje
    )

    if not hora_nueva:

        return (
            "No pude identificar la nueva hora "
            "del aviso."
        )

    if len(recordatorios) > 1:

        return (
            f"La tarea #{tarea[0]}: {tarea[1]} tiene "
            f"{len(recordatorios)} recordatorios vinculados. "
            f"Indicame el número del recordatorio que querés cambiar."
        )

    recordatorio = recordatorios[0]

    try:
        momento_actual = datetime.fromisoformat(
            recordatorio[3]
        )

    except ValueError:

        return (
            "El recordatorio vinculado tiene una fecha "
            "inválida y no pude modificarlo."
        )

    nuevo_momento = momento_actual.replace(
        hour=int(
            hora_nueva.split(":")[0]
        ),
        minute=int(
            hora_nueva.split(":")[1]
        ),
        second=0,
        microsecond=0,
    )

    if nuevo_momento <= datetime.now():

        return (
            "Ese nuevo horario ya pasó. "
            "Elegí una hora futura."
        )

    estado, recordatorio_id = modificar_recordatorio(
        recordatorio[0],
        nuevo_momento.isoformat()
    )

    if estado == "duplicado":

        return (
            f"Ya existe otro recordatorio pendiente "
            f"con ese horario como #{recordatorio_id}."
        )

    if estado != "actualizado":

        return (
            "No pude actualizar ese recordatorio."
        )

    return (
        f"Listo. Cambié el aviso de la tarea "
        f"#{tarea[0]}: {tarea[1]} "
        f"de {momento_actual.strftime('%H:%M')} "
        f"a {hora_nueva}. "
        f"El día sigue siendo "
        f"{fecha_para_mostrar(nuevo_momento.date().isoformat())}."
    )


# ==========================================================
# EDICIÓN DE FECHA DE TAREAS
# ==========================================================

def es_modificacion_fecha_tarea(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_tarea = (
        "tarea" in texto
    )

    accion = any(
        palabra in texto
        for palabra in (
            "move",
            "mover",
            "pasa",
            "pasar",
            "cambia",
            "cambiar",
            "reprograma",
            "reprogramar",
            "corre",
            "correr",
        )
    )

    return (
        menciona_tarea
        and accion
    )


def obtener_tarea_objetivo_para_edicion(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

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

        if (
            tarea
            and tarea[4] == "pendiente"
        ):
            return tarea

    return buscar_tarea_desde_mensaje(
        mensaje
    )


def modificar_fecha_tarea_desde_mensaje(
    mensaje
):
    tarea = obtener_tarea_objetivo_para_edicion(
        mensaje
    )

    if not tarea:

        return (
            "No pude identificar qué tarea "
            "querés mover."
        )

    fecha_nueva = extraer_fecha_del_mensaje(
        mensaje
    )

    if not fecha_nueva:

        return (
            f"¿A qué día querés mover la tarea "
            f"#{tarea[0]}: {tarea[1]}?"
        )

    fecha_anterior = tarea[3]

    if not fecha_anterior:

        estado, _ = modificar_tarea(
            tarea[0],
            fecha=fecha_nueva
        )

        if estado != "actualizado":

            return (
                "No pude actualizar esa tarea."
            )

        return (
            f"Listo. Moví la tarea "
            f"#{tarea[0]}: {tarea[1]} "
            f"al {fecha_para_mostrar(fecha_nueva)}."
        )

    estado, _ = modificar_tarea(
        tarea[0],
        fecha=fecha_nueva
    )

    if estado != "actualizado":

        return (
            "No pude actualizar esa tarea."
        )

    actualizados, cancelados = reprogramar_recordatorios_de_tarea(
        tarea[0],
        fecha_anterior,
        fecha_nueva
    )

    respuesta = (
        f"Listo. Moví la tarea "
        f"#{tarea[0]}: {tarea[1]} "
        f"al {fecha_para_mostrar(fecha_nueva)}."
    )

    if actualizados == 1:

        respuesta += (
            " También reprogramé 1 recordatorio "
            "vinculado."
        )

    elif actualizados > 1:

        respuesta += (
            f" También reprogramé "
            f"{actualizados} recordatorios "
            f"vinculados."
        )

    if cancelados == 1:

        respuesta += (
            " Cancelé 1 recordatorio vinculado "
            "porque su nuevo horario ya había pasado."
        )

    elif cancelados > 1:

        respuesta += (
            f" Cancelé {cancelados} recordatorios "
            f"vinculados porque sus nuevos horarios "
            f"ya habían pasado."
        )

    return respuesta


# ==========================================================
# RECORDATORIOS VINCULADOS A TAREAS
# ==========================================================

def buscar_tarea_desde_mensaje(
    mensaje
):
    tareas = obtener_tareas_pendientes()

    candidatos = []

    for tarea in tareas:

        puntuacion = puntuacion_coincidencia(
            mensaje,
            tarea[1]
        )

        if puntuacion > 0:

            candidatos.append(
                (
                    puntuacion,
                    tarea,
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda elemento: (
            -elemento[0],
            elemento[1][3] or "9999-12-31",
            elemento[1][0],
        )
    )

    return candidatos[0][1]


def es_recordatorio_vinculado_tarea(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    tiene_orden = es_orden_recordatorio(
        mensaje
    )

    menciona_tarea = bool(
        re.search(
            r"\b(?:la\s+)?tarea\b",
            texto
        )
    )

    return (
        tiene_orden
        and menciona_tarea
    )


def crear_recordatorio_vinculado_tarea_desde_mensaje(
    mensaje
):
    tarea = buscar_tarea_desde_mensaje(
        mensaje
    )

    if not tarea:

        return (
            "No pude identificar a qué tarea "
            "querés vincular el recordatorio."
        )

    fecha = extraer_fecha_del_mensaje(
        mensaje
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    if not fecha:
        fecha = tarea[3]

    if not fecha:

        return (
            f"La tarea #{tarea[0]}: {tarea[1]} no tiene fecha. "
            f"Decime qué día querés que te avise."
        )

    if not hora:

        return (
            f"Necesito saber a qué hora querés que te recuerde "
            f"la tarea {tarea[1]}."
        )

    momento = datetime.fromisoformat(
        f"{fecha}T{hora}:00"
    )

    if momento <= datetime.now():

        return (
            "Ese momento ya pasó."
        )

    existentes = obtener_recordatorios_de_tarea(
        tarea[0]
    )

    for recordatorio in existentes:

        if recordatorio[3] == momento.isoformat():

            return (
                f"Ya tenés ese aviso para la tarea "
                f"#{tarea[0]} como recordatorio "
                f"#{recordatorio[0]}."
            )

    mensaje_recordatorio = (
        f"Tarea pendiente: {tarea[1]}."
    )

    estado, recordatorio_id = crear_recordatorio(
        titulo=tarea[1],
        fecha_hora=momento.isoformat(),
        mensaje=mensaje_recordatorio,
        tarea_id=tarea[0],
    )

    if estado == "duplicado":

        return (
            f"Ya tenés ese recordatorio "
            f"programado como #{recordatorio_id}."
        )

    return (
        f"Listo. Creé el recordatorio "
        f"#{recordatorio_id} vinculado a la tarea "
        f"#{tarea[0]}: {tarea[1]}, para "
        f"{fecha_para_mostrar(fecha)} "
        f"a las {hora}."
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
    omitir_control_conflictos=False,
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

    if (
        not omitir_control_conflictos
        and hora_final
    ):
        conflictos = buscar_conflictos_para_evento(
            fecha=fecha_final,
            hora_inicio=hora_final,
            hora_fin=hora_fin_final,
            excluir_evento_id=evento_id,
        )

        if conflictos:
            global confirmacion_pendiente

            confirmacion_pendiente = {
                "tipo": "mover_evento_con_conflicto",
                "evento": evento,
                "fecha_nueva": fecha_final,
                "hora_nueva": hora_final,
                "hora_fin_nueva": hora_fin_final,
                "conflictos": conflictos,
            }

            return (
                "⚠️ Ese cambio se superpone con "
                f"{describir_conflictos_para_aviso(conflictos)}. "
                "¿Querés mover el evento igualmente?"
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


def procesar_confirmacion_mover_evento_con_conflicto(
    mensaje,
    pendiente,
):
    global confirmacion_pendiente

    texto = normalizar_texto(
        mensaje
    )

    negativas = (
        "no",
        "cancelalo",
        "cancelala",
        "cancela",
        "dejalo",
        "dejala",
        "olvidalo",
        "olvidala",
        "no lo muevas",
        "no la muevas",
    )

    afirmativas = (
        "si",
        "sí",
        "dale",
        "mover igual",
        "movelo",
        "movela",
        "confirmo",
        "hacelo",
        "hazlo",
        "igual",
    )

    if any(
        expresion == texto
        or expresion in texto
        for expresion in negativas
    ):
        confirmacion_pendiente = None

        return (
            "Perfecto. Dejé el evento como estaba."
        )

    if any(
        expresion == texto
        or expresion in texto
        for expresion in afirmativas
    ):
        evento = pendiente["evento"]

        confirmacion_pendiente = None

        respuesta = aplicar_modificacion_evento(
            evento=evento,
            fecha_nueva=pendiente["fecha_nueva"],
            hora_nueva=pendiente["hora_nueva"],
            hora_fin_nueva=pendiente["hora_fin_nueva"],
            omitir_control_conflictos=True,
        )

        if respuesta.startswith(
            "Listo."
        ):
            respuesta += (
                " Quedó registrado con conflicto de agenda."
            )

        return respuesta

    return (
        "Ese cambio se superpone con otro compromiso. "
        "Decime “sí” para moverlo igualmente o “no” para dejarlo como está."
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

    if tipo == "crear_evento_con_conflicto":

        return procesar_confirmacion_crear_evento_con_conflicto(
            mensaje,
            pendiente,
        )

    if tipo == "mover_evento_con_conflicto":

        return procesar_confirmacion_mover_evento_con_conflicto(
            mensaje,
            pendiente,
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

def es_listado_ruta_local(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"^(?:lista|listar|mostra|mostrar|mostrame)\s+(?:los\s+)?archivos\b",
        r"^(?:lista|listar|mostra|mostrar|mostrame)\s+(?:las\s+)?carpetas\b",
        r"^(?:lista|listar|mostra|mostrar|mostrame)\s+(?:el\s+)?contenido\s+de\b",
        r"^(?:que|qué)\s+hay\s+en\b",
    )

    return any(
        re.search(
            patron,
            texto,
        )
        for patron in patrones
    )


def extraer_ruta_listado_local(
    mensaje
):
    texto_original = str(
        mensaje or ""
    ).strip()

    texto_normalizado = normalizar_texto(
        texto_original
    )

    comandos_sin_ruta = (
        "mostrame los archivos",
        "mostra los archivos",
        "mostrar los archivos",
        "lista los archivos",
        "listar los archivos",
        "mostrame las carpetas",
        "mostra las carpetas",
        "mostrar las carpetas",
        "lista las carpetas",
        "listar las carpetas",
    )

    if texto_normalizado in comandos_sin_ruta:
        return "."

    patrones = (
        r"^\s*(?:list[áa]|listar|mostr[áa]|mostrar|mostrame)\s+(?:los\s+)?archivos\s+(?:de|en)\s+",
        r"^\s*(?:list[áa]|listar|mostr[áa]|mostrar|mostrame)\s+(?:las\s+)?carpetas\s+(?:de|en)\s+",
        r"^\s*(?:list[áa]|listar|mostr[áa]|mostrar|mostrame)\s+(?:el\s+)?contenido\s+de\s+",
        r"^\s*(?:qu[ée])\s+hay\s+en\s+",
    )

    ruta = texto_original

    for patron in patrones:
        nuevo = re.sub(
            patron,
            "",
            ruta,
            count=1,
            flags=re.IGNORECASE,
        )

        if nuevo != ruta:
            ruta = nuevo.strip()
            break

    ruta = ruta.strip().strip(
        "\"'"
    )

    if not ruta or ruta == texto_original:
        return "."

    return ruta


def listar_ruta_local(
    ruta
):
    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        path = Path.cwd()

    if not path.exists():
        return (
            f"No encontré la ruta: {path}"
        )

    if not path.is_dir():
        return (
            f"Esa ruta no es una carpeta: {path}"
        )

    try:
        elementos = sorted(
            path.iterdir(),
            key=lambda item: (
                not item.is_dir(),
                item.name.lower(),
            ),
        )
    except OSError as error:
        return (
            f"No pude listar la carpeta: {error}"
        )

    if not elementos:
        return (
            f"La carpeta está vacía: {path}"
        )

    lineas = [
        f"Contenido de {path}:"
    ]

    for item in elementos[:100]:
        tipo = (
            "[carpeta]"
            if item.is_dir()
            else "[archivo]"
        )

        lineas.append(
            f"{tipo} {item.name}"
        )

    if len(elementos) > 100:
        lineas.append(
            f"... y {len(elementos) - 100} elementos más."
        )

    return "\n".join(
        lineas
    )


def listar_ruta_local_desde_mensaje(
    mensaje
):
    ruta = extraer_ruta_listado_local(
        mensaje
    )

    return listar_ruta_local(
        ruta
    )


ARCHIVOS_PROTEGIDOS_HERMES = {
    "hermes.py",
    "memoria.py",
    "recordatorios.py",
    "hermes.db",
    ".gitignore",
}


CARPETAS_PROTEGIDAS_HERMES = {
    ".git",
    ".venv",
    ".vscode",
    "__pycache__",
}


def ruta_dentro_del_proyecto(
    path
):
    try:
        raiz = Path.cwd().resolve()
        objetivo = path.resolve()
        objetivo.relative_to(
            raiz
        )
        return True
    except (
        ValueError,
        OSError,
    ):
        return False


def es_ruta_protegida(
    path
):
    try:
        partes = set(
            path.resolve().parts
        )
    except OSError:
        partes = set(
            path.parts
        )

    if path.name in ARCHIVOS_PROTEGIDOS_HERMES:
        return True

    return any(
        carpeta in partes
        for carpeta in CARPETAS_PROTEGIDAS_HERMES
    )


def validar_ruta_escritura_local(
    path
):
    if not ruta_dentro_del_proyecto(
        path
    ):
        return (
            False,
            "Por seguridad, solo puedo crear, editar o eliminar "
            "archivos dentro de la carpeta del proyecto Hermes.",
        )

    if es_ruta_protegida(
        path
    ):
        return (
            False,
            f"La ruta está protegida y no se puede modificar: {path}",
        )

    return (
        True,
        None,
    )


def escapar_ics(
    texto
):
    texto = str(
        texto or ""
    )

    texto = texto.replace(
        "\\",
        "\\\\",
    )

    texto = texto.replace(
        ";",
        "\\;",
    )

    texto = texto.replace(
        ",",
        "\\,",
    )

    texto = texto.replace(
        "\r\n",
        "\\n",
    ).replace(
        "\n",
        "\\n",
    )

    return texto


def generar_ics_eventos(
    eventos
):
    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Hermes//Calendario//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    ahora = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    for evento in eventos:
        evento_id = evento[0]
        titulo = evento[1]
        descripcion = evento[2] or ""
        fecha = evento[3]
        hora_inicio = evento[4]
        hora_fin = evento[5]

        lineas.append(
            "BEGIN:VEVENT"
        )

        lineas.append(
            f"UID:hermes-{evento_id}@local"
        )

        lineas.append(
            f"DTSTAMP:{ahora}"
        )

        if hora_inicio:
            inicio = datetime.strptime(
                f"{fecha} {hora_inicio}",
                "%Y-%m-%d %H:%M",
            )

            lineas.append(
                "DTSTART:"
                + inicio.strftime(
                    "%Y%m%dT%H%M%S"
                )
            )

            if hora_fin:
                fin = datetime.strptime(
                    f"{fecha} {hora_fin}",
                    "%Y-%m-%d %H:%M",
                )
            else:
                fin = inicio + timedelta(
                    hours=1
                )

            lineas.append(
                "DTEND:"
                + fin.strftime(
                    "%Y%m%dT%H%M%S"
                )
            )

        else:
            fecha_dt = datetime.strptime(
                fecha,
                "%Y-%m-%d",
            )

            lineas.append(
                "DTSTART;VALUE=DATE:"
                + fecha_dt.strftime(
                    "%Y%m%d"
                )
            )

            fecha_fin = fecha_dt + timedelta(
                days=1
            )

            lineas.append(
                "DTEND;VALUE=DATE:"
                + fecha_fin.strftime(
                    "%Y%m%d"
                )
            )

        lineas.append(
            f"SUMMARY:{escapar_ics(titulo)}"
        )

        if descripcion:
            lineas.append(
                f"DESCRIPTION:{escapar_ics(descripcion)}"
            )

        lineas.append(
            "END:VEVENT"
        )

    lineas.append(
        "END:VCALENDAR"
    )

    return "\r\n".join(
        lineas
    ) + "\r\n"


def exportar_calendario_ics(
    ruta="hermes-calendario.ics"
):
    eventos = obtener_eventos_activos()

    if not eventos:
        return (
            "No hay eventos activos para exportar."
        )

    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        return (
            "No pude resolver la ruta del calendario."
        )

    permitido, motivo = validar_ruta_escritura_local(
        path
    )

    if not permitido:
        return motivo

    if path.suffix.lower() != ".ics":
        path = path.with_suffix(
            ".ics"
        )

    contenido = generar_ics_eventos(
        eventos
    )

    try:
        path.write_text(
            contenido,
            encoding="utf-8",
            newline="",
        )
    except OSError as error:
        return (
            f"No pude exportar el calendario: {error}"
        )

    return (
        f"Listo. Exporté {len(eventos)} eventos "
        f"al archivo: {path}"
    )


def es_exportacion_calendario(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "exporta el calendario",
        "exportar el calendario",
        "exporta mi calendario",
        "exportar mi calendario",
        "genera el calendario ics",
        "generar calendario ics",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def exportar_calendario_desde_mensaje(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    coincidencia = re.search(
        r"\b(?:como|a|en)\s+([^\s]+\.ics)\s*$",
        texto,
        flags=re.IGNORECASE,
    )

    ruta = (
        coincidencia.group(1)
        if coincidencia
        else "hermes-calendario.ics"
    )

    return exportar_calendario_ics(
        ruta
    )


def desescapar_ics(
    texto
):
    return (
        str(texto or "")
        .replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def desplegar_lineas_ics(
    contenido
):
    lineas = []

    for linea in str(
        contenido or ""
    ).splitlines():
        if (
            linea.startswith(" ")
            or linea.startswith("\t")
        ) and lineas:
            lineas[-1] += linea[1:]
        else:
            lineas.append(
                linea.rstrip("\r")
            )

    return lineas


def parsear_fecha_hora_ics(
    valor,
    parametros=""
):
    valor = str(
        valor or ""
    ).strip()

    parametros = str(
        parametros or ""
    ).upper()

    if not valor:
        return None, None

    if (
        "VALUE=DATE" in parametros
        or re.fullmatch(
            r"\d{8}",
            valor,
        )
    ):
        try:
            fecha = datetime.strptime(
                valor[:8],
                "%Y%m%d",
            ).date()

            return (
                fecha.isoformat(),
                None,
            )
        except ValueError:
            return None, None

    valor_limpio = valor.rstrip(
        "Z"
    )

    formatos = (
        "%Y%m%dT%H%M%S",
        "%Y%m%dT%H%M",
    )

    for formato in formatos:
        try:
            fecha_hora = datetime.strptime(
                valor_limpio,
                formato,
            )

            return (
                fecha_hora.date().isoformat(),
                fecha_hora.strftime(
                    "%H:%M"
                ),
            )
        except ValueError:
            continue

    return None, None


def extraer_eventos_ics(
    contenido
):
    lineas = desplegar_lineas_ics(
        contenido
    )

    eventos = []
    actual = None

    for linea in lineas:
        if linea == "BEGIN:VEVENT":
            actual = {}
            continue

        if linea == "END:VEVENT":
            if actual is not None:
                eventos.append(
                    actual
                )
            actual = None
            continue

        if actual is None:
            continue

        if ":" not in linea:
            continue

        cabecera, valor = linea.split(
            ":",
            1,
        )

        partes = cabecera.split(
            ";"
        )

        clave = partes[0].upper()
        parametros = ";".join(
            partes[1:]
        )

        actual[clave] = (
            parametros,
            valor,
        )

    return eventos


def importar_calendario_ics(
    ruta
):
    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        return "Decime qué archivo .ics querés importar."

    if not path.exists():
        return f"No encontré el archivo: {path}"

    if not path.is_file():
        return f"Esa ruta no es un archivo: {path}"

    if path.suffix.lower() != ".ics":
        return "El archivo debe tener extensión .ics."

    try:
        contenido = path.read_text(
            encoding="utf-8-sig"
        )
    except UnicodeDecodeError:
        contenido = path.read_text(
            encoding="latin-1"
        )
    except OSError as error:
        return f"No pude leer el calendario: {error}"

    eventos_ics = extraer_eventos_ics(
        contenido
    )

    if not eventos_ics:
        return "No encontré eventos VEVENT en ese archivo."

    importados = 0
    actualizados = 0
    duplicados = 0
    omitidos = 0

    for evento_ics in eventos_ics:
        summary = evento_ics.get(
            "SUMMARY",
            ("", ""),
        )[1]

        descripcion = evento_ics.get(
            "DESCRIPTION",
            ("", ""),
        )[1]

        uid = evento_ics.get(
            "UID",
            ("", ""),
        )[1].strip()

        inicio = evento_ics.get(
            "DTSTART"
        )

        if not summary or not inicio:
            omitidos += 1
            continue

        fecha, hora_inicio = parsear_fecha_hora_ics(
            inicio[1],
            inicio[0],
        )

        if not fecha:
            omitidos += 1
            continue

        hora_fin = None

        fin = evento_ics.get(
            "DTEND"
        )

        if fin:
            fecha_fin, hora_fin_parseada = parsear_fecha_hora_ics(
                fin[1],
                fin[0],
            )

            if hora_fin_parseada and fecha_fin == fecha:
                hora_fin = hora_fin_parseada

        titulo = desescapar_ics(
            summary
        ).strip()

        descripcion = desescapar_ics(
            descripcion
        ).strip()

        evento_objetivo = None

        if uid:
            match_hermes = re.fullmatch(
                r"hermes-(\d+)@local",
                uid,
                flags=re.IGNORECASE,
            )

            if match_hermes:
                evento_objetivo = obtener_evento_por_id(
                    int(match_hermes.group(1))
                )
            else:
                evento_objetivo = obtener_evento_por_external_uid(
                    uid
                )

        if evento_objetivo:
            if evento_objetivo[6] != "activo":
                duplicados += 1
                continue

            cambios = (
                evento_objetivo[1] != titulo
                or (evento_objetivo[2] or "") != descripcion
                or evento_objetivo[3] != fecha
                or evento_objetivo[4] != hora_inicio
                or evento_objetivo[5] != hora_fin
            )

            if cambios:
                actualizar_evento_desde_calendario(
                    evento_objetivo[0],
                    titulo=titulo,
                    descripcion=descripcion,
                    fecha=fecha,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
                actualizados += 1
            else:
                duplicados += 1

            if uid:
                asignar_external_uid_evento(
                    evento_objetivo[0],
                    uid,
                )

            continue

        candidatos = [
            evento
            for evento in obtener_eventos_activos()
            if str(evento[1] or "").strip().lower() == titulo.lower()
            and evento[3] == fecha
            and evento[4] == hora_inicio
        ]

        if candidatos:
            evento_objetivo = candidatos[0]

            cambios = (
                (evento_objetivo[2] or "") != descripcion
                or evento_objetivo[5] != hora_fin
            )

            if cambios:
                actualizar_evento_desde_calendario(
                    evento_objetivo[0],
                    titulo=titulo,
                    descripcion=descripcion,
                    fecha=fecha,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
                actualizados += 1
            else:
                duplicados += 1

            if uid:
                asignar_external_uid_evento(
                    evento_objetivo[0],
                    uid,
                )

            continue

        crear_evento(
            titulo=titulo,
            fecha=fecha,
            hora_inicio=hora_inicio,
            hora_fin=hora_fin,
            descripcion=descripcion,
            external_uid=uid or None,
        )

        importados += 1

    return (
        f"Calendario procesado: {len(eventos_ics)} eventos. "
        f"Importados: {importados}. "
        f"Actualizados: {actualizados}. "
        f"Duplicados omitidos: {duplicados}. "
        f"Inválidos omitidos: {omitidos}."
    )


def es_importacion_calendario(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"^(?:importa|importar|carga|cargar)\s+"
            r"(?:el\s+)?calendario\b",
            texto,
        )
    )


def importar_calendario_desde_mensaje(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    coincidencia = re.search(
        r"([^\s\"']+\.ics)\s*$",
        texto,
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return (
            "Decime qué archivo .ics querés importar."
        )

    return importar_calendario_ics(
        coincidencia.group(1)
    )


WEB_TIMEOUT_SEGUNDOS = 12
WEB_RESULTADOS_MAXIMOS = 5


class DuckDuckGoResultadosParser(
    HTMLParser
):
    def __init__(
        self
    ):
        super().__init__()
        self.resultados = []
        self._enlace = None
        self._titulo = []
        self._snippet = []
        self._capturando_titulo = False
        self._capturando_snippet = False

    def handle_starttag(
        self,
        tag,
        attrs
    ):
        atributos = dict(
            attrs
        )

        clases = atributos.get(
            "class",
            "",
        )

        if (
            tag == "a"
            and "result__a" in clases
        ):
            self._enlace = atributos.get(
                "href",
                "",
            )
            self._titulo = []
            self._capturando_titulo = True

        elif (
            tag in ("a", "div")
            and "result__snippet" in clases
        ):
            self._snippet = []
            self._capturando_snippet = True

    def handle_endtag(
        self,
        tag
    ):
        if (
            tag == "a"
            and self._capturando_titulo
        ):
            self._capturando_titulo = False

            if self._enlace:
                self.resultados.append({
                    "titulo": unescape(
                        "".join(
                            self._titulo
                        )
                    ).strip(),
                    "url": limpiar_url_duckduckgo(
                        self._enlace
                    ),
                    "snippet": "",
                })

        if (
            tag in ("a", "div")
            and self._capturando_snippet
        ):
            self._capturando_snippet = False

            if self.resultados:
                self.resultados[-1]["snippet"] = unescape(
                    "".join(
                        self._snippet
                    )
                ).strip()

    def handle_data(
        self,
        data
    ):
        if self._capturando_titulo:
            self._titulo.append(
                data
            )

        if self._capturando_snippet:
            self._snippet.append(
                data
            )


def limpiar_url_duckduckgo(
    url
):
    url = str(
        url or ""
    ).strip()

    if not url:
        return ""

    if url.startswith("//"):
        url = "https:" + url

    try:
        parsed = urlparse(
            url
        )

        if "duckduckgo.com" in parsed.netloc:
            parametros = parse_qs(
                parsed.query
            )
            destino = parametros.get(
                "uddg",
                [],
            )

            if destino:
                return unquote(
                    destino[0]
                )
    except Exception:
        pass

    return url


WEB_LECTURA_MAX_BYTES = 1_500_000
WEB_LECTURA_MAX_CARACTERES = 12_000


class PaginaTextoParser(
    HTMLParser
):
    def __init__(
        self
    ):
        super().__init__()
        self.titulo = []
        self.textos = []
        self._en_titulo = False
        self._ignorar = 0

    def handle_starttag(
        self,
        tag,
        attrs
    ):
        tag = tag.lower()

        if tag == "title":
            self._en_titulo = True

        if tag in (
            "script",
            "style",
            "noscript",
            "svg",
        ):
            self._ignorar += 1

    def handle_endtag(
        self,
        tag
    ):
        tag = tag.lower()

        if tag == "title":
            self._en_titulo = False

        if (
            tag in (
                "script",
                "style",
                "noscript",
                "svg",
            )
            and self._ignorar > 0
        ):
            self._ignorar -= 1

    def handle_data(
        self,
        data
    ):
        if self._ignorar:
            return

        limpio = re.sub(
            r"\s+",
            " ",
            str(
                data or ""
            ),
        ).strip()

        if not limpio:
            return

        if self._en_titulo:
            self.titulo.append(
                limpio
            )
        else:
            self.textos.append(
                limpio
            )


def host_web_seguro(
    hostname
):
    hostname = str(
        hostname or ""
    ).strip().lower()

    if not hostname:
        return False

    if hostname in (
        "localhost",
        "localhost.localdomain",
    ):
        return False

    try:
        direcciones = socket.getaddrinfo(
            hostname,
            None,
        )
    except socket.gaierror:
        return False

    ips = set()

    for direccion in direcciones:
        try:
            ips.add(
                ipaddress.ip_address(
                    direccion[4][0]
                )
            )
        except ValueError:
            continue

    if not ips:
        return False

    for ip in ips:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

    return True


def validar_url_web_publica(
    url
):
    try:
        parsed = urlparse(
            url
        )
    except Exception:
        return (
            False,
            "La URL no es válida.",
        )

    if parsed.scheme not in (
        "http",
        "https",
    ):
        return (
            False,
            "Solo puedo abrir URLs http o https.",
        )

    if not parsed.hostname:
        return (
            False,
            "La URL no tiene un dominio válido.",
        )

    if not host_web_seguro(
        parsed.hostname
    ):
        return (
            False,
            "Por seguridad, no puedo acceder a direcciones locales, "
            "privadas o internas.",
        )

    return (
        True,
        None,
    )


def es_lectura_web_controlada(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.match(
            r"^(?:abre|abrir|lee|leer|visita|visitar)\s+"
            r"(?:la\s+)?(?:pagina|web|url)?\s*https?://",
            texto,
        )
    )


def extraer_url_web(
    mensaje
):
    coincidencia = re.search(
        r"https?://[^\s]+",
        str(
            mensaje or ""
        ),
        flags=re.IGNORECASE,
    )

    if not coincidencia:
        return ""

    return coincidencia.group(0).rstrip(
        ".,);]"
    )


def leer_pagina_web(
    url
):
    global ultima_pagina_web
    url = str(
        url or ""
    ).strip()

    if not url:
        return (
            "Decime qué URL querés abrir."
        )

    segura, motivo = validar_url_web_publica(
        url
    )

    if not segura:
        return motivo

    try:
        respuesta = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "Chrome/120 Safari/537.36"
                ),
            },
            timeout=WEB_TIMEOUT_SEGUNDOS,
            allow_redirects=True,
            stream=True,
        )

        respuesta.raise_for_status()

        segura_final, motivo_final = validar_url_web_publica(
            respuesta.url
        )

        if not segura_final:
            return (
                "La página redirigió a una dirección no permitida. "
                + motivo_final
            )

        tipo = respuesta.headers.get(
            "Content-Type",
            "",
        ).lower()

        if not (
            "text/html" in tipo
            or "text/plain" in tipo
            or "application/xhtml+xml" in tipo
        ):
            return (
                "La URL no devuelve una página de texto compatible. "
                f"Tipo recibido: {tipo or 'desconocido'}"
            )

        partes = []
        total = 0

        for bloque in respuesta.iter_content(
            chunk_size=16_384
        ):
            if not bloque:
                continue

            total += len(
                bloque
            )

            if total > WEB_LECTURA_MAX_BYTES:
                return (
                    "La página es demasiado grande para la lectura "
                    "web controlada de Hermes."
                )

            partes.append(
                bloque
            )

        bruto = b"".join(
            partes
        )

        encoding = (
            respuesta.encoding
            or "utf-8"
        )

        html = bruto.decode(
            encoding,
            errors="replace",
        )

    except requests.RequestException as error:
        return (
            "No pude abrir esa página. "
            f"Detalle: {error}"
        )

    parser = PaginaTextoParser()

    try:
        parser.feed(
            html
        )
    except Exception as error:
        return (
            "La página respondió, pero no pude interpretar "
            f"su contenido. Detalle: {error}"
        )

    titulo = " ".join(
        parser.titulo
    ).strip()

    texto = "\n".join(
        parser.textos
    ).strip()

    if not texto:
        return (
            "La página abrió correctamente, pero no encontré "
            "texto legible."
        )

    if len(
        texto
    ) > WEB_LECTURA_MAX_CARACTERES:
        texto = (
            texto[
                :WEB_LECTURA_MAX_CARACTERES
            ]
            + "\n\n[Contenido recortado por seguridad.]"
        )

    ultima_pagina_web = {
        "url": respuesta.url,
        "titulo": titulo,
        "texto": texto,
    }

    lineas = [
        f"URL: {respuesta.url}",
    ]

    if titulo:
        lineas.append(
            f"Título: {titulo}"
        )

    lineas.extend([
        "",
        texto,
        "",
        "La página se abrió únicamente porque la pediste explícitamente.",
    ])

    return "\n".join(
        lineas
    ).strip()


def leer_web_desde_mensaje(
    mensaje
):
    url = extraer_url_web(
        mensaje
    )

    return leer_pagina_web(
        url
    )


def es_resumen_ultima_pagina_web(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    ).strip()

    expresiones = (
        "resume la pagina",
        "resumi la pagina",
        "resumime la pagina",
        "resume esta pagina",
        "resumi esta pagina",
        "resumime esta pagina",
        "resume lo que lei",
        "resumi lo que lei",
        "resumime lo que lei",
    )

    return texto in expresiones


def es_pregunta_sobre_ultima_pagina_web(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    ).strip()

    prefijos = (
        "segun la pagina",
        "sobre la pagina",
        "de la pagina",
        "en la pagina",
        "segun lo que lei",
        "sobre lo que lei",
    )

    return any(
        texto.startswith(
            prefijo
        )
        for prefijo in prefijos
    )


def consultar_modelo_sobre_pagina(
    instruccion,
    modo="pregunta"
):
    global ultima_pagina_web

    if not ultima_pagina_web:
        return (
            "Primero pedime que lea una página web concreta."
        )

    titulo = ultima_pagina_web.get(
        "titulo",
        "",
    )

    url = ultima_pagina_web.get(
        "url",
        "",
    )

    contenido = ultima_pagina_web.get(
        "texto",
        "",
    )

    if modo == "resumen":
        tarea = (
            "Resumí el contenido en español, de forma clara y breve. "
            "Usá solamente la información de la fuente. "
            "No agregues conocimiento externo ni inventes datos."
        )
    else:
        tarea = (
            "Respondé la pregunta en español usando solamente la fuente. "
            "Si la respuesta no aparece o no puede sostenerse con la fuente, "
            "decí claramente que la página no lo indica."
        )

    prompt = f"""
Sos Hermes.

FUENTE WEB:
Título: {titulo}
URL: {url}

CONTENIDO:
{contenido}

TAREA:
{tarea}

INSTRUCCIÓN DEL USUARIO:
{instruccion}

Respondé solamente con la respuesta final, sin JSON, sin repetir
estas instrucciones y sin agregar información externa.
"""

    datos = {
        "model": MODELO_RAPIDO,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_ctx": 8192,
        },
    }

    print(
        "Hermes 🌐 analizando página...",
        flush=True,
    )

    try:
        respuesta_http = requests.post(
            OLLAMA_URL,
            json=datos,
            timeout=120,
        )

        respuesta_http.raise_for_status()

        respuesta = (
            respuesta_http
            .json()
            .get(
                "response",
                "",
            )
            .strip()
        )

    except requests.RequestException as error:
        return (
            "No pude analizar la página con el modelo local. "
            f"Detalle: {error}"
        )

    if not respuesta:
        return (
            "No pude generar una respuesta sobre la página."
        )

    return respuesta


def resumir_ultima_pagina_web():
    return consultar_modelo_sobre_pagina(
        "Resumí la página leída.",
        modo="resumen",
    )


def preguntar_sobre_ultima_pagina_web(
    mensaje
):
    return consultar_modelo_sobre_pagina(
        mensaje,
        modo="pregunta",
    )


def es_busqueda_web_controlada(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.match(
            r"^(?:busca|buscar|investiga|investigar)\s+"
            r"(?:en\s+)?(?:internet|la\s+web|web)\b",
            texto,
        )
    )


def extraer_consulta_web(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    coincidencia = re.match(
        r"^\s*(?:busc[áa]|buscar|investig[áa]|investigar)\s+"
        r"(?:en\s+)?(?:internet|la\s+web|web)\s*[:,-]?\s*(.+?)\s*$",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not coincidencia:
        return ""

    return coincidencia.group(1).strip()


def buscar_en_web(
    consulta
):
    consulta = str(
        consulta or ""
    ).strip()

    if not consulta:
        return (
            "Decime qué querés buscar en internet."
        )

    if len(
        consulta
    ) > 300:
        return (
            "La consulta web es demasiado larga. "
            "Resumila en menos de 300 caracteres."
        )

    try:
        respuesta = requests.get(
            "https://html.duckduckgo.com/html/",
            params={
                "q": consulta,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "Chrome/120 Safari/537.36"
                ),
            },
            timeout=WEB_TIMEOUT_SEGUNDOS,
        )

        respuesta.raise_for_status()

    except requests.RequestException as error:
        return (
            "No pude acceder a la web en este momento. "
            f"Detalle: {error}"
        )

    parser = DuckDuckGoResultadosParser()

    try:
        parser.feed(
            respuesta.text
        )
    except Exception as error:
        return (
            "La búsqueda respondió, pero no pude interpretar "
            f"los resultados. Detalle: {error}"
        )

    resultados = [
        resultado
        for resultado in parser.resultados
        if resultado.get(
            "titulo"
        )
        and resultado.get(
            "url"
        )
    ][:WEB_RESULTADOS_MAXIMOS]

    if not resultados:
        return (
            "No encontré resultados web utilizables "
            f"para: {consulta}"
        )

    lineas = [
        f"Resultados web para: {consulta}",
        "",
    ]

    for indice, resultado in enumerate(
        resultados,
        start=1,
    ):
        lineas.append(
            f"{indice}. {resultado['titulo']}"
        )

        if resultado.get(
            "snippet"
        ):
            lineas.append(
                resultado["snippet"]
            )

        lineas.append(
            resultado["url"]
        )

        lineas.append(
            ""
        )

    lineas.append(
        "La búsqueda web solo se ejecutó porque la pediste explícitamente."
    )

    return "\n".join(
        lineas
    ).strip()


def buscar_web_desde_mensaje(
    mensaje
):
    consulta = extraer_consulta_web(
        mensaje
    )

    return buscar_en_web(
        consulta
    )


def es_auditoria_acceso_web(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    ).strip()

    expresiones = (
        "audita el acceso web",
        "auditar el acceso web",
        "audita la web",
        "auditar la web",
        "revisa la seguridad web",
        "revisar la seguridad web",
    )

    return texto in expresiones


def auditar_acceso_web():
    problemas = []

    # 1) Una pregunta normal no debe activar acceso web.
    if es_busqueda_web_controlada(
        "Qué es Python"
    ):
        problemas.append(
            "una consulta normal activa búsqueda web"
        )

    if es_lectura_web_controlada(
        "Contame sobre python.org"
    ):
        problemas.append(
            "una consulta normal activa lectura web"
        )

    # 2) Las órdenes explícitas sí deben activar las herramientas web.
    if not es_busqueda_web_controlada(
        "Buscá en internet Python 3.14"
    ):
        problemas.append(
            "la búsqueda explícita no se detecta"
        )

    if not es_lectura_web_controlada(
        "Leé la página https://www.python.org/"
    ):
        problemas.append(
            "la lectura explícita no se detecta"
        )

    # 3) Protocolos no web deben quedar bloqueados.
    segura, _ = validar_url_web_publica(
        "file:///etc/passwd"
    )

    if segura:
        problemas.append(
            "se permite el protocolo file://"
        )

    # 4) Hosts locales e internos deben quedar bloqueados.
    for url in (
        "http://localhost/",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
    ):
        segura, _ = validar_url_web_publica(
            url
        )

        if segura:
            problemas.append(
                f"se permite una dirección local: {url}"
            )

    # 5) El resumen/preguntas no deben fingir contexto si no hay página.
    if not callable(
        resumir_ultima_pagina_web
    ):
        problemas.append(
            "el resumen de páginas no está disponible"
        )

    if not callable(
        preguntar_sobre_ultima_pagina_web
    ):
        problemas.append(
            "las preguntas sobre páginas no están disponibles"
        )

    if problemas:
        return (
            "Encontré problemas en el acceso web: "
            + "; ".join(
                problemas
            )
            + "."
        )

    return (
        "El acceso web está correcto. "
        "Búsqueda explícita: OK. "
        "Lectura explícita: OK. "
        "Bloqueo de direcciones locales e internas: OK. "
        "Resumen y preguntas sobre páginas: OK."
    )


def es_auditoria_calendario_externo(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "audita el calendario externo",
        "auditar el calendario externo",
        "audita la integracion de calendario",
        "auditar la integracion de calendario",
        "revisa el calendario externo",
        "revisar el calendario externo",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def auditar_calendario_externo():
    auditoria_db = auditar_integracion_calendario_db()

    if not auditoria_db["correcto"]:
        return (
            "Encontré problemas en la integración de calendario: "
            + "; ".join(
                auditoria_db["problemas"]
            )
            + "."
        )

    eventos = obtener_eventos_activos()

    contenido = generar_ics_eventos(
        eventos
    )

    eventos_ics = extraer_eventos_ics(
        contenido
    )

    if len(
        eventos_ics
    ) != len(
        eventos
    ):
        return (
            "Encontré un problema: la exportación ICS no conserva "
            "la misma cantidad de eventos activos."
        )

    uids = []

    for evento_ics in eventos_ics:
        uid = evento_ics.get(
            "UID",
            ("", ""),
        )[1].strip()

        if not uid:
            return (
                "Encontré un problema: hay eventos exportados sin UID."
            )

        uids.append(
            uid
        )

    if len(
        uids
    ) != len(
        set(
            uids
        )
    ):
        return (
            "Encontré un problema: la exportación genera UID duplicados."
        )

    return (
        "La integración de calendario está correcta. "
        f"Eventos activos verificables: {len(eventos)}. "
        f"Eventos con UID externo guardado: "
        f"{auditoria_db['eventos_con_uid']}. "
        "Exportación ICS, UID y deduplicación: OK."
    )


def es_auditoria_archivos_locales(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "audita los archivos",
            "auditar los archivos",
            "audita archivos locales",
            "revisa la seguridad de archivos",
            "revisar la seguridad de archivos",
            "audita la seguridad de archivos",
        )
    )


def auditar_archivos_locales():
    raiz = Path.cwd().resolve()

    prueba_fuera = (
        raiz.parent
        / "hermes_prueba_seguridad.txt"
    )

    prueba_protegida = (
        raiz
        / "hermes.py"
    )

    fuera_ok, _ = validar_ruta_escritura_local(
        prueba_fuera
    )

    protegida_ok, _ = validar_ruta_escritura_local(
        prueba_protegida
    )

    problemas = []

    if fuera_ok:
        problemas.append(
            "la protección contra escritura fuera del proyecto falló"
        )

    if protegida_ok:
        problemas.append(
            "la protección de archivos críticos falló"
        )

    if problemas:
        return (
            "Encontré problemas de seguridad en archivos: "
            + "; ".join(
                problemas
            )
            + "."
        )

    return (
        "La seguridad de archivos está correcta. "
        "Las escrituras fuera del proyecto están bloqueadas "
        "y los archivos críticos están protegidos."
    )


def es_creacion_archivo_local(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"^(?:crea|crear|creame)\s+(?:el\s+)?archivo\b",
            texto,
        )
    )


def extraer_creacion_archivo_local(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    coincidencia = re.match(
        r"^\s*(?:cre[áa]|crear|cre[áa]me)\s+(?:el\s+)?archivo\s+"
        r"(.+?)\s+(?:con|que\s+diga|y\s+pone|y\s+pon[ée])\s+(.+)$",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not coincidencia:
        return None, None

    ruta = coincidencia.group(1).strip().strip(
        "\"'"
    )

    contenido = coincidencia.group(2).strip()

    return ruta, contenido


def crear_archivo_texto_local(
    ruta,
    contenido
):
    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        return "Decime qué archivo querés crear."

    permitido, motivo = validar_ruta_escritura_local(
        path
    )

    if not permitido:
        return motivo

    extension = path.suffix.lower()

    if extension not in EXTENSIONES_TEXTO_PERMITIDAS:
        return (
            "Solo puedo crear archivos de texto o código "
            "con una extensión permitida."
        )

    if path.name in ARCHIVOS_PROTEGIDOS_HERMES:
        return (
            f"No voy a crear ni sobrescribir el archivo protegido "
            f"{path.name} desde este comando."
        )

    if path.exists():
        return (
            f"El archivo ya existe: {path}. "
            "Usá un comando de edición si querés modificarlo."
        )

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            str(contenido),
            encoding="utf-8",
        )

    except OSError as error:
        return (
            f"No pude crear el archivo: {error}"
        )

    return (
        f"Listo. Creé el archivo: {path}"
    )


def crear_archivo_local_desde_mensaje(
    mensaje
):
    ruta, contenido = extraer_creacion_archivo_local(
        mensaje
    )

    if not ruta:
        return (
            "Usá, por ejemplo: "
            "Creá el archivo prueba.txt con hola mundo"
        )

    return crear_archivo_texto_local(
        ruta,
        contenido,
    )


def es_edicion_archivo_local(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"^(?:edita|editar|modifica|modificar|reemplaza|reemplazar)\s+"
            r"(?:el\s+)?archivo\b",
            texto,
        )
    )


def extraer_edicion_archivo_local(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    coincidencia = re.match(
        r"^\s*(?:edit[áa]|editar|modific[áa]|modificar|reemplaz[áa]|reemplazar)\s+"
        r"(?:el\s+)?archivo\s+(.+?)\s+"
        r"(?:con|por|que\s+diga|y\s+pone|y\s+pon[ée])\s+(.+)$",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not coincidencia:
        return None, None

    ruta = coincidencia.group(1).strip().strip(
        "\"'"
    )

    contenido = coincidencia.group(2).strip()

    return ruta, contenido


def editar_archivo_texto_local(
    ruta,
    contenido
):
    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        return "Decime qué archivo querés editar."

    permitido, motivo = validar_ruta_escritura_local(
        path
    )

    if not permitido:
        return motivo

    if path.name in ARCHIVOS_PROTEGIDOS_HERMES:
        return (
            f"No voy a modificar el archivo protegido {path.name} "
            "desde este comando."
        )

    if not path.exists():
        return (
            f"No encontré el archivo: {path}"
        )

    if not path.is_file():
        return (
            f"Esa ruta no es un archivo: {path}"
        )

    if path.suffix.lower() not in EXTENSIONES_TEXTO_PERMITIDAS:
        return (
            "Solo puedo editar archivos de texto o código "
            "con una extensión permitida."
        )

    try:
        path.write_text(
            str(contenido),
            encoding="utf-8",
        )
    except OSError as error:
        return (
            f"No pude editar el archivo: {error}"
        )

    return (
        f"Listo. Actualicé el archivo: {path}"
    )


def editar_archivo_local_desde_mensaje(
    mensaje
):
    ruta, contenido = extraer_edicion_archivo_local(
        mensaje
    )

    if not ruta:
        return (
            "Usá, por ejemplo: "
            "Editá el archivo prueba.txt con nuevo contenido"
        )

    return editar_archivo_texto_local(
        ruta,
        contenido,
    )


def es_eliminacion_archivo_local(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return bool(
        re.search(
            r"^(?:elimina|eliminar|borra|borrar)\s+(?:el\s+)?archivo\b",
            texto,
        )
    )


def extraer_ruta_eliminacion_archivo_local(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    ruta = re.sub(
        r"^\s*(?:elimin[áa]|eliminar|borr[áa]|borrar)\s+"
        r"(?:el\s+)?archivo\s+",
        "",
        texto,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    return ruta.strip(
        "\"'"
    )


def eliminar_archivo_texto_local(
    ruta
):
    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        return "Decime qué archivo querés eliminar."

    permitido, motivo = validar_ruta_escritura_local(
        path
    )

    if not permitido:
        return motivo

    if path.name in ARCHIVOS_PROTEGIDOS_HERMES:
        return (
            f"No voy a eliminar el archivo protegido {path.name}."
        )

    if not path.exists():
        return (
            f"No encontré el archivo: {path}"
        )

    if not path.is_file():
        return (
            f"Esa ruta no es un archivo: {path}"
        )

    if path.suffix.lower() not in EXTENSIONES_TEXTO_PERMITIDAS:
        return (
            "Solo puedo eliminar archivos de texto o código "
            "con una extensión permitida."
        )

    try:
        path.unlink()
    except OSError as error:
        return (
            f"No pude eliminar el archivo: {error}"
        )

    return (
        f"Listo. Eliminé el archivo: {path}"
    )


def eliminar_archivo_local_desde_mensaje(
    mensaje
):
    ruta = extraer_ruta_eliminacion_archivo_local(
        mensaje
    )

    if not ruta:
        return (
            "Decime qué archivo querés eliminar."
        )

    return eliminar_archivo_texto_local(
        ruta
    )


EXTENSIONES_TEXTO_PERMITIDAS = {
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".yaml",
    ".yml",
    ".log",
    ".ini",
    ".toml",
    ".sql",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}

MAX_BYTES_ARCHIVO_TEXTO = 1024 * 1024
MAX_CARACTERES_MOSTRAR_ARCHIVO = 12000


def es_lectura_archivo_local(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"^(?:lee|leer|leeme)\s+(?:el\s+)?archivo\b",
        r"^(?:abre|abrir|abreme)\s+(?:el\s+)?archivo\b",
        r"^(?:mostra|mostrar|mostrame)\s+(?:el\s+)?archivo\b",
    )

    return any(
        re.search(
            patron,
            texto,
        )
        for patron in patrones
    )


def extraer_ruta_archivo_local(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    patrones = (
        r"^\s*(?:le[ée]|leer|le[ée]me)\s+(?:el\s+)?archivo\s+",
        r"^\s*(?:abr[íi]|abrir|abr[íi]me)\s+(?:el\s+)?archivo\s+",
        r"^\s*(?:mostr[áa]|mostrar|mostrame)\s+(?:el\s+)?archivo\s+",
    )

    ruta = texto

    for patron in patrones:
        nuevo = re.sub(
            patron,
            "",
            ruta,
            count=1,
            flags=re.IGNORECASE,
        )

        if nuevo != ruta:
            ruta = nuevo.strip()
            break

    ruta = ruta.strip().strip(
        "\"'"
    )

    return ruta


def resolver_ruta_archivo_local(
    ruta
):
    ruta = str(
        ruta or ""
    ).strip()

    if not ruta:
        return None

    path = Path(
        ruta
    ).expanduser()

    if not path.is_absolute():
        path = Path.cwd() / path

    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def leer_archivo_texto_local(
    ruta
):
    path = resolver_ruta_archivo_local(
        ruta
    )

    if path is None:
        return (
            "Decime qué archivo querés leer."
        )

    if not path.exists():
        return (
            f"No encontré el archivo: {path}"
        )

    if not path.is_file():
        return (
            f"Esa ruta no es un archivo: {path}"
        )

    extension = path.suffix.lower()

    if extension not in EXTENSIONES_TEXTO_PERMITIDAS:
        return (
            "Por ahora puedo leer archivos de texto y código "
            f"compatibles. Extensión no soportada: "
            f"{extension or 'sin extensión'}."
        )

    try:
        tamano = path.stat().st_size
    except OSError as error:
        return (
            f"No pude revisar el archivo: {error}"
        )

    if tamano > MAX_BYTES_ARCHIVO_TEXTO:
        return (
            "El archivo es demasiado grande para esta etapa "
            f"({tamano} bytes). Límite actual: "
            f"{MAX_BYTES_ARCHIVO_TEXTO} bytes."
        )

    contenido = None

    for codificacion in (
        "utf-8",
        "utf-8-sig",
        "latin-1",
    ):
        try:
            contenido = path.read_text(
                encoding=codificacion
            )
            break
        except UnicodeDecodeError:
            continue
        except OSError as error:
            return (
                f"No pude leer el archivo: {error}"
            )

    if contenido is None:
        return (
            "No pude interpretar el archivo como texto."
        )

    contenido = contenido.strip()

    if not contenido:
        return (
            f"El archivo {path.name} está vacío."
        )

    truncado = (
        len(contenido)
        > MAX_CARACTERES_MOSTRAR_ARCHIVO
    )

    if truncado:
        contenido = contenido[
            :MAX_CARACTERES_MOSTRAR_ARCHIVO
        ].rstrip()

    respuesta = (
        f"Archivo: {path}\n\n"
        f"{contenido}"
    )

    if truncado:
        respuesta += (
            "\n\n[Contenido recortado para mostrarlo de forma segura.]"
        )

    return respuesta


def leer_archivo_local_desde_mensaje(
    mensaje
):
    ruta = extraer_ruta_archivo_local(
        mensaje
    )

    if not ruta:
        return (
            "Decime qué archivo querés leer."
        )

    return leer_archivo_texto_local(
        ruta
    )


def es_auditoria_busqueda_local(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        frase in texto
        for frase in (
            "audita la busqueda",
            "auditar la busqueda",
            "audita busqueda",
            "revisa la busqueda",
            "revisar la busqueda",
            "audita notas y memoria",
            "revisa notas y memoria",
        )
    )


def auditar_busqueda_local():
    datos = auditar_busqueda_local_db()

    if datos["correcto"]:
        return (
            "La búsqueda está correcta. "
            f'Notas activas indexables: {datos["notas_activas"]}. '
            f'Recuerdos indexables: {datos["recuerdos"]}.'
        )

    return (
        "Encontré problemas en la búsqueda: "
        + "; ".join(
            datos["errores"]
        )
        + "."
    )


def es_busqueda_combinada(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"^(?:busca|buscar|buscame)\s+(?:en\s+)?(?:mis\s+)?notas\s+y\s+(?:en\s+)?(?:mi\s+)?memoria\b",
        r"^(?:busca|buscar|buscame)\s+(?:en\s+)?(?:mi\s+)?memoria\s+y\s+(?:en\s+)?(?:mis\s+)?notas\b",
        r"^(?:busca|buscar|buscame)\s+(?:en\s+)?todo\b",
        r"^(?:busca|buscar|buscame)\s+(?:en\s+)?notas\s+y\s+memoria\b",
    )

    return any(
        re.search(
            patron,
            texto,
        )
        for patron in patrones
    )


def extraer_termino_busqueda_combinada(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    patrones = (
        r"^\s*busc[áa](?:me)?\s+(?:en\s+)?(?:mis\s+)?notas\s+y\s+(?:en\s+)?(?:mi\s+)?memoria\s+",
        r"^\s*busc[áa](?:me)?\s+(?:en\s+)?(?:mi\s+)?memoria\s+y\s+(?:en\s+)?(?:mis\s+)?notas\s+",
        r"^\s*busc[áa](?:me)?\s+(?:en\s+)?todo\s+",
        r"^\s*buscar\s+(?:en\s+)?(?:mis\s+)?notas\s+y\s+(?:en\s+)?(?:mi\s+)?memoria\s+",
        r"^\s*buscar\s+(?:en\s+)?(?:mi\s+)?memoria\s+y\s+(?:en\s+)?(?:mis\s+)?notas\s+",
        r"^\s*buscar\s+(?:en\s+)?todo\s+",
    )

    termino = texto

    for patron in patrones:
        nuevo = re.sub(
            patron,
            "",
            termino,
            count=1,
            flags=re.IGNORECASE,
        )

        if nuevo != termino:
            termino = nuevo.strip()
            break

    termino = re.sub(
        r"^(?:sobre|de|con)\s+",
        "",
        termino,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    return termino.strip(
        " .,:;-"
    )


def buscar_notas_y_memoria_desde_mensaje(
    mensaje
):
    termino = extraer_termino_busqueda_combinada(
        mensaje
    )

    if not termino:
        return (
            "Decime qué querés buscar en notas y memoria."
        )

    notas = buscar_notas(
        termino
    )

    recuerdos = buscar_recuerdos(
        termino
    )

    if not notas and not recuerdos:
        return (
            f'No encontré coincidencias para "{termino}" '
            f'en notas ni en memoria.'
        )

    lineas = [
        f'Resultados para "{termino}":'
    ]

    if notas:
        lineas.append(
            "Notas:"
        )

        for nota in notas:
            categoria = (
                nota[6]
                if len(nota) > 6 and nota[6]
                else "general"
            )

            lineas.append(
                f"- #{nota[0]} [{categoria}] — {nota[1]}"
            )

    if recuerdos:
        lineas.append(
            "Memoria:"
        )

        for categoria, clave, valor in recuerdos:
            lineas.append(
                f"- [{categoria}] {clave}: {valor}"
            )

    return "\n".join(
        lineas
    )


def es_busqueda_memoria(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    patrones = (
        r"^(?:busca|buscar|buscame)\s+(?:en\s+)?(?:mi\s+)?memoria\b",
        r"^(?:busca|buscar|buscame)\s+(?:en\s+)?(?:mis\s+)?recuerdos\b",
        r"^(?:encontra|encontrar)\s+(?:en\s+)?(?:mi\s+)?memoria\b",
        r"^(?:encontra|encontrar)\s+(?:en\s+)?(?:mis\s+)?recuerdos\b",
    )

    return any(
        re.search(
            patron,
            texto,
        )
        for patron in patrones
    )


def extraer_termino_busqueda_memoria(
    mensaje
):
    texto = str(
        mensaje or ""
    ).strip()

    patrones = (
        r"^\s*busc[áa](?:me)?\s+(?:en\s+)?(?:mi\s+)?memoria\s+",
        r"^\s*busc[áa](?:me)?\s+(?:en\s+)?(?:mis\s+)?recuerdos\s+",
        r"^\s*buscar\s+(?:en\s+)?(?:mi\s+)?memoria\s+",
        r"^\s*buscar\s+(?:en\s+)?(?:mis\s+)?recuerdos\s+",
        r"^\s*encontr[áa]\s+(?:en\s+)?(?:mi\s+)?memoria\s+",
        r"^\s*encontrar\s+(?:en\s+)?(?:mi\s+)?memoria\s+",
    )

    termino = texto

    for patron in patrones:
        nuevo = re.sub(
            patron,
            "",
            termino,
            count=1,
            flags=re.IGNORECASE,
        )

        if nuevo != termino:
            termino = nuevo.strip()
            break

    termino = re.sub(
        r"^(?:sobre|de|con|que\s+diga|que\s+tenga)\s+",
        "",
        termino,
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    return termino.strip(
        " .,:;-"
    )


def buscar_memoria_desde_mensaje(
    mensaje
):
    termino = extraer_termino_busqueda_memoria(
        mensaje
    )

    if not termino:
        return (
            "Decime qué querés buscar en mi memoria."
        )

    resultados = buscar_recuerdos(
        termino
    )

    if not resultados:
        return (
            f'No encontré recuerdos que coincidan con "{termino}".'
        )

    lineas = [
        f'Recuerdos para "{termino}":'
    ]

    for categoria, clave, valor in resultados:
        lineas.append(
            f"- [{categoria}] {clave}: {valor}"
        )

    return "\n".join(
        lineas
    )


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
        f"{tarea[3] or 'sin fecha'} | "
        f"prioridad {tarea[5] if len(tarea) > 5 else 'media'}"
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

        prioridad = (
            tarea[5]
            if len(tarea) > 5 and tarea[5]
            else "media"
        )

        texto += (
            f" — prioridad "
            f"{prioridad}"
        )

        vencimiento = etiqueta_vencimiento_tarea(
            tarea[3]
        )

        if vencimiento:

            texto += (
                f" — {vencimiento}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )






# ==========================================================
# EVENTOS RECURRENTES
# ==========================================================

def extraer_recurrencia_evento(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if any(
        expresion in texto
        for expresion in (
            "todos los dias",
            "cada dia",
            "diariamente",
        )
    ):
        return (
            "diaria",
            None
        )

    for dia in DIAS_SEMANA_RUTINA:

        if any(
            expresion in texto
            for expresion in (
                f"todos los {dia}",
                f"cada {dia}",
            )
        ):
            return (
                "semanal",
                dia
            )

    return (
        None,
        None
    )


def es_creacion_evento_recurrente(
    mensaje
):
    frecuencia, _ = extraer_recurrencia_evento(
        mensaje
    )

    if not frecuencia:
        return False

    texto = normalizar_texto(
        mensaje
    )

    # Evitamos capturar recordatorios/rutinas recurrentes.
    if any(
        palabra in texto
        for palabra in (
            "recordame",
            "recordar",
            "rutina",
        )
    ):
        return False

    hora_inicio, _ = extraer_horas_del_mensaje(
        mensaje
    )

    tiene_evento = any(
        expresion in texto
        for expresion in (
            "tengo",
            "hay",
            "evento",
            "reunion",
            "reunión",
            "clase",
            "turno",
            "cita",
        )
    )

    return (
        tiene_evento
        and hora_inicio is not None
    )


def extraer_titulo_evento_recurrente(
    mensaje
):
    titulo = mensaje.strip()

    patrones = (
        r"^\s*todos\s+los\s+d[ií]as?\s*",
        r"^\s*cada\s+d[ií]a\s*",
        r"^\s*diariamente\s*",
        r"^\s*todos\s+los\s+lunes\s*",
        r"^\s*todos\s+los\s+martes\s*",
        r"^\s*todos\s+los\s+mi[eé]rcoles\s*",
        r"^\s*todos\s+los\s+jueves\s*",
        r"^\s*todos\s+los\s+viernes\s*",
        r"^\s*todos\s+los\s+s[aá]bados\s*",
        r"^\s*todos\s+los\s+domingos\s*",
        r"^\s*cada\s+lunes\s*",
        r"^\s*cada\s+martes\s*",
        r"^\s*cada\s+mi[eé]rcoles\s*",
        r"^\s*cada\s+jueves\s*",
        r"^\s*cada\s+viernes\s*",
        r"^\s*cada\s+s[aá]bado\s*",
        r"^\s*cada\s+domingo\s*",
    )

    for patron in patrones:
        titulo = re.sub(
            patron,
            "",
            titulo,
            count=1,
            flags=re.IGNORECASE,
        )

    titulo = re.sub(
        r"\b(?:a\s+las?|a\s+la)\s+\d{1,2}(?::\d{2})?\b",
        " ",
        titulo,
        count=1,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"^\s*(?:tengo|hay)\s+",
        "",
        titulo,
        count=1,
        flags=re.IGNORECASE,
    )

    # Quitamos expresiones de duración para que no formen parte
    # del nombre del evento recurrente.
    titulo = re.sub(
        r"\b(?:por|durante)\s+"
        r"(?:\d+|una?|media)\s+"
        r"(?:hora|horas|minuto|minutos)\b",
        " ",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\bdura\s+"
        r"(?:\d+|una?|media)\s+"
        r"(?:hora|horas|minuto|minutos)\b",
        " ",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    ).strip(" .,-")

    if titulo:
        titulo = (
            titulo[0].upper()
            + titulo[1:]
        )

    return titulo


def crear_evento_recurrente_desde_mensaje(
    mensaje
):
    frecuencia, dia_semana = extraer_recurrencia_evento(
        mensaje
    )

    if not frecuencia:

        return (
            "No pude identificar cada cuánto "
            "se repite el evento."
        )

    hora_inicio, hora_fin = extraer_horas_del_mensaje(
        mensaje
    )

    if not hora_inicio:

        return (
            "Necesito saber a qué hora "
            "empieza el evento recurrente."
        )

    duracion = extraer_duracion_evento_minutos(
        mensaje
    )

    if (
        not hora_fin
        and duracion is not None
    ):

        fecha_referencia = date.today().isoformat()

        hora_fin = calcular_hora_fin_por_duracion(
            fecha_referencia,
            hora_inicio,
            duracion
        )

    titulo = extraer_titulo_evento_recurrente(
        mensaje
    )

    if not titulo:

        return (
            "No pude identificar el nombre "
            "del evento recurrente."
        )

    existentes = obtener_eventos_recurrentes_activos()

    for evento in existentes:

        if (
            normalizar_texto(evento[1])
            == normalizar_texto(titulo)
            and evento[2] == frecuencia
            and evento[3] == dia_semana
            and evento[4] == hora_inicio
            and evento[5] == hora_fin
        ):

            return (
                f"Ese evento recurrente ya existe "
                f"como #{evento[0]}."
            )

    evento_id = crear_evento_recurrente(
        titulo=titulo,
        frecuencia=frecuencia,
        dia_semana=dia_semana,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
    )

    if frecuencia == "diaria":

        recurrencia = "todos los días"

    else:

        recurrencia = (
            f"todos los {dia_semana}"
        )

    respuesta = (
        f"Listo. Creé el evento recurrente "
        f"#{evento_id}: {titulo} — "
        f"{recurrencia} a las {hora_inicio}"
    )

    if hora_fin:
        respuesta += (
            f" hasta las {hora_fin}"
        )

    respuesta += "."

    return respuesta



def buscar_evento_recurrente_desde_mensaje(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    coincidencia = re.search(
        r"(?:evento\s+recurrente|recurrente)\s*#?\s*(\d+)\b",
        texto
    )

    if coincidencia:

        evento = obtener_evento_recurrente_por_id(
            int(coincidencia.group(1))
        )

        if evento and evento[6] != "eliminado":
            return evento

    eventos = obtener_eventos_recurrentes()

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
            elemento[1][0],
        )
    )

    return candidatos[0][1]


def es_pausa_evento_recurrente(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "recurrente" in texto
        and any(
            expresion in texto
            for expresion in (
                "pausa",
                "pausar",
                "suspende",
                "suspender",
                "detene",
                "detener",
            )
        )
    )


def es_reanudacion_evento_recurrente(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "recurrente" in texto
        and any(
            expresion in texto
            for expresion in (
                "reanuda",
                "reanudar",
                "reactiva",
                "reactivar",
                "activa",
                "activar",
            )
        )
    )


def es_eliminacion_evento_recurrente(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "recurrente" in texto
        and any(
            expresion in texto
            for expresion in (
                "elimina",
                "eliminar",
                "borra",
                "borrar",
                "cancela",
                "cancelar",
                "quita",
                "quitar",
            )
        )
    )


def es_renombrado_evento_recurrente(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "recurrente" in texto
        and any(
            expresion in texto
            for expresion in (
                "renombra",
                "renombrar",
                "cambia el nombre",
                "cambiar el nombre",
            )
        )
    )


def extraer_nuevo_titulo_evento_recurrente(
    mensaje
):
    patrones = (
        r"(?:renombr[áa]|renombrar)\s+"
        r"(?:el\s+)?(?:evento\s+)?recurrente\s+"
        r"(?:#?\d+|.+?)\s+a\s+(.+)$",
        r"(?:cambi[áa]|cambiar)\s+el\s+nombre\s+"
        r"(?:del\s+)?(?:evento\s+)?recurrente\s+"
        r"(?:#?\d+|.+?)\s+a\s+(.+)$",
    )

    for patron in patrones:

        coincidencia = re.search(
            patron,
            mensaje,
            flags=re.IGNORECASE,
        )

        if coincidencia:

            titulo = coincidencia.group(1).strip(
                " .,-"
            )

            if titulo:

                return (
                    titulo[0].upper()
                    + titulo[1:]
                )

    return None


def es_edicion_evento_recurrente(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if "recurrente" not in texto:
        return False

    if (
        es_pausa_evento_recurrente(mensaje)
        or es_reanudacion_evento_recurrente(mensaje)
        or es_eliminacion_evento_recurrente(mensaje)
        or es_renombrado_evento_recurrente(mensaje)
    ):
        return False

    accion = any(
        expresion in texto
        for expresion in (
            "cambia",
            "cambiar",
            "move",
            "mover",
            "pasa",
            "pasar",
            "edita",
            "editar",
            "reprograma",
            "reprogramar",
        )
    )

    hora_inicio, _ = extraer_horas_del_mensaje(
        mensaje
    )

    frecuencia, _ = extraer_recurrencia_evento(
        mensaje
    )

    return (
        accion
        and (
            hora_inicio is not None
            or frecuencia is not None
        )
    )


def pausar_evento_recurrente_desde_mensaje(
    mensaje
):
    evento = buscar_evento_recurrente_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué evento "
            "recurrente querés pausar."
        )

    estado, _ = cambiar_estado_evento_recurrente(
        evento[0],
        "pausado"
    )

    if estado == "sin_cambios":

        return (
            f"El evento recurrente #{evento[0]}: "
            f"{evento[1]} ya estaba pausado."
        )

    if estado != "actualizado":

        return (
            "No pude pausar ese evento recurrente."
        )

    return (
        f"Listo. Pausé el evento recurrente "
        f"#{evento[0]}: {evento[1]}. "
        f"También cancelé sus próximas ocurrencias "
        f"materializadas."
    )


def reanudar_evento_recurrente_desde_mensaje(
    mensaje
):
    evento = buscar_evento_recurrente_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué evento "
            "recurrente querés reanudar."
        )

    estado, _ = cambiar_estado_evento_recurrente(
        evento[0],
        "activo"
    )

    if estado == "sin_cambios":

        return (
            f"El evento recurrente #{evento[0]}: "
            f"{evento[1]} ya estaba activo."
        )

    if estado != "actualizado":

        return (
            "No pude reanudar ese evento recurrente."
        )

    return (
        f"Listo. Reanudé el evento recurrente "
        f"#{evento[0]}: {evento[1]}. "
        f"El motor generará su próxima ocurrencia."
    )


def eliminar_evento_recurrente_desde_mensaje(
    mensaje
):
    evento = buscar_evento_recurrente_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué evento "
            "recurrente querés eliminar."
        )

    estado, _ = eliminar_evento_recurrente(
        evento[0]
    )

    if estado == "ya_eliminado":

        return (
            f"El evento recurrente #{evento[0]}: "
            f"{evento[1]} ya estaba eliminado."
        )

    if estado != "eliminado":

        return (
            "No pude eliminar ese evento recurrente."
        )

    return (
        f"Listo. Eliminé el evento recurrente "
        f"#{evento[0]}: {evento[1]} "
        f"y cancelé sus próximas ocurrencias."
    )


def renombrar_evento_recurrente_desde_mensaje(
    mensaje
):
    evento = buscar_evento_recurrente_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué evento "
            "recurrente querés renombrar."
        )

    nuevo_titulo = extraer_nuevo_titulo_evento_recurrente(
        mensaje
    )

    if not nuevo_titulo:

        return (
            "No pude identificar el nuevo nombre "
            "del evento recurrente."
        )

    estado, _ = modificar_evento_recurrente(
        evento[0],
        titulo=nuevo_titulo
    )

    if estado != "actualizado":

        return (
            "No pude renombrar ese evento recurrente."
        )

    return (
        f"Listo. Renombré el evento recurrente "
        f"#{evento[0]} como {nuevo_titulo}. "
        f"El motor regenerará su próxima ocurrencia."
    )


def editar_evento_recurrente_desde_mensaje(
    mensaje
):
    evento = buscar_evento_recurrente_desde_mensaje(
        mensaje
    )

    if not evento:

        return (
            "No pude identificar qué evento "
            "recurrente querés editar."
        )

    frecuencia_nueva, dia_nuevo = extraer_recurrencia_evento(
        mensaje
    )

    hora_inicio_nueva, hora_fin_nueva = extraer_horas_del_mensaje(
        mensaje
    )

    duracion = extraer_duracion_evento_minutos(
        mensaje
    )

    if (
        hora_inicio_nueva
        and not hora_fin_nueva
        and duracion is not None
    ):

        fecha_referencia = date.today().isoformat()

        hora_fin_nueva = calcular_hora_fin_por_duracion(
            fecha_referencia,
            hora_inicio_nueva,
            duracion
        )

    if (
        frecuencia_nueva is None
        and hora_inicio_nueva is None
        and hora_fin_nueva is None
    ):

        return (
            "No pude identificar qué querés cambiar "
            "del evento recurrente."
        )

    estado, _ = modificar_evento_recurrente(
        evento[0],
        frecuencia=frecuencia_nueva,
        dia_semana=dia_nuevo,
        hora_inicio=hora_inicio_nueva,
        hora_fin=hora_fin_nueva,
    )

    if estado != "actualizado":

        return (
            "No pude editar ese evento recurrente."
        )

    actualizado = obtener_evento_recurrente_por_id(
        evento[0]
    )

    if actualizado[2] == "diaria":

        recurrencia = "todos los días"

    else:

        recurrencia = (
            f"todos los {actualizado[3]}"
        )

    respuesta = (
        f"Listo. Actualicé el evento recurrente "
        f"#{actualizado[0]}: {actualizado[1]} "
        f"— {recurrencia} "
        f"a las {actualizado[4]}"
    )

    if actualizado[5]:
        respuesta += (
            f" hasta las {actualizado[5]}"
        )

    respuesta += (
        ". El motor regenerará su próxima ocurrencia."
    )

    return respuesta


def mostrar_eventos_recurrentes():
    eventos = obtener_eventos_recurrentes()

    if not eventos:

        return (
            "No tenés eventos recurrentes activos."
        )

    lineas = [
        "Tus eventos recurrentes son:"
    ]

    for evento in eventos:

        if evento[2] == "diaria":

            frecuencia = "todos los días"

        else:

            frecuencia = (
                f"todos los {evento[3]}"
            )

        texto = (
            f"{evento[0]}. {evento[1]} "
            f"— {frecuencia} "
            f"a las {evento[4]}"
        )

        if evento[5]:
            texto += (
                f" hasta las {evento[5]}"
            )

        estado_texto = (
            "activo"
            if evento[6] == "activo"
            else "pausado"
        )

        texto += (
            f" — {estado_texto}"
        )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


def es_auditoria_eventos_recurrentes(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    tiene_recurrencia = any(
        expresion in texto
        for expresion in (
            "eventos recurrentes",
            "recurrencias de eventos",
            "recurrencias",
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "revisa",
            "revisar",
            "audita",
            "auditar",
            "limpia",
            "limpiar",
            "verifica",
            "verificar",
            "corrobora",
            "corroborar",
        )
    )

    return (
        tiene_recurrencia
        and accion
    )


def revisar_y_limpiar_eventos_recurrentes():
    resultado = auditar_y_limpiar_eventos_recurrentes()

    revisados = resultado[
        "revisados"
    ]

    corregidos = resultado[
        "corregidos"
    ]

    pausados = resultado[
        "pausados"
    ]

    ocurrencias_canceladas = resultado[
        "ocurrencias_canceladas"
    ]

    duplicados = resultado[
        "duplicados"
    ]

    observaciones = resultado[
        "observaciones"
    ]

    if (
        corregidos == 0
        and pausados == 0
        and ocurrencias_canceladas == 0
        and not duplicados
        and not observaciones
    ):
        return (
            "Eventos recurrentes correctos. "
            f"Revisé {revisados} recurrencias "
            "y no encontré inconsistencias."
        )

    partes = [
        (
            f"Auditoría terminada. "
            f"Revisé {revisados} recurrencias."
        )
    ]

    if corregidos:
        partes.append(
            f"Corregí {corregidos} "
            f"{'dato seguro' if corregidos == 1 else 'datos seguros'}."
        )

    if pausados:
        partes.append(
            f"Pausé {pausados} "
            f"{'recurrencia inválida' if pausados == 1 else 'recurrencias inválidas'}."
        )

    if ocurrencias_canceladas:
        partes.append(
            f"Cancelé {ocurrencias_canceladas} "
            f"{'ocurrencia futura inconsistente' if ocurrencias_canceladas == 1 else 'ocurrencias futuras inconsistentes'}."
        )

    if duplicados:
        pares = ", ".join(
            f"#{primero} y #{segundo}"
            for primero, segundo in duplicados
        )

        partes.append(
            "Detecté posibles duplicados exactos "
            f"({pares}), pero no los eliminé "
            "porque eso requiere tu decisión."
        )

    if observaciones:
        partes.append(
            "Detalles: "
            + " ".join(observaciones)
        )

    partes.append(
        "El motor puede regenerar las próximas "
        "ocurrencias válidas cuando corresponda."
    )

    return " ".join(
        partes
    )


def es_consulta_eventos_recurrentes(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        expresion in texto
        for expresion in (
            "que eventos recurrentes tengo",
            "mis eventos recurrentes",
            "eventos recurrentes",
            "mostrame mis eventos recurrentes",
            "mostra mis eventos recurrentes",
        )
    )


# ==========================================================
# RUTINAS RECURRENTES
# ==========================================================

DIAS_SEMANA_RUTINA = (
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
)


def extraer_recurrencia_rutina(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if any(
        expresion in texto
        for expresion in (
            "todos los dias",
            "cada dia",
            "diariamente",
        )
    ):
        return (
            "diaria",
            None
        )

    for dia in DIAS_SEMANA_RUTINA:

        if any(
            expresion in texto
            for expresion in (
                f"todos los {dia}",
                f"cada {dia}",
            )
        ):
            return (
                "semanal",
                dia
            )

    return (
        None,
        None
    )


def es_creacion_rutina(
    mensaje
):
    frecuencia, _ = extraer_recurrencia_rutina(
        mensaje
    )

    if not frecuencia:
        return False

    texto = normalizar_texto(
        mensaje
    )

    accion = any(
        expresion in texto
        for expresion in (
            "recordame",
            "recordar",
            "crea una rutina",
            "crear una rutina",
            "agrega una rutina",
            "agregame una rutina",
        )
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    return (
        accion
        and hora is not None
    )


def extraer_titulo_rutina(
    mensaje
):
    titulo = mensaje.strip()

    patrones = (
        r"^\s*todos\s+los\s+d[ií]as?\s*",
        r"^\s*cada\s+d[ií]a\s*",
        r"^\s*diariamente\s*",
        r"^\s*todos\s+los\s+lunes\s*",
        r"^\s*todos\s+los\s+martes\s*",
        r"^\s*todos\s+los\s+mi[eé]rcoles\s*",
        r"^\s*todos\s+los\s+jueves\s*",
        r"^\s*todos\s+los\s+viernes\s*",
        r"^\s*todos\s+los\s+s[aá]bados\s*",
        r"^\s*todos\s+los\s+domingos\s*",
        r"^\s*cada\s+lunes\s*",
        r"^\s*cada\s+martes\s*",
        r"^\s*cada\s+mi[eé]rcoles\s*",
        r"^\s*cada\s+jueves\s*",
        r"^\s*cada\s+viernes\s*",
        r"^\s*cada\s+s[aá]bado\s*",
        r"^\s*cada\s+domingo\s*",
    )

    for patron in patrones:
        titulo = re.sub(
            patron,
            "",
            titulo,
            count=1,
            flags=re.IGNORECASE,
        )

    titulo = re.sub(
        r"\b(?:a\s+las?|a\s+la)\s+\d{1,2}(?::\d{2})?\b",
        " ",
        titulo,
        count=1,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\b(?:recordame|recu[eé]rdame|recordar)\b",
        " ",
        titulo,
        count=1,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\b(?:que|de)\b\s*$",
        " ",
        titulo,
        flags=re.IGNORECASE,
    )

    titulo = re.sub(
        r"\s+",
        " ",
        titulo
    ).strip(" .,-")

    if titulo:
        titulo = (
            titulo[0].upper()
            + titulo[1:]
        )

    return titulo


def crear_rutina_desde_mensaje(
    mensaje
):
    frecuencia, dia_semana = extraer_recurrencia_rutina(
        mensaje
    )

    if not frecuencia:

        return (
            "No pude identificar cada cuánto "
            "querés repetir la rutina."
        )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    if not hora:

        return (
            "Necesito saber a qué hora "
            "querés ejecutar la rutina."
        )

    titulo = extraer_titulo_rutina(
        mensaje
    )

    if not titulo:

        return (
            "No pude identificar qué querés "
            "que te recuerde."
        )

    existentes = obtener_rutinas_activas()

    for rutina in existentes:

        if (
            normalizar_texto(rutina[1])
            == normalizar_texto(titulo)
            and rutina[2] == frecuencia
            and rutina[3] == dia_semana
            and rutina[4] == hora
        ):

            return (
                f"Esa rutina ya existe como "
                f"#{rutina[0]}."
            )

    rutina_id = crear_rutina(
        titulo=titulo,
        frecuencia=frecuencia,
        hora=hora,
        dia_semana=dia_semana,
    )

    if frecuencia == "diaria":

        recurrencia = "todos los días"

    else:

        recurrencia = (
            f"todos los {dia_semana}"
        )

    return (
        f"Listo. Creé la rutina "
        f"#{rutina_id}: {titulo} — "
        f"{recurrencia} a las {hora}."
    )



def buscar_rutina_desde_mensaje(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    coincidencia = re.search(
        r"\brutina\s*#?\s*(\d+)\b",
        texto
    )

    if coincidencia:

        rutina = obtener_rutina_por_id(
            int(coincidencia.group(1))
        )

        if rutina:
            return rutina

    rutinas = obtener_rutinas()

    candidatos = []

    for rutina in rutinas:

        puntuacion = puntuacion_coincidencia(
            mensaje,
            rutina[1]
        )

        if puntuacion > 0:

            candidatos.append(
                (
                    puntuacion,
                    rutina,
                )
            )

    if not candidatos:
        return None

    candidatos.sort(
        key=lambda elemento: (
            -elemento[0],
            elemento[1][0],
        )
    )

    return candidatos[0][1]


def es_pausa_rutina(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "rutina" in texto
        and any(
            expresion in texto
            for expresion in (
                "pausa",
                "pausar",
                "suspende",
                "suspender",
                "detene",
                "detener",
            )
        )
    )


def es_reanudacion_rutina(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "rutina" in texto
        and any(
            expresion in texto
            for expresion in (
                "reanuda",
                "reanudar",
                "reactiva",
                "reactivar",
                "activa",
                "activar",
            )
        )
    )


def pausar_rutina_desde_mensaje(
    mensaje
):
    rutina = buscar_rutina_desde_mensaje(
        mensaje
    )

    if not rutina:

        return (
            "No pude identificar qué rutina "
            "querés pausar."
        )

    estado, _ = cambiar_estado_rutina(
        rutina[0],
        "pausada"
    )

    if estado == "sin_cambios":

        return (
            f"La rutina #{rutina[0]}: "
            f"{rutina[1]} ya estaba pausada."
        )

    if estado != "actualizada":

        return (
            "No pude pausar esa rutina."
        )

    return (
        f"Listo. Pausé la rutina "
        f"#{rutina[0]}: {rutina[1]}."
    )


def reanudar_rutina_desde_mensaje(
    mensaje
):
    rutina = buscar_rutina_desde_mensaje(
        mensaje
    )

    if not rutina:

        return (
            "No pude identificar qué rutina "
            "querés reanudar."
        )

    estado, _ = cambiar_estado_rutina(
        rutina[0],
        "activa"
    )

    if estado == "sin_cambios":

        return (
            f"La rutina #{rutina[0]}: "
            f"{rutina[1]} ya estaba activa."
        )

    if estado != "actualizada":

        return (
            "No pude reanudar esa rutina."
        )

    return (
        f"Listo. Reanudé la rutina "
        f"#{rutina[0]}: {rutina[1]}."
    )


def es_edicion_rutina(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    if "rutina" not in texto:
        return False

    if es_pausa_rutina(
        mensaje
    ) or es_reanudacion_rutina(
        mensaje
    ):
        return False

    accion = any(
        expresion in texto
        for expresion in (
            "cambia",
            "cambiar",
            "move",
            "mover",
            "pasa",
            "pasar",
            "edita",
            "editar",
            "reprograma",
            "reprogramar",
        )
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    frecuencia, dia_semana = extraer_recurrencia_rutina(
        mensaje
    )

    return (
        accion
        and (
            hora is not None
            or frecuencia is not None
            or dia_semana is not None
        )
    )


def editar_rutina_desde_mensaje(
    mensaje
):
    rutina = buscar_rutina_desde_mensaje(
        mensaje
    )

    if not rutina:

        return (
            "No pude identificar qué rutina "
            "querés editar."
        )

    hora_nueva, _ = extraer_horas_del_mensaje(
        mensaje
    )

    frecuencia_nueva, dia_nuevo = extraer_recurrencia_rutina(
        mensaje
    )

    if (
        hora_nueva is None
        and frecuencia_nueva is None
    ):

        return (
            "No pude identificar qué querés "
            "cambiar de la rutina."
        )

    estado, _ = modificar_rutina(
        rutina[0],
        frecuencia=frecuencia_nueva,
        dia_semana=dia_nuevo,
        hora=hora_nueva,
    )

    if estado != "actualizada":

        return (
            "No pude editar esa rutina."
        )

    actualizada = obtener_rutina_por_id(
        rutina[0]
    )

    if actualizada[2] == "diaria":

        frecuencia_texto = (
            "todos los días"
        )

    else:

        frecuencia_texto = (
            f"todos los {actualizada[3]}"
        )

    return (
        f"Listo. Actualicé la rutina "
        f"#{actualizada[0]}: {actualizada[1]} "
        f"— {frecuencia_texto} "
        f"a las {actualizada[4]}."
    )



def es_eliminacion_rutina(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return (
        "rutina" in texto
        and any(
            expresion in texto
            for expresion in (
                "elimina",
                "eliminar",
                "borra",
                "borrar",
                "cancela",
                "cancelar",
                "quita",
                "quitar",
            )
        )
    )


def eliminar_rutina_desde_mensaje(
    mensaje
):
    rutina = buscar_rutina_desde_mensaje(
        mensaje
    )

    if not rutina:

        return (
            "No pude identificar qué rutina "
            "querés eliminar."
        )

    estado, _ = eliminar_rutina(
        rutina[0]
    )

    if estado == "ya_eliminada":

        return (
            f"La rutina #{rutina[0]}: "
            f"{rutina[1]} ya estaba eliminada."
        )

    if estado != "eliminada":

        return (
            "No pude eliminar esa rutina."
        )

    return (
        f"Listo. Eliminé la rutina "
        f"#{rutina[0]}: {rutina[1]}."
    )


def es_auditoria_rutinas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    habla_de_rutinas = (
        "rutina" in texto
        or "rutinas" in texto
    )

    revision = any(
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
            "sincronizacion",
            "integridad",
        )
    )

    return (
        habla_de_rutinas
        and revision
    )


def revisar_y_limpiar_rutinas():
    rutinas = obtener_rutinas()

    if not rutinas:

        return (
            "No hay rutinas recurrentes para revisar."
        )

    corregidas = []
    pausadas = []
    advertencias = []

    claves_vistas = {}

    for rutina in rutinas:

        (
            rutina_id,
            titulo,
            frecuencia,
            dia_semana,
            hora,
            estado,
            ultimo_disparo,
        ) = rutina

        # Estado inválido: la pausamos por seguridad.
        if estado not in (
            "activa",
            "pausada",
        ):

            resultado, _ = cambiar_estado_rutina(
                rutina_id,
                "pausada"
            )

            if resultado == "actualizada":
                pausadas.append(
                    (
                        rutina_id,
                        "tenía un estado inválido",
                    )
                )

            continue

        # Frecuencia inválida: no sabemos cuándo ejecutarla.
        if frecuencia not in (
            "diaria",
            "semanal",
        ):

            resultado, _ = cambiar_estado_rutina(
                rutina_id,
                "pausada"
            )

            if resultado == "actualizada":
                pausadas.append(
                    (
                        rutina_id,
                        "tenía una frecuencia inválida",
                    )
                )

            continue

        # Hora inválida: la pausamos para evitar ejecuciones erróneas.
        try:
            datetime.strptime(
                hora,
                "%H:%M"
            )

        except (TypeError, ValueError):

            resultado, _ = cambiar_estado_rutina(
                rutina_id,
                "pausada"
            )

            if resultado == "actualizada":
                pausadas.append(
                    (
                        rutina_id,
                        "tenía un horario inválido",
                    )
                )

            continue

        # Una rutina diaria no necesita día de semana.
        if (
            frecuencia == "diaria"
            and dia_semana is not None
        ):

            resultado, _ = modificar_rutina(
                rutina_id,
                frecuencia="diaria",
                dia_semana=None,
            )

            if resultado == "actualizada":
                corregidas.append(
                    (
                        rutina_id,
                        "eliminé un día semanal sobrante",
                    )
                )

                dia_semana = None

        # Una semanal sí necesita un día válido.
        if frecuencia == "semanal":

            if dia_semana not in DIAS_SEMANA_RUTINA:

                resultado, _ = cambiar_estado_rutina(
                    rutina_id,
                    "pausada"
                )

                if resultado == "actualizada":
                    pausadas.append(
                        (
                            rutina_id,
                            "le faltaba un día semanal válido",
                        )
                    )

                continue

        # Duplicados exactos: informamos, pero no eliminamos solos.
        clave = (
            normalizar_texto(titulo),
            frecuencia,
            dia_semana,
            hora,
        )

        if clave in claves_vistas:

            advertencias.append(
                (
                    rutina_id,
                    claves_vistas[clave],
                )
            )

        else:

            claves_vistas[clave] = rutina_id

    if (
        not corregidas
        and not pausadas
        and not advertencias
    ):

        cantidad = len(
            rutinas
        )

        return (
            f"Rutinas correctas. Revisé {cantidad} "
            f"{'rutina' if cantidad == 1 else 'rutinas'} "
            f"y no encontré inconsistencias."
        )

    lineas = []

    if corregidas:

        lineas.append(
            f"Corregí {len(corregidas)} "
            f"{'rutina' if len(corregidas) == 1 else 'rutinas'}:"
        )

        for rutina_id, detalle in corregidas:
            lineas.append(
                f"- Rutina #{rutina_id}: {detalle}."
            )

    if pausadas:

        if lineas:
            lineas.append("")

        lineas.append(
            f"Pausé {len(pausadas)} "
            f"{'rutina' if len(pausadas) == 1 else 'rutinas'} "
            f"por seguridad:"
        )

        for rutina_id, detalle in pausadas:
            lineas.append(
                f"- Rutina #{rutina_id}: {detalle}."
            )

    if advertencias:

        if lineas:
            lineas.append("")

        lineas.append(
            f"Encontré {len(advertencias)} "
            f"{'posible duplicado' if len(advertencias) == 1 else 'posibles duplicados'}:"
        )

        for rutina_id, original_id in advertencias:
            lineas.append(
                f"- Rutina #{rutina_id} parece duplicar "
                f"a la rutina #{original_id}."
            )

        lineas.append(
            "No eliminé duplicados automáticamente."
        )

    return "\n".join(
        lineas
    )


def mostrar_rutinas():
    rutinas = obtener_rutinas()

    if not rutinas:

        return (
            "No tenés rutinas recurrentes activas."
        )

    lineas = [
        "Tus rutinas recurrentes son:"
    ]

    for rutina in rutinas:

        if rutina[2] == "diaria":

            frecuencia = "todos los días"

        elif rutina[2] == "semanal":

            frecuencia = (
                f"todos los {rutina[3]}"
            )

        else:

            frecuencia = rutina[2]

        estado_texto = (
            "activa"
            if rutina[5] == "activa"
            else "pausada"
        )

        lineas.append(
            f"{rutina[0]}. {rutina[1]} "
            f"— {frecuencia} "
            f"a las {rutina[4]} "
            f"— {estado_texto}"
        )

    return "\n".join(
        lineas
    )


def es_consulta_rutinas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        expresion in texto
        for expresion in (
            "que rutinas tengo",
            "mis rutinas",
            "rutinas recurrentes",
            "mostrame mis rutinas",
            "mostra mis rutinas",
        )
    )


# ==========================================================
# ORDEN DE TAREAS POR URGENCIA REAL
# ==========================================================

def puntaje_urgencia_tarea(
    tarea
):
    """
    Menor puntaje = más urgente.

    Criterios:
    1. Tareas atrasadas primero.
    2. Después tareas que vencen antes.
    3. A igual fecha, prioridad alta > media > baja.
    4. Tareas sin fecha quedan al final.
    """
    fecha_tarea = tarea[3]

    prioridad = (
        tarea[5]
        if len(tarea) > 5 and tarea[5]
        else "media"
    )

    prioridad_orden = {
        "alta": 0,
        "media": 1,
        "baja": 2,
    }.get(
        prioridad,
        1
    )

    if not fecha_tarea:
        return (
            3,
            date.max,
            prioridad_orden,
            tarea[0],
        )

    try:
        fecha_objetivo = date.fromisoformat(
            fecha_tarea
        )

    except ValueError:
        return (
            3,
            date.max,
            prioridad_orden,
            tarea[0],
        )

    hoy = date.today()

    if fecha_objetivo < hoy:
        categoria = 0
    elif fecha_objetivo == hoy:
        categoria = 1
    else:
        categoria = 2

    return (
        categoria,
        fecha_objetivo,
        prioridad_orden,
        tarea[0],
    )


def obtener_tareas_por_urgencia():
    tareas = obtener_tareas_pendientes()

    return sorted(
        tareas,
        key=puntaje_urgencia_tarea
    )


def mostrar_tareas_por_urgencia():
    tareas = obtener_tareas_por_urgencia()

    if not tareas:
        return (
            "No tenés tareas pendientes."
        )

    lineas = [
        "Tus tareas ordenadas por urgencia son:"
    ]

    for tarea in tareas:

        prioridad = (
            tarea[5]
            if len(tarea) > 5 and tarea[5]
            else "media"
        )

        texto = (
            f"{tarea[0]}. "
            f"{tarea[1]}"
        )

        if tarea[3]:
            texto += (
                f" — "
                f"{fecha_para_mostrar(tarea[3])}"
            )
        else:
            texto += (
                " — sin fecha"
            )

        texto += (
            f" — prioridad {prioridad}"
        )

        vencimiento = etiqueta_vencimiento_tarea(
            tarea[3]
        )

        if vencimiento:
            texto += (
                f" — {vencimiento}"
            )

        lineas.append(
            texto
        )

    return "\n".join(
        lineas
    )


# ==========================================================
# VENCIMIENTOS Y TAREAS ATRASADAS
# ==========================================================

def dias_de_atraso_tarea(
    fecha_tarea
):
    if not fecha_tarea:
        return None

    try:
        fecha_objetivo = date.fromisoformat(
            fecha_tarea
        )

    except ValueError:
        return None

    hoy = date.today()

    if fecha_objetivo >= hoy:
        return 0

    return (
        hoy
        - fecha_objetivo
    ).days


def etiqueta_vencimiento_tarea(
    fecha_tarea
):
    if not fecha_tarea:
        return None

    try:
        fecha_objetivo = date.fromisoformat(
            fecha_tarea
        )

    except ValueError:
        return None

    hoy = date.today()

    if fecha_objetivo < hoy:

        dias = (
            hoy
            - fecha_objetivo
        ).days

        if dias == 1:
            return "ATRASADA 1 día"

        return (
            f"ATRASADA {dias} días"
        )

    if fecha_objetivo == hoy:
        return "vence hoy"

    if fecha_objetivo == (
        hoy
        + timedelta(days=1)
    ):
        return "vence mañana"

    return None


def mostrar_tareas_atrasadas():
    tareas = obtener_tareas_pendientes()

    atrasadas = []

    hoy = date.today()

    for tarea in tareas:

        if not tarea[3]:
            continue

        try:
            fecha_tarea = date.fromisoformat(
                tarea[3]
            )

        except ValueError:
            continue

        if fecha_tarea < hoy:
            atrasadas.append(
                tarea
            )

    if not atrasadas:

        return (
            "No tenés tareas atrasadas."
        )

    lineas = [
        "Tus tareas atrasadas son:"
    ]

    for tarea in atrasadas:

        dias = dias_de_atraso_tarea(
            tarea[3]
        )

        prioridad = (
            tarea[5]
            if len(tarea) > 5 and tarea[5]
            else "media"
        )

        atraso = (
            "1 día"
            if dias == 1
            else f"{dias} días"
        )

        lineas.append(
            f"{tarea[0]}. {tarea[1]} "
            f"— venció {fecha_para_mostrar(tarea[3])} "
            f"— {atraso} de atraso "
            f"— prioridad {prioridad}"
        )

    return "\n".join(
        lineas
    )


def mostrar_tareas_que_vencen(
    fecha_objetivo,
    etiqueta
):
    tareas = obtener_tareas_por_fecha(
        fecha_objetivo
    )

    if not tareas:

        return (
            f"No tenés tareas que venzan {etiqueta}."
        )

    lineas = [
        f"Tareas que vencen {etiqueta}:"
    ]

    for tarea in tareas:

        prioridad = (
            tarea[5]
            if len(tarea) > 5 and tarea[5]
            else "media"
        )

        lineas.append(
            f"{tarea[0]}. {tarea[1]} "
            f"— prioridad {prioridad}"
        )

    return "\n".join(
        lineas
    )


def mostrar_vencimientos_hoy():
    return mostrar_tareas_que_vencen(
        date.today().isoformat(),
        "hoy"
    )


def mostrar_vencimientos_manana():
    return mostrar_tareas_que_vencen(
        (
            date.today()
            + timedelta(days=1)
        ).isoformat(),
        "mañana"
    )



# ==========================================================
# CONFLICTOS DE AGENDA
# ==========================================================

def es_auditoria_conflictos_agenda(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_conflictos = any(
        expresion in texto
        for expresion in (
            "conflictos de agenda",
            "conflictos en la agenda",
            "agenda",
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "audita",
            "auditar",
            "revisa a fondo",
            "revisar a fondo",
            "verifica conflictos",
            "verificar conflictos",
            "auditoria de agenda",
            "auditoría de agenda",
        )
    )

    return (
        menciona_conflictos
        and accion
    )


def auditar_conflictos_agenda():
    eventos = obtener_eventos_activos()

    problemas = []
    duplicados = []
    claves_vistas = {}

    for evento in eventos:
        evento_id = evento[0]
        titulo = evento[1]
        fecha = evento[3]
        hora_inicio = evento[4]
        hora_fin = evento[5]

        try:
            date.fromisoformat(
                fecha
            )

        except (TypeError, ValueError):
            problemas.append(
                f"#{evento_id} {titulo}: fecha inválida ({fecha})."
            )
            continue

        if not hora_inicio:
            problemas.append(
                f"#{evento_id} {titulo}: no tiene hora de inicio."
            )
            continue

        try:
            datetime.strptime(
                hora_inicio,
                "%H:%M"
            )

        except (TypeError, ValueError):
            problemas.append(
                f"#{evento_id} {titulo}: hora de inicio inválida ({hora_inicio})."
            )
            continue

        if hora_fin:
            try:
                datetime.strptime(
                    hora_fin,
                    "%H:%M"
                )

            except (TypeError, ValueError):
                problemas.append(
                    f"#{evento_id} {titulo}: hora de fin inválida ({hora_fin})."
                )

        clave = (
            normalizar_texto(
                titulo
            ),
            fecha,
            hora_inicio,
            hora_fin or "",
        )

        if clave in claves_vistas:
            duplicados.append(
                (
                    claves_vistas[clave],
                    evento,
                )
            )
        else:
            claves_vistas[
                clave
            ] = evento

    conflictos = detectar_conflictos_agenda()

    return {
        "eventos_revisados": len(eventos),
        "problemas": problemas,
        "duplicados": duplicados,
        "conflictos": conflictos,
    }


def mostrar_auditoria_conflictos_agenda():
    resultado = auditar_conflictos_agenda()

    problemas = resultado[
        "problemas"
    ]
    duplicados = resultado[
        "duplicados"
    ]
    conflictos = resultado[
        "conflictos"
    ]

    if (
        not problemas
        and not duplicados
        and not conflictos
    ):
        return (
            "La agenda está correcta. "
            f"Revisé {resultado['eventos_revisados']} eventos activos "
            "y no encontré horarios inválidos, duplicados exactos "
            "ni conflictos próximos."
        )

    lineas = [
        (
            "Auditoría de agenda:"
        ),
        (
            f"- Eventos activos revisados: "
            f"{resultado['eventos_revisados']}"
        ),
        (
            f"- Problemas de datos: "
            f"{len(problemas)}"
        ),
        (
            f"- Duplicados exactos: "
            f"{len(duplicados)}"
        ),
        (
            f"- Conflictos próximos: "
            f"{len(conflictos)}"
        ),
    ]

    if problemas:
        lineas.append("")
        lineas.append(
            "Problemas de datos:"
        )

        for problema in problemas:
            lineas.append(
                f"- {problema}"
            )

    if duplicados:
        lineas.append("")
        lineas.append(
            "Duplicados exactos:"
        )

        for evento_a, evento_b in duplicados:
            lineas.append(
                f"- #{evento_a[0]} {evento_a[1]} "
                f"y #{evento_b[0]} {evento_b[1]} "
                f"— {fecha_para_mostrar(evento_a[3])} "
                f"{evento_a[4]}"
            )

    if conflictos:
        lineas.append("")
        lineas.append(
            "Conflictos:"
        )

        for evento_a, evento_b in conflictos:
            lineas.append(
                f"- {describir_evento_conflicto(evento_a)} "
                f"se superpone con "
                f"{describir_evento_conflicto(evento_b)}"
            )

    lineas.append("")
    lineas.append(
        "La auditoría no elimina ni modifica eventos automáticamente."
    )

    return "\n".join(
        lineas
    )


def es_consulta_conflictos_agenda(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "tengo conflictos en la agenda",
        "hay conflictos en la agenda",
        "revisa conflictos de agenda",
        "revisar conflictos de agenda",
        "busca conflictos en la agenda",
        "buscar conflictos en la agenda",
        "eventos superpuestos",
        "eventos solapados",
        "eventos que se pisan",
        "se pisan mis eventos",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def intervalo_evento_para_conflictos(
    evento
):
    fecha = evento[3]
    hora_inicio = evento[4]
    hora_fin = evento[5]

    if not fecha or not hora_inicio:
        return None

    try:
        inicio = datetime.fromisoformat(
            f"{fecha}T{hora_inicio}:00"
        )

    except ValueError:
        return None

    if not hora_fin:
        return (
            inicio,
            None,
        )

    try:
        fin = datetime.fromisoformat(
            f"{fecha}T{hora_fin}:00"
        )

    except ValueError:
        return (
            inicio,
            None,
        )

    if fin < inicio:
        fin += timedelta(
            days=1
        )

    return (
        inicio,
        fin,
    )


def eventos_se_superponen(
    evento_a,
    evento_b
):
    intervalo_a = intervalo_evento_para_conflictos(
        evento_a
    )

    intervalo_b = intervalo_evento_para_conflictos(
        evento_b
    )

    if not intervalo_a or not intervalo_b:
        return False

    inicio_a, fin_a = intervalo_a
    inicio_b, fin_b = intervalo_b

    # Si ninguno tiene hora de fin, solo consideramos
    # conflicto si comienzan exactamente al mismo tiempo.
    if fin_a is None and fin_b is None:
        return inicio_a == inicio_b

    # Si uno no tiene hora de fin, lo tratamos como un punto
    # de agenda y comprobamos si cae dentro del otro intervalo.
    if fin_a is None:
        return (
            inicio_b <= inicio_a
            and (
                fin_b is None
                or inicio_a < fin_b
            )
        )

    if fin_b is None:
        return (
            inicio_a <= inicio_b
            and inicio_b < fin_a
        )

    # Dos eventos con rango se pisan si uno empieza antes de
    # que termine el otro y viceversa. Tocar justo en el límite
    # (por ejemplo 10:00-11:00 y 11:00-12:00) no es conflicto.
    return (
        inicio_a < fin_b
        and inicio_b < fin_a
    )


def buscar_conflictos_para_evento(
    fecha,
    hora_inicio,
    hora_fin=None,
    excluir_evento_id=None,
):
    if not fecha or not hora_inicio:
        return []

    candidato = (
        -1,
        "Evento candidato",
        "",
        fecha,
        hora_inicio,
        hora_fin,
        "activo",
    )

    conflictos = []

    for evento in obtener_eventos_por_fecha(
        fecha
    ):
        if (
            excluir_evento_id is not None
            and evento[0] == excluir_evento_id
        ):
            continue

        if eventos_se_superponen(
            candidato,
            evento
        ):
            conflictos.append(
                evento
            )

    return conflictos


def describir_conflictos_para_aviso(
    conflictos
):
    if not conflictos:
        return ""

    partes = []

    for evento in conflictos:
        texto = (
            f"#{evento[0]} {evento[1]}"
        )

        if evento[4]:
            texto += (
                f" de {evento[4]}"
            )

        if evento[5]:
            texto += (
                f" a {evento[5]}"
            )

        partes.append(
            texto
        )

    return "; ".join(
        partes
    )


def crear_evento_con_control_conflictos(
    titulo,
    fecha,
    hora_inicio,
    hora_fin=None,
    descripcion="",
):
    global confirmacion_pendiente

    conflictos = buscar_conflictos_para_evento(
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
    )

    if conflictos:
        confirmacion_pendiente = {
            "tipo": "crear_evento_con_conflicto",
            "titulo": titulo,
            "fecha": fecha,
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "descripcion": descripcion,
            "conflictos": conflictos,
        }

        return (
            "⚠️ Ese horario se superpone con "
            f"{describir_conflictos_para_aviso(conflictos)}. "
            "¿Querés crear el evento igualmente?"
        )

    evento_id = crear_evento(
        titulo=titulo,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        descripcion=descripcion,
    )

    respuesta = (
        f"Listo. Agregué el evento "
        f"#{evento_id}: {titulo} para "
        f"{fecha_para_mostrar(fecha)}"
    )

    if hora_inicio:
        respuesta += (
            f" a las {hora_inicio}"
        )

    if hora_fin:
        respuesta += (
            f" hasta las {hora_fin}"
        )

    respuesta += "."

    return respuesta


def procesar_confirmacion_crear_evento_con_conflicto(
    mensaje,
    pendiente,
):
    global confirmacion_pendiente

    texto = normalizar_texto(
        mensaje
    )

    afirmativas = (
        "si",
        "sí",
        "dale",
        "crealo",
        "creala",
        "crear igual",
        "igual",
        "confirmo",
        "hacelo",
        "hazlo",
    )

    negativas = (
        "no",
        "cancelalo",
        "cancelala",
        "cancela",
        "dejalo",
        "dejala",
        "olvidalo",
        "olvidala",
        "no lo crees",
        "no la crees",
    )

    if any(
        expresion == texto
        or expresion in texto
        for expresion in negativas
    ):
        confirmacion_pendiente = None

        return (
            "Perfecto. No creé el evento."
        )

    if any(
        expresion == texto
        or expresion in texto
        for expresion in afirmativas
    ):
        evento_id = crear_evento(
            titulo=pendiente["titulo"],
            fecha=pendiente["fecha"],
            hora_inicio=pendiente["hora_inicio"],
            hora_fin=pendiente["hora_fin"],
            descripcion=pendiente["descripcion"],
        )

        confirmacion_pendiente = None

        respuesta = (
            f"Listo. Agregué igualmente el evento "
            f"#{evento_id}: {pendiente['titulo']} para "
            f"{fecha_para_mostrar(pendiente['fecha'])} "
            f"a las {pendiente['hora_inicio']}"
        )

        if pendiente["hora_fin"]:
            respuesta += (
                f" hasta las {pendiente['hora_fin']}"
            )

        respuesta += (
            ". Quedó registrado con conflicto de agenda."
        )

        return respuesta

    return (
        "Ese evento se superpone con otro compromiso. "
        "Decime “sí” para crearlo igualmente o “no” para cancelarlo."
    )


def detectar_conflictos_agenda():
    eventos = obtener_eventos_activos()

    ahora = datetime.now()

    futuros = []

    for evento in eventos:
        intervalo = intervalo_evento_para_conflictos(
            evento
        )

        if not intervalo:
            continue

        inicio, fin = intervalo

        referencia_fin = (
            fin
            if fin is not None
            else inicio
        )

        if referencia_fin < ahora:
            continue

        futuros.append(
            evento
        )

    conflictos = []

    for indice, evento_a in enumerate(
        futuros
    ):

        for evento_b in futuros[
            indice + 1:
        ]:

            if eventos_se_superponen(
                evento_a,
                evento_b
            ):
                conflictos.append(
                    (
                        evento_a,
                        evento_b,
                    )
                )

    return conflictos


def describir_evento_conflicto(
    evento
):
    texto = (
        f"#{evento[0]} {evento[1]} "
        f"— {fecha_para_mostrar(evento[3])}"
    )

    if evento[4]:
        texto += (
            f" — {evento[4]}"
        )

    if evento[5]:
        texto += (
            f" a {evento[5]}"
        )

    return texto


def mostrar_conflictos_agenda():
    conflictos = detectar_conflictos_agenda()

    if not conflictos:
        return (
            "No encontré conflictos entre tus "
            "eventos próximos."
        )

    lineas = [
        (
            f"Encontré {len(conflictos)} "
            f"{'conflicto' if len(conflictos) == 1 else 'conflictos'} "
            "en tu agenda:"
        )
    ]

    for indice, (
        evento_a,
        evento_b,
    ) in enumerate(
        conflictos,
        start=1
    ):
        lineas.append(
            f"{indice}. "
            f"{describir_evento_conflicto(evento_a)} "
            f"se superpone con "
            f"{describir_evento_conflicto(evento_b)}"
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

            prioridad = (
                tarea[5]
                if len(tarea) > 5 and tarea[5]
                else "media"
            )

            lineas.append(
                f"- #{tarea[0]} "
                f"{tarea[1]} "
                f"[prioridad {prioridad}]"
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

            prioridad = (
                tarea[5]
                if len(tarea) > 5 and tarea[5]
                else "media"
            )

            lineas.append(
                f"- "
                f"{fecha_para_mostrar(tarea[3])}: "
                f"#{tarea[0]} "
                f"{tarea[1]} "
                f"[prioridad {prioridad}]"
            )

    return "\n".join(
        lineas
    )




# ==========================================================
# AUDITORÍA Y LIMPIEZA TAREA ↔ RECORDATORIOS
# ==========================================================

def es_auditoria_sincronizacion_tareas(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    habla_de_tareas = (
        "tarea" in texto
        or "tareas" in texto
    )

    menciona_revision = any(
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
            "sincronizacion",
            "sincronizados",
            "sincronizado",
        )
    )

    return (
        habla_de_tareas
        and menciona_revision
    )


def revisar_y_limpiar_sincronizacion_tareas():
    """
    Revisa todos los recordatorios pendientes vinculados a tareas.

    Limpia de forma segura:
    - recordatorios vinculados a tareas inexistentes;
    - recordatorios vinculados a tareas ya completadas;
    - recordatorios vinculados con fecha/hora inválida.

    No toca recordatorios independientes ni recordatorios de eventos.
    """

    pendientes = obtener_recordatorios_pendientes()

    vinculados = []
    cancelados = []
    problemas_no_modificados = []

    for pendiente in pendientes:

        recordatorio_id = pendiente[0]

        recordatorio = obtener_recordatorio_por_id(
            recordatorio_id
        )

        if not recordatorio:
            continue

        tarea_id = (
            recordatorio[7]
            if len(recordatorio) > 7
            else None
        )

        if tarea_id is None:
            continue

        vinculados.append(
            recordatorio
        )

        tarea = obtener_tarea_por_id(
            tarea_id
        )

        if not tarea:

            estado, _ = cancelar_recordatorio(
                recordatorio_id
            )

            if estado == "cancelado":
                cancelados.append(
                    (
                        recordatorio_id,
                        (
                            f"estaba vinculado a la tarea "
                            f"#{tarea_id}, pero esa tarea no existe"
                        ),
                    )
                )

            continue

        if tarea[4] != "pendiente":

            estado, _ = cancelar_recordatorio(
                recordatorio_id
            )

            if estado == "cancelado":
                cancelados.append(
                    (
                        recordatorio_id,
                        (
                            f"estaba vinculado a la tarea "
                            f"#{tarea_id}: {tarea[1]}, "
                            f"que ya está {tarea[4]}"
                        ),
                    )
                )

            continue

        try:
            momento = datetime.fromisoformat(
                recordatorio[3]
            )

        except (TypeError, ValueError):

            estado, _ = cancelar_recordatorio(
                recordatorio_id
            )

            if estado == "cancelado":
                cancelados.append(
                    (
                        recordatorio_id,
                        (
                            f"tenía una fecha/hora inválida "
                            f"para la tarea #{tarea_id}: {tarea[1]}"
                        ),
                    )
                )

            continue

        if tarea[3]:

            try:
                fecha_tarea = datetime.fromisoformat(
                    tarea[3]
                ).date()

            except ValueError:
                problemas_no_modificados.append(
                    (
                        recordatorio_id,
                        (
                            f"la tarea #{tarea_id}: {tarea[1]} "
                            f"tiene una fecha inválida"
                        ),
                    )
                )

                continue

            # Un aviso puede ser anterior al vencimiento de la tarea,
            # por eso no exigimos que ambas fechas sean iguales.
            if momento.date() > fecha_tarea:

                problemas_no_modificados.append(
                    (
                        recordatorio_id,
                        (
                            f"está programado para después de la fecha "
                            f"de la tarea #{tarea_id}: {tarea[1]}"
                        ),
                    )
                )

    if not vinculados:

        return (
            "No hay recordatorios pendientes vinculados a tareas "
            "para revisar."
        )

    if (
        not cancelados
        and not problemas_no_modificados
    ):

        cantidad = len(
            vinculados
        )

        return (
            f"Sincronización de tareas correcta. Revisé "
            f"{cantidad} "
            f"{'recordatorio vinculado' if cantidad == 1 else 'recordatorios vinculados'} "
            f"y no encontré vínculos huérfanos ni inconsistencias."
        )

    lineas = []

    if cancelados:

        lineas.append(
            (
                f"Limpié {len(cancelados)} "
                f"{'recordatorio inválido' if len(cancelados) == 1 else 'recordatorios inválidos'}:"
            )
        )

        for recordatorio_id, detalle in cancelados:

            lineas.append(
                f"- Recordatorio #{recordatorio_id}: {detalle}."
            )

    if problemas_no_modificados:

        if lineas:
            lineas.append("")

        lineas.append(
            (
                f"También encontré {len(problemas_no_modificados)} "
                f"{'situación para revisar' if len(problemas_no_modificados) == 1 else 'situaciones para revisar'}:"
            )
        )

        for recordatorio_id, detalle in problemas_no_modificados:

            lineas.append(
                f"- Recordatorio #{recordatorio_id}: {detalle}."
            )

        lineas.append("")
        lineas.append(
            "No modifiqué esas situaciones porque podrían ser intencionales."
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





# ==========================================================
# CONFIGURACIÓN DEL RESUMEN NOCTURNO
# ==========================================================

def es_auditoria_resumen_nocturno(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_nocturno = any(
        expresion in texto
        for expresion in (
            "resumen nocturno",
            "resumen de la noche",
            "cierre del dia",
            "cierre diario",
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "revisa",
            "revisar",
            "audita",
            "auditar",
            "verifica",
            "verificar",
            "corrobora",
            "corroborar",
        )
    )

    return (
        menciona_nocturno
        and accion
    )


def revisar_resumen_nocturno_desde_hermes():
    resultado = auditar_configuracion_resumen_nocturno()

    correcciones = resultado.get(
        "correcciones",
        []
    )

    if resultado.get("estado") == "correcto":

        estado = (
            "activo"
            if resultado.get("activo")
            else "desactivado"
        )

        ultimo_envio = resultado.get(
            "ultimo_envio"
        )

        respuesta = (
            "La configuración del resumen nocturno "
            f"está correcta. Está {estado} y "
            f"programado para las "
            f"{resultado.get('hora')}."
        )

        if ultimo_envio:
            respuesta += (
                f" Último envío registrado: "
                f"{ultimo_envio}."
            )

        respuesta += (
            " El control antidupl. está activo: "
            "solo puede reclamarse un envío automático "
            "por noche."
        )

        return respuesta

    partes = [
        "Revisé la configuración del resumen nocturno "
        "y corregí lo necesario."
    ]

    if correcciones:
        partes.append(
            " ".join(correcciones)
        )

    partes.append(
        "El control antidupl. quedó activo."
    )

    return " ".join(
        partes
    )


def es_cambio_hora_resumen_nocturno(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_resumen = any(
        expresion in texto
        for expresion in (
            "resumen nocturno",
            "resumen de la noche",
            "cierre del dia",
            "cierre diario",
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "mandame",
            "enviame",
            "envia",
            "cambia",
            "cambiar",
            "pone",
            "poner",
            "programa",
            "programar",
            "quiero",
        )
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    return (
        menciona_resumen
        and accion
        and hora is not None
    )


def cambiar_hora_resumen_nocturno_desde_mensaje(
    mensaje
):
    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    if not hora:
        return (
            "No pude identificar la hora del "
            "resumen nocturno."
        )

    estado, hora_guardada = configurar_hora_resumen_nocturno(
        hora
    )

    if estado != "actualizada":
        return (
            "No pude guardar esa hora para "
            "el resumen nocturno."
        )

    return (
        f"Listo. El resumen nocturno automático "
        f"queda programado para las "
        f"{hora_guardada}."
    )


def es_consulta_hora_resumen_nocturno(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        expresion in texto
        for expresion in (
            "a que hora esta el resumen nocturno",
            "a que hora tengo el resumen nocturno",
            "a que hora se envia el resumen nocturno",
            "hora del resumen nocturno",
            "cuando se envia el resumen nocturno",
            "cuando llega el resumen nocturno",
            "a que hora esta el resumen de la noche",
            "a que hora se envia el resumen de la noche",
        )
    )


def mostrar_hora_resumen_nocturno():
    configuracion = obtener_configuracion_resumen_nocturno()

    if not configuracion:
        return (
            "No encontré la configuración "
            "del resumen nocturno."
        )

    activo, hora, ultimo_envio = configuracion

    estado = (
        "activo"
        if activo
        else "desactivado"
    )

    respuesta = (
        f"El resumen nocturno automático está "
        f"{estado} y programado para las "
        f"{hora}."
    )

    if ultimo_envio:
        respuesta += (
            f" Último envío registrado: "
            f"{ultimo_envio}."
        )

    return respuesta


# ==========================================================
# RESUMEN NOCTURNO
# ==========================================================

def es_resumen_nocturno_manual(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "dame mi resumen nocturno",
        "resumen nocturno",
        "cierre del dia",
        "cerrame el dia",
        "como termino mi dia",
        "como cerro mi dia",
        "resumen de la noche",
        "preparame para manana",
        "que me queda para manana",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def generar_resumen_nocturno():
    hoy = date.today()
    manana = (
        hoy
        + timedelta(days=1)
    )

    hoy_iso = hoy.isoformat()
    manana_iso = manana.isoformat()

    tareas_pendientes = obtener_tareas_pendientes()
    tareas_completadas = obtener_tareas_completadas_en_fecha(
        hoy_iso
    )

    tareas_atrasadas = []

    for tarea in tareas_pendientes:

        if not tarea[3]:
            continue

        try:
            fecha_tarea = date.fromisoformat(
                tarea[3]
            )

        except ValueError:
            continue

        if fecha_tarea < hoy:
            tareas_atrasadas.append(
                tarea
            )

    tareas_manana = obtener_tareas_por_fecha(
        manana_iso
    )

    eventos_hoy = obtener_eventos_por_fecha(
        hoy_iso
    )

    eventos_manana = obtener_eventos_por_fecha(
        manana_iso
    )

    lineas = [
        (
            f"Resumen nocturno — "
            f"{hoy.strftime('%d/%m/%Y')}"
        ),
        "",
        (
            f"Hoy completaste "
            f"{len(tareas_completadas)} "
            f"{'tarea' if len(tareas_completadas) == 1 else 'tareas'}. "
            f"Quedan {len(tareas_atrasadas)} "
            f"{'tarea atrasada' if len(tareas_atrasadas) == 1 else 'tareas atrasadas'}."
        ),
        "",
        "✅ Completado hoy:",
    ]

    if tareas_completadas:

        for tarea in tareas_completadas:

            prioridad = (
                tarea[5]
                if len(tarea) > 5 and tarea[5]
                else "media"
            )

            lineas.append(
                f"- #{tarea[0]} {tarea[1]} "
                f"— prioridad {prioridad}"
            )

    else:
        lineas.append(
            "No registraste tareas completadas hoy."
        )

    lineas.extend(
        [
            "",
            "⚠️ Pendientes atrasados:",
        ]
    )

    if tareas_atrasadas:

        atrasadas_ordenadas = sorted(
            tareas_atrasadas,
            key=puntaje_urgencia_tarea
        )

        for tarea in atrasadas_ordenadas:

            lineas.append(
                f"- {formatear_tarea_resumen(tarea)}"
            )

    else:
        lineas.append(
            "No tenés tareas atrasadas."
        )

    lineas.extend(
        [
            "",
            "📅 Lo que pasó hoy:",
        ]
    )

    if eventos_hoy:

        for evento in eventos_hoy:

            texto_evento = (
                f"- #{evento[0]} {evento[1]}"
            )

            if evento[4]:
                texto_evento += (
                    f" — {evento[4]}"
                )

            if evento[5]:
                texto_evento += (
                    f" a {evento[5]}"
                )

            lineas.append(
                texto_evento
            )

    else:
        lineas.append(
            "No tenías eventos registrados para hoy."
        )

    lineas.extend(
        [
            "",
            "🌅 Mañana:",
        ]
    )

    if tareas_manana:

        lineas.append(
            "Tareas:"
        )

        tareas_manana_ordenadas = sorted(
            tareas_manana,
            key=puntaje_urgencia_tarea
        )

        for tarea in tareas_manana_ordenadas:
            lineas.append(
                f"- {formatear_tarea_resumen(tarea)}"
            )

    else:
        lineas.append(
            "No tenés tareas con vencimiento mañana."
        )

    if eventos_manana:

        lineas.append(
            "Eventos:"
        )

        for evento in eventos_manana:

            texto_evento = (
                f"- #{evento[0]} {evento[1]}"
            )

            if evento[4]:
                texto_evento += (
                    f" — {evento[4]}"
                )

            if evento[5]:
                texto_evento += (
                    f" a {evento[5]}"
                )

            lineas.append(
                texto_evento
            )

    else:
        lineas.append(
            "No tenés eventos mañana."
        )

    if tareas_atrasadas:

        mas_urgente = sorted(
            tareas_atrasadas,
            key=puntaje_urgencia_tarea
        )[0]

        lineas.extend(
            [
                "",
                "🎯 Foco recomendado para mañana:",
                f"- {formatear_tarea_resumen(mas_urgente)}",
            ]
        )

    return "\n".join(
        lineas
    )


# ==========================================================
# CONFIGURACIÓN DEL RESUMEN DIARIO
# ==========================================================

def es_auditoria_resumen_diario(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_resumen = any(
        expresion in texto
        for expresion in (
            "resumen diario",
            "resumen de la manana",
            "resumen matutino",
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "revisa",
            "revisar",
            "audita",
            "auditar",
            "verifica",
            "verificar",
            "corrobora",
            "corroborar",
        )
    )

    return (
        menciona_resumen
        and accion
    )


def revisar_resumen_diario_desde_hermes():
    resultado = auditar_configuracion_resumen_diario()

    correcciones = resultado.get(
        "correcciones",
        []
    )

    if resultado.get("estado") == "correcto":

        estado = (
            "activo"
            if resultado.get("activo")
            else "desactivado"
        )

        ultimo_envio = resultado.get(
            "ultimo_envio"
        )

        respuesta = (
            "La configuración del resumen diario "
            f"está correcta. Está {estado} y "
            f"programado para las "
            f"{resultado.get('hora')}."
        )

        if ultimo_envio:
            respuesta += (
                f" Último envío registrado: "
                f"{ultimo_envio}."
            )

        respuesta += (
            " El control antidupl. está activo: "
            "solo puede reclamarse un envío automático "
            "por día."
        )

        return respuesta

    partes = [
        "Revisé la configuración del resumen diario "
        "y corregí lo necesario."
    ]

    if correcciones:
        partes.append(
            " ".join(correcciones)
        )

    partes.append(
        "El control antidupl. quedó activo."
    )

    return " ".join(
        partes
    )


def es_cambio_hora_resumen_diario(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    menciona_resumen = any(
        expresion in texto
        for expresion in (
            "resumen diario",
            "resumen de la manana",
            "resumen de mañana",
            "resumen matutino",
            "resumen de cada manana",
            "resumen cada manana",
        )
    )

    accion = any(
        expresion in texto
        for expresion in (
            "mandame",
            "enviame",
            "envia",
            "cambia",
            "cambiar",
            "pone",
            "poner",
            "programa",
            "programar",
            "quiero",
        )
    )

    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    return (
        menciona_resumen
        and accion
        and hora is not None
    )


def cambiar_hora_resumen_diario_desde_mensaje(
    mensaje
):
    hora, _ = extraer_horas_del_mensaje(
        mensaje
    )

    if not hora:
        return (
            "No pude identificar la hora del "
            "resumen diario."
        )

    estado, hora_guardada = configurar_hora_resumen_diario(
        hora
    )

    if estado != "actualizada":
        return (
            "No pude guardar esa hora para "
            "el resumen diario."
        )

    return (
        f"Listo. El resumen diario automático "
        f"queda programado para las "
        f"{hora_guardada}."
    )


def es_consulta_hora_resumen_diario(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    return any(
        expresion in texto
        for expresion in (
            "a que hora esta el resumen diario",
            "a que hora tengo el resumen diario",
            "a que hora se envia el resumen diario",
            "hora del resumen diario",
            "cuando se envia el resumen diario",
            "cuando llega el resumen diario",
        )
    )


def mostrar_hora_resumen_diario():
    configuracion = obtener_configuracion_resumen_diario()

    if not configuracion:
        return (
            "No encontré la configuración "
            "del resumen diario."
        )

    activo, hora, ultimo_envio = configuracion

    if activo:
        estado = "activo"
    else:
        estado = "desactivado"

    respuesta = (
        f"El resumen diario automático está "
        f"{estado} y programado para las "
        f"{hora}."
    )

    if ultimo_envio:
        respuesta += (
            f" Último envío registrado: "
            f"{ultimo_envio}."
        )

    return respuesta


# ==========================================================
# RESUMEN DIARIO
# ==========================================================

def es_resumen_diario_manual(
    mensaje
):
    texto = normalizar_texto(
        mensaje
    )

    expresiones = (
        "dame mi resumen de hoy",
        "dame el resumen de hoy",
        "mi resumen de hoy",
        "resumen de hoy",
        "resumen diario",
        "como viene mi dia",
        "como esta mi dia",
        "que tengo para hoy",
        "organizame el dia",
        "organiza mi dia",
    )

    return any(
        expresion in texto
        for expresion in expresiones
    )


def formatear_tarea_resumen(
    tarea
):
    prioridad = (
        tarea[5]
        if len(tarea) > 5 and tarea[5]
        else "media"
    )

    texto = (
        f"#{tarea[0]} {tarea[1]} "
        f"— prioridad {prioridad}"
    )

    if tarea[3]:

        etiqueta = etiqueta_vencimiento_tarea(
            tarea[3]
        )

        if etiqueta:
            texto += (
                f" — {etiqueta}"
            )

        elif tarea[3] != date.today().isoformat():
            texto += (
                f" — {fecha_para_mostrar(tarea[3])}"
            )

    else:
        texto += (
            " — sin fecha"
        )

    return texto


def generar_resumen_diario():
    hoy = date.today()
    hoy_iso = hoy.isoformat()

    tareas = obtener_tareas_pendientes()

    tareas_hoy = [
        tarea
        for tarea in tareas
        if tarea[3] == hoy_iso
    ]

    tareas_atrasadas = []

    for tarea in tareas:

        if not tarea[3]:
            continue

        try:
            fecha_tarea = date.fromisoformat(
                tarea[3]
            )

        except ValueError:
            continue

        if fecha_tarea < hoy:
            tareas_atrasadas.append(
                tarea
            )

    prioridades = sorted(
        tareas,
        key=puntaje_urgencia_tarea
    )[:3]

    eventos_hoy = obtener_eventos_por_fecha(
        hoy_iso
    )

    recordatorios = obtener_recordatorios_pendientes()

    recordatorios_relevantes = []

    for recordatorio in recordatorios:

        try:
            momento = datetime.fromisoformat(
                recordatorio[3]
            )

        except (TypeError, ValueError):
            continue

        if momento.date() <= hoy:
            recordatorios_relevantes.append(
                (
                    recordatorio,
                    momento,
                )
            )

    lineas = [
        (
            f"Resumen de hoy — "
            f"{hoy.strftime('%d/%m/%Y')}"
        ),
        "",
        (
            f"Tenés {len(tareas_hoy)} "
            f"{'tarea' if len(tareas_hoy) == 1 else 'tareas'} "
            f"para hoy, {len(tareas_atrasadas)} "
            f"{'atrasada' if len(tareas_atrasadas) == 1 else 'atrasadas'}, "
            f"{len(eventos_hoy)} "
            f"{'evento' if len(eventos_hoy) == 1 else 'eventos'} "
            "hoy."
        ),
        "",
        "📌 Prioridades:",
    ]

    if prioridades:

        for indice, tarea in enumerate(
            prioridades,
            start=1
        ):
            lineas.append(
                f"{indice}. "
                f"{formatear_tarea_resumen(tarea)}"
            )

    else:
        lineas.append(
            "No tenés tareas pendientes."
        )

    lineas.extend(
        [
            "",
            "✅ Tareas de hoy:",
        ]
    )

    if tareas_hoy:

        tareas_hoy_ordenadas = sorted(
            tareas_hoy,
            key=puntaje_urgencia_tarea
        )

        for tarea in tareas_hoy_ordenadas:
            lineas.append(
                f"- {formatear_tarea_resumen(tarea)}"
            )

    else:
        lineas.append(
            "No tenés tareas con vencimiento hoy."
        )

    lineas.extend(
        [
            "",
            "⚠️ Tareas atrasadas:",
        ]
    )

    if tareas_atrasadas:

        tareas_atrasadas_ordenadas = sorted(
            tareas_atrasadas,
            key=puntaje_urgencia_tarea
        )

        for tarea in tareas_atrasadas_ordenadas:
            lineas.append(
                f"- {formatear_tarea_resumen(tarea)}"
            )

    else:
        lineas.append(
            "No tenés tareas atrasadas."
        )

    lineas.extend(
        [
            "",
            "📅 Agenda de hoy:",
        ]
    )

    if eventos_hoy:

        for evento in eventos_hoy:

            texto_evento = (
                f"- #{evento[0]} {evento[1]}"
            )

            if evento[4]:
                texto_evento += (
                    f" — {evento[4]}"
                )

            if evento[5]:
                texto_evento += (
                    f" a {evento[5]}"
                )

            lineas.append(
                texto_evento
            )

    else:
        lineas.append(
            "No tenés eventos hoy."
        )

    lineas.extend(
        [
            "",
            "🔔 Recordatorios pendientes:",
        ]
    )

    if recordatorios_relevantes:

        recordatorios_relevantes.sort(
            key=lambda elemento: elemento[1]
        )

        for recordatorio, momento in recordatorios_relevantes:

            if momento.date() < hoy:
                cuando = (
                    f"vencido "
                    f"{momento.strftime('%d/%m %H:%M')}"
                )
            else:
                cuando = (
                    f"hoy {momento.strftime('%H:%M')}"
                )

            lineas.append(
                f"- #{recordatorio[0]} "
                f"{recordatorio[1]} "
                f"— {cuando}"
            )

    else:
        lineas.append(
            "No tenés recordatorios pendientes "
            "para hoy ni vencidos."
        )

    return "\n".join(
        lineas
    )


def procesar_comandos_directos(
    mensaje
):
    global confirmacion_pendiente
    global ultimo_contexto_edicion

    texto = normalizar_texto(
        mensaje
    )

    if es_auditoria_acceso_web(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return auditar_acceso_web()

    if es_resumen_ultima_pagina_web(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return resumir_ultima_pagina_web()

    if es_pregunta_sobre_ultima_pagina_web(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return preguntar_sobre_ultima_pagina_web(
            mensaje
        )

    if es_lectura_web_controlada(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return leer_web_desde_mensaje(
            mensaje
        )

    if es_busqueda_web_controlada(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return buscar_web_desde_mensaje(
            mensaje
        )

    if es_auditoria_calendario_externo(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return auditar_calendario_externo()

    if es_importacion_calendario(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return importar_calendario_desde_mensaje(
            mensaje
        )

    if es_exportacion_calendario(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return exportar_calendario_desde_mensaje(
            mensaje
        )

    if es_auditoria_archivos_locales(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return auditar_archivos_locales()

    if es_creacion_archivo_local(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return crear_archivo_local_desde_mensaje(
            mensaje
        )

    if es_edicion_archivo_local(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return editar_archivo_local_desde_mensaje(
            mensaje
        )

    if es_eliminacion_archivo_local(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return eliminar_archivo_local_desde_mensaje(
            mensaje
        )

    if es_listado_ruta_local(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return listar_ruta_local_desde_mensaje(
            mensaje
        )

    if es_lectura_archivo_local(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return leer_archivo_local_desde_mensaje(
            mensaje
        )

    if es_auditoria_busqueda_local(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return auditar_busqueda_local()

    if es_busqueda_combinada(
        mensaje
    ):
        return buscar_notas_y_memoria_desde_mensaje(
            mensaje
        )

    if es_busqueda_memoria(
        mensaje
    ):
        return buscar_memoria_desde_mensaje(
            mensaje
        )

    if es_busqueda_notas(
        mensaje
    ):
        return buscar_notas_desde_mensaje(
            mensaje
        )

    if es_auditoria_notas(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return auditar_notas()

    if es_limpieza_notas(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return limpiar_notas()

    if es_cambio_categoria_nota(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return cambiar_categoria_nota_desde_mensaje(
            mensaje
        )

    if es_consulta_categorias_notas(
        mensaje
    ):
        return mostrar_categorias_notas()

    if es_consulta_notas_por_categoria(
        mensaje
    ):
        respuesta_categoria = mostrar_notas_por_categoria_desde_mensaje(
            mensaje
        )

        if respuesta_categoria is not None:
            return respuesta_categoria

    if es_edicion_nota(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return editar_nota_desde_mensaje(
            mensaje
        )

    if es_eliminacion_nota(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return eliminar_nota_desde_mensaje(
            mensaje
        )

    if es_creacion_nota(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return crear_nota_desde_mensaje(
            mensaje
        )

    if es_consulta_nota_por_id(
        mensaje
    ):
        respuesta_nota = mostrar_nota_por_id_desde_mensaje(
            mensaje
        )

        if respuesta_nota is not None:
            return respuesta_nota

    if es_consulta_notas(
        mensaje
    ):
        return mostrar_notas()

    if es_referencia_natural_corta(
        mensaje
    ):
        respuesta_referencia = resolver_referencia_natural_corta(
            mensaje
        )

        if respuesta_referencia is not None:
            confirmacion_pendiente = None
            ultimo_contexto_edicion = None

            return respuesta_referencia

    if es_auditoria_contexto_conversacional(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return auditar_contexto_conversacional()

    if es_reparacion_contexto_conversacional(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return reparar_contexto_conversacional()

    if es_comando_compactar_contexto(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return compactar_contexto_conversacional(
            forzar=True
        )

    if es_consulta_estado_contexto(
        mensaje
    ):
        return mostrar_estado_contexto()

    if es_limpieza_contexto_conversacional(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return limpiar_contexto_conversacional_desde_hermes()

    if es_auditoria_resumen_nocturno(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return revisar_resumen_nocturno_desde_hermes()

    if es_cambio_hora_resumen_nocturno(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return cambiar_hora_resumen_nocturno_desde_mensaje(
            mensaje
        )

    if es_consulta_hora_resumen_nocturno(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return mostrar_hora_resumen_nocturno()

    if es_resumen_nocturno_manual(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return generar_resumen_nocturno()

    if es_auditoria_resumen_diario(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return revisar_resumen_diario_desde_hermes()

    if es_cambio_hora_resumen_diario(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return cambiar_hora_resumen_diario_desde_mensaje(
            mensaje
        )

    if es_consulta_hora_resumen_diario(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return mostrar_hora_resumen_diario()

    if es_resumen_diario_manual(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return generar_resumen_diario()

    if es_auditoria_conflictos_agenda(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return mostrar_auditoria_conflictos_agenda()

    if es_consulta_conflictos_agenda(
        mensaje
    ):

        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return mostrar_conflictos_agenda()

    # Las órdenes completas de prioridad + fecha deben resolverse
    # antes que la edición contextual. Palabras como "pasala"
    # también aparecen en órdenes completas y no deben confundirse
    # con referencias a una acción anterior.
    if es_cambio_combinado_tarea(
        mensaje
    ):
        confirmacion_pendiente = None
        ultimo_contexto_edicion = None

        return cambiar_prioridad_y_fecha_tarea_desde_mensaje(
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

    if (
        confirmacion_pendiente is not None
        and es_cambio_horario_aviso_tarea(
            mensaje
        )
    ):
        confirmacion_pendiente = None

        return cambiar_horario_aviso_tarea_desde_mensaje(
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

    if es_auditoria_sincronizacion_tareas(
        mensaje
    ):

        return revisar_y_limpiar_sincronizacion_tareas()

    if es_auditoria_sincronizacion(
        mensaje
    ):

        return revisar_sincronizacion_eventos()

    # ======================================================
    # EVENTOS RECURRENTES
    # Deben resolverse antes que eventos normales y rutinas.
    # ======================================================

    if es_auditoria_eventos_recurrentes(
        mensaje
    ):

        return revisar_y_limpiar_eventos_recurrentes()

    if es_pausa_evento_recurrente(
        mensaje
    ):

        return pausar_evento_recurrente_desde_mensaje(
            mensaje
        )

    if es_reanudacion_evento_recurrente(
        mensaje
    ):

        return reanudar_evento_recurrente_desde_mensaje(
            mensaje
        )

    if es_eliminacion_evento_recurrente(
        mensaje
    ):

        return eliminar_evento_recurrente_desde_mensaje(
            mensaje
        )

    if es_renombrado_evento_recurrente(
        mensaje
    ):

        return renombrar_evento_recurrente_desde_mensaje(
            mensaje
        )

    if es_edicion_evento_recurrente(
        mensaje
    ):

        return editar_evento_recurrente_desde_mensaje(
            mensaje
        )

    if es_consulta_eventos_recurrentes(
        mensaje
    ):

        return mostrar_eventos_recurrentes()

    if es_creacion_evento_recurrente(
        mensaje
    ):

        return crear_evento_recurrente_desde_mensaje(
            mensaje
        )

    # ======================================================
    # RUTINAS RECURRENTES
    # Deben resolverse antes que los recordatorios normales,
    # para que "todos los días..." no cree un aviso único.
    # ======================================================

    if es_auditoria_rutinas(
        mensaje
    ):

        return revisar_y_limpiar_rutinas()

    if es_eliminacion_rutina(
        mensaje
    ):

        return eliminar_rutina_desde_mensaje(
            mensaje
        )

    if es_pausa_rutina(
        mensaje
    ):

        return pausar_rutina_desde_mensaje(
            mensaje
        )

    if es_reanudacion_rutina(
        mensaje
    ):

        return reanudar_rutina_desde_mensaje(
            mensaje
        )

    if es_edicion_rutina(
        mensaje
    ):

        return editar_rutina_desde_mensaje(
            mensaje
        )

    if es_consulta_rutinas(
        mensaje
    ):

        return mostrar_rutinas()

    if es_creacion_rutina(
        mensaje
    ):

        return crear_rutina_desde_mensaje(
            mensaje
        )

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

    # CONSULTAS DE URGENCIA DE TAREAS
    # Deben resolverse antes que los cambios de prioridad.

    if any(
        patron in texto
        for patron in (
            "que tarea es mas urgente",
            "que tareas son mas urgentes",
            "cual tarea es mas urgente",
            "cuales tareas son mas urgentes",
            "que hago primero",
            "por cual tarea empiezo",
            "cual hago primero",
            "cual deberia hacer primero",
            "ordena mis tareas por urgencia",
            "ordenalas por urgencia",
            "tareas por urgencia",
            "mostrame las tareas mas urgentes",
            "mostra las tareas mas urgentes",
        )
    ):

        return mostrar_tareas_por_urgencia()

    # CAMBIAR PRIORIDAD DE TAREA

    if es_cambio_prioridad_tarea(
        mensaje
    ):

        return cambiar_prioridad_tarea_desde_mensaje(
            mensaje
        )

    # CAMBIAR HORARIO DE AVISO DE TAREA

    if es_cambio_horario_aviso_tarea(
        mensaje
    ):

        return cambiar_horario_aviso_tarea_desde_mensaje(
            mensaje
        )

    # MODIFICAR FECHA DE TAREAS

    if es_modificacion_fecha_tarea(
        mensaje
    ):

        return modificar_fecha_tarea_desde_mensaje(
            mensaje
        )

    # RECORDATORIOS VINCULADOS A TAREAS

    if es_recordatorio_vinculado_tarea(
        mensaje
    ):

        return crear_recordatorio_vinculado_tarea_desde_mensaje(
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

    # TAREAS POR URGENCIA REAL

    if any(
        patron in texto
        for patron in (
            "ordenalas por urgencia",
            "ordena mis tareas por urgencia",
            "tareas por urgencia",
            "que tarea es mas urgente",
            "que tareas son mas urgentes",
            "mostrame las tareas mas urgentes",
            "mostra las tareas mas urgentes",
        )
    ):

        return mostrar_tareas_por_urgencia()

    # VENCIMIENTOS DE TAREAS

    if any(
        patron in texto
        for patron in (
            "tareas atrasadas",
            "tareas vencidas",
            "que tareas estan atrasadas",
            "que tareas tengo atrasadas",
            "que tengo atrasado",
            "que tareas vencieron",
        )
    ):

        return mostrar_tareas_atrasadas()

    if any(
        patron in texto
        for patron in (
            "que tareas vencen hoy",
            "que vence hoy",
            "vencimientos de hoy",
            "tareas que vencen hoy",
        )
    ):

        return mostrar_vencimientos_hoy()

    if any(
        patron in texto
        for patron in (
            "que tareas vencen manana",
            "que vence manana",
            "vencimientos de manana",
            "tareas que vencen manana",
        )
    ):

        return mostrar_vencimientos_manana()

    if any(
        patron in texto
        for patron in (
            "que hago primero",
            "por cual tarea empiezo",
            "cual hago primero",
            "cual deberia hacer primero",
        )
    ):

        return mostrar_tareas_por_urgencia()

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
            "completa",
            "complete",
            "termine",
            "termina",
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

                cantidad_cancelada = cancelar_recordatorios_de_tarea(
                    tarea_id
                )

                respuesta = (
                    f"La tarea #{tarea_id} "
                    f"ya estaba completada."
                )

                if cantidad_cancelada == 1:

                    respuesta += (
                        " Cancelé 1 recordatorio "
                        "vinculado que seguía pendiente."
                    )

                elif cantidad_cancelada > 1:

                    respuesta += (
                        f" Cancelé {cantidad_cancelada} "
                        f"recordatorios vinculados "
                        f"que seguían pendientes."
                    )

                return respuesta

            completar_tarea(
                tarea_id
            )

            cantidad_cancelada = cancelar_recordatorios_de_tarea(
                tarea_id
            )

            respuesta = (
                f"Listo. Completé la tarea "
                f"#{tarea_id}: "
                f"{tarea[1]}."
            )

            if cantidad_cancelada == 1:

                respuesta += (
                    " También cancelé 1 recordatorio "
                    "vinculado a esa tarea."
                )

            elif cantidad_cancelada > 1:

                respuesta += (
                    f" También cancelé "
                    f"{cantidad_cancelada} recordatorios "
                    f"vinculados a esa tarea."
                )

            return respuesta

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

def limpiar_respuesta_modelo(
    respuesta,
    mensaje_usuario=None,
):
    texto = str(
        respuesta
    ).strip()

    if mensaje_usuario:
        mensaje = str(
            mensaje_usuario
        ).strip()

        if texto.lower().endswith(
            mensaje.lower()
        ):
            texto = texto[
                :len(texto) - len(mensaje)
            ].rstrip(
                " \n\t-–—:;"
            )

    # El modelo pequeño a veces agrega una pregunta de seguimiento
    # no solicitada. La quitamos si aparece al final.
    texto = re.sub(
        r"\s*¿Y\b[^?]*\?\s*$",
        "",
        texto,
        flags=re.IGNORECASE,
    ).strip()

    return texto


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

RESUMEN DE CONTEXTO ANTERIOR:
{obtener_texto_resumen_contexto()}

CONVERSACIÓN RECIENTE:
{obtener_texto_contexto_conversacional()}

REFERENTE MÁS RECIENTE:
{obtener_referente_conversacional_reciente()}

MENSAJE ACTUAL DE LEO:
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

Usá la CONVERSACIÓN RECIENTE para entender referencias,
pronombres y continuaciones del tema anterior.

Cuando respondas usando la conversación reciente:
- contestá solamente a la pregunta actual;
- no repitas la pregunta de Leo al final;
- no agregues preguntas que Leo no hizo;
- no copies texto de turnos anteriores salvo que sea necesario para responder;
- si recordás un dato reciente, respondelo de forma natural y breve;
- resolvé referencias naturales como "eso", "ese", "esa", "lo anterior",
  "¿y cuándo?", "¿y dónde?", "¿y con quién?" usando primero
  REFERENTE MÁS RECIENTE y después CONVERSACIÓN RECIENTE;
- si una referencia puede corresponder a más de una cosa, pedí aclaración breve;
- una referencia conversacional nunca autoriza por sí sola a crear,
  modificar o borrar tareas, eventos o recordatorios.

No inventes una tarea o evento a partir de una respuesta
corta que dependa de una conversación anterior.
Para crear o modificar datos, la intención debe seguir siendo explícita.

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

    respuesta = limpiar_respuesta_modelo(
        respuesta,
        mensaje
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
        # El modelo puede interpretar una frase descriptiva
        # como una posible tarea. En ese caso no ejecutamos
        # ninguna acción, pero conservamos su respuesta natural.
        accion = "ninguna"

    if (
        accion == "crear_evento"
        and not autoriza_creacion_evento_desde_modelo(
            mensaje
        )
    ):
        # Igual que con las tareas: una intención o comentario
        # no debe convertirse automáticamente en un evento.
        # Solo bloqueamos la acción; no reemplazamos la respuesta.
        accion = "ninguna"

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

            prioridad = (
                extraer_prioridad_tarea(
                    mensaje
                )
                or "media"
            )

            tarea_id = crear_tarea(
                titulo,
                descripcion,
                fecha,
                prioridad,
            )

            respuesta = (
                f"Listo. Agregué la tarea "
                f"#{tarea_id}: {titulo}. "
                f"Prioridad: {prioridad}."
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

            if not hora_inicio:
                respuesta = (
                    "Necesito una hora "
                    "para crear el evento."
                )

            else:
                respuesta = crear_evento_con_control_conflictos(
                    titulo=titulo,
                    fecha=fecha,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                    descripcion=descripcion,
                )

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
print("✅ Recordatorios vinculados a tareas: activos")
print("📅 Sincronización fecha de tarea ↔ recordatorios: activa")
print("⏰ Edición de horario de avisos de tareas: activa")
print("🛡️ Prioridad de edición de avisos de tareas: activa")
print("🔎 Auditoría y limpieza tarea ↔ recordatorios: activa")
print("🚩 Prioridades de tareas: activas")
print("⏳ Vencimientos y tareas atrasadas: activos")
print("🧩 Cambio combinado prioridad + fecha: activo")
print("🛡️ Prioridad de órdenes combinadas sobre contexto: activa")
print("🔥 Orden inteligente de tareas por urgencia: activo")
print("🛡️ Consultas de urgencia protegidas frente a cambios de prioridad: activas")
print("🔁 Rutinas recurrentes: creación y consulta activas")
print("⏰ Ejecución automática de rutinas: integrada al motor")
print("🎛️ Pausa, reanudación y edición de rutinas: activas")
print("🧪 Auditoría, limpieza y eliminación de rutinas: activas")
print("🔁 Eventos recurrentes: creación y consulta activas")
print("🗓️ Próximas ocurrencias recurrentes: materialización automática activa")
print("🎛️ Edición, pausa, reanudación y eliminación de eventos recurrentes: activas")
print("🧪 Auditoría y limpieza de eventos recurrentes: activas")
print("☀️ Resumen diario manual: activo")
hora_resumen_configurada = obtener_hora_resumen_diario()

if hora_resumen_configurada:
    print(
        f"🌅 Resumen diario automático: activo a las "
        f"{hora_resumen_configurada}"
    )

print("🧪 Auditoría y control antidupl. del resumen diario: activos")
print("🌙 Resumen nocturno manual: activo")
hora_resumen_nocturno_configurada = obtener_hora_resumen_nocturno()

if hora_resumen_nocturno_configurada:
    print(
        f"🌃 Resumen nocturno automático: activo a las "
        f"{hora_resumen_nocturno_configurada}"
    )

print("🧪 Auditoría y control antidupl. del resumen nocturno: activos")
print("⚠️ Detección de conflictos de agenda: activa")
print("🛑 Advertencia de conflictos al crear eventos: activa")
print("↔️ Advertencia de conflictos al mover eventos: activa")
print("🧪 Auditoría avanzada de conflictos de agenda: activa")
print("🧠 Contexto conversacional profundo: activo")
print("🔗 Referencias naturales de conversación: activas")
print("🗜️ Compresión automática del contexto: activa")
print("🧪 Auditoría y limpieza del contexto: activas")
print("📝 Sistema de notas: creación, edición, categorías y auditoría activas")
print("🔎 Búsqueda de notas por texto: activa")
print("🧠 Búsqueda en memoria permanente: activa")
print("🔎 Búsqueda combinada notas + memoria: activa")
print("🧪 Auditoría de búsqueda local: activa")
print("📄 Lectura de archivos de texto locales: activa")
print("📁 Listado de archivos y carpetas locales: activo")
print("✍️ Creación, edición y eliminación de archivos de texto: activas")
print("🛡️ Seguridad y auditoría de archivos locales: activas")
print("📆 Exportación de calendario externo (.ics): activa")
print("📥 Importación de calendarios externos (.ics): activa")
print("🔄 Sincronización segura por UID y deduplicación: activa")
print("✅ Auditoría de integración de calendario: activa")
print("🕒 Importación exacta de horarios de calendario: activa")
print("🌐 Búsqueda web controlada y explícita: activa")
print("📖 Lectura controlada de páginas web públicas: activa")
print("🧠 Resumen y preguntas sobre la última página web: activos")
print("🛡️ Auditoría de acceso web controlado: activa")
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

        if not es_comando_mantenimiento_contexto(
            mensaje
        ):
            guardar_mensaje_conversacion(
                "usuario",
                mensaje,
            )

            guardar_mensaje_conversacion(
                "asistente",
                respuesta,
            )

            compactar_contexto_conversacional()

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

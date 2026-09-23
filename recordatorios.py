import logging
import re
import unicodedata
from contextlib import closing
from pathlib import Path

from memoria import crear_tablas_automatizaciones, validar_configuracion_automatizacion

import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta


DB_PATH = "hermes.db"
INTERVALO_REVISION = 15


# ==========================================================
# BASE DE DATOS
# ==========================================================

def conectar():
    return sqlite3.connect(DB_PATH)


def crear_tabla_recordatorios():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recordatorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            mensaje TEXT,
            fecha_hora TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_disparo TIMESTAMP,
            evento_id INTEGER,
            anticipacion_minutos INTEGER,
            tarea_id INTEGER
        )
    """)

    columnas = {
        fila[1]
        for fila in cursor.execute(
            "PRAGMA table_info(recordatorios)"
        ).fetchall()
    }

    if "evento_id" not in columnas:
        cursor.execute("""
            ALTER TABLE recordatorios
            ADD COLUMN evento_id INTEGER
        """)

    if "anticipacion_minutos" not in columnas:
        cursor.execute("""
            ALTER TABLE recordatorios
            ADD COLUMN anticipacion_minutos INTEGER
        """)

    if "tarea_id" not in columnas:
        cursor.execute("""
            ALTER TABLE recordatorios
            ADD COLUMN tarea_id INTEGER
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_resumen_diario (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            activo INTEGER NOT NULL DEFAULT 1,
            hora TEXT NOT NULL DEFAULT '08:00',
            ultimo_envio TEXT,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO configuracion_resumen_diario (
            id,
            activo,
            hora,
            ultimo_envio
        )
        VALUES (1, 1, '08:00', NULL)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_resumen_nocturno (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            activo INTEGER NOT NULL DEFAULT 1,
            hora TEXT NOT NULL DEFAULT '21:00',
            ultimo_envio TEXT,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO configuracion_resumen_nocturno (
            id,
            activo,
            hora,
            ultimo_envio
        )
        VALUES (1, 1, '21:00', NULL)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rutinas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            frecuencia TEXT NOT NULL,
            dia_semana TEXT,
            hora TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'activa',
            ultimo_disparo TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    columnas_rutinas = {
        fila[1]
        for fila in cursor.execute(
            "PRAGMA table_info(rutinas)"
        ).fetchall()
    }

    if "ultimo_disparo" not in columnas_rutinas:
        cursor.execute("""
            ALTER TABLE rutinas
            ADD COLUMN ultimo_disparo TEXT
        """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eventos_recurrentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            frecuencia TEXT NOT NULL,
            dia_semana TEXT,
            hora_inicio TEXT NOT NULL,
            hora_fin TEXT,
            estado TEXT NOT NULL DEFAULT 'activo',
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha TEXT NOT NULL,
            hora_inicio TEXT,
            hora_fin TEXT,
            estado TEXT NOT NULL DEFAULT 'activo',
            recurrente_id INTEGER,
            fecha_ocurrencia TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    columnas_eventos = {
        fila[1]
        for fila in cursor.execute(
            "PRAGMA table_info(eventos)"
        ).fetchall()
    }

    if "recurrente_id" not in columnas_eventos:
        cursor.execute("""
            ALTER TABLE eventos
            ADD COLUMN recurrente_id INTEGER
        """)

    if "fecha_ocurrencia" not in columnas_eventos:
        cursor.execute("""
            ALTER TABLE eventos
            ADD COLUMN fecha_ocurrencia TEXT
        """)

    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_eventos_recurrentes_ocurrencia
        ON eventos (
            recurrente_id,
            fecha_ocurrencia
        )
        WHERE recurrente_id IS NOT NULL
          AND fecha_ocurrencia IS NOT NULL
    """)

    crear_tablas_automatizaciones(conexion)

    conexion.commit()
    conexion.close()


# ==========================================================
# CONSULTAS
# ==========================================================

def obtener_recordatorio_por_id(
    recordatorio_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            mensaje,
            fecha_hora,
            estado,
            evento_id,
            anticipacion_minutos,
            tarea_id
        FROM recordatorios
        WHERE id = ?
        LIMIT 1
    """, (
        recordatorio_id,
    ))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def obtener_recordatorios_pendientes():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            mensaje,
            fecha_hora
        FROM recordatorios
        WHERE estado = 'pendiente'
        ORDER BY fecha_hora ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_recordatorios_de_evento(
    evento_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            mensaje,
            fecha_hora,
            estado,
            evento_id,
            anticipacion_minutos,
            tarea_id
        FROM recordatorios
        WHERE evento_id = ?
          AND estado = 'pendiente'
        ORDER BY
            anticipacion_minutos DESC,
            fecha_hora ASC,
            id ASC
    """, (
        evento_id,
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_recordatorios_de_tarea(
    tarea_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            mensaje,
            fecha_hora,
            estado,
            evento_id,
            anticipacion_minutos,
            tarea_id
        FROM recordatorios
        WHERE tarea_id = ?
          AND estado = 'pendiente'
        ORDER BY fecha_hora ASC, id ASC
    """, (
        tarea_id,
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def buscar_recordatorio_pendiente(
    titulo,
    fecha_hora,
    excluir_id=None
):
    conexion = conectar()
    cursor = conexion.cursor()

    if excluir_id is None:

        cursor.execute("""
            SELECT
                id,
                titulo,
                fecha_hora
            FROM recordatorios
            WHERE estado = 'pendiente'
              AND lower(titulo) = lower(?)
              AND fecha_hora = ?
            LIMIT 1
        """, (
            titulo.strip(),
            fecha_hora
        ))

    else:

        cursor.execute("""
            SELECT
                id,
                titulo,
                fecha_hora
            FROM recordatorios
            WHERE estado = 'pendiente'
              AND lower(titulo) = lower(?)
              AND fecha_hora = ?
              AND id != ?
            LIMIT 1
        """, (
            titulo.strip(),
            fecha_hora,
            excluir_id
        ))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


# ==========================================================
# CREAR
# ==========================================================

def crear_recordatorio(
    titulo,
    fecha_hora,
    mensaje="",
    evento_id=None,
    anticipacion_minutos=None,
    tarea_id=None
):
    existente = buscar_recordatorio_pendiente(
        titulo,
        fecha_hora
    )

    if existente:
        return (
            "duplicado",
            existente[0]
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO recordatorios (
            titulo,
            mensaje,
            fecha_hora,
            estado,
            evento_id,
            anticipacion_minutos,
            tarea_id
        )
        VALUES (?, ?, ?, 'pendiente', ?, ?, ?)
    """, (
        titulo.strip(),
        mensaje.strip(),
        fecha_hora,
        evento_id,
        anticipacion_minutos,
        tarea_id
    ))

    recordatorio_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return (
        "creado",
        recordatorio_id
    )


# ==========================================================
# MODIFICAR
# ==========================================================

def modificar_recordatorio(
    recordatorio_id,
    nueva_fecha_hora,
    nuevo_titulo=None,
    nuevo_mensaje=None
):
    actual = obtener_recordatorio_por_id(
        recordatorio_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[4] != "pendiente":
        return (
            "no_pendiente",
            recordatorio_id
        )

    titulo_actual = actual[1]
    mensaje_actual = actual[2] or ""

    titulo_final = (
        nuevo_titulo.strip()
        if nuevo_titulo
        else titulo_actual
    )

    mensaje_final = (
        nuevo_mensaje.strip()
        if nuevo_mensaje is not None
        else mensaje_actual
    )

    duplicado = buscar_recordatorio_pendiente(
        titulo_final,
        nueva_fecha_hora,
        excluir_id=recordatorio_id
    )

    if duplicado:
        return (
            "duplicado",
            duplicado[0]
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recordatorios
        SET titulo = ?,
            mensaje = ?,
            fecha_hora = ?
        WHERE id = ?
          AND estado = 'pendiente'
    """, (
        titulo_final,
        mensaje_final,
        nueva_fecha_hora,
        recordatorio_id
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizado",
        recordatorio_id
    )


def actualizar_recordatorio_vinculado(
    recordatorio_id,
    nueva_fecha_hora,
    anticipacion_minutos,
    nuevo_mensaje=None
):
    actual = obtener_recordatorio_por_id(
        recordatorio_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[4] != "pendiente":
        return (
            "no_pendiente",
            recordatorio_id
        )

    mensaje_final = (
        nuevo_mensaje.strip()
        if nuevo_mensaje is not None
        else (actual[2] or "")
    )

    duplicado = buscar_recordatorio_pendiente(
        actual[1],
        nueva_fecha_hora,
        excluir_id=recordatorio_id
    )

    if duplicado:
        return (
            "duplicado",
            duplicado[0]
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recordatorios
        SET fecha_hora = ?,
            mensaje = ?,
            anticipacion_minutos = ?
        WHERE id = ?
          AND estado = 'pendiente'
    """, (
        nueva_fecha_hora,
        mensaje_final,
        anticipacion_minutos,
        recordatorio_id
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizado",
        recordatorio_id
    )


# ==========================================================
# VÍNCULO CON EVENTOS
# ==========================================================

def reprogramar_recordatorios_de_evento(
    evento_id,
    fecha_evento,
    hora_evento
):
    if not fecha_evento or not hora_evento:
        return 0

    try:
        momento_evento = datetime.fromisoformat(
            f"{fecha_evento}T{hora_evento}:00"
        )

    except ValueError:
        return 0

    recordatorios = (
        obtener_recordatorios_de_evento(
            evento_id
        )
    )

    actualizados = 0

    conexion = conectar()
    cursor = conexion.cursor()

    for recordatorio in recordatorios:

        recordatorio_id = recordatorio[0]
        anticipacion_minutos = recordatorio[6]

        if anticipacion_minutos is None:
            continue

        nuevo_momento = (
            momento_evento
            - timedelta(
                minutes=anticipacion_minutos
            )
        )

        cursor.execute("""
            UPDATE recordatorios
            SET fecha_hora = ?
            WHERE id = ?
              AND estado = 'pendiente'
        """, (
            nuevo_momento
            .replace(microsecond=0)
            .isoformat(),
            recordatorio_id
        ))

        actualizados += 1

    conexion.commit()
    conexion.close()

    return actualizados


def cancelar_recordatorios_de_evento(
    evento_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recordatorios
        SET estado = 'cancelado'
        WHERE evento_id = ?
          AND estado = 'pendiente'
    """, (
        evento_id,
    ))

    cantidad = cursor.rowcount

    conexion.commit()
    conexion.close()

    return cantidad


# ==========================================================
# VÍNCULO CON TAREAS
# ==========================================================

def reprogramar_recordatorios_de_tarea(
    tarea_id,
    fecha_anterior,
    fecha_nueva
):
    if not fecha_anterior or not fecha_nueva:
        return (
            0,
            0
        )

    try:
        fecha_origen = datetime.fromisoformat(
            fecha_anterior
        ).date()

        fecha_destino = datetime.fromisoformat(
            fecha_nueva
        ).date()

    except ValueError:
        return (
            0,
            0
        )

    diferencia = (
        fecha_destino
        - fecha_origen
    )

    recordatorios = obtener_recordatorios_de_tarea(
        tarea_id
    )

    actualizados = 0
    cancelados = 0
    ahora = datetime.now()

    conexion = conectar()
    cursor = conexion.cursor()

    for recordatorio in recordatorios:

        recordatorio_id = recordatorio[0]

        try:
            momento_actual = datetime.fromisoformat(
                recordatorio[3]
            )

        except ValueError:
            continue

        nuevo_momento = (
            momento_actual
            + diferencia
        )

        if nuevo_momento <= ahora:

            cursor.execute("""
                UPDATE recordatorios
                SET estado = 'cancelado'
                WHERE id = ?
                  AND estado = 'pendiente'
            """, (
                recordatorio_id,
            ))

            cancelados += 1

        else:

            cursor.execute("""
                UPDATE recordatorios
                SET fecha_hora = ?
                WHERE id = ?
                  AND estado = 'pendiente'
            """, (
                nuevo_momento
                .replace(microsecond=0)
                .isoformat(),
                recordatorio_id
            ))

            actualizados += 1

    conexion.commit()
    conexion.close()

    return (
        actualizados,
        cancelados
    )


def cancelar_recordatorios_de_tarea(
    tarea_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recordatorios
        SET estado = 'cancelado'
        WHERE tarea_id = ?
          AND estado = 'pendiente'
    """, (
        tarea_id,
    ))

    cantidad = cursor.rowcount

    conexion.commit()
    conexion.close()

    return cantidad


# ==========================================================
# CANCELAR
# ==========================================================

def cancelar_recordatorio(
    recordatorio_id
):
    actual = obtener_recordatorio_por_id(
        recordatorio_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[4] == "cancelado":
        return (
            "ya_cancelado",
            recordatorio_id
        )

    if actual[4] == "disparado":
        return (
            "ya_disparado",
            recordatorio_id
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recordatorios
        SET estado = 'cancelado'
        WHERE id = ?
          AND estado = 'pendiente'
    """, (
        recordatorio_id,
    ))

    conexion.commit()
    conexion.close()

    return (
        "cancelado",
        recordatorio_id
    )


# ==========================================================
# MATERIALIZACIÓN DE EVENTOS RECURRENTES
# ==========================================================

DIAS_SEMANA_EVENTOS = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "domingo": 6,
}


def obtener_eventos_recurrentes_activos():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            frecuencia,
            dia_semana,
            hora_inicio,
            hora_fin,
            estado
        FROM eventos_recurrentes
        WHERE estado = 'activo'
        ORDER BY id ASC
    """)

    resultados = cursor.fetchall()
    conexion.close()

    return resultados


def siguiente_fecha_evento_recurrente(
    frecuencia,
    dia_semana,
    hora_inicio,
    ahora
):
    hoy = ahora.date()

    try:
        hora_objetivo = datetime.strptime(
            hora_inicio,
            "%H:%M"
        ).time()

    except (TypeError, ValueError):
        return None

    if frecuencia == "diaria":
        fecha_objetivo = hoy

        if datetime.combine(
            hoy,
            hora_objetivo
        ) < ahora:
            fecha_objetivo = hoy + timedelta(days=1)

        return fecha_objetivo

    if frecuencia == "semanal":
        objetivo = DIAS_SEMANA_EVENTOS.get(
            dia_semana
        )

        if objetivo is None:
            return None

        dias_hasta = (
            objetivo
            - hoy.weekday()
        ) % 7

        fecha_objetivo = (
            hoy
            + timedelta(days=dias_hasta)
        )

        if (
            dias_hasta == 0
            and datetime.combine(
                hoy,
                hora_objetivo
            ) < ahora
        ):
            fecha_objetivo = hoy + timedelta(days=7)

        return fecha_objetivo

    return None


def materializar_proximos_eventos_recurrentes():
    ahora = datetime.now()
    recurrentes = obtener_eventos_recurrentes_activos()

    creados = 0

    conexion = conectar()
    cursor = conexion.cursor()

    for recurrente in recurrentes:
        (
            recurrente_id,
            titulo,
            frecuencia,
            dia_semana,
            hora_inicio,
            hora_fin,
            estado,
        ) = recurrente

        fecha_objetivo = siguiente_fecha_evento_recurrente(
            frecuencia,
            dia_semana,
            hora_inicio,
            ahora
        )

        if fecha_objetivo is None:
            continue

        fecha_iso = fecha_objetivo.isoformat()

        cursor.execute("""
            SELECT
                id,
                estado
            FROM eventos
            WHERE recurrente_id = ?
              AND fecha_ocurrencia = ?
            LIMIT 1
        """, (
            recurrente_id,
            fecha_iso,
        ))

        existente = cursor.fetchone()

        if existente:
            evento_id, estado_existente = existente

            if estado_existente != "activo":
                cursor.execute("""
                    UPDATE eventos
                    SET titulo = ?,
                        descripcion = '',
                        fecha = ?,
                        hora_inicio = ?,
                        hora_fin = ?,
                        estado = 'activo',
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    titulo,
                    fecha_iso,
                    hora_inicio,
                    hora_fin,
                    evento_id,
                ))

                creados += 1

            else:
                cursor.execute("""
                    UPDATE eventos
                    SET titulo = ?,
                        hora_inicio = ?,
                        hora_fin = ?,
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    titulo,
                    hora_inicio,
                    hora_fin,
                    evento_id,
                ))

            continue

        try:
            cursor.execute("""
                INSERT INTO eventos (
                    titulo,
                    descripcion,
                    fecha,
                    hora_inicio,
                    hora_fin,
                    estado,
                    recurrente_id,
                    fecha_ocurrencia
                )
                VALUES (?, '', ?, ?, ?, 'activo', ?, ?)
            """, (
                titulo,
                fecha_iso,
                hora_inicio,
                hora_fin,
                recurrente_id,
                fecha_iso,
            ))

            creados += 1

        except sqlite3.IntegrityError:
            continue

    conexion.commit()
    conexion.close()

    if creados:
        print(
            f"🗓️ Materialicé {creados} "
            f"{'ocurrencia recurrente' if creados == 1 else 'ocurrencias recurrentes'}.",
            flush=True
        )

    return creados


# ==========================================================
# RUTINAS RECURRENTES
# ==========================================================

DIAS_SEMANA_RUTINA = {
    0: "lunes",
    1: "martes",
    2: "miercoles",
    3: "jueves",
    4: "viernes",
    5: "sabado",
    6: "domingo",
}


def obtener_rutinas_activas():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            frecuencia,
            dia_semana,
            hora,
            estado,
            ultimo_disparo
        FROM rutinas
        WHERE estado = 'activa'
        ORDER BY id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def marcar_rutina_disparada(
    rutina_id,
    clave_disparo
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE rutinas
        SET ultimo_disparo = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado = 'activa'
    """, (
        clave_disparo,
        rutina_id,
    ))

    conexion.commit()
    conexion.close()


def rutina_debe_dispararse(
    rutina,
    ahora
):
    (
        rutina_id,
        titulo,
        frecuencia,
        dia_semana,
        hora,
        estado,
        ultimo_disparo,
    ) = rutina

    try:
        hora_objetivo = datetime.strptime(
            hora,
            "%H:%M"
        ).time()

    except (TypeError, ValueError):
        return (
            False,
            None
        )

    momento_objetivo = ahora.replace(
        hour=hora_objetivo.hour,
        minute=hora_objetivo.minute,
        second=0,
        microsecond=0,
    )

    # El motor revisa cada 15 segundos. Permitimos una pequeña ventana
    # de gracia para reinicios o demoras, pero evitamos disparar una
    # rutina varias horas tarde al iniciar Hermes.
    segundos_de_atraso = (
        ahora
        - momento_objetivo
    ).total_seconds()

    if segundos_de_atraso < 0:
        return (
            False,
            None
        )

    if segundos_de_atraso > 300:
        return (
            False,
            None
        )

    if frecuencia == "diaria":

        clave_disparo = (
            f"diaria:{ahora.date().isoformat()}"
        )

    elif frecuencia == "semanal":

        dia_actual = DIAS_SEMANA_RUTINA.get(
            ahora.weekday()
        )

        if dia_actual != dia_semana:
            return (
                False,
                None
            )

        clave_disparo = (
            f"semanal:{ahora.date().isoformat()}"
        )

    else:
        return (
            False,
            None
        )

    if ultimo_disparo == clave_disparo:
        return (
            False,
            None
        )

    return (
        True,
        clave_disparo
    )


def revisar_rutinas():
    ahora = datetime.now()

    for rutina in obtener_rutinas_activas():

        debe_dispararse, clave_disparo = rutina_debe_dispararse(
            rutina,
            ahora
        )

        if not debe_dispararse:
            continue

        rutina_id = rutina[0]
        titulo = rutina[1]

        enviar_notificacion(
            titulo,
            titulo
        )

        marcar_rutina_disparada(
            rutina_id,
            clave_disparo
        )

        print(
            f"🔁 Rutina #{rutina_id}: "
            f"{titulo}",
            flush=True
        )


# ==========================================================
# DISPARO
# ==========================================================

def marcar_como_disparado(
    recordatorio_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE recordatorios
        SET estado = 'disparado',
            fecha_disparo = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        recordatorio_id,
    ))

    conexion.commit()
    conexion.close()


# ==========================================================
# NOTIFICACIONES macOS
# ==========================================================

def escapar_applescript(texto):
    return (
        texto
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )


def enviar_notificacion(
    titulo,
    mensaje
):
    titulo = escapar_applescript(
        titulo
    )

    mensaje = escapar_applescript(
        mensaje
    )

    script = (
        f'display notification "{mensaje}" '
        f'with title "Hermes" '
        f'subtitle "{titulo}" '
        f'sound name "Glass"'
    )

    subprocess.run(
        [
            "osascript",
            "-e",
            script
        ],
        check=False
    )



# ==========================================================
# RESUMEN DIARIO AUTOMÁTICO
# ==========================================================

def obtener_configuracion_resumen_diario():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            activo,
            hora,
            ultimo_envio
        FROM configuracion_resumen_diario
        WHERE id = 1
        LIMIT 1
    """)

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def configurar_hora_resumen_diario(
    nueva_hora
):
    try:
        hora_validada = datetime.strptime(
            nueva_hora,
            "%H:%M"
        ).strftime(
            "%H:%M"
        )

    except (TypeError, ValueError):
        return (
            "hora_invalida",
            None
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE configuracion_resumen_diario
        SET hora = ?,
            activo = 1,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (
        hora_validada,
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizada",
        hora_validada
    )


def obtener_hora_resumen_diario():
    configuracion = obtener_configuracion_resumen_diario()

    if not configuracion:
        return None

    return configuracion[1]


def auditar_configuracion_resumen_diario():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            activo,
            hora,
            ultimo_envio
        FROM configuracion_resumen_diario
        WHERE id = 1
        LIMIT 1
    """)

    fila = cursor.fetchone()

    if not fila:
        cursor.execute("""
            INSERT INTO configuracion_resumen_diario (
                id,
                activo,
                hora,
                ultimo_envio
            )
            VALUES (1, 1, '08:00', NULL)
        """)

        conexion.commit()
        conexion.close()

        return {
            "estado": "corregido",
            "correcciones": [
                "La configuración no existía y fue recreada con 08:00."
            ],
        }

    activo, hora, ultimo_envio = fila
    correcciones = []

    if activo not in (0, 1):
        cursor.execute("""
            UPDATE configuracion_resumen_diario
            SET activo = 0,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = 1
        """)

        activo = 0
        correcciones.append(
            "El estado era inválido y el resumen fue desactivado por seguridad."
        )

    hora_valida = True

    try:
        datetime.strptime(
            hora,
            "%H:%M"
        )

    except (TypeError, ValueError):
        hora_valida = False

    if not hora_valida:
        cursor.execute("""
            UPDATE configuracion_resumen_diario
            SET hora = '08:00',
                activo = 0,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = 1
        """)

        hora = "08:00"
        activo = 0
        correcciones.append(
            "La hora era inválida; la restablecí a 08:00 y desactivé el envío automático."
        )

    if ultimo_envio:
        ultimo_valido = True

        try:
            fecha_ultimo = datetime.strptime(
                ultimo_envio,
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            ultimo_valido = False
            fecha_ultimo = None

        if (
            not ultimo_valido
            or (
                fecha_ultimo is not None
                and fecha_ultimo > datetime.now().date()
            )
        ):
            cursor.execute("""
                UPDATE configuracion_resumen_diario
                SET ultimo_envio = NULL,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = 1
            """)

            ultimo_envio = None
            correcciones.append(
                "El último envío registrado era inválido y fue limpiado."
            )

    conexion.commit()
    conexion.close()

    return {
        "estado": (
            "corregido"
            if correcciones
            else "correcto"
        ),
        "activo": activo,
        "hora": hora,
        "ultimo_envio": ultimo_envio,
        "correcciones": correcciones,
    }


def reclamar_envio_resumen_diario(
    ahora
):
    hoy_iso = ahora.date().isoformat()

    conexion = conectar(
    )

    try:
        conexion.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                activo,
                hora,
                ultimo_envio
            FROM configuracion_resumen_diario
            WHERE id = 1
            LIMIT 1
        """)

        configuracion = cursor.fetchone()

        if not configuracion:
            conexion.rollback()
            return False

        activo, hora, ultimo_envio = configuracion

        if not activo:
            conexion.rollback()
            return False

        if not resumen_diario_debe_enviarse(
            ahora,
            hora,
            ultimo_envio
        ):
            conexion.rollback()
            return False

        cursor.execute("""
            UPDATE configuracion_resumen_diario
            SET ultimo_envio = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = 1
              AND (
                    ultimo_envio IS NULL
                    OR ultimo_envio != ?
              )
        """, (
            hoy_iso,
            hoy_iso,
        ))

        reclamado = (
            cursor.rowcount == 1
        )

        if reclamado:
            conexion.commit()
        else:
            conexion.rollback()

        return reclamado

    finally:
        conexion.close()


def marcar_resumen_diario_enviado(
    fecha_iso
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE configuracion_resumen_diario
        SET ultimo_envio = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (
        fecha_iso,
    ))

    conexion.commit()
    conexion.close()


def obtener_datos_resumen_diario():
    ahora = datetime.now()
    hoy = ahora.date()
    hoy_iso = hoy.isoformat()

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha,
            prioridad
        FROM tareas
        WHERE estado = 'pendiente'
        ORDER BY
            CASE
                WHEN fecha IS NULL THEN 1
                ELSE 0
            END,
            fecha ASC,
            CASE prioridad
                WHEN 'alta' THEN 0
                WHEN 'media' THEN 1
                WHEN 'baja' THEN 2
                ELSE 1
            END,
            id ASC
    """)

    tareas = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha,
            hora_inicio,
            hora_fin
        FROM eventos
        WHERE estado = 'activo'
          AND fecha = ?
        ORDER BY
            CASE
                WHEN hora_inicio IS NULL THEN 1
                ELSE 0
            END,
            hora_inicio ASC,
            id ASC
    """, (
        hoy_iso,
    ))

    eventos_hoy = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha_hora
        FROM recordatorios
        WHERE estado = 'pendiente'
        ORDER BY fecha_hora ASC, id ASC
    """)

    recordatorios = cursor.fetchall()

    conexion.close()

    tareas_hoy = []
    tareas_atrasadas = []

    for tarea in tareas:
        fecha = tarea[2]

        if not fecha:
            continue

        try:
            fecha_obj = datetime.strptime(
                fecha,
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            continue

        if fecha_obj == hoy:
            tareas_hoy.append(
                tarea
            )

        elif fecha_obj < hoy:
            tareas_atrasadas.append(
                tarea
            )

    recordatorios_relevantes = []

    for recordatorio in recordatorios:

        try:
            momento = datetime.fromisoformat(
                recordatorio[2]
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

    return {
        "ahora": ahora,
        "hoy": hoy,
        "tareas": tareas,
        "tareas_hoy": tareas_hoy,
        "tareas_atrasadas": tareas_atrasadas,
        "eventos_hoy": eventos_hoy,
        "recordatorios": recordatorios_relevantes,
    }


def prioridad_numerica_resumen(
    prioridad
):
    return {
        "alta": 0,
        "media": 1,
        "baja": 2,
    }.get(
        prioridad or "media",
        1
    )


def clave_urgencia_resumen(
    tarea,
    hoy
):
    fecha = tarea[2]

    if fecha:
        try:
            fecha_obj = datetime.strptime(
                fecha,
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            fecha_obj = None

        if fecha_obj is not None:

            if fecha_obj < hoy:
                grupo = 0

            elif fecha_obj == hoy:
                grupo = 1

            else:
                grupo = 2

            return (
                grupo,
                fecha_obj,
                prioridad_numerica_resumen(
                    tarea[3]
                ),
                tarea[0],
            )

    return (
        3,
        datetime.max.date(),
        prioridad_numerica_resumen(
            tarea[3]
        ),
        tarea[0],
    )


def generar_resumen_diario_motor():
    datos = obtener_datos_resumen_diario()

    hoy = datos["hoy"]
    tareas = datos["tareas"]
    tareas_hoy = datos["tareas_hoy"]
    tareas_atrasadas = datos[
        "tareas_atrasadas"
    ]
    eventos_hoy = datos[
        "eventos_hoy"
    ]
    recordatorios = datos[
        "recordatorios"
    ]

    prioridades = sorted(
        tareas,
        key=lambda tarea: clave_urgencia_resumen(
            tarea,
            hoy
        )
    )[:3]

    lineas = [
        (
            f"Resumen de hoy — "
            f"{hoy.strftime('%d/%m/%Y')}"
        ),
        (
            f"{len(tareas_hoy)} tareas para hoy, "
            f"{len(tareas_atrasadas)} atrasadas, "
            f"{len(eventos_hoy)} eventos hoy."
        ),
    ]

    if prioridades:
        lineas.append(
            "Prioridades:"
        )

        for indice, tarea in enumerate(
            prioridades,
            start=1
        ):
            prioridad = (
                tarea[3]
                if tarea[3]
                else "media"
            )

            texto = (
                f"{indice}. {tarea[1]} "
                f"({prioridad})"
            )

            if tarea[2]:
                try:
                    fecha_obj = datetime.strptime(
                        tarea[2],
                        "%Y-%m-%d"
                    ).date()

                    if fecha_obj < hoy:
                        dias = (
                            hoy
                            - fecha_obj
                        ).days

                        texto += (
                            f" — atrasada "
                            f"{dias} "
                            f"{'día' if dias == 1 else 'días'}"
                        )

                    elif fecha_obj == hoy:
                        texto += (
                            " — vence hoy"
                        )

                except (TypeError, ValueError):
                    pass

            lineas.append(
                texto
            )

    if eventos_hoy:
        lineas.append(
            "Agenda:"
        )

        for evento in eventos_hoy:

            texto = (
                f"- {evento[1]}"
            )

            if evento[3]:
                texto += (
                    f" {evento[3]}"
                )

            if evento[4]:
                texto += (
                    f"-{evento[4]}"
                )

            lineas.append(
                texto
            )

    if recordatorios:
        lineas.append(
            "Recordatorios pendientes:"
        )

        for recordatorio, momento in recordatorios:

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
                f"- {recordatorio[1]} — {cuando}"
            )

    return "\n".join(
        lineas
    )


def generar_texto_notificacion_resumen():
    datos = obtener_datos_resumen_diario()

    hoy = datos["hoy"]
    tareas = datos["tareas"]
    tareas_hoy = datos["tareas_hoy"]
    atrasadas = datos["tareas_atrasadas"]
    eventos = datos["eventos_hoy"]

    prioridades = sorted(
        tareas,
        key=lambda tarea: clave_urgencia_resumen(
            tarea,
            hoy
        )
    )[:1]

    partes = [
        f"{len(tareas_hoy)} tareas hoy",
        f"{len(atrasadas)} atrasadas",
        f"{len(eventos)} eventos",
    ]

    if prioridades:
        partes.append(
            f"Prioridad: {prioridades[0][1]}"
        )

    return " • ".join(
        partes
    )


def resumen_diario_debe_enviarse(
    ahora,
    hora_configurada,
    ultimo_envio
):
    if ultimo_envio == ahora.date().isoformat():
        return False

    try:
        hora_objetivo = datetime.strptime(
            hora_configurada,
            "%H:%M"
        ).time()

    except (TypeError, ValueError):
        return False

    objetivo = datetime.combine(
        ahora.date(),
        hora_objetivo
    )

    # En 19.2 usamos una ventana de mañana:
    # desde la hora configurada hasta 4 horas después.
    limite = objetivo + timedelta(
        hours=4
    )

    return (
        objetivo <= ahora < limite
    )


def revisar_resumen_diario():
    ahora = datetime.now()

    if not reclamar_envio_resumen_diario(
        ahora
    ):
        return False

    resumen = generar_resumen_diario_motor()
    texto_notificacion = (
        generar_texto_notificacion_resumen()
    )

    enviar_notificacion(
        "Resumen diario",
        texto_notificacion
    )

    print()
    print(
        "☀️ RESUMEN DIARIO AUTOMÁTICO"
    )
    print(
        resumen,
        flush=True
    )
    print()

    return True

def probar_resumen_diario():
    resumen = generar_resumen_diario_motor()

    enviar_notificacion(
        "Prueba de resumen diario",
        generar_texto_notificacion_resumen()
    )

    print()
    print(
        "☀️ PRUEBA DE RESUMEN DIARIO"
    )
    print(
        resumen
    )
    print()
    print(
        "La prueba no marca el resumen de hoy como enviado."
    )
    print()



# ==========================================================
# RESUMEN NOCTURNO AUTOMÁTICO
# ==========================================================

def obtener_configuracion_resumen_nocturno():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            activo,
            hora,
            ultimo_envio
        FROM configuracion_resumen_nocturno
        WHERE id = 1
        LIMIT 1
    """)

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def configurar_hora_resumen_nocturno(
    nueva_hora
):
    try:
        hora_validada = datetime.strptime(
            nueva_hora,
            "%H:%M"
        ).strftime(
            "%H:%M"
        )

    except (TypeError, ValueError):
        return (
            "hora_invalida",
            None
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE configuracion_resumen_nocturno
        SET hora = ?,
            activo = 1,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (
        hora_validada,
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizada",
        hora_validada
    )


def obtener_hora_resumen_nocturno():
    configuracion = obtener_configuracion_resumen_nocturno()

    if not configuracion:
        return None

    return configuracion[1]


def auditar_configuracion_resumen_nocturno():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            activo,
            hora,
            ultimo_envio
        FROM configuracion_resumen_nocturno
        WHERE id = 1
        LIMIT 1
    """)

    fila = cursor.fetchone()

    if not fila:
        cursor.execute("""
            INSERT INTO configuracion_resumen_nocturno (
                id,
                activo,
                hora,
                ultimo_envio
            )
            VALUES (1, 1, '21:00', NULL)
        """)

        conexion.commit()
        conexion.close()

        return {
            "estado": "corregido",
            "correcciones": [
                "La configuración nocturna no existía y fue recreada con 21:00."
            ],
        }

    activo, hora, ultimo_envio = fila
    correcciones = []

    if activo not in (0, 1):
        cursor.execute("""
            UPDATE configuracion_resumen_nocturno
            SET activo = 0,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = 1
        """)

        activo = 0
        correcciones.append(
            "El estado era inválido y el resumen nocturno fue desactivado por seguridad."
        )

    hora_valida = True

    try:
        datetime.strptime(
            hora,
            "%H:%M"
        )

    except (TypeError, ValueError):
        hora_valida = False

    if not hora_valida:
        cursor.execute("""
            UPDATE configuracion_resumen_nocturno
            SET hora = '21:00',
                activo = 0,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = 1
        """)

        hora = "21:00"
        activo = 0
        correcciones.append(
            "La hora nocturna era inválida; la restablecí a 21:00 y desactivé el envío automático."
        )

    if ultimo_envio:
        ultimo_valido = True

        try:
            fecha_ultimo = datetime.strptime(
                ultimo_envio,
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            ultimo_valido = False
            fecha_ultimo = None

        if (
            not ultimo_valido
            or (
                fecha_ultimo is not None
                and fecha_ultimo > datetime.now().date()
            )
        ):
            cursor.execute("""
                UPDATE configuracion_resumen_nocturno
                SET ultimo_envio = NULL,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = 1
            """)

            ultimo_envio = None
            correcciones.append(
                "El último envío nocturno registrado era inválido y fue limpiado."
            )

    conexion.commit()
    conexion.close()

    return {
        "estado": (
            "corregido"
            if correcciones
            else "correcto"
        ),
        "activo": activo,
        "hora": hora,
        "ultimo_envio": ultimo_envio,
        "correcciones": correcciones,
    }


def reclamar_envio_resumen_nocturno(
    ahora
):
    hoy_iso = ahora.date().isoformat()

    conexion = conectar()

    try:
        conexion.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = conexion.cursor()

        cursor.execute("""
            SELECT
                activo,
                hora,
                ultimo_envio
            FROM configuracion_resumen_nocturno
            WHERE id = 1
            LIMIT 1
        """)

        configuracion = cursor.fetchone()

        if not configuracion:
            conexion.rollback()
            return False

        activo, hora, ultimo_envio = configuracion

        if not activo:
            conexion.rollback()
            return False

        if not resumen_nocturno_debe_enviarse(
            ahora,
            hora,
            ultimo_envio
        ):
            conexion.rollback()
            return False

        cursor.execute("""
            UPDATE configuracion_resumen_nocturno
            SET ultimo_envio = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = 1
              AND (
                    ultimo_envio IS NULL
                    OR ultimo_envio != ?
              )
        """, (
            hoy_iso,
            hoy_iso,
        ))

        reclamado = (
            cursor.rowcount == 1
        )

        if reclamado:
            conexion.commit()
        else:
            conexion.rollback()

        return reclamado

    finally:
        conexion.close()


def marcar_resumen_nocturno_enviado(
    fecha_iso
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE configuracion_resumen_nocturno
        SET ultimo_envio = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (
        fecha_iso,
    ))

    conexion.commit()
    conexion.close()


def obtener_datos_resumen_nocturno():
    ahora = datetime.now()
    hoy = ahora.date()
    manana = hoy + timedelta(days=1)

    hoy_iso = hoy.isoformat()
    manana_iso = manana.isoformat()

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha,
            prioridad
        FROM tareas
        WHERE estado = 'pendiente'
        ORDER BY
            CASE
                WHEN fecha IS NULL THEN 1
                ELSE 0
            END,
            fecha ASC,
            CASE prioridad
                WHEN 'alta' THEN 0
                WHEN 'media' THEN 1
                WHEN 'baja' THEN 2
                ELSE 1
            END,
            id ASC
    """)

    tareas_pendientes = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha,
            prioridad
        FROM tareas
        WHERE estado = 'completada'
          AND date(fecha_actualizacion) = ?
        ORDER BY
            CASE prioridad
                WHEN 'alta' THEN 0
                WHEN 'media' THEN 1
                WHEN 'baja' THEN 2
                ELSE 1
            END,
            id ASC
    """, (
        hoy_iso,
    ))

    tareas_completadas = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha,
            hora_inicio,
            hora_fin
        FROM eventos
        WHERE estado = 'activo'
          AND fecha = ?
        ORDER BY
            CASE
                WHEN hora_inicio IS NULL THEN 1
                ELSE 0
            END,
            hora_inicio ASC,
            id ASC
    """, (
        hoy_iso,
    ))

    eventos_hoy = cursor.fetchall()

    cursor.execute("""
        SELECT
            id,
            titulo,
            fecha,
            hora_inicio,
            hora_fin
        FROM eventos
        WHERE estado = 'activo'
          AND fecha = ?
        ORDER BY
            CASE
                WHEN hora_inicio IS NULL THEN 1
                ELSE 0
            END,
            hora_inicio ASC,
            id ASC
    """, (
        manana_iso,
    ))

    eventos_manana = cursor.fetchall()

    conexion.close()

    tareas_atrasadas = []
    tareas_manana = []

    for tarea in tareas_pendientes:
        fecha = tarea[2]

        if not fecha:
            continue

        try:
            fecha_obj = datetime.strptime(
                fecha,
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            continue

        if fecha_obj < hoy:
            tareas_atrasadas.append(
                tarea
            )

        elif fecha_obj == manana:
            tareas_manana.append(
                tarea
            )

    return {
        "ahora": ahora,
        "hoy": hoy,
        "manana": manana,
        "tareas_pendientes": tareas_pendientes,
        "tareas_completadas": tareas_completadas,
        "tareas_atrasadas": tareas_atrasadas,
        "tareas_manana": tareas_manana,
        "eventos_hoy": eventos_hoy,
        "eventos_manana": eventos_manana,
    }


def clave_urgencia_nocturna(
    tarea,
    hoy
):
    fecha = tarea[2]

    if fecha:
        try:
            fecha_obj = datetime.strptime(
                fecha,
                "%Y-%m-%d"
            ).date()

        except (TypeError, ValueError):
            fecha_obj = None

        if fecha_obj is not None:

            if fecha_obj < hoy:
                grupo = 0

            elif fecha_obj == hoy:
                grupo = 1

            else:
                grupo = 2

            prioridad = {
                "alta": 0,
                "media": 1,
                "baja": 2,
            }.get(
                tarea[3] or "media",
                1
            )

            return (
                grupo,
                fecha_obj,
                prioridad,
                tarea[0],
            )

    prioridad = {
        "alta": 0,
        "media": 1,
        "baja": 2,
    }.get(
        tarea[3] or "media",
        1
    )

    return (
        3,
        datetime.max.date(),
        prioridad,
        tarea[0],
    )


def generar_resumen_nocturno_motor():
    datos = obtener_datos_resumen_nocturno()

    hoy = datos["hoy"]
    completadas = datos[
        "tareas_completadas"
    ]
    atrasadas = datos[
        "tareas_atrasadas"
    ]
    tareas_manana = datos[
        "tareas_manana"
    ]
    eventos_hoy = datos[
        "eventos_hoy"
    ]
    eventos_manana = datos[
        "eventos_manana"
    ]
    pendientes = datos[
        "tareas_pendientes"
    ]

    lineas = [
        (
            f"Resumen nocturno — "
            f"{hoy.strftime('%d/%m/%Y')}"
        ),
        (
            f"{len(completadas)} tareas completadas hoy, "
            f"{len(atrasadas)} atrasadas."
        ),
    ]

    if completadas:
        lineas.append(
            "Completado hoy:"
        )

        for tarea in completadas:
            lineas.append(
                f"- {tarea[1]}"
            )

    if atrasadas:
        lineas.append(
            "Pendientes atrasados:"
        )

        for tarea in sorted(
            atrasadas,
            key=lambda elemento: clave_urgencia_nocturna(
                elemento,
                hoy
            )
        ):
            prioridad = (
                tarea[3]
                if tarea[3]
                else "media"
            )

            lineas.append(
                f"- {tarea[1]} ({prioridad})"
            )

    if eventos_hoy:
        lineas.append(
            "Eventos de hoy:"
        )

        for evento in eventos_hoy:
            texto = (
                f"- {evento[1]}"
            )

            if evento[3]:
                texto += (
                    f" {evento[3]}"
                )

            if evento[4]:
                texto += (
                    f"-{evento[4]}"
                )

            lineas.append(
                texto
            )

    lineas.append(
        "Mañana:"
    )

    if tareas_manana:

        for tarea in sorted(
            tareas_manana,
            key=lambda elemento: clave_urgencia_nocturna(
                elemento,
                hoy
            )
        ):
            prioridad = (
                tarea[3]
                if tarea[3]
                else "media"
            )

            lineas.append(
                f"- Tarea: {tarea[1]} ({prioridad})"
            )

    else:
        lineas.append(
            "- Sin tareas con vencimiento mañana."
        )

    if eventos_manana:

        for evento in eventos_manana:
            texto = (
                f"- Evento: {evento[1]}"
            )

            if evento[3]:
                texto += (
                    f" {evento[3]}"
                )

            if evento[4]:
                texto += (
                    f"-{evento[4]}"
                )

            lineas.append(
                texto
            )

    else:
        lineas.append(
            "- Sin eventos mañana."
        )

    if pendientes:
        foco = sorted(
            pendientes,
            key=lambda elemento: clave_urgencia_nocturna(
                elemento,
                hoy
            )
        )[0]

        lineas.append(
            f"Foco para mañana: {foco[1]}."
        )

    return "\n".join(
        lineas
    )


def generar_texto_notificacion_nocturna():
    datos = obtener_datos_resumen_nocturno()

    hoy = datos["hoy"]
    completadas = datos["tareas_completadas"]
    atrasadas = datos["tareas_atrasadas"]
    manana_tareas = datos["tareas_manana"]
    manana_eventos = datos["eventos_manana"]
    pendientes = datos["tareas_pendientes"]

    partes = [
        f"{len(completadas)} completadas",
        f"{len(atrasadas)} atrasadas",
        (
            f"mañana: {len(manana_tareas)} tareas, "
            f"{len(manana_eventos)} eventos"
        ),
    ]

    if pendientes:
        foco = sorted(
            pendientes,
            key=lambda elemento: clave_urgencia_nocturna(
                elemento,
                hoy
            )
        )[0]

        partes.append(
            f"Foco: {foco[1]}"
        )

    return " • ".join(
        partes
    )


def resumen_nocturno_debe_enviarse(
    ahora,
    hora_configurada,
    ultimo_envio
):
    if ultimo_envio == ahora.date().isoformat():
        return False

    try:
        hora_objetivo = datetime.strptime(
            hora_configurada,
            "%H:%M"
        ).time()

    except (TypeError, ValueError):
        return False

    objetivo = datetime.combine(
        ahora.date(),
        hora_objetivo
    )

    fin_del_dia = datetime.combine(
        ahora.date(),
        datetime.max.time()
    )

    return (
        objetivo <= ahora <= fin_del_dia
    )


def revisar_resumen_nocturno():
    ahora = datetime.now()

    if not reclamar_envio_resumen_nocturno(
        ahora
    ):
        return False

    resumen = generar_resumen_nocturno_motor()
    texto_notificacion = (
        generar_texto_notificacion_nocturna()
    )

    enviar_notificacion(
        "Resumen nocturno",
        texto_notificacion
    )

    print()
    print(
        "🌙 RESUMEN NOCTURNO AUTOMÁTICO"
    )
    print(
        resumen,
        flush=True
    )
    print()

    return True

def probar_resumen_nocturno():
    resumen = generar_resumen_nocturno_motor()

    enviar_notificacion(
        "Prueba de resumen nocturno",
        generar_texto_notificacion_nocturna()
    )

    print()
    print(
        "🌙 PRUEBA DE RESUMEN NOCTURNO"
    )
    print(
        resumen
    )
    print()
    print(
        "La prueba no marca el resumen nocturno "
        "de hoy como enviado."
    )
    print()


# ==========================================================
# MOTOR
# ==========================================================

def revisar_recordatorios():
    ahora = datetime.now()

    recordatorios = (
        obtener_recordatorios_pendientes()
    )

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

        except ValueError:
            continue

        if momento <= ahora:

            texto = (
                mensaje
                if mensaje
                else titulo
            )

            enviar_notificacion(
                titulo,
                texto
            )

            marcar_como_disparado(
                recordatorio_id
            )

            print(
                f"🔔 Recordatorio "
                f"#{recordatorio_id}: "
                f"{titulo}",
                flush=True
            )


# ==========================================================
# AUTOMATIZACIONES: SOLO CONSULTAS LOCALES (28.2)
# ==========================================================

LOGGER_AUTOMATIZACIONES = logging.getLogger('hermes.automatizaciones')


def clasificar_instruccion_automatizacion(instruccion):
    """Valida sin ejecutar: fuente única de la lista segura para motor y auditoría."""
    if not isinstance(instruccion, str):
        raise ValueError("Instrucción no permitida: debe ser texto.")
    texto = ''.join(c for c in unicodedata.normalize('NFD', instruccion.lower())
                    if unicodedata.category(c) != 'Mn')
    texto = ' '.join(texto.strip().rstrip('.!?').split())
    match = re.fullmatch(
        r'(?:mostrar|mostra|mostrame|muestrame|consultar|consulta|ver) '
        r'(?:(?:el|las|los|mis) )?'
        r'(resumen diario|tareas pendientes|eventos de hoy|eventos|notas)', texto
    )
    if not match:
        raise ValueError('Instrucción no permitida en 28.2; solo consultas locales explícitas.')
    return match.group(1)


def resolver_instruccion_automatizacion(instruccion):
    capacidad = clasificar_instruccion_automatizacion(instruccion)
    if capacidad == 'resumen diario':
        return generar_resumen_diario_motor()
    consultas = {
        'tareas pendientes': "SELECT id, titulo, fecha, prioridad FROM tareas WHERE estado = 'pendiente' ORDER BY id",
        'eventos': "SELECT id, titulo, fecha, hora_inicio, hora_fin FROM eventos WHERE estado = 'activo' ORDER BY fecha, hora_inicio, id",
        'notas': "SELECT id, titulo, contenido FROM notas WHERE estado = 'activa' ORDER BY id",
    }
    with closing(conectar()) as conexion:
        if capacidad == 'eventos de hoy':
            filas = conexion.execute(
                consultas['eventos'].replace('ORDER BY', 'AND fecha = ? ORDER BY'),
                (datetime.now().date().isoformat(),)
            ).fetchall()
        else:
            filas = conexion.execute(consultas[capacidad]).fetchall()
    return capacidad.capitalize() + ':\n' + (
        '\n'.join(' | '.join(str(valor) if valor is not None else '-' for valor in fila)
                  for fila in filas) if filas else 'Sin resultados.'
    )


def ventana_automatizacion(fila, ahora):
    if fila['estado'] != 'activa' or fila['fecha_eliminacion'] is not None:
        return None
    hora = fila['hora']
    if not isinstance(hora, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', hora):
        raise ValueError('Horario inválido')
    if type(fila['version_programacion']) is not int or fila['version_programacion'] < 0:
        raise ValueError('Versión de programación inválida')
    frecuencia = fila['frecuencia']
    if frecuencia not in ('diaria', 'semanal'):
        raise ValueError('Frecuencia inválida')
    if frecuencia == 'semanal' and fila['dia_semana'] not in DIAS_SEMANA_RUTINA.values():
        raise ValueError('Día de semana inválido')
    if frecuencia == 'diaria' and fila['dia_semana'] is not None:
        raise ValueError('Una automatización diaria no lleva día de semana')
    # Revisar también ayer para cubrir la gracia de horarios cercanos a medianoche.
    for fecha in (ahora, ahora - timedelta(days=1)):
        objetivo = fecha.replace(hour=int(hora[:2]), minute=int(hora[3:]), second=0, microsecond=0)
        if not 0 <= (ahora - objetivo).total_seconds() <= 300:
            continue
        if frecuencia == 'semanal' and fila['dia_semana'] != DIAS_SEMANA_RUTINA[objetivo.weekday()]:
            continue
        clave = f"{frecuencia}:{objetivo.date().isoformat()}"
        if fila['version_programacion']:
            clave += f":v{fila['version_programacion']}"
        return clave if fila['ultimo_disparo'] != clave else None
    return None


def reclamar_automatizacion(identificador, ahora):
    # La selección, comprobación del estado y reserva ocurren bajo el mismo
    # bloqueo. La PK persiste incluso tras errores, reinicios o dos motores.
    with closing(conectar()) as conexion, conexion:
        conexion.row_factory = sqlite3.Row
        conexion.execute('BEGIN IMMEDIATE')
        if not proteccion_duplicados_automatizaciones(conexion):
            raise ValueError('Protección contra doble disparo ausente; ejecución bloqueada.')
        fila = conexion.execute('SELECT * FROM automatizaciones WHERE id = ?', (identificador,)).fetchone()
        if fila is None:
            return None
        ventana = ventana_automatizacion(fila, ahora)
        if ventana is None:
            return None
        cursor = conexion.execute("""
            INSERT OR IGNORE INTO ejecuciones_automatizaciones
                (automatizacion_id, ventana, estado, inicio)
            VALUES (?, ?, 'en_curso', ?)
        """, (identificador, ventana, ahora.isoformat(timespec='seconds')))
        return (dict(fila), ventana) if cursor.rowcount == 1 else None


def finalizar_automatizacion(identificador, ventana, resultado=None, error=None, conexion=None):
    if error is None and not isinstance(resultado, str):
        raise ValueError('Una ejecución correcta requiere resultado de texto.')
    if error is not None and (not isinstance(error, str) or not error.strip() or resultado is not None):
        raise ValueError('Una ejecución fallida requiere error no vacío y ningún resultado.')
    if conexion is None:
        with closing(conectar()) as propia, propia:
            return finalizar_automatizacion(identificador, ventana, resultado, error, propia)
    cursor = conexion.execute("""
        UPDATE ejecuciones_automatizaciones
        SET estado = ?, fin = ?, resultado = ?, error = ?
        WHERE automatizacion_id = ? AND ventana = ? AND estado = 'en_curso'
    """, ('error' if error is not None else 'correcta',
          datetime.now().isoformat(timespec='seconds'), resultado, error, identificador, ventana))
    if error is None and cursor.rowcount:
        conexion.execute("""
            UPDATE automatizaciones SET ultimo_disparo = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?
                AND estado = 'activa' AND fecha_eliminacion IS NULL
                AND ((version_programacion = 0 AND ? NOT LIKE '%:v%')
                     OR ? LIKE '%:v' || version_programacion)
        """, (ventana, identificador, ventana, ventana))


def ejecutar_reserva_automatizacion(fila, ventana):
    # Serializa la consulta local y su finalización con pausa/edición/borrado.
    # Si la gestión gana el bloqueo, la reserva obsoleta no se ejecuta.
    with closing(conectar()) as conexion, conexion:
        conexion.row_factory = sqlite3.Row
        conexion.execute('BEGIN IMMEDIATE')
        if not proteccion_duplicados_automatizaciones(conexion):
            raise ValueError('Protección contra doble disparo ausente; ejecución bloqueada.')
        actual = conexion.execute('SELECT * FROM automatizaciones WHERE id=?', (fila['id'],)).fetchone()
        campos = ('nombre', 'instruccion', 'frecuencia', 'dia_semana', 'hora', 'version_programacion')
        if (actual is None or actual['estado'] != 'activa' or actual['fecha_eliminacion'] is not None
                or any(actual[campo] != fila[campo] for campo in campos)):
            finalizar_automatizacion(fila['id'], ventana, error='Reserva cancelada por cambio de configuración o estado.', conexion=conexion)
            return None
        ejecucion = conexion.execute("""SELECT estado FROM ejecuciones_automatizaciones
            WHERE automatizacion_id=? AND ventana=?""", (fila['id'], ventana)).fetchone()
        if ejecucion is None or ejecucion['estado'] != 'en_curso':
            return None
        resultado = resolver_instruccion_automatizacion(actual['instruccion'])
        finalizar_automatizacion(fila['id'], ventana, resultado=resultado, conexion=conexion)
        return resultado


def revisar_automatizaciones(ahora=None):
    ahora = ahora or datetime.now()
    try:
        with closing(conectar()) as conexion:
            ids = conexion.execute("SELECT id FROM automatizaciones WHERE estado = 'activa' AND fecha_eliminacion IS NULL ORDER BY id").fetchall()
    except Exception:
        LOGGER_AUTOMATIZACIONES.exception('No se pudieron consultar las automatizaciones')
        return
    for (identificador,) in ids:
        reserva = None
        try:
            reserva = reclamar_automatizacion(identificador, ahora)
            if reserva is None:
                continue
            fila, ventana = reserva
            resultado = ejecutar_reserva_automatizacion(fila, ventana)
            if resultado is None:
                continue
        except Exception as error:
            LOGGER_AUTOMATIZACIONES.exception('Error en automatización #%s', identificador)
            if reserva is not None:
                try:
                    finalizar_automatizacion(identificador, reserva[1], error=str(error) or type(error).__name__)
                except Exception:
                    LOGGER_AUTOMATIZACIONES.exception('No se pudo registrar el error de #%s', identificador)
            continue
        # La salida es informativa: el resultado ya quedó persistido en SQLite.
        try:
            print(f"⚙️ Automatización #{identificador}: {fila['nombre']}\n{resultado}", flush=True)
        except Exception:
            LOGGER_AUTOMATIZACIONES.exception('No se pudo mostrar el resultado de #%s', identificador)


def proteccion_duplicados_automatizaciones(conexion):
    columnas = conexion.execute('PRAGMA table_info(ejecuciones_automatizaciones)').fetchall()
    clave = [fila[1] for fila in sorted(columnas, key=lambda fila: fila[5]) if fila[5]]
    requeridas = {fila[1]: fila for fila in columnas}
    return (clave == ['automatizacion_id', 'ventana']
            and all(requeridas[nombre][3] for nombre in clave))


def auditar_automatizaciones(ahora=None):
    """Inspección de solo lectura: nunca ejecuta instrucciones ni repara datos."""
    ahora = ahora or datetime.now()
    informe = {'errores': [], 'advertencias': [], 'automatizaciones': 0,
               'ejecuciones': 0, 'errores_registrados': 0, 'antiduplicados': False}
    errores, avisos = informe['errores'], informe['advertencias']
    try:
        # mode=ro evita crear una base vacía si la ruta es incorrecta.
        uri = Path(DB_PATH).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as conexion:
            conexion.row_factory = sqlite3.Row
            conexion.execute('PRAGMA query_only=ON')
            conexion.execute('BEGIN')  # Una sola instantánea, incluso con el motor activo.
            with closing(sqlite3.connect(':memory:')) as referencia:
                crear_tablas_automatizaciones(referencia)
                for tabla in ('automatizaciones', 'ejecuciones_automatizaciones'):
                    esperado = {fila[1]: fila for fila in referencia.execute(f'PRAGMA table_info({tabla})')}
                    actual = {fila[1]: fila for fila in conexion.execute(f'PRAGMA table_info({tabla})')}
                    for nombre, columna in esperado.items():
                        if nombre not in actual:
                            errores.append(f'Esquema: falta {tabla}.{nombre}.')
                        elif tuple(actual[nombre][2:6]) != tuple(columna[2:6]):
                            errores.append(f'Esquema: tipo, nulabilidad, valor por defecto o clave inválidos en {tabla}.{nombre}.')
                    # Comprobar también los CHECK existentes, sin probar INSERT en la base real.
                    sql = conexion.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone()
                    sql_ref = referencia.execute("SELECT sql FROM sqlite_master WHERE name=?", (tabla,)).fetchone()[0]
                    if sql is not None:
                        for restriccion in restricciones_check_automatizaciones(sql_ref):
                            if restriccion not in restricciones_check_automatizaciones(sql[0]):
                                errores.append(f'Esquema: falta una restricción CHECK en {tabla}.')
            informe['antiduplicados'] = proteccion_duplicados_automatizaciones(conexion)
            if not informe['antiduplicados']:
                errores.append('Protección contra doble disparo ausente: se requiere PK (automatizacion_id, ventana) no nula.')
            if errores:
                return informe  # No consultar columnas que podrían faltar.
            filas = [dict(fila) for fila in conexion.execute('SELECT * FROM automatizaciones ORDER BY id')]
            ejecuciones = [dict(fila) for fila in conexion.execute('SELECT * FROM ejecuciones_automatizaciones ORDER BY automatizacion_id, ventana')]
            informe['automatizaciones'], informe['ejecuciones'] = len(filas), len(ejecuciones)
            por_id = {fila['id']: fila for fila in filas}
            por_clave = {(fila['automatizacion_id'], fila['ventana']): fila for fila in ejecuciones}
            configuraciones = {}
            for fila in filas:
                etiqueta = f"Automatización #{fila['id']}"
                if fila['estado'] not in ('activa', 'pausada'):
                    errores.append(f'{etiqueta}: estado inválido.')
                if fila['fecha_eliminacion'] is not None and fila['estado'] != 'pausada':
                    errores.append(f'{etiqueta}: eliminada sin estado interno pausada (el motor igualmente la bloquea).')
                if type(fila['version_programacion']) is not int or fila['version_programacion'] < 0:
                    errores.append(f'{etiqueta}: versión de programación inválida.')
                # Validar horarios incluso para pausadas/eliminadas, sin invocar consultas.
                try:
                    validar_configuracion_automatizacion(
                        fila['nombre'], fila['instruccion'], fila['frecuencia'], fila['hora'], fila['dia_semana'])
                    if fila['dia_semana'] not in (None, *DIAS_SEMANA_RUTINA.values()):
                        raise ValueError('Día semanal no canónico.')
                except (ValueError, TypeError):
                    errores.append(f'{etiqueta}: nombre, instrucción, frecuencia, día u hora inválidos.')
                try:
                    capacidad = clasificar_instruccion_automatizacion(fila['instruccion'])
                except ValueError:
                    capacidad = None
                    avisos.append(f'{etiqueta}: instrucción no permitida; será rechazada sin ejecutar acciones.')
                for campo in ('fecha_creacion', 'fecha_actualizacion', 'fecha_eliminacion'):
                    if campo == 'fecha_eliminacion' and fila[campo] is None:
                        continue
                    if fecha_auditoria_automatizaciones(fila[campo]) is None:
                        errores.append(f'{etiqueta}: {campo} inválida.')
                if fila['estado'] == 'activa' and fila['fecha_eliminacion'] is None and capacidad:
                    clave = (capacidad, fila['frecuencia'], fila['dia_semana'], fila['hora'])
                    if clave in configuraciones:
                        avisos.append(f"{etiqueta}: misma consulta y horario que #{configuraciones[clave]}; IDs distintos pueden ejecutar ambas.")
                    else:
                        configuraciones[clave] = fila['id']
                ultimo = fila['ultimo_disparo']
                if ultimo is not None:
                    registro = por_clave.get((fila['id'], ultimo))
                    ventana = analizar_ventana_automatizacion(ultimo)
                    if (registro is None or registro['estado'] != 'correcta' or ventana is None
                            or ventana[0] != fila['frecuencia'] or ventana[2] != fila['version_programacion']):
                        errores.append(f'{etiqueta}: ultimo_disparo no corresponde a una ejecución correcta de su programación.')
            for ejecucion in ejecuciones:
                etiqueta = f"Ejecución #{ejecucion['automatizacion_id']} / {ejecucion['ventana']}"
                padre = por_id.get(ejecucion['automatizacion_id'])
                ventana = analizar_ventana_automatizacion(ejecucion['ventana'])
                if padre is None:
                    errores.append(f'{etiqueta}: automatización inexistente.')
                if ventana is None:
                    errores.append(f'{etiqueta}: ventana inválida.')
                elif padre is not None and type(padre['version_programacion']) is int:
                    if ventana[2] > padre['version_programacion']:
                        errores.append(f'{etiqueta}: versión posterior a la configuración.')
                    if ventana[2] == padre['version_programacion']:
                        if (ventana[0] != padre['frecuencia'] or (ventana[0] == 'semanal'
                                and DIAS_SEMANA_RUTINA[ventana[1].weekday()] != padre['dia_semana'])):
                            errores.append(f'{etiqueta}: ventana incompatible con la programación vigente.')
                        if ejecucion['estado'] == 'correcta':
                            ultimo = analizar_ventana_automatizacion(padre['ultimo_disparo'])
                            if ultimo is None or ultimo[1] < ventana[1]:
                                errores.append(f'{etiqueta}: ultimo_disparo ausente o anterior a una ejecución correcta vigente.')
                inicio = fecha_auditoria_automatizaciones(ejecucion['inicio'])
                fin = fecha_auditoria_automatizaciones(ejecucion['fin'])
                if inicio is None:
                    errores.append(f'{etiqueta}: inicio inválido.')
                estado = ejecucion['estado']
                if estado == 'en_curso':
                    if any(ejecucion[campo] is not None for campo in ('fin', 'resultado', 'error')):
                        errores.append(f'{etiqueta}: reserva en_curso con datos de finalización.')
                    if inicio is not None and (ahora - inicio).total_seconds() > 300:
                        avisos.append(f'{etiqueta}: reserva en_curso antigua; posible interrupción, sin reintento automático.')
                elif estado in ('correcta', 'error'):
                    if fin is None or (inicio is not None and fin < inicio):
                        errores.append(f'{etiqueta}: finalización inválida o anterior al inicio.')
                    if estado == 'correcta' and (not isinstance(ejecucion['resultado'], str) or ejecucion['error'] is not None):
                        errores.append(f'{etiqueta}: éxito sin resultado de texto o con error.')
                    if estado == 'error':
                        informe['errores_registrados'] += 1
                        if not isinstance(ejecucion['error'], str) or not ejecucion['error'].strip() or ejecucion['resultado'] is not None:
                            errores.append(f'{etiqueta}: error sin descripción o con resultado.')
                else:
                    errores.append(f'{etiqueta}: estado de ejecución inválido.')
    except (sqlite3.Error, OSError, ValueError, TypeError) as error:
        errores.append(f'No se pudo completar la auditoría: {error}')
    return informe


def restricciones_check_automatizaciones(sql):
    # Los CHECK de estas tablas son expresiones simples, sin paréntesis en literales.
    texto = ' '.join(sql.lower().split())
    restricciones = []
    for match in re.finditer(r'check\s*\(', texto):
        nivel = 1
        fin = match.end()
        while fin < len(texto) and nivel:
            nivel += (texto[fin] == '(') - (texto[fin] == ')')
            fin += 1
        restricciones.append(texto[match.start():fin])
    return restricciones


def fecha_auditoria_automatizaciones(valor):
    try:
        fecha = datetime.fromisoformat(valor)
        return fecha if fecha.tzinfo is None else None
    except (TypeError, ValueError):
        return None


def analizar_ventana_automatizacion(valor):
    if not isinstance(valor, str):
        return None
    match = re.fullmatch(r'(diaria|semanal):(\d{4}-\d{2}-\d{2})(?::v([1-9][0-9]{0,17}))?', valor)
    if not match:
        return None
    try:
        return match[1], datetime.strptime(match[2], '%Y-%m-%d').date(), int(match[3] or 0)
    except ValueError:
        return None


def mostrar_auditoria_automatizaciones():
    informe = auditar_automatizaciones()
    lineas = ['Auditoría de automatizaciones (solo lectura).',
              f"Configuraciones: {informe['automatizaciones']}. Ejecuciones: {informe['ejecuciones']}.",
              f"Protección SQLite contra doble disparo: {'activa' if informe['antiduplicados'] else 'NO verificada'}.",
              'Motor: lista segura compartida; pausadas y eliminadas bloqueadas; errores aislados por automatización.',
              f"Ejecuciones con error registradas: {informe['errores_registrados']}.",
              'No hay UID externo: se identifica por ID y ventana/version de programación.',
              'Esta inspección no confirma que el proceso del motor esté encendido.']
    lineas.extend('ERROR: ' + error for error in informe['errores'])
    lineas.extend('AVISO: ' + aviso for aviso in informe['advertencias'])
    if not informe['errores'] and not informe['advertencias']:
        lineas.append('Auditoría correcta: sin inconsistencias detectadas.')
    return '\n'.join(lineas)


def ejecutar_motor():
    crear_tabla_recordatorios()

    print("Automatizaciones: consultas locales seguras activas (28.2).")
    print()
    print(
        "════════════════════════════════"
    )
    print(
        "   MOTOR DE RECORDATORIOS HERMES"
    )
    print(
        "════════════════════════════════"
    )
    print()
    print(
        f"Revisando cada "
        f"{INTERVALO_REVISION} segundos."
    )
    print(
        "Rutinas recurrentes: activas."
    )
    print(
        "Eventos recurrentes: materialización automática activa."
    )
    configuracion_resumen = obtener_configuracion_resumen_diario()

    if configuracion_resumen:
        estado_resumen = (
            "activo"
            if configuracion_resumen[0]
            else "desactivado"
        )

        print(
            f"Resumen diario automático: "
            f"{estado_resumen} a las "
            f"{configuracion_resumen[1]}."
        )

    configuracion_nocturna = obtener_configuracion_resumen_nocturno()

    if configuracion_nocturna:
        estado_nocturno = (
            "activo"
            if configuracion_nocturna[0]
            else "desactivado"
        )

        print(
            f"Resumen nocturno automático: "
            f"{estado_nocturno} a las "
            f"{configuracion_nocturna[1]}."
        )

    print(
        "Ctrl + C para detener."
    )
    print()

    while True:

        try:
            materializar_proximos_eventos_recurrentes()
            revisar_resumen_diario()
            revisar_resumen_nocturno()
            revisar_recordatorios()
            revisar_rutinas()
            revisar_automatizaciones()

            time.sleep(
                INTERVALO_REVISION
            )

        except KeyboardInterrupt:
            print()
            print(
                "Motor de recordatorios detenido."
            )
            break 


if __name__ == "__main__":
    crear_tabla_recordatorios()

    if "--probar-resumen" in sys.argv:
        probar_resumen_diario()

    elif "--probar-resumen-nocturno" in sys.argv:
        probar_resumen_nocturno()

    elif "--auditar-resumen" in sys.argv:
        resultado = auditar_configuracion_resumen_diario()

        print()
        print("🧪 AUDITORÍA DEL RESUMEN DIARIO")
        print(resultado)
        print()

    elif "--auditar-resumen-nocturno" in sys.argv:
        resultado = auditar_configuracion_resumen_nocturno()

        print()
        print("🧪 AUDITORÍA DEL RESUMEN NOCTURNO")
        print(resultado)
        print()

    else:
        ejecutar_motor()

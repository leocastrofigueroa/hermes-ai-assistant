import sqlite3
import subprocess
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


def ejecutar_motor():
    crear_tabla_recordatorios()

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
        "Ctrl + C para detener."
    )
    print()

    while True:

        try:
            revisar_recordatorios()
            revisar_rutinas()

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
    ejecutar_motor()

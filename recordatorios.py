import sqlite3
import subprocess
import time
from datetime import datetime

DB_PATH = "hermes.db"

INTERVALO_REVISION = 15


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
            fecha_disparo TIMESTAMP
        )
    """)

    conexion.commit()
    conexion.close()


def buscar_recordatorio_pendiente(
    titulo,
    fecha_hora
):
    conexion = conectar()
    cursor = conexion.cursor()

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

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def crear_recordatorio(
    titulo,
    fecha_hora,
    mensaje=""
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
            estado
        )
        VALUES (?, ?, ?, 'pendiente')
    """, (
        titulo.strip(),
        mensaje.strip(),
        fecha_hora
    ))

    recordatorio_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return (
        "creado",
        recordatorio_id
    )


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
                f"{titulo}"
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
        "Ctrl + C para detener."
    )
    print()

    while True:
        try:
            revisar_recordatorios()

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

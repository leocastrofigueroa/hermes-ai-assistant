import sqlite3
from datetime import datetime


DB_PATH = "hermes.db"


# ==========================================================
# CONEXIÓN
# ==========================================================

def conectar():
    return sqlite3.connect(DB_PATH)


# ==========================================================
# CREAR / MIGRAR BASE
# ==========================================================

def crear_base():
    conexion = conectar()
    cursor = conexion.cursor()

    # ------------------------------------------------------
    # RECUERDOS
    # ------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recuerdos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            categoria TEXT NOT NULL,
            clave TEXT NOT NULL,
            valor TEXT NOT NULL,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    columnas_recuerdos = {
        fila[1]
        for fila in cursor.execute(
            "PRAGMA table_info(recuerdos)"
        ).fetchall()
    }

    if "fecha_actualizacion" not in columnas_recuerdos:
        cursor.execute("""
            ALTER TABLE recuerdos
            ADD COLUMN fecha_actualizacion TIMESTAMP
        """)

    # ------------------------------------------------------
    # TAREAS
    # ------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha TEXT,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ------------------------------------------------------
    # EVENTOS
    # ------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha TEXT NOT NULL,
            hora_inicio TEXT,
            hora_fin TEXT,
            estado TEXT NOT NULL DEFAULT 'activo',
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conexion.commit()
    conexion.close()


# ==========================================================
# RECUERDOS
# ==========================================================

def guardar_recuerdo(
    categoria,
    clave,
    valor
):
    categoria = categoria.strip()
    clave = clave.strip().lower()
    valor = valor.strip()

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            valor
        FROM recuerdos
        WHERE lower(clave) = lower(?)
        LIMIT 1
    """, (
        clave,
    ))

    existente = cursor.fetchone()

    if existente:
        recuerdo_id = existente[0]
        valor_actual = existente[1]

        if valor_actual.strip() == valor:
            conexion.close()
            return "sin_cambios"

        cursor.execute("""
            UPDATE recuerdos
            SET categoria = ?,
                valor = ?,
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            categoria,
            valor,
            recuerdo_id
        ))

        conexion.commit()
        conexion.close()

        return "actualizado"

    cursor.execute("""
        INSERT INTO recuerdos (
            categoria,
            clave,
            valor
        )
        VALUES (?, ?, ?)
    """, (
        categoria,
        clave,
        valor
    ))

    conexion.commit()
    conexion.close()

    return "creado"


def obtener_recuerdos():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            categoria,
            clave,
            valor
        FROM recuerdos
        ORDER BY id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


# ==========================================================
# TAREAS
# ==========================================================

def crear_tarea(
    titulo,
    descripcion="",
    fecha=None
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO tareas (
            titulo,
            descripcion,
            fecha,
            estado
        )
        VALUES (?, ?, ?, 'pendiente')
    """, (
        titulo.strip(),
        descripcion.strip(),
        fecha
    ))

    tarea_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return tarea_id


def obtener_tareas_pendientes():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            estado
        FROM tareas
        WHERE estado = 'pendiente'
        ORDER BY
            CASE
                WHEN fecha IS NULL THEN 1
                ELSE 0
            END,
            fecha ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_tareas_por_fecha(
    fecha
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            estado
        FROM tareas
        WHERE estado = 'pendiente'
          AND fecha = ?
        ORDER BY id ASC
    """, (
        fecha,
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_tareas_entre_fechas(
    fecha_inicio,
    fecha_fin
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            estado
        FROM tareas
        WHERE estado = 'pendiente'
          AND fecha BETWEEN ? AND ?
        ORDER BY fecha ASC, id ASC
    """, (
        fecha_inicio,
        fecha_fin
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_tarea_por_id(
    tarea_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            estado
        FROM tareas
        WHERE id = ?
        LIMIT 1
    """, (
        tarea_id,
    ))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def completar_tarea(
    tarea_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE tareas
        SET estado = 'completada',
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado = 'pendiente'
    """, (
        tarea_id,
    ))

    actualizado = (
        cursor.rowcount > 0
    )

    conexion.commit()
    conexion.close()

    return actualizado


# ==========================================================
# EVENTOS
# ==========================================================

def crear_evento(
    titulo,
    fecha,
    hora_inicio=None,
    hora_fin=None,
    descripcion=""
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO eventos (
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado
        )
        VALUES (?, ?, ?, ?, ?, 'activo')
    """, (
        titulo.strip(),
        descripcion.strip(),
        fecha,
        hora_inicio,
        hora_fin
    ))

    evento_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return evento_id


def obtener_eventos_activos():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado
        FROM eventos
        WHERE estado = 'activo'
        ORDER BY
            fecha ASC,
            CASE
                WHEN hora_inicio IS NULL THEN 1
                ELSE 0
            END,
            hora_inicio ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_eventos_por_fecha(
    fecha
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado
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
        fecha,
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_eventos_entre_fechas(
    fecha_inicio,
    fecha_fin
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado
        FROM eventos
        WHERE estado = 'activo'
          AND fecha BETWEEN ? AND ?
        ORDER BY
            fecha ASC,
            CASE
                WHEN hora_inicio IS NULL THEN 1
                ELSE 0
            END,
            hora_inicio ASC,
            id ASC
    """, (
        fecha_inicio,
        fecha_fin
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_evento_por_id(
    evento_id
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            titulo,
            descripcion,
            fecha,
            hora_inicio,
            hora_fin,
            estado
        FROM eventos
        WHERE id = ?
        LIMIT 1
    """, (
        evento_id,
    ))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def modificar_evento(
    evento_id,
    fecha=None,
    hora_inicio=None,
    hora_fin=None,
    titulo=None,
    descripcion=None
):
    actual = obtener_evento_por_id(
        evento_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[6] != "activo":
        return (
            "no_activo",
            evento_id
        )

    titulo_final = (
        titulo.strip()
        if titulo is not None
        else actual[1]
    )

    descripcion_final = (
        descripcion.strip()
        if descripcion is not None
        else (actual[2] or "")
    )

    fecha_final = (
        fecha
        if fecha is not None
        else actual[3]
    )

    hora_inicio_final = (
        hora_inicio
        if hora_inicio is not None
        else actual[4]
    )

    hora_fin_final = (
        hora_fin
        if hora_fin is not None
        else actual[5]
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE eventos
        SET titulo = ?,
            descripcion = ?,
            fecha = ?,
            hora_inicio = ?,
            hora_fin = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado = 'activo'
    """, (
        titulo_final,
        descripcion_final,
        fecha_final,
        hora_inicio_final,
        hora_fin_final,
        evento_id
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizado",
        evento_id
    )


def cancelar_evento(
    evento_id
):
    actual = obtener_evento_por_id(
        evento_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[6] == "cancelado":
        return (
            "ya_cancelado",
            evento_id
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE eventos
        SET estado = 'cancelado',
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado = 'activo'
    """, (
        evento_id,
    ))

    conexion.commit()
    conexion.close()

    return (
        "cancelado",
        evento_id
    )


if __name__ == "__main__":
    crear_base()

    print(
        "Base de datos de Hermes lista."
    )

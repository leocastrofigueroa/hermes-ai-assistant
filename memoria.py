import sqlite3

DB_PATH = "hermes.db"


def conectar():
    return sqlite3.connect(DB_PATH)


def crear_base():
    conexion = conectar()
    cursor = conexion.cursor()

    # -------------------------
    # MEMORIA PERMANENTE
    # -------------------------

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

    columnas = cursor.execute(
        "PRAGMA table_info(recuerdos)"
    ).fetchall()

    nombres_columnas = [
        columna[1]
        for columna in columnas
    ]

    if "fecha_actualizacion" not in nombres_columnas:
        cursor.execute("""
            ALTER TABLE recuerdos
            ADD COLUMN fecha_actualizacion TIMESTAMP
        """)

        cursor.execute("""
            UPDATE recuerdos
            SET fecha_actualizacion = fecha_creacion
            WHERE fecha_actualizacion IS NULL
        """)

    # -------------------------
    # TAREAS
    # -------------------------

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

    conexion.commit()
    conexion.close()


def normalizar_clave(clave):
    return clave.strip().lower()


# ==========================================================
# MEMORIA
# ==========================================================

def guardar_recuerdo(categoria, clave, valor):
    conexion = conectar()
    cursor = conexion.cursor()

    clave = normalizar_clave(clave)
    valor = valor.strip()

    existente = cursor.execute("""
        SELECT id, valor
        FROM recuerdos
        WHERE clave = ?
        LIMIT 1
    """, (clave,)).fetchone()

    if existente:
        recuerdo_id, valor_actual = existente

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
            valor,
            fecha_actualizacion
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
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
        ORDER BY
            COALESCE(
                fecha_actualizacion,
                fecha_creacion
            ) DESC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


# ==========================================================
# TAREAS
# ==========================================================

def crear_tarea(titulo, descripcion="", fecha=None):
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
                WHEN fecha IS NULL OR fecha = '' THEN 1
                ELSE 0
            END,
            fecha ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_tareas_por_fecha(fecha):
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
    """, (fecha,))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_tareas_entre_fechas(fecha_inicio, fecha_fin):
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
        AND fecha IS NOT NULL
        AND fecha >= ?
        AND fecha <= ?
        ORDER BY fecha ASC, id ASC
    """, (
        fecha_inicio,
        fecha_fin
    ))

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def completar_tarea(tarea_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE tareas
        SET estado = 'completada',
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
        AND estado = 'pendiente'
    """, (tarea_id,))

    cambios = cursor.rowcount

    conexion.commit()
    conexion.close()

    return cambios > 0


def obtener_tarea_por_id(tarea_id):
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
    """, (tarea_id,))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


if __name__ == "__main__":
    crear_base()

    print(
        "Base de datos de Hermes lista."
    )

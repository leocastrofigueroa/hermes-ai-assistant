import sqlite3

DB_PATH = "hermes.db"


def conectar():
    return sqlite3.connect(DB_PATH)


def crear_base():
    conexion = conectar()
    cursor = conexion.cursor()

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

    conexion.commit()
    conexion.close()


def normalizar_clave(clave):
    return clave.strip().lower()


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


def obtener_recuerdo_por_clave(clave):
    conexion = conectar()
    cursor = conexion.cursor()

    clave = normalizar_clave(clave)

    cursor.execute("""
        SELECT
            categoria,
            clave,
            valor
        FROM recuerdos
        WHERE clave = ?
        LIMIT 1
    """, (clave,))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def listar_recuerdos():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            categoria,
            clave,
            valor,
            fecha_creacion,
            fecha_actualizacion
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


if __name__ == "__main__":
    crear_base()
    print("Base de memoria de Hermes lista.")

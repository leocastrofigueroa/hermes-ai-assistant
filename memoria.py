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
            prioridad TEXT NOT NULL DEFAULT 'media',
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    columnas_tareas = {
        fila[1]
        for fila in cursor.execute(
            "PRAGMA table_info(tareas)"
        ).fetchall()
    }

    if "prioridad" not in columnas_tareas:
        cursor.execute("""
            ALTER TABLE tareas
            ADD COLUMN prioridad TEXT NOT NULL DEFAULT 'media'
        """)

    # ------------------------------------------------------
    # RUTINAS RECURRENTES
    # ------------------------------------------------------

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

    # ------------------------------------------------------
    # EVENTOS RECURRENTES
    # ------------------------------------------------------

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
    fecha=None,
    prioridad="media"
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO tareas (
            titulo,
            descripcion,
            fecha,
            estado,
            prioridad
        )
        VALUES (?, ?, ?, 'pendiente', ?)
    """, (
        titulo.strip(),
        descripcion.strip(),
        fecha,
        prioridad.strip().lower()
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
            estado,
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
            estado,
            prioridad
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
            estado,
            prioridad
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
            estado,
            prioridad
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


def modificar_tarea(
    tarea_id,
    fecha=None,
    titulo=None,
    descripcion=None,
    prioridad=None
):
    actual = obtener_tarea_por_id(
        tarea_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[4] != "pendiente":
        return (
            "no_pendiente",
            tarea_id
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

    prioridad_final = (
        prioridad.strip().lower()
        if prioridad is not None
        else (
            actual[5]
            if len(actual) > 5 and actual[5]
            else "media"
        )
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE tareas
        SET titulo = ?,
            descripcion = ?,
            fecha = ?,
            prioridad = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado = 'pendiente'
    """, (
        titulo_final,
        descripcion_final,
        fecha_final,
        prioridad_final,
        tarea_id
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizado",
        tarea_id
    )


# ==========================================================
# RUTINAS RECURRENTES
# ==========================================================

def crear_rutina(
    titulo,
    frecuencia,
    hora,
    dia_semana=None
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO rutinas (
            titulo,
            frecuencia,
            dia_semana,
            hora,
            estado
        )
        VALUES (?, ?, ?, ?, 'activa')
    """, (
        titulo.strip(),
        frecuencia.strip().lower(),
        (
            dia_semana.strip().lower()
            if dia_semana
            else None
        ),
        hora,
    ))

    rutina_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return rutina_id


def obtener_rutinas():
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
        WHERE estado != 'eliminada'
        ORDER BY
            CASE estado
                WHEN 'activa' THEN 0
                ELSE 1
            END,
            CASE frecuencia
                WHEN 'diaria' THEN 0
                WHEN 'semanal' THEN 1
                ELSE 2
            END,
            CASE dia_semana
                WHEN 'lunes' THEN 0
                WHEN 'martes' THEN 1
                WHEN 'miercoles' THEN 2
                WHEN 'jueves' THEN 3
                WHEN 'viernes' THEN 4
                WHEN 'sabado' THEN 5
                WHEN 'domingo' THEN 6
                ELSE 7
            END,
            hora ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


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
        ORDER BY
            CASE frecuencia
                WHEN 'diaria' THEN 0
                WHEN 'semanal' THEN 1
                ELSE 2
            END,
            CASE dia_semana
                WHEN 'lunes' THEN 0
                WHEN 'martes' THEN 1
                WHEN 'miercoles' THEN 2
                WHEN 'jueves' THEN 3
                WHEN 'viernes' THEN 4
                WHEN 'sabado' THEN 5
                WHEN 'domingo' THEN 6
                ELSE 7
            END,
            hora ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_rutina_por_id(
    rutina_id
):
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
        WHERE id = ?
        LIMIT 1
    """, (
        rutina_id,
    ))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def modificar_rutina(
    rutina_id,
    titulo=None,
    frecuencia=None,
    dia_semana=None,
    hora=None
):
    actual = obtener_rutina_por_id(
        rutina_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    titulo_final = (
        titulo.strip()
        if titulo is not None
        else actual[1]
    )

    frecuencia_final = (
        frecuencia.strip().lower()
        if frecuencia is not None
        else actual[2]
    )

    if frecuencia_final == "diaria":
        dia_final = None
    elif dia_semana is not None:
        dia_final = (
            dia_semana.strip().lower()
            if dia_semana
            else None
        )
    else:
        dia_final = actual[3]

    hora_final = (
        hora
        if hora is not None
        else actual[4]
    )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE rutinas
        SET titulo = ?,
            frecuencia = ?,
            dia_semana = ?,
            hora = ?,
            ultimo_disparo = NULL,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        titulo_final,
        frecuencia_final,
        dia_final,
        hora_final,
        rutina_id,
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizada",
        rutina_id
    )


def cambiar_estado_rutina(
    rutina_id,
    nuevo_estado
):
    if nuevo_estado not in (
        "activa",
        "pausada",
    ):
        return (
            "estado_invalido",
            rutina_id
        )

    actual = obtener_rutina_por_id(
        rutina_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[5] == nuevo_estado:
        return (
            "sin_cambios",
            rutina_id
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE rutinas
        SET estado = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        nuevo_estado,
        rutina_id,
    ))

    conexion.commit()
    conexion.close()

    return (
        "actualizada",
        rutina_id
    )


def eliminar_rutina(
    rutina_id
):
    actual = obtener_rutina_por_id(
        rutina_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[5] == "eliminada":
        return (
            "ya_eliminada",
            rutina_id
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE rutinas
        SET estado = 'eliminada',
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        rutina_id,
    ))

    conexion.commit()
    conexion.close()

    return (
        "eliminada",
        rutina_id
    )


# ==========================================================
# EVENTOS RECURRENTES
# ==========================================================

def crear_evento_recurrente(
    titulo,
    frecuencia,
    hora_inicio,
    dia_semana=None,
    hora_fin=None
):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        INSERT INTO eventos_recurrentes (
            titulo,
            frecuencia,
            dia_semana,
            hora_inicio,
            hora_fin,
            estado
        )
        VALUES (?, ?, ?, ?, ?, 'activo')
    """, (
        titulo.strip(),
        frecuencia.strip().lower(),
        (
            dia_semana.strip().lower()
            if dia_semana
            else None
        ),
        hora_inicio,
        hora_fin,
    ))

    evento_id = cursor.lastrowid

    conexion.commit()
    conexion.close()

    return evento_id


def obtener_eventos_recurrentes():
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
        WHERE estado != 'eliminado'
        ORDER BY
            CASE estado
                WHEN 'activo' THEN 0
                WHEN 'pausado' THEN 1
                ELSE 2
            END,
            CASE frecuencia
                WHEN 'diaria' THEN 0
                WHEN 'semanal' THEN 1
                ELSE 2
            END,
            CASE dia_semana
                WHEN 'lunes' THEN 0
                WHEN 'martes' THEN 1
                WHEN 'miercoles' THEN 2
                WHEN 'jueves' THEN 3
                WHEN 'viernes' THEN 4
                WHEN 'sabado' THEN 5
                WHEN 'domingo' THEN 6
                ELSE 7
            END,
            hora_inicio ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


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
        ORDER BY
            CASE frecuencia
                WHEN 'diaria' THEN 0
                WHEN 'semanal' THEN 1
                ELSE 2
            END,
            CASE dia_semana
                WHEN 'lunes' THEN 0
                WHEN 'martes' THEN 1
                WHEN 'miercoles' THEN 2
                WHEN 'jueves' THEN 3
                WHEN 'viernes' THEN 4
                WHEN 'sabado' THEN 5
                WHEN 'domingo' THEN 6
                ELSE 7
            END,
            hora_inicio ASC,
            id ASC
    """)

    resultados = cursor.fetchall()

    conexion.close()

    return resultados


def obtener_evento_recurrente_por_id(
    evento_id
):
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
        WHERE id = ?
        LIMIT 1
    """, (
        evento_id,
    ))

    resultado = cursor.fetchone()

    conexion.close()

    return resultado


def cancelar_ocurrencias_futuras_recurrente(
    recurrente_id
):
    ahora = datetime.now()

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT
            id,
            fecha,
            hora_inicio
        FROM eventos
        WHERE recurrente_id = ?
          AND estado = 'activo'
    """, (
        recurrente_id,
    ))

    filas = cursor.fetchall()

    cancelados = 0

    for evento_id, fecha, hora_inicio in filas:

        try:
            hora = (
                hora_inicio
                if hora_inicio
                else "23:59"
            )

            momento = datetime.fromisoformat(
                f"{fecha}T{hora}:00"
            )

        except (TypeError, ValueError):
            continue

        if momento < ahora:
            continue

        cursor.execute("""
            UPDATE eventos
            SET estado = 'cancelado',
                fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
              AND estado = 'activo'
        """, (
            evento_id,
        ))

        cancelados += cursor.rowcount

    conexion.commit()
    conexion.close()

    return cancelados


def modificar_evento_recurrente(
    evento_id,
    titulo=None,
    frecuencia=None,
    dia_semana=None,
    hora_inicio=None,
    hora_fin=None
):
    actual = obtener_evento_recurrente_por_id(
        evento_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[6] == "eliminado":
        return (
            "eliminado",
            evento_id
        )

    titulo_final = (
        titulo.strip()
        if titulo is not None
        else actual[1]
    )

    frecuencia_final = (
        frecuencia.strip().lower()
        if frecuencia is not None
        else actual[2]
    )

    if frecuencia_final == "diaria":
        dia_final = None
    elif dia_semana is not None:
        dia_final = (
            dia_semana.strip().lower()
            if dia_semana
            else None
        )
    else:
        dia_final = actual[3]

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
        UPDATE eventos_recurrentes
        SET titulo = ?,
            frecuencia = ?,
            dia_semana = ?,
            hora_inicio = ?,
            hora_fin = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado != 'eliminado'
    """, (
        titulo_final,
        frecuencia_final,
        dia_final,
        hora_inicio_final,
        hora_fin_final,
        evento_id,
    ))

    actualizado = (
        cursor.rowcount > 0
    )

    conexion.commit()
    conexion.close()

    if not actualizado:
        return (
            "sin_cambios",
            evento_id
        )

    cancelar_ocurrencias_futuras_recurrente(
        evento_id
    )

    return (
        "actualizado",
        evento_id
    )


def cambiar_estado_evento_recurrente(
    evento_id,
    nuevo_estado
):
    if nuevo_estado not in (
        "activo",
        "pausado",
    ):
        return (
            "estado_invalido",
            evento_id
        )

    actual = obtener_evento_recurrente_por_id(
        evento_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[6] == "eliminado":
        return (
            "eliminado",
            evento_id
        )

    if actual[6] == nuevo_estado:
        return (
            "sin_cambios",
            evento_id
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE eventos_recurrentes
        SET estado = ?,
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
          AND estado != 'eliminado'
    """, (
        nuevo_estado,
        evento_id,
    ))

    conexion.commit()
    conexion.close()

    if nuevo_estado == "pausado":
        cancelar_ocurrencias_futuras_recurrente(
            evento_id
        )

    return (
        "actualizado",
        evento_id
    )


def eliminar_evento_recurrente(
    evento_id
):
    actual = obtener_evento_recurrente_por_id(
        evento_id
    )

    if not actual:
        return (
            "no_existe",
            None
        )

    if actual[6] == "eliminado":
        return (
            "ya_eliminado",
            evento_id
        )

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        UPDATE eventos_recurrentes
        SET estado = 'eliminado',
            fecha_actualizacion = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        evento_id,
    ))

    conexion.commit()
    conexion.close()

    cancelar_ocurrencias_futuras_recurrente(
        evento_id
    )

    return (
        "eliminado",
        evento_id
    )


def auditar_y_limpiar_eventos_recurrentes():
    dias_validos = {
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo",
    }

    estados_validos = {
        "activo",
        "pausado",
        "eliminado",
    }

    frecuencias_validas = {
        "diaria",
        "semanal",
    }

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
        ORDER BY id ASC
    """)

    recurrentes = cursor.fetchall()

    revisados = 0
    corregidos = 0
    pausados = 0
    ocurrencias_canceladas = 0
    duplicados = []
    observaciones = []

    reglas_vistas = {}

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

        revisados += 1

        # Las recurrencias eliminadas se conservan como historial.
        if estado == "eliminado":
            continue

        # Estado inválido: se pausa para evitar ejecuciones inesperadas.
        if estado not in estados_validos:
            cursor.execute("""
                UPDATE eventos_recurrentes
                SET estado = 'pausado',
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                recurrente_id,
            ))

            estado = "pausado"
            pausados += 1
            observaciones.append(
                f"#{recurrente_id} tenía un estado inválido y fue pausado."
            )

        # Frecuencia inválida: pausar es más seguro que adivinar.
        if frecuencia not in frecuencias_validas:
            cursor.execute("""
                UPDATE eventos_recurrentes
                SET estado = 'pausado',
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                recurrente_id,
            ))

            estado = "pausado"
            pausados += 1
            observaciones.append(
                f"#{recurrente_id} tenía una frecuencia inválida y fue pausado."
            )

        # Una diaria no necesita día de semana.
        if frecuencia == "diaria" and dia_semana is not None:
            cursor.execute("""
                UPDATE eventos_recurrentes
                SET dia_semana = NULL,
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                recurrente_id,
            ))

            dia_semana = None
            corregidos += 1
            observaciones.append(
                f"#{recurrente_id} era diaria y tenía día de semana; lo corregí."
            )

        # Una semanal necesita un día válido.
        if (
            frecuencia == "semanal"
            and dia_semana not in dias_validos
        ):
            if estado != "pausado":
                cursor.execute("""
                    UPDATE eventos_recurrentes
                    SET estado = 'pausado',
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    recurrente_id,
                ))
                estado = "pausado"
                pausados += 1

            observaciones.append(
                f"#{recurrente_id} no tenía un día semanal válido y fue pausado."
            )

        # Validamos horarios con formato HH:MM.
        hora_inicio_valida = True

        try:
            datetime.strptime(
                hora_inicio,
                "%H:%M"
            )

        except (TypeError, ValueError):
            hora_inicio_valida = False

        hora_fin_valida = True

        if hora_fin is not None:
            try:
                datetime.strptime(
                    hora_fin,
                    "%H:%M"
                )

            except (TypeError, ValueError):
                hora_fin_valida = False

        if not hora_inicio_valida or not hora_fin_valida:
            if estado != "pausado":
                cursor.execute("""
                    UPDATE eventos_recurrentes
                    SET estado = 'pausado',
                        fecha_actualizacion = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    recurrente_id,
                ))
                estado = "pausado"
                pausados += 1

            observaciones.append(
                f"#{recurrente_id} tenía un horario inválido y fue pausado."
            )

        # Detectamos reglas exactamente duplicadas, pero no eliminamos ninguna.
        clave = (
            (titulo or "").strip().lower(),
            frecuencia,
            dia_semana,
            hora_inicio,
            hora_fin,
            estado,
        )

        if estado != "eliminado":
            if clave in reglas_vistas:
                duplicados.append(
                    (
                        reglas_vistas[clave],
                        recurrente_id,
                    )
                )
            else:
                reglas_vistas[clave] = recurrente_id

    # Cancelamos ocurrencias futuras huérfanas:
    # están vinculadas a una recurrencia que no existe o fue eliminada.
    ahora = datetime.now()

    cursor.execute("""
        SELECT
            e.id,
            e.fecha,
            e.hora_inicio,
            e.recurrente_id,
            r.estado
        FROM eventos e
        LEFT JOIN eventos_recurrentes r
          ON r.id = e.recurrente_id
        WHERE e.recurrente_id IS NOT NULL
          AND e.estado = 'activo'
    """)

    ocurrencias = cursor.fetchall()

    for (
        evento_id,
        fecha,
        hora_inicio,
        recurrente_id,
        estado_recurrente,
    ) in ocurrencias:

        try:
            hora = (
                hora_inicio
                if hora_inicio
                else "23:59"
            )

            momento = datetime.fromisoformat(
                f"{fecha}T{hora}:00"
            )

        except (TypeError, ValueError):
            continue

        if momento < ahora:
            continue

        if (
            estado_recurrente is None
            or estado_recurrente in (
                "pausado",
                "eliminado",
            )
        ):
            cursor.execute("""
                UPDATE eventos
                SET estado = 'cancelado',
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND estado = 'activo'
            """, (
                evento_id,
            ))

            ocurrencias_canceladas += cursor.rowcount

    # Cancelamos ocurrencias futuras que ya no coinciden con su regla.
    cursor.execute("""
        SELECT
            e.id,
            e.fecha,
            e.hora_inicio,
            e.hora_fin,
            e.recurrente_id,
            r.titulo,
            r.frecuencia,
            r.dia_semana,
            r.hora_inicio,
            r.hora_fin,
            r.estado,
            e.titulo
        FROM eventos e
        JOIN eventos_recurrentes r
          ON r.id = e.recurrente_id
        WHERE e.estado = 'activo'
          AND r.estado = 'activo'
    """)

    vinculadas = cursor.fetchall()

    indice_dias = {
        "lunes": 0,
        "martes": 1,
        "miercoles": 2,
        "jueves": 3,
        "viernes": 4,
        "sabado": 5,
        "domingo": 6,
    }

    for fila in vinculadas:
        (
            evento_id,
            fecha,
            evento_hora_inicio,
            evento_hora_fin,
            recurrente_id,
            titulo_regla,
            frecuencia,
            dia_semana,
            regla_hora_inicio,
            regla_hora_fin,
            estado_regla,
            titulo_evento,
        ) = fila

        try:
            fecha_obj = datetime.strptime(
                fecha,
                "%Y-%m-%d"
            ).date()

            hora = (
                evento_hora_inicio
                if evento_hora_inicio
                else "23:59"
            )

            momento = datetime.fromisoformat(
                f"{fecha}T{hora}:00"
            )

        except (TypeError, ValueError):
            continue

        if momento < ahora:
            continue

        coincide_dia = True

        if frecuencia == "semanal":
            dia_objetivo = indice_dias.get(
                dia_semana
            )

            coincide_dia = (
                dia_objetivo is not None
                and fecha_obj.weekday() == dia_objetivo
            )

        coincide = (
            coincide_dia
            and evento_hora_inicio == regla_hora_inicio
            and evento_hora_fin == regla_hora_fin
            and (titulo_evento or "").strip()
                == (titulo_regla or "").strip()
        )

        if not coincide:
            cursor.execute("""
                UPDATE eventos
                SET estado = 'cancelado',
                    fecha_actualizacion = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND estado = 'activo'
            """, (
                evento_id,
            ))

            ocurrencias_canceladas += cursor.rowcount

    conexion.commit()
    conexion.close()

    return {
        "revisados": revisados,
        "corregidos": corregidos,
        "pausados": pausados,
        "ocurrencias_canceladas": ocurrencias_canceladas,
        "duplicados": duplicados,
        "observaciones": observaciones,
    }


# ==========================================================
# EVENTOS
# ==========================================================

def crear_evento(
    titulo,
    fecha,
    hora_inicio=None,
    hora_fin=None,
    descripcion="",
    recurrente_id=None,
    fecha_ocurrencia=None
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
            estado,
            recurrente_id,
            fecha_ocurrencia
        )
        VALUES (?, ?, ?, ?, ?, 'activo', ?, ?)
    """, (
        titulo.strip(),
        descripcion.strip(),
        fecha,
        hora_inicio,
        hora_fin,
        recurrente_id,
        fecha_ocurrencia
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

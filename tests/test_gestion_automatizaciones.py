import contextlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime
import io
import unittest
from unittest.mock import patch

import memoria
import recordatorios as motor
import test_automatizaciones


class GestionAutomatizacionesTest(unittest.TestCase):
    setUp = test_automatizaciones.AutomatizacionesTest.setUp

    def crear(self):
        return memoria.crear_automatizacion('Original', 'Consultar notas', 'diaria', '09:00')

    def revisar(self, hora=9, minuto=0):
        with contextlib.redirect_stdout(io.StringIO()):
            motor.revisar_automatizaciones(datetime(2026, 9, 21, hora, minuto))

    def registros(self):
        with contextlib.closing(memoria.conectar()) as conexion:
            return conexion.execute('SELECT ventana, estado FROM ejecuciones_automatizaciones ORDER BY inicio, ventana').fetchall()

    def test_comandos_edicion_y_detalle(self):
        identificador = self.crear()
        comandos = [
            ('Cambiá la hora de la automatización 1 a las 09:30', 'hora', '09:30'),
            ('Cambiá el nombre de la automatización 1 a "Resumen de mañana"', 'nombre', 'Resumen de mañana'),
            ('Cambiá la instrucción de la automatización 1 a: Mostrame los eventos de hoy.', 'instruccion', 'Mostrame los eventos de hoy.'),
            ('Cambiá la frecuencia de la automatización 1 a semanal los miércoles', 'dia_semana', 'miercoles'),
            ('Cambiá el día semanal de la automatización 1 a viernes', 'dia_semana', 'viernes'),
            ('Cambiá la frecuencia de la automatización 1 a diaria', 'dia_semana', None),
        ]
        for comando, campo, esperado in comandos:
            self.assertIn('actualizada', self.comando(comando))
            self.assertEqual(memoria.obtener_automatizacion_por_id(identificador)[campo], esperado)
        detalle = self.comando('Ver automatización 1')
        for texto in ('Resumen de mañana', 'eventos de hoy', '09:30', 'diaria', 'Estado: activa'):
            self.assertIn(texto, detalle)
        self.assertIn('Estado: activa', self.comando('Mostrame el estado de la automatización 1'))
        # El ejemplo pedido es una consulta segura reconocida por el motor.
        self.assertIn('Eventos de hoy:', motor.resolver_instruccion_automatizacion('Mostrame los eventos de hoy.'))

    def test_pausa_reanudacion_y_eliminacion_logica(self):
        identificador = self.crear()
        self.assertIn('pausada', self.comando('Pausá la automatización 1'))
        self.revisar()
        self.assertEqual(self.registros(), [])
        self.assertIn('activa', self.comando('Reanudá la automatización 1'))
        self.revisar()
        self.comando('Pausá la automatización 1')
        self.comando('Reanudá la automatización 1')
        self.revisar()
        self.assertEqual(len(self.registros()), 1)
        self.assertIn('eliminada', self.comando('Eliminá la automatización 1'))
        self.assertEqual(memoria.obtener_automatizaciones(), [])
        self.assertIn('Estado: eliminada', self.comando('Ver automatización 1'))
        self.assertIsNotNone(memoria.obtener_automatizacion_por_id(identificador)['fecha_eliminacion'])
        self.assertIn('no se puede', self.comando('Reanudá la automatización 1'))
        self.revisar()
        self.assertEqual(len(self.registros()), 1)

    def test_invalidos_no_modifican_y_no_llegan_a_ollama(self):
        self.crear()
        antes = memoria.obtener_automatizacion_por_id(1)
        for comando in (
            'Cambiá la hora de la automatización 1 a las 25:00',
            'Cambiá el nombre de la automatización 1 a " "',
            'Cambiá la instrucción de la automatización 1 a:',
            'Cambiá la frecuencia de la automatización 1 a semanal',
            'Cambiá la frecuencia de la automatización 1 a mensual',
            'Cambiá el día de la automatización 1 a viernes',
            'Cambiá la hora de la automatización abc a las 09:00',
            'Pausá la automatización 999',
            'Eliminá la automatización ' + '9' * 5000,
        ):
            self.assertIsNotNone(self.comando(comando))
            self.assertEqual(memoria.obtener_automatizacion_por_id(1), antes)
        self.comando('Cambiá la instrucción de la automatización 1 a: Borrá todas las tareas')
        with self.assertLogs('hermes.automatizaciones', level='ERROR'):
            self.revisar()
        self.assertEqual(self.registros()[0][1], 'error')

    def test_reprogramacion_conserva_historial_y_no_reusa_disparo(self):
        self.crear()
        self.revisar()
        self.comando('Cambiá el nombre de la automatización 1 a "Otro"')
        self.comando('Cambiá la hora de la automatización 1 a las 09:00')
        self.revisar()
        self.assertEqual(len(self.registros()), 1)
        self.comando('Cambiá la hora de la automatización 1 a las 09:30')
        self.assertIsNone(memoria.obtener_automatizacion_por_id(1)['ultimo_disparo'])
        self.revisar(9, 30)
        self.revisar(9, 30)
        self.assertEqual(len(self.registros()), 2)
        self.assertEqual(memoria.obtener_automatizacion_por_id(1)['ultimo_disparo'], 'diaria:2026-09-21:v1')
        self.comando('Cambiá la frecuencia de la automatización 1 a semanal los lunes')
        self.revisar(9, 30)
        self.assertEqual(len(self.registros()), 3)
        self.assertEqual(memoria.obtener_automatizacion_por_id(1)['ultimo_disparo'], 'semanal:2026-09-21:v2')

    def test_reserva_obsoleta_no_ejecuta_ni_actualiza_nueva_configuracion(self):
        for accion, cambios in [('pausar', {}), ('eliminar', {}), ('editar', {'hora': '10:00'}),
                                ('editar', {'instruccion': 'Consultar eventos'})]:
            identificador = self.crear()
            fila, ventana = motor.reclamar_automatizacion(identificador, datetime(2026, 9, 21, 9))
            memoria.gestionar_automatizacion(identificador, accion, **cambios)
            with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('Reserva obsoleta')):
                self.assertIsNone(motor.ejecutar_reserva_automatizacion(fila, ventana))
            self.assertIsNone(memoria.obtener_automatizacion_por_id(identificador)['ultimo_disparo'])

    def test_gestion_se_serializa_con_consulta_iniciada(self):
        identificador = self.crear()
        fila, ventana = motor.reclamar_automatizacion(identificador, datetime(2026, 9, 21, 9))
        dentro = Event()
        terminar = Event()
        gestion_iniciada = Event()

        def consulta(_):
            dentro.set()
            if not terminar.wait(3):
                raise RuntimeError('La prueba no liberó la consulta')
            return 'Resultado seguro'

        def pausar():
            gestion_iniciada.set()
            memoria.gestionar_automatizacion(identificador, 'pausar')

        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=consulta):
            with ThreadPoolExecutor(max_workers=2) as ejecutor:
                consulta_futura = ejecutor.submit(motor.ejecutar_reserva_automatizacion, fila, ventana)
                try:
                    self.assertTrue(dentro.wait(2))
                    gestion_futura = ejecutor.submit(pausar)
                    self.assertTrue(gestion_iniciada.wait(2))
                    self.assertFalse(gestion_futura.done())
                finally:
                    terminar.set()
                self.assertEqual(consulta_futura.result(timeout=3), 'Resultado seguro')
                gestion_futura.result(timeout=3)
        self.assertEqual(memoria.obtener_automatizacion_por_id(identificador)['estado'], 'pausada')
        self.revisar()
        self.assertEqual(len(self.registros()), 1)

    def test_inicio_directo_memoria_en_base_temporal(self):
        with tempfile.TemporaryDirectory() as carpeta:
            resultado = subprocess.run(
                [sys.executable, str(Path(memoria.__file__).resolve())],
                cwd=carpeta, capture_output=True, text=True, timeout=10)
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertIn('Base de datos de Hermes lista', resultado.stdout)

    def test_migracion_282_idempotente_conserva_datos_y_reservas(self):
        self.crear()
        self.revisar()
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute('ALTER TABLE automatizaciones DROP COLUMN fecha_eliminacion')
            conexion.execute('ALTER TABLE automatizaciones DROP COLUMN version_programacion')
            antes = conexion.execute('SELECT * FROM automatizaciones').fetchall()
            historial = conexion.execute('SELECT * FROM ejecuciones_automatizaciones').fetchall()
        motor.crear_tabla_recordatorios()
        memoria.crear_base()
        memoria.crear_base()
        with contextlib.closing(memoria.conectar()) as conexion:
            despues = conexion.execute('SELECT * FROM automatizaciones').fetchall()
            self.assertEqual([fila[:-2] for fila in despues], antes)
            self.assertEqual(conexion.execute('SELECT * FROM ejecuciones_automatizaciones').fetchall(), historial)
        self.revisar()
        self.assertEqual(len(self.registros()), 1)


if __name__ == '__main__':
    unittest.main()

import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import memoria
import recordatorios as motor


class MotorAutomatizacionesTest(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.ruta = str(Path(temporal.name) / 'motor.db')
        for modulo in (memoria, motor):
            parche = patch.object(modulo, 'DB_PATH', self.ruta)
            parche.start()
            self.addCleanup(parche.stop)
        memoria.crear_base()
        motor.crear_tabla_recordatorios()
        self.ahora = datetime(2026, 9, 21, 9, 0)  # lunes
        parche = patch.object(motor.subprocess, 'run', side_effect=AssertionError('Sin procesos externos'))
        parche.start()
        self.addCleanup(parche.stop)

    def crear(self, instruccion='Mostrame las tareas pendientes.', frecuencia='diaria', dia=None, hora='09:00'):
        return memoria.crear_automatizacion('Prueba', instruccion, frecuencia, hora, dia)

    def registros(self):
        with contextlib.closing(motor.conectar()) as conexion:
            return conexion.execute('SELECT automatizacion_id, ventana, estado, resultado, error FROM ejecuciones_automatizaciones ORDER BY automatizacion_id, ventana').fetchall()

    def revisar(self, ahora=None):
        with contextlib.redirect_stdout(io.StringIO()):
            motor.revisar_automatizaciones(ahora or self.ahora)

    def test_diaria_ventana_reinicio_y_siguiente_dia(self):
        identificador = self.crear()
        self.revisar(self.ahora - timedelta(seconds=1))
        self.assertEqual(self.registros(), [])
        self.revisar()
        self.revisar(self.ahora + timedelta(seconds=15))
        motor.crear_tabla_recordatorios()  # reinicio conserva las reservas
        self.revisar()
        self.assertEqual(len(self.registros()), 1)
        self.assertEqual(self.registros()[0][2], 'correcta')
        self.assertEqual(memoria.obtener_automatizacion_por_id(identificador)['ultimo_disparo'], 'diaria:2026-09-21')
        self.revisar(self.ahora + timedelta(days=1, seconds=301))
        self.assertEqual(len(self.registros()), 1)
        self.revisar(self.ahora + timedelta(days=2, seconds=300))
        self.assertEqual(len(self.registros()), 2)

    def test_semanal_pausada_y_medianoche(self):
        semanal = self.crear(frecuencia='semanal', dia='lunes', hora='23:59')
        pausada = self.crear()
        with contextlib.closing(motor.conectar()) as conexion, conexion:
            conexion.execute("UPDATE automatizaciones SET estado='pausada' WHERE id=?", (pausada,))
        self.revisar()
        self.assertEqual(self.registros(), [])
        self.revisar(datetime(2026, 9, 22, 0, 1))
        self.assertEqual(self.registros()[0][:3], (semanal, 'semanal:2026-09-21', 'correcta'))
        self.revisar(datetime(2026, 9, 23, 0, 1))
        self.assertEqual(len(self.registros()), 1)

    def test_rechazo_y_error_no_interrumpen_ni_reintentan(self):
        malo = self.crear('Mostrame las tareas pendientes y borrá todas las notas')
        bueno = self.crear()
        with self.assertLogs('hermes.automatizaciones', level='ERROR'):
            self.revisar()
        self.revisar()
        self.assertEqual([fila[2] for fila in self.registros()], ['error', 'correcta'])
        self.assertIsNone(memoria.obtener_automatizacion_por_id(malo)['ultimo_disparo'])
        self.assertIsNotNone(memoria.obtener_automatizacion_por_id(bueno)['ultimo_disparo'])
        self.assertIn('no permitida', self.registros()[0][4])
        self.crear()
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=RuntimeError('fallo simulado')):
            with self.assertLogs('hermes.automatizaciones', level='ERROR'):
                self.revisar()
        self.assertEqual(self.registros()[-1][4], 'fallo simulado')

    def test_reserva_concurrente_y_caida_sin_doble_disparo(self):
        identificador = self.crear()
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            reservas = list(ejecutor.map(lambda _: motor.reclamar_automatizacion(identificador, self.ahora), range(2)))
        self.assertEqual(sum(reserva is not None for reserva in reservas), 1)
        # Simular caída luego de reservar: queda en_curso y no vuelve a ejecutarse.
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('Duplicado')):
            self.revisar()
        self.assertEqual(self.registros()[0][2], 'en_curso')
        self.assertIsNone(memoria.obtener_automatizacion_por_id(identificador)['ultimo_disparo'])

    def test_consultas_solo_lectura(self):
        memoria.crear_tarea('Tarea conservada', '', None)
        memoria.crear_nota('Nota conservada', 'Contenido')
        with contextlib.closing(motor.conectar()) as conexion:
            antes = list(conexion.iterdump())
        for instruccion, esperado in [
            ('Mostrame las tareas pendientes.', 'Tarea conservada'),
            ('Consultar notas', 'Contenido'),
            ('Consultar eventos', 'Sin resultados'),
            ('Mostrar resumen diario', 'Tarea conservada'),
        ]:
            self.assertIn(esperado, motor.resolver_instruccion_automatizacion(instruccion))
        for instruccion in ('Borrá las tareas', 'Editar notas', 'ejecutar rm -rf /',
                            'Mostrar eventos; borrar notas', 'Buscá en la web'):
            with self.assertRaises(ValueError):
                motor.resolver_instruccion_automatizacion(instruccion)
        with contextlib.closing(motor.conectar()) as conexion:
            self.assertEqual(antes, list(conexion.iterdump()))

    def test_error_base_se_registra_y_motor_integra_todos_los_servicios(self):
        with patch.object(motor, 'conectar', side_effect=RuntimeError('base no disponible')):
            with self.assertLogs('hermes.automatizaciones', level='ERROR'):
                self.revisar()
        nombres = ['materializar_proximos_eventos_recurrentes', 'revisar_resumen_diario',
                   'revisar_resumen_nocturno', 'revisar_recordatorios', 'revisar_rutinas',
                   'revisar_automatizaciones']
        with contextlib.ExitStack() as pila:
            funciones = [pila.enter_context(patch.object(motor, nombre)) for nombre in nombres]
            pila.enter_context(patch.object(motor.time, 'sleep', side_effect=KeyboardInterrupt))
            pila.enter_context(contextlib.redirect_stdout(io.StringIO()))
            motor.ejecutar_motor()
        for funcion in funciones:
            funcion.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()

import contextlib
from datetime import datetime, timedelta
import io
import unittest
from unittest.mock import patch

import memoria
import recordatorios as motor
import test_automatizaciones


class AuditoriaAutomatizacionesTest(unittest.TestCase):
    setUp = test_automatizaciones.AutomatizacionesTest.setUp

    def crear(self, instruccion='Consultar notas'):
        return memoria.crear_automatizacion('Auditoría', instruccion, 'diaria', datetime.now().strftime('%H:%M'))

    def revisar(self):
        with contextlib.redirect_stdout(io.StringIO()):
            motor.revisar_automatizaciones()

    def datos(self):
        with contextlib.closing(memoria.conectar()) as conexion:
            return list(conexion.iterdump())

    def test_comando_local_correcto_y_solo_lectura(self):
        self.crear()
        self.revisar()
        antes = self.datos()
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('Auditar no ejecuta')):
            informe = self.comando('Auditá las automatizaciones')
        self.assertIn('Auditoría correcta', informe)
        self.assertIn('doble disparo: activa', informe)
        self.assertEqual(self.datos(), antes)

    def test_pausadas_y_eliminadas_no_ejecutan(self):
        pausada, eliminada = self.crear(), self.crear()
        memoria.gestionar_automatizacion(pausada, 'pausar')
        memoria.gestionar_automatizacion(eliminada, 'eliminar')
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('No debe ejecutar')):
            self.revisar()
        informe = motor.auditar_automatizaciones()
        self.assertEqual(informe['errores'], [])
        self.assertEqual(informe['ejecuciones'], 0)

    def test_destructivas_bloqueadas_y_error_aislado(self):
        memoria.crear_tarea('Conservar', '', None)
        instrucciones = ['Borrá el archivo prueba.txt', 'Editá el archivo prueba.txt',
                         'Eliminá todas las tareas', 'Eliminá los eventos', 'Modificá mis datos',
                         'Ejecutá shell: rm -rf .', 'Buscá en la web', 'Leer https://example.com',
                         'Consultar notas; borrar tareas', 'Mostrar resumen diario\ny eliminar eventos']
        for instruccion in instrucciones:
            self.crear(instruccion)
        buena = self.crear('Mostrame las tareas pendientes.')
        tareas = memoria.obtener_tareas_pendientes()
        with patch.object(motor.subprocess, 'run', side_effect=AssertionError('Sin shell')):
            with self.assertLogs('hermes.automatizaciones', level='ERROR'):
                self.revisar()
        self.assertEqual(memoria.obtener_tareas_pendientes(), tareas)
        self.assertIsNotNone(memoria.obtener_automatizacion_por_id(buena)['ultimo_disparo'])
        informe = motor.auditar_automatizaciones()
        self.assertEqual(informe['errores'], [])
        self.assertEqual(informe['errores_registrados'], len(instrucciones))
        self.assertEqual(informe['ejecuciones'], len(instrucciones) + 1)
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('Doble disparo')):
            self.revisar()
        self.assertEqual(motor.auditar_automatizaciones()['ejecuciones'], len(instrucciones) + 1)

    def test_configuraciones_duplicadas_aviso_no_reparacion(self):
        self.crear('Consultar notas')
        self.crear('Mostrame las notas.')
        antes = self.datos()
        informe = motor.auditar_automatizaciones()
        self.assertEqual(informe['errores'], [])
        self.assertTrue(any('misma consulta' in aviso for aviso in informe['advertencias']))
        self.assertEqual(antes, self.datos())

    def test_esquema_incompleto_y_pk_ausente_bloquean_motor(self):
        self.crear()
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute('ALTER TABLE ejecuciones_automatizaciones RENAME TO ejecuciones_originales')
            conexion.execute('CREATE TABLE ejecuciones_automatizaciones AS SELECT * FROM ejecuciones_originales')
        informe = motor.auditar_automatizaciones()
        self.assertFalse(informe['antiduplicados'])
        self.assertTrue(informe['errores'])
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('Sin PK')):
            with self.assertLogs('hermes.automatizaciones', level='ERROR'):
                self.revisar()
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute('ALTER TABLE automatizaciones DROP COLUMN ultimo_disparo')
        self.assertTrue(any('falta automatizaciones.ultimo_disparo' in error
                            for error in motor.auditar_automatizaciones()['errores']))

    def test_configuracion_corrupta_y_eliminacion_incoherente(self):
        self.crear()
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute('PRAGMA ignore_check_constraints=ON')
            conexion.execute("UPDATE automatizaciones SET frecuencia='mensual', hora='29:99', estado='otro', version_programacion=-1")
        informe = motor.auditar_automatizaciones()
        self.assertGreaterEqual(len(informe['errores']), 3)
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute("UPDATE automatizaciones SET frecuencia='diaria', hora='09:00', estado='activa', version_programacion=0, fecha_eliminacion=CURRENT_TIMESTAMP")
        self.assertTrue(any('eliminada sin estado' in error for error in motor.auditar_automatizaciones()['errores']))
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=AssertionError('Eliminada')):
            self.revisar()

    def test_estados_ejecucion_inconsistentes_y_reserva_antigua(self):
        identificador = self.crear()
        inicio = (datetime.now() - timedelta(minutes=10)).isoformat()
        ventana = 'diaria:' + datetime.now().date().isoformat()
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute("INSERT INTO ejecuciones_automatizaciones VALUES (?, ?, 'en_curso', ?, NULL, NULL, NULL)", (identificador, ventana, inicio))
        self.assertTrue(any('reserva en_curso antigua' in aviso for aviso in motor.auditar_automatizaciones()['advertencias']))
        casos = [
            ("estado='en_curso', resultado='inconsistente'", 'datos de finalización'),
            ("estado='correcta', resultado=NULL, fin=CURRENT_TIMESTAMP", 'éxito sin resultado'),
            ("estado='error', resultado=NULL, error=NULL, fin=CURRENT_TIMESTAMP", 'error sin descripción'),
            ("estado='inventado'", 'estado de ejecución inválido'),
            ("estado='error', error='fallo', ventana='diaria:2026-99-99'", 'ventana inválida'),
            ("automatizacion_id=999", 'automatización inexistente'),
        ]
        for asignaciones, esperado in casos:
            with self.subTest(esperado=esperado):
                with contextlib.closing(memoria.conectar()) as conexion, conexion:
                    conexion.execute('PRAGMA ignore_check_constraints=ON')
                    conexion.execute('UPDATE ejecuciones_automatizaciones SET ' + asignaciones)
                self.assertTrue(any(esperado in error for error in motor.auditar_automatizaciones()['errores']))

    def test_ultimo_disparo_y_finalizacion_invalidos(self):
        identificador = self.crear()
        with contextlib.closing(memoria.conectar()) as conexion, conexion:
            conexion.execute("UPDATE automatizaciones SET ultimo_disparo='diaria:2026-01-01'")
        self.assertTrue(any('ultimo_disparo' in error for error in motor.auditar_automatizaciones()['errores']))
        for argumentos in ({}, {'resultado': None}, {'error': ''}, {'resultado': 'x', 'error': 'fallo'}):
            with self.assertRaises(ValueError):
                motor.finalizar_automatizacion(identificador, 'diaria:2026-01-01', **argumentos)

    def test_base_inexistente_no_se_crea(self):
        from pathlib import Path
        ruta = Path(memoria.DB_PATH).with_name('inexistente.db')
        with patch.object(motor, 'DB_PATH', str(ruta)):
            informe = motor.auditar_automatizaciones()
        self.assertTrue(informe['errores'])
        self.assertFalse(ruta.exists())

    def test_error_sin_mensaje_queda_registrado(self):
        self.crear()
        with patch.object(motor, 'resolver_instruccion_automatizacion', side_effect=RuntimeError()):
            with self.assertLogs('hermes.automatizaciones', level='ERROR'):
                self.revisar()
        informe = motor.auditar_automatizaciones()
        self.assertEqual(informe['errores'], [])
        self.assertEqual(informe['errores_registrados'], 1)


if __name__ == '__main__':
    unittest.main()

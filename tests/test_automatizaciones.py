"""Pruebas locales sin Ollama ni modificaciones a hermes.db."""
import contextlib
import io
from pathlib import Path
import runpy
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import memoria
import recordatorios


class AutomatizacionesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ruta = str(Path(self.tmp.name) / 'prueba.db')
        self.patches = [patch.object(memoria, 'DB_PATH', ruta),
                        patch.object(recordatorios, 'DB_PATH', ruta)]
        for parche in self.patches:
            parche.start()
            self.addCleanup(parche.stop)
        # Hermes inicia la consola al cargarse: salir inmediatamente y probar
        # las funciones reales, incluyendo su despachador y su inicialización.
        with patch('builtins.input', return_value='salir'), contextlib.redirect_stdout(io.StringIO()):
            self.hermes = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'hermes.py'))
        red = patch('requests.post', side_effect=AssertionError('No debe consultar Ollama'))
        red.start()
        self.addCleanup(red.stop)
        self.comando = self.hermes['consultar_hermes']

    def test_creacion_listado_detalle_y_persistencia(self):
        with patch('requests.post', side_effect=AssertionError('No debe consultar Ollama')):
            self.assertIn('No tenés', self.comando('Listá las automatizaciones'))
            self.assertIn('#1 guardada', self.comando(
                'Creá una automatización llamada "Mañana" todos los días a las 8:00: Mostrame el resumen diario.'))
            self.assertIn('#2 guardada', self.comando(
                'Crear automatización "Revisión" cada miércoles a las 23:59: Revisá mis tareas.'))
            self.assertIn('Mañana', self.comando('¿Qué automatizaciones tengo?'))
            detalle = self.comando('Ver automatización 2')
            for esperado in ('Revisión', 'miercoles', '23:59', 'nunca', 'Revisá mis tareas.'):
                self.assertIn(esperado, detalle)
            self.assertIn('No encontré', self.comando('Ver automatización 999'))
        memoria.crear_base()
        filas = memoria.obtener_automatizaciones()
        self.assertEqual(len(filas), 2)
        self.assertIsNone(filas[0]['dia_semana'])
        self.assertEqual(filas[0]['hora'], '08:00')
        self.assertTrue(filas[0]['fecha_creacion'])
        self.assertIsNone(filas[0]['ultimo_disparo'])

    def test_rechaza_configuracion_invalida(self):
        for horario in ('24:00', '12:60', '09:99'):
            self.comando(f'Creá automatización "X" diaria a las {horario}: resumen')
        for recurrencia in ('mensual', 'semanal', 'cada lunes y martes'):
            self.comando(f'Creá automatización "X" {recurrencia} a las 09:00: resumen')
        self.comando('Creá una automatización')
        self.comando('Creá automatización " " diaria a las 09:00: resumen')
        self.assertEqual(memoria.obtener_automatizaciones(), [])
        for args in [('X', '', 'diaria', '09:00', None),
                     ('X', 'Y', 'diaria', '9:00', None),
                     ('X', 'Y', 'semanal', '09:00', None),
                     ('X', 'Y', 'diaria', '09:00', 'lunes')]:
            with self.assertRaises(ValueError):
                memoria.crear_automatizacion(*args)
        with contextlib.closing(memoria.conectar()) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO automatizaciones(nombre,instruccion,frecuencia,hora) VALUES ('X','Y','semanal','09:00')")

    def test_instrucciones_son_datos_y_no_acciones(self):
        memoria.crear_tarea('Conservar', 'Descripción', None)
        antes = memoria.obtener_tareas_pendientes()
        self.comando('Creá automatización "Borrado" diaria a las 00:00: Borrá todas las tareas y eliminá el archivo prueba.txt')
        self.assertEqual(memoria.obtener_tareas_pendientes(), antes)
        self.assertEqual(len(memoria.obtener_automatizaciones()), 1)
        self.assertIsNone(memoria.obtener_automatizacion_por_id(1)['ultimo_disparo'])
        self.assertEqual(memoria.obtener_rutinas(), [])
        self.assertEqual(recordatorios.obtener_recordatorios_pendientes(), [])
        for orden in ('Auditá', 'Ejecutá'):
            self.assertIn('no disponibles', self.comando(f'{orden} la automatización 1'))
        self.assertEqual(len(memoria.obtener_automatizaciones()), 1)

    def test_comandos_existentes_y_migracion(self):
        self.comando('Creá una nota: conservar esta nota')
        self.assertEqual(len(memoria.obtener_notas_activas()), 1)
        antes = memoria.obtener_notas_activas()
        memoria.crear_base()
        self.assertEqual(memoria.obtener_notas_activas(), antes)
        self.assertIsNone(self.hermes['procesar_comando_automatizaciones']('Mostrame mis tareas'))
        self.assertIsNone(self.hermes['procesar_comando_automatizaciones']('Creá una rutina todos los días a las 09:00'))


if __name__ == '__main__':
    unittest.main()

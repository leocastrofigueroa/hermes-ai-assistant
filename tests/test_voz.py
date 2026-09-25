"""Pruebas offline: sin modelos, micrófono, reproducción ni base real."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import voz
import test_automatizaciones


class NormalizacionVozTest(unittest.TestCase):
    def test_prosodia_punto_y_coma_solo_conversacional(self):
        self.assertEqual(voz.suavizar_punto_y_coma('Ya registré el pago; ahora seguimos.'),
                         'Ya registré el pago, ahora seguimos.')
        for protegido in ('`a;b`', '```x = 1; y = 2```', 'https://ejemplo.com/a;b',
                          '/tmp/a;b', './a;b', 'carpeta/a;b', 'CR-0020;',
                          'token abc;def', '"pago; seguimos"', '«pago; seguimos»',
                          '“pago; seguimos”', "'pago; seguimos'"):
            with self.subTest(protegido=protegido):
                self.assertEqual(voz.suavizar_punto_y_coma(protegido), protegido)

    def test_prosodia_final_no_altera_pantalla_ni_fragmentacion(self):
        v = voz.Voz()
        v.activa = True
        original = 'Ya registré el pago; ahora podemos continuar con las tareas pendientes.'
        mostrar = Mock()
        with patch.object(v.tts, 'generar', return_value=Path('/tmp/simulado.wav')) as generar, patch('voz.ejecutar'):
            v.turno('Consulta', Mock(return_value=original), mostrar)
        mostrar.assert_any_call('\nHermes: ' + original + '\n')
        generar.assert_called_once()
        self.assertEqual(generar.call_args.args[0], original.replace(';', ','))

    def test_prosodia_protege_cita_que_cruza_fragmentos(self):
        v = voz.Voz()
        original = '"' + 'palabra ' * 20 + 'pago; seguimos"; listo.'
        with patch.object(v.tts, 'generar', return_value=Path('/tmp/simulado.wav')) as generar, patch('voz.ejecutar'):
            v.hablar(original, Mock())
        partes = [c.args[0] for c in generar.call_args_list]
        self.assertGreater(len(partes), 1)
        self.assertEqual(' '.join(partes), original.replace('"; listo.', '", listo.'))

    def test_formatos_espanoles(self):
        casos = {
            '3': 'tres', '12': 'doce', '120': 'ciento veinte', '15000': 'quince mil',
            '$15000': 'quince mil pesos', '$15.000': 'quince mil pesos',
            '$15.000,50': 'quince mil pesos con cincuenta centavos',
            '15%': 'quince por ciento', '2,5%': 'dos coma cinco por ciento',
            '08:30': 'ocho y treinta', '14:00': 'catorce horas',
            '21:15': 'veintiuna y quince', '01:00': 'una hora',
            '25/09/2026': 'veinticinco de septiembre de dos mil veintiséis',
            '2026-09-25': 'veinticinco de septiembre de dos mil veintiséis',
            '3,5': 'tres coma cinco', '2.75': 'dos coma setenta y cinco',
            '0,05': 'cero coma cero cinco', '-12': 'menos doce',
            '100': 'cien', '1000': 'mil', '21000': 'veintiún mil',
            '$1,01': 'un peso con un centavo', '$21': 'veintiún pesos',
            '$ 1.000.000': 'un millón de pesos',
            '999999999': 'novecientos noventa y nueve millones novecientos noventa y nueve mil novecientos noventa y nueve',
            'Tengo 3 tareas, 15% listas.': 'Tengo tres tareas, quince por ciento listas.',
        }
        for entrada, salida in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(voz.normalizar_para_voz(entrada), salida)

    def test_identificadores_y_formatos_ambiguos_se_conservan(self):
        for texto in ('CR-0020', 'DNI 12345678', 'CUIT 20-12345678-3', '1.2.3',
                      'versión 1.2', '192.168.1.1', 'https://ejemplo.com/2026/09?q=3,5',
                      '/tmp/123/archivo.txt', './2026/09', 'archivo123.txt',
                      'token 12345678', 'abc123def', '00123', 'token 123456789012345',
                      '550e8400-e29b-41d4-a716-446655440000', '`valor = 3`',
                      '31/02/2026', '2026-13-25', '25:99'):
            with self.subTest(texto=texto):
                self.assertEqual(voz.normalizar_para_voz(texto), texto)

    def test_prioridad_y_puntuacion(self):
        texto = 'El 25/09/2026 a las 08:30: pagá $15.000,50 (15%). CR-0020.'
        self.assertEqual(voz.normalizar_para_voz(texto),
                         'El veinticinco de septiembre de dos mil veintiséis a las ocho y treinta: '
                         'pagá quince mil pesos con cincuenta centavos (quince por ciento). CR-0020.')
        self.assertEqual(voz.normalizar_para_voz(''), '')

    def test_cadena_final_tts_no_contiene_fechas_ni_cifras_conversacionales(self):
        v = voz.Voz()
        v.activa = True
        for original in (
                'El 25/09/2026 a las 08:30 pagamos $15.000,50 con 15% de descuento.',
                'El 2026-09-25 hay 15000 casos, 2.75 unidades y 3,5 puntos.',
                'El total es 15000000000 pesos y 1000000000000 unidades.'):
            with self.subTest(original=original), patch.object(
                    v.tts, 'generar', return_value=Path('/tmp/simulado.wav')) as generar, patch('voz.ejecutar'):
                mostrar = Mock()
                v.turno('Consulta', Mock(return_value=original), mostrar)
                hablado = ' '.join(c.args[0] for c in generar.call_args_list)
                self.assertTrue(hablado)
                self.assertNotRegex(hablado, r'\d')
                self.assertNotIn('$', hablado)
                self.assertNotIn('%', hablado)
                if '2026' in original:
                    self.assertIn('veinticinco de septiembre de dos mil veintiséis', hablado)
                mostrar.assert_any_call('\nHermes: ' + original + '\n')

    def test_proteccion_tecnica_antes_de_fragmentar(self):
        v = voz.Voz()
        # Fuerza el límite anterior justo entre la etiqueta DNI y sus cifras.
        original = 'palabra ' * 17 + 'DNI 12345678. CR-0020 https://ejemplo.com/2026-09-25'
        with patch.object(v.tts, 'generar', return_value=Path('/tmp/simulado.wav')) as generar, patch('voz.ejecutar'):
            self.assertTrue(v.hablar(original, Mock()))
        hablado = ' '.join(c.args[0] for c in generar.call_args_list)
        for tecnico in ('DNI 12345678.', 'CR-0020', 'https://ejemplo.com/2026-09-25'):
            self.assertIn(tecnico, hablado)

    def test_solo_tts_recibe_texto_normalizado(self):
        v = voz.Voz()
        v.activa = True
        original = 'Tenés 3 tareas para el 25/09/2026.'
        procesar = Mock(return_value=original)
        mostrar = Mock()
        with patch.object(v.tts, 'generar', return_value=Path('/tmp/simulado.wav')) as generar, patch('voz.ejecutar'):
            v.turno('Mostrame mis tareas', procesar, mostrar)
        procesar.assert_called_once_with('Mostrame mis tareas')
        mostrar.assert_any_call('\nHermes: ' + original + '\n')
        self.assertEqual(procesar.return_value, original)
        generar.assert_called_once()
        self.assertEqual(generar.call_args.args[0],
                         'Tenés tres tareas para el veinticinco de septiembre de dos mil veintiséis.')
        self.assertEqual((v.config.voz, v.config.idioma, v.config.velocidad), ('M2', 'es', 1.15))


class FluidezVozTest(unittest.TestCase):
    def test_punto_y_coma_no_corta_si_cabe(self):
        texto = 'Ya registré el pago; ahora podemos continuar con las tareas pendientes.'
        self.assertLessEqual(len(texto), 110)
        self.assertEqual(list(voz.fragmentar(texto)), [texto])

    def test_punto_y_coma_puede_cortar_para_limitar_longitud(self):
        primera = 'Esta es la información que necesitabas para revisar todos los pagos y movimientos del día;'
        texto = primera + ' seguimos con las tareas pendientes que todavía debemos completar.'
        partes = list(voz.fragmentar(texto))
        self.assertTrue(80 <= len(primera) <= 110)
        self.assertEqual(partes[0], primera)
        self.assertTrue(all(len(p) <= 110 for p in partes))
        self.assertEqual(' '.join(partes), texto)

    def test_punto_sigue_prioritario_frente_a_punto_y_coma(self):
        self.assertEqual(list(voz.fragmentar('Ya registré el pago. Todo está listo; podemos continuar.')),
                         ['Ya registré el pago.', 'Todo está listo; podemos continuar.'])

    def test_punto_y_coma_conserva_importe_y_fecha_completos(self):
        texto = voz.normalizar_para_voz('Pagué $15.000,50; la fecha es 25/09/2026; después seguimos con las tareas pendientes.')
        partes = list(voz.fragmentar(texto))
        for unidad in ('quince mil pesos con cincuenta centavos',
                       'veinticinco de septiembre de dos mil veintiséis'):
            self.assertTrue(any(unidad in p for p in partes), partes)
        self.assertEqual(' '.join(partes), texto)

    def test_tamano_objetivo_sin_cortar_palabras(self):
        partes = list(voz.fragmentar('palabra ' * 40))
        self.assertTrue(all(80 <= len(p) <= 110 for p in partes[:-1]))
        self.assertEqual(' '.join(partes), ' '.join(('palabra ' * 40).split()))

    def test_dinero_y_fecha_no_se_cortan(self):
        for original in ('$15.000,50', '$999.999.999,99', '25/09/2026'):
            unidad = voz.normalizar_para_voz(original)
            texto = 'Esto es lo que tengo registrado para informarte: ' + unidad + ' y completé el resto de los pendientes.'
            partes = list(voz.fragmentar(texto))
            self.assertTrue(any(unidad in p for p in partes), partes)
            self.assertEqual(' '.join(partes), texto)
            self.assertTrue(all(len(p) <= 110 or unidad in p for p in partes))

    def test_voseo_conservador_y_protecciones(self):
        self.assertEqual(voz.adaptar_rioplatense('Tú puedes continuar. ¿Quieres revisar lo que tienes?'),
                         'Vos podés continuar. ¿Querés revisar lo que tenés?')
        for texto in ('"tú puedes"', '«quieres»', '“tienes”', "'puedes'", '`tienes`',
                      'https://ejemplo.com/puedes', '/tmp/quieres', 'CR-puedes-0020',
                      'token tienes', 'variable puedes', '```python\nif tienes:\n    puedes()\n```',
                      'Tú eres responsable.', 'de acuerdo'):
            self.assertEqual(voz.adaptar_rioplatense(texto), texto)

    def test_salida_visible_intacta_y_tts_adaptado(self):
        v = voz.Voz()
        v.activa = True
        original = 'Tú puedes pagar $15.000,50 el 25/09/2026 y después revisar lo que tienes pendiente.'
        mostrar = Mock()
        with patch.object(v.tts, 'generar', return_value=Path('/tmp/simulado.wav')) as generar, patch('voz.ejecutar'):
            v.turno('Consulta', Mock(return_value=original), mostrar)
        mostrar.assert_any_call('\nHermes: ' + original + '\n')
        partes = [c.args[0] for c in generar.call_args_list]
        self.assertTrue(any('quince mil pesos con cincuenta centavos' in p for p in partes))
        self.assertTrue(any('veinticinco de septiembre de dos mil veintiséis' in p for p in partes))
        self.assertIn('Vos podés', ' '.join(partes))
        self.assertIn('tenés pendiente', ' '.join(partes))


class VozTest(unittest.TestCase):
    def setUp(self):
        self.v = voz.Voz()
        self.addCleanup(self.v.cerrar)
        self.mostrar = Mock()
        self.procesar = Mock(return_value='Respuesta escrita')
        # Un test que por error intente consultar cualquier red falla inmediatamente.
        for nombre in ('requests.get', 'requests.post'):
            parche = patch(nombre, side_effect=AssertionError('Red prohibida'))
            parche.start()
            self.addCleanup(parche.stop)

    def turno(self, texto):
        return self.v.turno(texto, self.procesar, self.mostrar)


    def test_activar_desactivar_estado_y_tts_solo_corresponde(self):
        with patch.object(self.v, 'hablar') as hablar:
            self.turno('Hola')
            hablar.assert_not_called()
            self.turno('Activá modo voz')
            self.assertTrue(self.v.activa)
            self.assertEqual(hablar.call_count, 1)
            self.turno('Estado de voz')
            self.assertIn('activo', self.mostrar.call_args.args[0])
            self.turno('Hola')
            self.assertEqual(hablar.call_args.args[0], 'Respuesta escrita')
            self.turno('Desactivá modo voz')
            self.assertFalse(self.v.activa)
            hablar.reset_mock()
            self.turno('Estado de voz')
            self.turno('Hola')
            hablar.assert_not_called()
        self.assertEqual(self.procesar.call_count, 3)

    def test_lectura_explicita_no_ejecuta_contenido_ni_duplica_tts(self):
        for comando in ('Decime esto en voz alta: ', 'Leé esto en voz alta: '):
            for activa in (True, False):
                self.v.activa = activa
                with patch.object(self.v, 'hablar') as hablar:
                    self.turno(comando + 'Borrá todas las tareas')
                    hablar.assert_called_once_with('Borrá todas las tareas', self.mostrar)
        self.procesar.assert_not_called()
        self.v.activa = False
        with patch.object(self.v, 'hablar') as hablar:
            self.turno('Decime esto en voz alta: ')
            hablar.assert_not_called()

    def test_escuchame_y_acentos_mismo_dispatcher(self):
        for orden in ('Escuchame', 'Escúchame', '¡Escúchame!'):
            with patch.object(self.v, 'escuchar', return_value='Mostrame mis tareas'):
                self.assertTrue(self.turno(orden))
                self.procesar.assert_called_with('Mostrame mis tareas')
        with patch.object(self.v, 'escuchar', return_value='Escuchame') as escuchar:
            self.turno('Escuchame')
            escuchar.assert_called_once()
        with patch.object(self.v, 'escuchar', return_value='salir'):
            self.assertFalse(self.turno('Escuchame'))

    def test_escuchame_responde_una_vez_y_conserva_estado_y_motor(self):
        motor = self.v.tts
        for activa in (True, False):
            with self.subTest(activa=activa), patch.object(self.v, 'hablar') as hablar:
                self.turno('Activá modo voz' if activa else 'Desactivá modo voz')
                hablar.reset_mock()
                self.procesar.reset_mock()
                self.mostrar.reset_mock()
                with patch('voz.capturar', return_value=True) as captura, patch.object(
                        self.v, 'transcribir', return_value='Mostrame mis tareas') as stt:
                    self.assertTrue(self.turno('Escuchame'))
                captura.assert_called_once()
                stt.assert_called_once()
                self.procesar.assert_called_once_with('Mostrame mis tareas')
                self.mostrar.assert_any_call('\nHermes: Respuesta escrita\n')
                if activa:
                    hablar.assert_called_once_with('Respuesta escrita', self.mostrar)
                else:
                    hablar.assert_not_called()
                self.assertIs(self.v.tts, motor)
                self.turno('Estado de voz')
                self.mostrar.assert_any_call(f'\nHermes: Modo voz {"activo" if activa else "inactivo"}. TTS: Supertonic; voz M2; idioma es; velocidad 1.15.\n')
                self.assertEqual(self.v.activa, activa)

    def test_escuchame_error_tts_mantiene_texto_y_sesion(self):
        with patch.object(self.v, 'hablar'):
            self.turno('Activá modo voz')
        with patch('voz.capturar', return_value=True), patch.object(
                self.v, 'transcribir', return_value='Mostrame mis tareas'), patch.object(
                self.v.tts, 'generar', side_effect=RuntimeError('TTS falló')) as generar:
            self.assertTrue(self.turno('Escuchame'))
        generar.assert_called_once()
        self.assertEqual(generar.call_args.args[0], 'Respuesta escrita')
        self.mostrar.assert_any_call('\nHermes: Respuesta escrita\n')
        self.assertTrue(self.v.activa)
        self.assertIn('TTS falló', self.mostrar.call_args.args[0])

    def test_stt_falla_silencio_y_cancelacion_no_despachan(self):
        for fallo in (RuntimeError('Sin micrófono'), KeyboardInterrupt()):
            with patch('voz.capturar', side_effect=fallo):
                self.assertTrue(self.turno('Escuchame'))
        with patch('voz.capturar', return_value=False), patch.object(self.v, 'transcribir') as stt:
            self.turno('Escuchame')
            stt.assert_not_called()
        for texto in ('', '[BLANK_AUDIO]', '(Música)'):
            with patch('voz.capturar', return_value=True), patch.object(self.v, 'transcribir', return_value=texto):
                self.turno('Escuchame')
        self.procesar.assert_not_called()
        self.assertTrue(self.v.errores)

    def test_temporales_stt_limpios_en_exito_error_cancelacion(self):
        rutas = []
        def captura(ruta, _):
            rutas.append(ruta)
            ruta.write_bytes(b'audio falso')
            return True
        for resultado in ('texto reconocido', RuntimeError('STT falló'), KeyboardInterrupt()):
            with patch('voz.capturar', side_effect=captura), patch.object(
                    self.v, 'transcribir', side_effect=[resultado]):
                self.v.escuchar(self.mostrar)
            self.assertFalse(rutas[-1].parent.exists())

    def test_tts_falla_conserva_respuesta_y_limpia_audio(self):
        rutas = []
        def generar(texto, carpeta):
            ruta = Path(carpeta) / 'salida.wav'
            ruta.write_bytes(b'falso')
            rutas.append(ruta)
            return ruta
        self.v.activa = True
        with patch.object(self.v.tts, 'generar', side_effect=generar), patch(
                'voz.ejecutar', side_effect=RuntimeError('Reproducción falló')):
            self.assertTrue(self.turno('Consulta normal'))
        self.assertTrue(any('Respuesta escrita' in c.args[0] for c in self.mostrar.call_args_list))
        self.assertTrue(any('No pude reproducir' in c.args[0] for c in self.mostrar.call_args_list))
        self.assertFalse(rutas[0].parent.exists())
        self.assertIn('TTS', self.v.errores[-1])

    def test_tts_generacion_fallida_cancelada_y_fragmentos_limpios(self):
        carpetas = []
        def fallo(texto, carpeta):
            carpetas.append(Path(carpeta))
            (Path(carpeta) / 'parcial.wav').touch()
            raise KeyboardInterrupt()
        with patch.object(self.v.tts, 'generar', side_effect=fallo):
            self.assertFalse(self.v.hablar('texto', self.mostrar))
        self.assertFalse(carpetas[0].exists())
        def generar(texto, carpeta):
            self.assertLessEqual(len(texto), 140)
            ruta = Path(carpeta) / 'salida.wav'
            ruta.touch()
            carpetas.append(Path(carpeta))
            return ruta
        with patch.object(self.v.tts, 'generar', side_effect=generar) as gen, patch('voz.ejecutar'):
            self.assertTrue(self.v.hablar('Una respuesta larga. ' * 100, self.mostrar))
            self.assertGreater(gen.call_count, 1)
        self.assertTrue(all(not p.exists() for p in carpetas))

    def test_auditoria_solo_lectura_no_habla_ni_carga(self):
        with tempfile.TemporaryDirectory() as carpeta:
            self.v.config.supertonic = Path(carpeta)
            self.v.config.tts_cache = Path(carpeta)
            self.v.activa = True
            with patch('voz.microfono_estado', return_value='micrófono simulado'), patch.object(
                    self.v, 'hablar') as hablar, patch.object(self.v.tts, 'iniciar') as iniciar:
                self.turno('Auditá la voz')
            hablar.assert_not_called()
            iniciar.assert_not_called()
            self.assertEqual(list(Path(carpeta).iterdir()), [])
            texto = self.mostrar.call_args.args[0]
            for esperado in ('activo', 'micrófono simulado', 'whisper.cpp', 'Supertonic', 'M2', 'es', '1.15', 'Errores recientes'):
                self.assertIn(esperado, texto)
            self.procesar.assert_not_called()

    def test_stt_invoca_solo_binario_local_espanol_cpu(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'microfono.wav'
            self.v.config.stt_modelo = Path(carpeta) / 'ggml-base.bin'
            self.v.config.stt_modelo.touch()
            ruta.with_suffix('.txt').write_text('  texto  ')
            with patch('voz.ejecutar') as ejecutar:
                self.assertEqual(self.v.transcribir(ruta), 'texto')
            args = ejecutar.call_args.args[0]
            self.assertIn('es', args)
            self.assertIn('-ng', args)
            self.assertNotIn('http', ' '.join(args))

    def test_captura_cierra_stream_en_error_y_escribe_wav(self):
        from array import array
        stream = Mock()
        stream.read_available = 1600
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        sd = Mock()
        sd.RawInputStream.return_value = stream
        with patch.dict(sys.modules, {'sounddevice': sd}), tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'audio.wav'
            stream.read.return_value = (array('h', [500] * 1600).tobytes(), False)
            self.assertTrue(voz.capturar(ruta, 0.1))
            self.assertEqual(ruta.read_bytes()[:4], b'RIFF')
            stream.read.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                voz.capturar(ruta, 0.1)
            self.assertEqual(stream.__exit__.call_count, 2)


class LatenciaTest(unittest.TestCase):
    def test_buffer_cffi_real_y_bytes_pcm_no_producen_typeerror(self):
        from array import array
        from cffi import FFI
        import wave
        ffi = FFI()
        voz_pcm = array('h', [500, -500] * 800).tobytes()
        silencio_pcm = bytes(3200)
        def buffer_cffi(pcm):
            return ffi.buffer(ffi.new('char[]', pcm), len(pcm))
        # Reproduce exactamente el error de la conversión anterior.
        with self.assertRaisesRegex(TypeError, "'bytes' object cannot be interpreted as an integer"):
            array('h', buffer_cffi(voz_pcm))
        for convertir in (bytes, buffer_cffi):
            with self.subTest(tipo=convertir.__name__):
                stream = Mock(read_available=1600)
                stream.__enter__ = Mock(return_value=stream)
                stream.__exit__ = Mock(return_value=False)
                stream.read.side_effect = [(convertir(pcm), False)
                                          for pcm in [voz_pcm] + [silencio_pcm] * 8]
                sd = Mock()
                sd.RawInputStream.return_value = stream
                with patch.dict(sys.modules, {'sounddevice': sd}), tempfile.TemporaryDirectory() as carpeta:
                    ruta = Path(carpeta) / 'voz.wav'
                    self.assertTrue(voz.capturar(ruta, 8))
                    self.assertEqual(stream.read.call_count, 9)
                    with wave.open(str(ruta)) as wav:
                        self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getsampwidth()), (1, 16000, 2))
                        self.assertEqual(wav.readframes(wav.getnframes()), voz_pcm + silencio_pcm * 8)
                stream.__exit__.assert_called_once()

    def test_dispositivo_sin_frames_termina_por_plazo_sin_read_bloqueante(self):
        stream = Mock(read_available=0)
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        sd = Mock()
        sd.RawInputStream.return_value = stream
        reloj = [0.0]
        def dormir(segundos):
            self.assertGreater(segundos, 0)
            self.assertLessEqual(segundos, 0.01)
            reloj[0] += segundos
        with patch.dict(sys.modules, {'sounddevice': sd}), patch(
                'voz.time.monotonic', side_effect=lambda: reloj[0]), patch(
                'voz.time.sleep', side_effect=dormir), tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / 'voz.wav'
            self.assertFalse(voz.capturar(ruta, 8))
            self.assertFalse(ruta.exists())
        self.assertAlmostEqual(reloj[0], 8)
        stream.read.assert_not_called()
        stream.__exit__.assert_called_once()

    def test_captura_real_cancelada_o_fallida_limpia_temporal_de_escuchar(self):
        for fallo in (KeyboardInterrupt(), RuntimeError('dispositivo desconectado')):
            stream = Mock(read_available=1600)
            stream.__enter__ = Mock(return_value=stream)
            stream.__exit__ = Mock(return_value=False)
            stream.read.side_effect = fallo
            sd = Mock()
            sd.RawInputStream.return_value = stream
            rutas = []
            capturar = voz.capturar
            def captura(ruta, segundos):
                rutas.append(ruta)
                return capturar(ruta, segundos)
            v = voz.Voz()
            with patch.dict(sys.modules, {'sounddevice': sd}), patch(
                    'voz.capturar', side_effect=captura), patch.object(v, 'transcribir') as stt:
                self.assertIsNone(v.escuchar(Mock()))
            stt.assert_not_called()
            self.assertFalse(rutas[0].parent.exists())
            stream.__exit__.assert_called_once()

    def test_captura_limite_de_reloj_y_cancelacion_cierra_stream(self):
        from array import array
        stream = Mock()
        stream.read_available = 1600
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.read.return_value = (array('h', [500] * 1600).tobytes(), False)
        sd = Mock()
        sd.RawInputStream.return_value = stream
        with patch.dict(sys.modules, {'sounddevice': sd}), tempfile.TemporaryDirectory() as carpeta:
            with patch('voz.time.monotonic', side_effect=[0, 0, 8]):
                self.assertTrue(voz.capturar(Path(carpeta) / 'voz.wav', 8))
            stream.read.assert_called_once()
            stream.read.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                voz.capturar(Path(carpeta) / 'cancelado.wav', 8)
            self.assertFalse((Path(carpeta) / 'cancelado.wav').exists())
        self.assertEqual(stream.__exit__.call_count, 2)

    def test_fin_de_habla_por_bloques_y_wav(self):
        from array import array
        import wave
        casos = [
            ([500] * 3 + [0] * 8, 11, True),
            ([0] * 12 + [500] * 2 + [0] * 8, 22, True),
            ([500] * 2 + [0] * 7 + [500] + [0] * 8, 18, True),
            ([500] * 100, 80, True),
            ([0] * 100, 80, False),
        ]
        for niveles, lecturas, detectada in casos:
            with self.subTest(lecturas=lecturas, detectada=detectada):
                stream = Mock()
                stream.read_available = 1600
                stream.__enter__ = Mock(return_value=stream)
                stream.__exit__ = Mock(return_value=False)
                stream.read.side_effect = [(array('h', [n] * 1600).tobytes(), False) for n in niveles]
                sd = Mock()
                sd.RawInputStream.return_value = stream
                with patch.dict(sys.modules, {'sounddevice': sd}), tempfile.TemporaryDirectory() as carpeta:
                    ruta = Path(carpeta) / 'voz.wav'
                    self.assertEqual(voz.capturar(ruta, 20), detectada)
                    self.assertEqual(stream.read.call_count, lecturas)
                    stream.__exit__.assert_called_once()
                    if detectada:
                        with wave.open(str(ruta)) as wav:
                            self.assertEqual((wav.getnchannels(), wav.getframerate(), wav.getsampwidth()), (1, 16000, 2))
                            self.assertEqual(wav.getnframes(), lecturas * 1600)
                    else:
                        self.assertFalse(ruta.exists())

    def test_fragmentador_preserva_palabras_orden_y_puntuacion(self):
        for texto in ('Hola Leo. ¿Cómo estás? Bien; seguimos.', 'palabra ' * 100,
                      '', '  \n ', 'x' * 150, 'Primero.\nSegundo: una prueba.'):
            partes = list(voz.fragmentar(texto))
            self.assertEqual(' '.join(partes), ' '.join(texto.split()))
            self.assertTrue(all(p and (len(p) <= 140 or ' ' not in p) for p in partes))
        self.assertEqual(list(voz.fragmentar('Hola Leo. Otra oración.')), ['Hola Leo.', 'Otra oración.'])

    def test_primero_reproduce_antes_de_generar_el_siguiente_y_mide(self):
        v = voz.Voz()
        eventos = []
        def generar(texto, carpeta):
            eventos.append(('generar', texto))
            return Path(carpeta) / 'voz.wav'
        def reproducir(*args):
            eventos.append(('reproducir', None))
        with patch.object(v.tts, 'generar', side_effect=generar), patch(
                'voz.ejecutar', side_effect=reproducir), patch('voz.time.monotonic', side_effect=[10, 12, 17]):
            self.assertTrue(v.hablar('Primero. Segundo.', Mock()))
        self.assertEqual(eventos, [('generar', 'Primero.'), ('reproducir', None),
                                  ('generar', 'Segundo.'), ('reproducir', None)])
        self.assertEqual(v.tiempos, {'Primer audio': 2, 'TTS total': 7})


    def test_diagnostico_no_habla_y_conserva_ultimo_turno(self):
        v = voz.Voz()
        v.activa = True
        mostrar = Mock()
        with patch('voz.capturar', return_value=True), patch.object(v, 'transcribir', return_value='Hola'), patch.object(
                v, 'hablar'), patch('voz.time.monotonic', side_effect=[0, 1, 1, 3, 3, 6]):
            v.turno('Escuchame', Mock(return_value='Respuesta'), mostrar)
        self.assertEqual(v.tiempos, {'Captura': 1, 'STT': 2, 'Procesamiento': 3})
        with patch.object(v, 'hablar') as hablar:
            v.turno('Diagnóstico de voz', Mock(), mostrar)
            hablar.assert_not_called()
        texto = mostrar.call_args.args[0]
        for linea in ('Captura: 1.0 s', 'STT: 2.0 s', 'Procesamiento: 3.0 s', 'Primer audio: sin medición'):
            self.assertIn(linea, texto)
        with patch.object(v.tts, 'generar'), patch('voz.ejecutar'):
            v.turno('Estado de voz', Mock(), mostrar)
        self.assertEqual(v.tiempos, {'Captura': 1, 'STT': 2, 'Procesamiento': 3})


class SupertonicTest(unittest.TestCase):
    def test_auditoria_detecta_instalacion_y_cache_sin_cargar_modelos(self):
        with tempfile.TemporaryDirectory() as carpeta, patch('voz.microfono_estado', return_value='simulado'):
            raiz = Path(carpeta)
            v = voz.Voz(voz.ConfigVoz(supertonic=raiz, tts_cache=raiz))
            self.assertIn('faltan archivos', v.auditar())
            cli = raiz / '.venv/bin/supertonic'
            cli.parent.mkdir(parents=True)
            cli.touch()
            cli.chmod(0o700)
            for nombre in ('onnx/tts.json', 'onnx/unicode_indexer.json', 'onnx/duration_predictor.onnx',
                           'onnx/text_encoder.onnx', 'onnx/vector_estimator.onnx', 'onnx/vocoder.onnx',
                           'voice_styles/M2.json'):
                archivo = raiz / nombre
                archivo.parent.mkdir(parents=True, exist_ok=True)
                archivo.touch()
            with patch.object(v.tts, 'iniciar') as iniciar:
                auditoria = v.auditar()
            iniciar.assert_not_called()
            self.assertIn(f'{cli} (disponible)', auditoria)
            self.assertIn('archivos presentes', auditoria)

    def test_configuracion_y_comandos(self):
        v = voz.Voz()
        self.assertEqual(v.config.supertonic, Path('/Users/leocast/supertonic-test'))
        self.assertEqual((v.config.voz, v.config.idioma, v.config.velocidad), ('M2', 'es', 1.15))
        for comando in ('Estado de voz', 'Diagnóstico de voz', 'Modo voz rápido', 'Modo voz calidad'):
            texto, _, _ = v.comando(comando)
            self.assertIn('Supertonic', texto)
            self.assertIn('M2', texto)
            self.assertIn('1.15', texto)
        self.assertFalse(v.activa)

    def test_ollama_rapido_no_descarga_worker_ni_consulta_red(self):
        v = voz.Voz()
        v.activa = True
        datos = {'model': 'qwen3:4b'}
        with patch.object(v.tts, 'cerrar') as cerrar, patch('requests.get') as get:
            v.antes_ollama(datos)
        cerrar.assert_not_called()
        get.assert_not_called()
        self.assertEqual(datos, {'model': 'qwen3:1.7b', 'keep_alive': 0})
        self.assertIn('qwen3:1.7b', v.diagnostico())

    def test_worker_api_equivalente_cli_y_cache_sin_descargas(self):
        import voz_tts_worker
        from types import SimpleNamespace
        motor = Mock()
        motor.get_voice_style.return_value = 'estilo M2'
        motor.synthesize.return_value = ('pcm simulado', None)
        constructor = Mock(return_value=motor)
        pedido = dict(texto='Hola Leo.', voz='M2', idioma='es', velocidad=1.15, carpeta='/tmp')
        salida = io.StringIO()
        with patch.dict(sys.modules, {'supertonic': SimpleNamespace(TTS=constructor)}):
            voz_tts_worker.servir(Path('/cache/local'), io.StringIO((json.dumps(pedido)+'\n')*2), salida)
        constructor.assert_called_once_with(model='supertonic-3', model_dir=Path('/cache/local'), auto_download=False)
        motor.get_voice_style.assert_called_once_with('M2')
        self.assertEqual(motor.synthesize.call_count, 2)
        motor.synthesize.assert_called_with(text='Hola Leo.', voice_style='estilo M2', lang='es', speed=1.15, total_steps=8)
        motor.save_audio.assert_called_with('pcm simulado', '/tmp/voz.wav')
        self.assertEqual([json.loads(x) for x in salida.getvalue().splitlines()], [{'ruta': '/tmp/voz.wav'}]*2)

    def test_error_cargando_api_no_expone_texto_privado(self):
        import voz_tts_worker
        from types import SimpleNamespace
        salida = io.StringIO()
        with patch.dict(sys.modules, {'supertonic': SimpleNamespace(TTS=Mock(side_effect=FileNotFoundError('secreto')))}):
            voz_tts_worker.servir(Path('/cache'), io.StringIO('{}\n'), salida)
        error = json.loads(salida.getvalue())['error']
        self.assertIn('Supertonic: FileNotFoundError', error)
        self.assertNotIn('secreto', error)


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        (self.raiz / '.venv/bin').mkdir(parents=True)
        (self.raiz / '.venv/bin/python').symlink_to(sys.executable)
        cli = self.raiz / '.venv/bin/supertonic'
        cli.write_text('# CLI simulado; el worker utiliza API Python')
        cli.chmod(0o700)
        (self.raiz / 'supertonic.py').write_text('''
import os
import sys
import wave
from pathlib import Path
print('Mensaje biblioteca')
os.write(1, b'Mensaje nativo\\n')
class TTS:
    def __init__(self, *, model, model_dir, auto_download):
        assert model == 'supertonic-3' and auto_download is False
        assert Path(model_dir).is_absolute()
        assert os.environ['HF_HUB_OFFLINE'] == '1'
        assert 'mlx' not in sys.modules and 'tts' not in sys.modules
        self.contador = 0
    def get_voice_style(self, nombre):
        assert nombre == 'M2'
        return nombre
    def synthesize(self, *, text, voice_style, lang, speed, total_steps):
        assert voice_style == 'M2' and lang == 'es' and speed == 1.15 and total_steps == 8
        if text == 'error':
            raise ValueError('texto privado secreto')
        if text == 'timeout':
            import time
            time.sleep(5)
        if text == 'exit':
            os._exit(1)
        self.contador += 1
        return text, None
    def save_audio(self, audio, ruta):
        if audio == 'invalido':
            Path(ruta).write_bytes(b'no es wav')
            return
        if audio == 'ausente':
            return
        with wave.open(ruta, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(44100)
            wav.writeframes(bytes(2 * self.contador))
''')
        entorno = patch.dict('os.environ', {'PYTHONPATH': str(self.raiz)})
        entorno.start()
        self.addCleanup(entorno.stop)
        self.motor = voz.MotorTTS(voz.ConfigVoz(supertonic=self.raiz, tts_cache=self.raiz, timeout_tts=3))
        self.addCleanup(self.motor.cerrar)

    def test_proceso_ruta_absoluta_sin_shell_reutiliza_modelo(self):
        import subprocess
        import wave
        with patch('voz.subprocess.Popen', wraps=subprocess.Popen) as popen:
            ruta = self.motor.generar('uno', self.raiz)
            self.assertEqual(ruta.suffix, '.wav')
            args = popen.call_args.args[0]
            self.assertEqual(args[0], str(self.raiz / '.venv/bin/python'))
            self.assertEqual(args[2], str(Path(voz.__file__).with_name('voz_tts_worker.py')))
            self.assertFalse(popen.call_args.kwargs.get('shell', False))
            proceso = self.motor.proceso
            v = voz.Voz(self.motor.config)
            v.tts = self.motor
            v.activa = True
            v.antes_ollama({'model': 'qwen3:4b'})
            ruta = self.motor.generar('dos', self.raiz)
            self.assertIs(self.motor.proceso, proceso)
            self.assertEqual(popen.call_count, 1)
            with wave.open(str(ruta)) as wav:
                self.assertEqual(wav.getnframes(), 2)
        otro = voz.MotorTTS(self.motor.config)
        with self.assertRaisesRegex(RuntimeError, 'Otro proceso Hermes'):
            otro.iniciar()
        otro.cerrar()
        trabajo = Path(self.motor._trabajo.name)
        self.motor.cerrar()
        self.assertFalse(trabajo.exists())

    def test_errores_timeout_y_wav_invalido_cierran_hijo(self):
        for texto in ('error', 'timeout', 'exit', 'invalido', 'ausente'):
            with self.subTest(texto=texto), tempfile.TemporaryDirectory() as carpeta:
                self.motor.config.timeout_tts = 0.5
                with self.assertRaises(Exception) as error:
                    self.motor.generar(texto, carpeta)
                self.assertNotIn('secreto', str(error.exception))
                self.assertFalse(self.motor.activo())
                self.assertIsNone(self.motor._trabajo)
                self.assertIsNone(self.motor._lock)

    def test_ejecutable_ausente_no_busca_en_path(self):
        self.motor.config.supertonic = self.raiz / 'ausente'
        with patch('voz.subprocess.Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, 'Falta Supertonic'):
                self.motor.generar('Hola', self.raiz)
            popen.assert_not_called()

    def test_cancelacion_recoge_worker(self):
        self.motor.iniciar()
        proceso = self.motor.proceso
        with patch('voz.select.select', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self.motor.generar('Hola', self.raiz)
        self.assertIsNotNone(proceso.poll())
        self.assertIsNone(self.motor._trabajo)

    def test_fallo_supertonic_vuelve_a_texto_y_permite_reintentar(self):
        v = voz.Voz(self.motor.config)
        v.tts = self.motor
        v.activa = True
        mostrar = Mock()
        with patch('voz.ejecutar') as reproducir:
            self.assertTrue(v.turno('Consulta', Mock(return_value='error'), mostrar))
            mostrar.assert_any_call('\nHermes: error\n')
            self.assertIn('Supertonic: ValueError', v.errores[-1])
            reproducir.assert_not_called()
            self.assertFalse(self.motor.activo())
            self.assertTrue(v.hablar('Hola.', mostrar))
            reproducir.assert_called_once()
            self.assertEqual(reproducir.call_args.args[0][0], '/usr/bin/afplay')
            self.assertFalse(Path(reproducir.call_args.args[0][1]).exists())


class IntegracionVozTest(unittest.TestCase):
    setUp = test_automatizaciones.AutomatizacionesTest.setUp

    def test_sesion_escuchame_dispatcher_real_imprime_y_habla(self):
        v = self.hermes['voz']
        with patch.object(v, 'hablar') as hablar, contextlib.redirect_stdout(io.StringIO()) as salida:
            v.turno('Activá modo voz', self.hermes['procesar_turno_texto'])
            hablar.reset_mock()
            with patch('voz.capturar', return_value=True), patch.object(
                    v, 'transcribir', return_value='Mostrame mis tareas'):
                v.turno('Escuchame', self.hermes['procesar_turno_texto'])
            hablar.assert_called_once_with('No tenés tareas pendientes.', print)
            self.assertIn('Hermes: No tenés tareas pendientes.', salida.getvalue())
            self.assertTrue(v.activa)

    def test_respuesta_vacia_del_modelo_no_deja_turno_mudo(self):
        v = self.hermes['voz']
        v.activa = True
        respuesta = Mock()
        # El limpiador elimina un eco de la consulta y puede dejar texto vacío.
        respuesta.json.return_value = {'response': json.dumps({'respuesta': 'Hola'})}
        with patch('requests.post', return_value=respuesta), patch.object(
                v, 'escuchar', return_value='Hola'), patch.object(v, 'hablar') as hablar:
            mostrar = Mock()
            v.turno('Escuchame', self.hermes['procesar_turno_texto'], mostrar)
        texto = hablar.call_args.args[0]
        self.assertTrue(texto.strip())
        mostrar.assert_any_call(f'\nHermes: {texto}\n')

    def test_texto_y_voz_comparten_seguridad_real_e_historial(self):
        v = self.hermes['voz']
        procesar = self.hermes['procesar_turno_texto']
        for mensaje in ('Creá archivo /tmp/hermes-prohibido.txt con hola',
                        'Creá archivo hermes.py con hola',
                        'Creá archivo voz.py con hola'):
            escrito, hablado = [], []
            with contextlib.redirect_stdout(io.StringIO()):
                v.turno(mensaje, procesar, escrito.append)
                with patch.object(v, 'escuchar', return_value=mensaje):
                    v.turno('Escuchame', procesar, hablado.append)
            self.assertEqual(escrito, hablado)
            self.assertTrue('seguridad' in hablado[-1] or 'protegido' in hablado[-1] or 'protegida' in hablado[-1])
        import memoria
        historial = memoria.obtener_historial_conversacion()
        self.assertTrue(historial)

    def test_voz_no_autoriza_acciones_inventadas_por_modelo(self):
        import memoria
        v = self.hermes['voz']
        v.activa = True
        for accion in ('crear_tarea', 'crear_evento'):
            respuesta = Mock()
            respuesta.json.return_value = {'response': json.dumps({
                'respuesta': 'Te escucho.', 'accion': accion,
                'tarea_titulo': 'No autorizada', 'evento_titulo': 'No autorizado',
                'guardar_memoria': False})}
            with patch.object(v, 'escuchar', return_value='Hoy me siento tranquilo'), patch.object(
                    v, 'hablar'), patch.object(v.tts, 'cerrar') as cerrar, patch(
                    'requests.post', return_value=respuesta) as post, contextlib.redirect_stdout(io.StringIO()):
                v.turno('Escuchame', self.hermes['procesar_turno_texto'], lambda _: None)
                self.assertEqual(post.call_args.kwargs['json']['keep_alive'], 0)
                cerrar.assert_not_called()
        self.assertEqual(memoria.obtener_tareas_pendientes(), [])
        self.assertEqual(memoria.obtener_eventos_activos(), [])

    def test_nota_por_voz_pasa_dispatcher_real(self):
        v = self.hermes['voz']
        with patch.object(v, 'escuchar', return_value='Creá una nota: prueba de voz'), contextlib.redirect_stdout(io.StringIO()):
            v.turno('Escuchame', self.hermes['procesar_turno_texto'], lambda _: None)
        import memoria
        self.assertEqual(len(memoria.obtener_notas_activas()), 1)


if __name__ == '__main__':
    unittest.main()

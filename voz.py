"""Voz local opcional. Importar este módulo no abre audio ni carga modelos."""
from array import array
from collections import deque
from dataclasses import dataclass, field
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import tempfile
import time
import unicodedata
import wave


@dataclass
class ConfigVoz:
    supertonic: Path = field(default_factory=lambda: Path(os.getenv('HERMES_SUPERTONIC_DIR', '/Users/leocast/supertonic-test')).expanduser())
    voz: str = 'M2'
    idioma: str = 'es'
    velocidad: float = 1.15
    modelo: str = 'supertonic-3'
    tts_cache: Path = field(default_factory=lambda: Path(os.getenv('SUPERTONIC_CACHE_DIR', '~/.cache/supertonic3')).expanduser())
    whisper: str = field(default_factory=lambda: os.getenv('HERMES_WHISPER_BIN', str(Path.home() / 'whisper.cpp/build/bin/whisper-cli')))
    stt_modelo: Path = field(default_factory=lambda: Path(os.getenv('HERMES_WHISPER_MODEL', '~/whisper.cpp/models/ggml-base.bin')).expanduser())
    segundos: float = 8.0
    timeout_stt: float = 120.0
    timeout_tts: float = 600.0
    ollama: str = 'http://localhost:11434/api/generate'


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower())
                   if unicodedata.category(c) != 'Mn').strip(' ¿?¡!.')


def ejecutar(args, timeout):
    """Sin shell; siempre recoger al hijo, también al cancelar con Ctrl+C."""
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proceso:
        try:
            salida, _ = proceso.communicate(timeout=timeout)
            if proceso.returncode:
                raise RuntimeError(f'{Path(args[0]).name} terminó con error {proceso.returncode}')
            return salida
        except BaseException:
            proceso.kill()
            proceso.wait()
            raise


def capturar(ruta, segundos):
    import sounddevice as sd
    # El stream se cierra incluso si el usuario cancela; nunca hay escucha de fondo.
    bloques = []
    detectada = False
    silencio = 0
    limite = time.monotonic() + min(segundos, 8.0)
    with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16') as stream:
        for _ in range(int(min(segundos, 8.0) * 10)):
            # read() espera todos los frames solicitados. No entrar en esa
            # espera nativa si el dispositivo dejó de entregar muestras.
            while True:
                restante = limite - time.monotonic()
                if restante <= 0 or stream.read_available >= 1600:
                    break
                time.sleep(min(0.01, restante))
            if restante <= 0:
                break
            bloque, overflow = stream.read(1600)
            if overflow:
                raise RuntimeError('El micrófono perdió audio; volvé a intentar')
            # RawInputStream devuelve un buffer CFFI, no necesariamente bytes.
            # Su iteración produce bytes individuales, no enteros int16.
            pcm = bytes(bloque)
            if len(pcm) != 1600 * 2:
                raise RuntimeError('El micrófono devolvió un bloque PCM incompleto')
            bloques.append(pcm)
            muestras = array('h')
            muestras.frombytes(pcm)  # int16 nativo (little-endian en este Mac).
            rms = (sum(x * x for x in muestras) / len(muestras)) ** 0.5 if muestras else 0
            if rms >= 80:
                detectada = True
                silencio = 0
            elif detectada:
                silencio += 1
                if silencio >= 8:  # 8 bloques de 100 ms, después de detectar voz.
                    break
    audio = b''.join(bloques)
    if not detectada:
        return False
    with wave.open(str(ruta), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(audio)
    return True


def _entero_en_palabras(numero):
    """Cardinal español; escala larga, sin dependencias externas."""
    if numero >= 10 ** 24:
        return ' '.join(_entero_en_palabras(int(d)) for d in str(numero))
    unidades = ('cero', 'uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete',
                'ocho', 'nueve', 'diez', 'once', 'doce', 'trece', 'catorce', 'quince',
                'dieciséis', 'diecisiete', 'dieciocho', 'diecinueve', 'veinte',
                'veintiuno', 'veintidós', 'veintitrés', 'veinticuatro', 'veinticinco',
                'veintiséis', 'veintisiete', 'veintiocho', 'veintinueve')
    if numero < 30:
        return unidades[numero]
    if numero < 100:
        decenas = ('', '', '', 'treinta', 'cuarenta', 'cincuenta', 'sesenta',
                   'setenta', 'ochenta', 'noventa')
        return decenas[numero // 10] + (' y ' + unidades[numero % 10] if numero % 10 else '')
    if numero == 100:
        return 'cien'
    if numero < 1000:
        centenas = ('', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos',
                    'quinientos', 'seiscientos', 'setecientos', 'ochocientos', 'novecientos')
        return centenas[numero // 100] + (' ' + _entero_en_palabras(numero % 100) if numero % 100 else '')
    divisor = next(d for d in (10 ** 18, 10 ** 12, 10 ** 6, 1000) if numero >= d)
    cantidad, resto = divmod(numero, divisor)
    if divisor == 1000:
        prefijo = 'mil' if cantidad == 1 else _apocopar(_entero_en_palabras(cantidad)) + ' mil'
    else:
        singular, plural = {10 ** 6: ('millón', 'millones'),
                            10 ** 12: ('billón', 'billones'),
                            10 ** 18: ('trillón', 'trillones')}[divisor]
        prefijo = 'un ' + singular if cantidad == 1 else _apocopar(_entero_en_palabras(cantidad)) + ' ' + plural
    return prefijo + (' ' + _entero_en_palabras(resto) if resto else '')


def _apocopar(texto):
    if texto.endswith('veintiuno'):
        return texto[:-9] + 'veintiún'
    return texto[:-3] + 'un' if texto.endswith('uno') else texto


def normalizar_para_voz(texto):
    """Sólo pronunciación: conserva tokens técnicos y formatos ambiguos.

    Punto de tres cifras = miles; coma = decimal; punto de una/dos cifras =
    decimal. Fechas y horas válidas preceden a cantidades. No altera el original.
    """
    from datetime import date

    meses = ('', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
             'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')
    # Primero aislar tokens completos: URLs, rutas, UUIDs y códigos nunca se
    # recorren buscando dígitos interiores. Proteger también etiquetas con valor.
    etiquetas = r'(?i:\b(?:DNI|CUIT|CUIL|ID|token|UUID|versión|version|IP)\s*[:=]?\s+\S+)'
    patron = etiquetas + r'|`[^`]*`|\$\s*[+-]?\d[\d.,]*(?:%)?|\S+'

    def cantidad(valor):
        signo = ''
        if valor.startswith(('-', '+')):
            signo = 'menos ' if valor[0] == '-' else 'más '
            valor = valor[1:]
        if re.fullmatch(r'\d{1,3}(?:\.\d{3})+(?:,\d+)?', valor):
            valor = valor.replace('.', '')
        if not re.fullmatch(r'\d+(?:[,.]\d+)?', valor):
            return None
        partes = re.split('[,.]', valor)
        entero = partes[0]
        # Los ceros iniciales suelen indicar códigos. La longitud por sí sola
        # no vuelve técnico un número conversacional.
        if len(entero) > 60 or (len(entero) > 1 and entero.startswith('0')):
            return None
        fraccion = partes[1] if len(partes) == 2 else ''
        if len(fraccion) > 9:
            return None
        return signo, int(entero), fraccion

    def pronunciar(match):
        token = match.group()
        if re.fullmatch(etiquetas, token) or token.startswith('`'):
            return token
        # Conservar envoltorios y puntuación de la frase.
        inicio = re.match(r'^[¿¡("\[\{]*', token).group()
        fin = re.search(r'[.,;:!?\)"\]\}]*$', token).group()
        centro = token[len(inicio):len(token)-len(fin) if fin else len(token)]
        resultado = centro
        fecha = re.fullmatch(r'(\d{2})/(\d{2})/(\d{4})|(\d{4})-(\d{2})-(\d{2})', centro)
        hora = re.fullmatch(r'(\d{1,2}):(\d{2})', centro)
        if fecha:
            d, m, a, ai, mi, di = fecha.groups()
            try:
                f = date(int(a or ai), int(m or mi), int(d or di))
            except ValueError:
                return token
            resultado = f'{_entero_en_palabras(f.day)} de {meses[f.month]} de {_entero_en_palabras(f.year)}'
        elif hora:
            h, minuto = map(int, hora.groups())
            if h > 23 or minuto > 59:
                return token
            horas = _entero_en_palabras(h)
            if horas.endswith('uno'):
                horas = horas[:-3] + 'una'
            resultado = horas + (' y ' + _entero_en_palabras(minuto) if minuto else (' hora' if h == 1 else ' horas'))
        else:
            dinero = centro.startswith('$')
            porcentaje = centro.endswith('%')
            valor = centro[1:].strip() if dinero else centro[:-1] if porcentaje else centro
            datos = cantidad(valor)
            if datos is None:
                return token
            signo, entero, fraccion = datos
            if dinero:
                if len(fraccion) > 2:
                    return token
                resultado = signo + _apocopar(_entero_en_palabras(entero))
                resultado += (' de' if entero and entero % 1000000 == 0 else '')
                resultado += ' peso' if entero == 1 else ' pesos'
                centavos = int(fraccion.ljust(2, '0')) if fraccion else 0
                if centavos:
                    resultado += ' con ' + _apocopar(_entero_en_palabras(centavos))
                    resultado += ' centavo' if centavos == 1 else ' centavos'
            else:
                resultado = signo + _entero_en_palabras(entero)
                if fraccion:
                    parte = (' '.join(_entero_en_palabras(int(x)) for x in fraccion)
                             if fraccion.startswith('0') else _entero_en_palabras(int(fraccion)))
                    resultado += ' coma ' + parte
                if porcentaje:
                    resultado += ' por ciento'
        return inicio + resultado + fin

    return re.sub(patron, pronunciar, str(texto))


def adaptar_rioplatense(texto):
    """Voseo léxico conservador; citas y tokens técnicos quedan intactos."""
    cambios = {'tú': 'vos', 'puedes': 'podés', 'quieres': 'querés', 'tienes': 'tenés'}
    # Se consumen completos: nunca reemplazar subcadenas de URLs o identificadores.
    patron = (r'```[\s\S]*?```|`[^`]*`|"[^"\n]*"|“[^”]*”|«[^»]*»|\'[^\'\n]*\'|'
              r'(?i:\b(?:token|ID|UUID|variable|función|funcion|parámetro|parametro)\s*[:=]?\s+\S+)|\S+')
    def adaptar(match):
        token = match.group()
        if token.startswith(('`', '"', '“', '«', "'")):
            return token
        palabra = re.fullmatch(r'([¿¡(]*)(tú|puedes|quieres|tienes)([.,;:!?)]*)', token, re.IGNORECASE)
        if not palabra:
            return token
        inicio, original, fin = palabra.groups()
        # "según tú", "de tú a tú", etc. requieren otra construcción: abstenerse.
        if original.lower() == 'tú':
            if not re.match(r'\s+(?:puedes|quieres|tienes)\b', match.string[match.end():], re.IGNORECASE):
                return token
        valor = cambios[original.lower()]
        if original.isupper():
            valor = valor.upper()
        elif original[0].isupper():
            valor = valor.capitalize()
        return inicio + valor + fin
    return re.sub(patron, adaptar, str(texto))


def suavizar_punto_y_coma(texto):
    """Sólo prosodia TTS; conservar literalmente citas y tokens técnicos."""
    protegidos = (
        r'```[\s\S]*?```|`[^`]*`|"[^"]*"|“[^”]*”|«[^»]*»|\'[^\']*\'|'
        r'(?i:(?:https?://|www\.)\S+)|'
        r'(?:[A-Za-z]:[\\/]|[~/]|\.{1,2}/)\S+|'
        r'(?i:\b(?:token|ID|UUID|variable|función|funcion|parámetro|parametro)\s*[:=]?\s+\S+)|'
        r'\S*[\w][/_=\\]\S*|\S*\d\S*|\S*\w-\w\S*'
    )
    # Sustituir sólo los separadores que no pertenecen a un tramo protegido.
    return re.sub(protegidos + r'|;', lambda m: ',' if m.group() == ';' else m.group(), texto)


def fragmentar(texto, limite=110):
    """Prioriza pausas naturales; dinero y fechas son unidades indivisibles."""
    texto = ' '.join(str(texto).split())
    # Vocabulario acotado del cardinal español, para reconocer también texto
    # que ya llegó escrito en palabras (no sólo expansiones del normalizador).
    vocabulario = set(' '.join(_entero_en_palabras(n) for n in range(100)).split())
    vocabulario.update('un una veintiún veintiuna cien ciento doscientos trescientos cuatrocientos quinientos seiscientos setecientos ochocientos novecientos mil millón millones billón billones trillón trillones'.split())
    vocabulario.discard('y')
    numero = '(?:' + '|'.join(sorted(vocabulario, key=len, reverse=True)) + ')'
    cardinal = numero + r'(?:\s+(?:y\s+)?' + numero + r')*'
    meses = '(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)'
    unidades = (r'\b' + cardinal + r'\s+(?:de\s+)?pesos?(?:\s+con\s+' + cardinal + r'\s+centavos?)?\b|'
                r'\b' + cardinal + r'\s+de\s+' + meses + r'\s+de\s+' + cardinal + r'\b')
    protegidos = [(m.start(), m.end()) for m in re.finditer(unidades, texto, re.IGNORECASE)]
    cortes = [m.start() for m in re.finditer(' ', texto)
              if not any(a < m.start() < b for a, b in protegidos)] + [len(texto)]
    inicio = 0
    while inicio < len(texto):
        posibles = [c for c in cortes if inicio < c <= inicio + limite]
        if not posibles:
            # Una expresión indivisible puede superar el objetivo; preservarla.
            corte = next(c for c in cortes if c > inicio)
        else:
            def prioridad(c):
                previo = texto[c-1]
                if previo in '.!?':
                    return 0
                if previo == ';':
                    # No es una pausa fuerte: sólo favorece el corte cuando
                    # el texto restante supera el tamaño objetivo.
                    return 4 if len(texto) - inicio > limite else 5
                if previo == ',':
                    return 2
                if re.match(r'(?:y|pero|además|entonces|después|aunque)\b', texto[c+1:], re.IGNORECASE):
                    return 3
                return 5
            naturales = [c for c in posibles if prioridad(c) < 3]
            candidatos = naturales or [c for c in posibles if c-inicio >= 80] or posibles
            corte = min(candidatos, key=lambda c: (prioridad(c), c if prioridad(c) == 0 else -c))
        yield texto[inicio:corte]
        inicio = corte + 1


def microfono_estado():
    try:
        import sounddevice as sd
        dispositivo = sd.query_devices(kind='input')
        return f"disponible: {dispositivo['name']} (permiso de captura sin verificar)"
    except Exception as exc:
        return f'no disponible ({type(exc).__name__}); revisar sounddevice y permisos de macOS'


class MotorTTS:
    """Un hijo persistente, IPC por pipes privados; sin HTTP ni Gradio."""
    def __init__(self, config):
        self.config = config
        self.proceso = None
        self.cargado = False
        self._lock = None
        self._trabajo = None

    def activo(self):
        return self.proceso is not None and self.proceso.poll() is None

    def iniciar(self):
        if self.activo():
            return
        self.cerrar()
        python = self.config.supertonic / '.venv/bin/python'
        cli = self.config.supertonic / '.venv/bin/supertonic'
        if not python.is_file() or not cli.is_file() or not os.access(cli, os.X_OK):
            raise RuntimeError('Falta Supertonic en .venv/bin; revisá Auditá la voz')
        clave = hashlib.sha256(str(self.config.supertonic.resolve()).encode()).hexdigest()[:16]
        ruta_lock = Path(tempfile.gettempdir()) / f'hermes-tts-{os.getuid()}-{clave}.lock'
        fd = os.open(ruta_lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self._lock = os.fdopen(fd, 'a')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            entorno = dict(os.environ, HF_HUB_OFFLINE='1',
                           HF_HUB_DISABLE_TELEMETRY='1', PYTHONDONTWRITEBYTECODE='1')
            self._trabajo = tempfile.TemporaryDirectory(prefix="hermes-worker-")
            self.proceso = subprocess.Popen(
                [str(python), '-u', str(Path(__file__).with_name('voz_tts_worker.py')),
                 str(self.config.tts_cache.resolve()), self.config.modelo], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=entorno, cwd=self._trabajo.name, start_new_session=True,
                pass_fds=(self._lock.fileno(),))
        except BlockingIOError as exc:
            self.cerrar()
            raise RuntimeError('Otro proceso Hermes está usando Supertonic; desactivá su modo voz') from exc
        except BaseException:
            self.cerrar()
            raise

    def generar(self, texto, carpeta):
        self.iniciar()
        try:
            pedido = dict(texto=texto, carpeta=str(carpeta), voz=self.config.voz,
                          idioma=self.config.idioma, velocidad=self.config.velocidad)
            self.proceso.stdin.write((json.dumps(pedido) + '\n').encode())
            self.proceso.stdin.flush()
            limite = time.monotonic() + self.config.timeout_tts
            datos = b''
            while b'\n' not in datos:
                restante = limite - time.monotonic()
                if restante <= 0 or not select.select([self.proceso.stdout], [], [], restante)[0]:
                    raise TimeoutError('Supertonic excedió el tiempo máximo')
                bloque = os.read(self.proceso.stdout.fileno(), 65536)
                if not bloque:
                    raise RuntimeError('El motor Supertonic se cerró inesperadamente')
                datos += bloque
                if len(datos) > 131072:
                    raise RuntimeError('Respuesta inválida del motor TTS')
            resultado = json.loads(datos)
            if 'error' in resultado:
                raise RuntimeError(resultado['error'])
            ruta = Path(resultado['ruta']).resolve()
            if ruta.parent != Path(carpeta).resolve() or not ruta.is_file():
                raise RuntimeError('El motor devolvió una ruta de audio inválida')
            with wave.open(str(ruta), 'rb') as wav:
                if wav.getnframes() <= 0 or wav.getnchannels() != 1:
                    raise RuntimeError('Supertonic devolvió un WAV vacío o inválido')
            self.cargado = True
            return ruta
        except BaseException:
            self.cerrar()
            raise

    def cerrar(self):
        if self.proceso is not None:
            if self.proceso.poll() is None:
                self.proceso.terminate()
                try:
                    self.proceso.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proceso.kill()
                    self.proceso.wait()
            for pipe in (self.proceso.stdin, self.proceso.stdout):
                if pipe:
                    pipe.close()
        self.proceso = None
        self.cargado = False
        if self._lock is not None:
            self._lock.close()
            self._lock = None
        if self._trabajo is not None:
            self._trabajo.cleanup()
            self._trabajo = None


class Voz:
    def __init__(self, config=None):
        self.config = config or ConfigVoz()
        self.activa = False  # Estado de sesión, sin escrituras en SQLite.
        self.errores = deque(maxlen=5)
        self.tts = MotorTTS(self.config)
        self.tiempos = {}
        self.politica_memoria = 'Sin consulta a Ollama todavía'

    def error(self, etapa, exc):
        mensaje = f'{etapa}: {exc or type(exc).__name__}'
        self.errores.append(mensaje)
        return mensaje

    def antes_ollama(self, datos):
        if self.activa:
            datos['model'] = 'qwen3:1.7b'
            datos['keep_alive'] = 0
            self.politica_memoria = 'Ollama: qwen3:1.7b; se libera después de responder (keep_alive=0)'
        else:
            # Una consulta textual profunda no necesita conservar TTS en RAM.
            self.tts.cerrar()
            self.politica_memoria = 'Ollama: selección normal; modo voz inactivo'

    def hablar(self, texto, mostrar=print):
        inicio = time.monotonic()
        self.tiempos.pop('Primer audio', None)
        try:
            mostrar('🔊 Generando/reproduciendo voz Supertonic M2 (Ctrl+C cancela)...')
            # Obligatorio sobre la copia hablada completa, antes de fragmentar:
            # evita separar "DNI" de su valor o "$" de un importe al cortar.
            hablado = ' '.join(normalizar_para_voz(adaptar_rioplatense(texto)).split())
            prosodia = suavizar_punto_y_coma(hablado)
            posicion = 0
            fragmentos = fragmentar(hablado)
            for fragmento in fragmentos:
                with tempfile.TemporaryDirectory(prefix='hermes-tts-') as carpeta:
                    # La sustitución conserva longitud; los cortes siguen usando
                    # el texto previo y las citas se protegen incluso entre cortes.
                    salida = prosodia[posicion:posicion + len(fragmento)]
                    posicion += len(fragmento) + 1
                    ruta = self.tts.generar(salida, carpeta)
                    if 'Primer audio' not in self.tiempos:
                        self.tiempos['Primer audio'] = time.monotonic() - inicio
                    ejecutar(['/usr/bin/afplay', str(ruta)], self.config.timeout_tts)
            return True
        except (Exception, KeyboardInterrupt) as exc:
            self.tts.cerrar()
            mostrar('No pude reproducir la voz. ' + self.error('TTS', exc))
            return False
        finally:
            self.tiempos['TTS total'] = time.monotonic() - inicio

    def transcribir(self, ruta):
        if not self.config.stt_modelo.is_file():
            raise RuntimeError(f'Falta el modelo STT: {self.config.stt_modelo}')
        destino = ruta.with_suffix('')
        ejecutar([self.config.whisper, '-m', str(self.config.stt_modelo), '-f', str(ruta),
                  '-l', 'es', '-otxt', '-of', str(destino), '-nt', '-ng'], self.config.timeout_stt)
        return destino.with_suffix('.txt').read_text().strip()

    def escuchar(self, mostrar=print):
        try:
            mostrar('🎙️ Escuchando...')
            with tempfile.TemporaryDirectory(prefix='hermes-stt-') as carpeta:
                ruta = Path(carpeta) / 'microfono.wav'
                with self.medir('Captura'):
                    detectada = capturar(ruta, self.config.segundos)
                if not detectada:
                    mostrar('No reconocí voz. Volvé a intentar con Escuchame.')
                    return None
                with self.medir('STT'):
                    texto = self.transcribir(ruta).strip()
            if not texto or re.fullmatch(r'[\[(*].*[\])*]', texto):
                mostrar('No reconocí palabras. Volvé a intentar con Escuchame.')
                return None
            mostrar(f'Vos (voz): {texto}')
            return texto
        except KeyboardInterrupt:
            mostrar('Captura/transcripción cancelada.')
        except Exception as exc:
            mostrar('No pude reconocer la voz. ' + self.error('STT', exc))
        return None

    @contextmanager
    def medir(self, etapa):
        inicio = time.monotonic()
        try:
            yield
        finally:
            self.tiempos[etapa] = time.monotonic() - inicio

    def diagnostico(self):
        lineas = [f'{etapa}: {self.tiempos[etapa]:.1f} s' if etapa in self.tiempos
                  else f'{etapa}: sin medición'
                  for etapa in ('Captura', 'STT', 'Procesamiento', 'Primer audio', 'TTS total')]
        return '\n'.join([f'Motor TTS: Supertonic; voz: {self.config.voz}; idioma: {self.config.idioma}; velocidad: {self.config.velocidad}'] + lineas + [self.politica_memoria])

    def auditar(self):
        c = self.config
        cli = c.supertonic / '.venv/bin/supertonic'
        archivos = ['onnx/tts.json', 'onnx/unicode_indexer.json',
                    'onnx/duration_predictor.onnx', 'onnx/text_encoder.onnx',
                    'onnx/vector_estimator.onnx', 'onnx/vocoder.onnx',
                    f'voice_styles/{c.voz}.json']
        cache_ok = all((c.tts_cache / nombre).is_file() for nombre in archivos)
        return '\n'.join([
            f"Modo voz: {'activo' if self.activa else 'inactivo'} (sesión)",
            f'Micrófono: {microfono_estado()}',
            f"STT: whisper.cpp, español, CPU; ejecutable: {shutil.which(c.whisper) or 'no encontrado'}",
            f"Modelo STT: {c.stt_modelo} ({'disponible' if c.stt_modelo.is_file() else 'falta'})",
            f'TTS: Supertonic; voz {c.voz}; idioma {c.idioma}; velocidad {c.velocidad}; modelo {c.modelo}',
            f"Ejecutable TTS: {cli} ({'disponible' if cli.is_file() and os.access(cli, os.X_OK) else 'falta'})",
            f"Python TTS: {c.supertonic / '.venv/bin/python'}",
            f"Caché TTS: {c.tts_cache} ({'archivos presentes; integridad sin verificar' if cache_ok else 'faltan archivos'})",
            f"Motor propio: {'cargado' if self.tts.activo() and self.tts.cargado else 'inactivo/no cargado'}",
            self.politica_memoria,
            'Errores recientes: ' + (' | '.join(self.errores) or 'ninguno'),
        ])

    def comando(self, mensaje):
        n = normalizar(mensaje)
        if n == 'diagnostico de voz':
            return self.diagnostico(), None, True
        if n in ('modo voz rapido', 'modo voz calidad'):
            return 'Supertonic usa M2, español y velocidad 1.15; los modos rápido/calidad de Qwen fueron retirados.', None, True
        if n in ('activa modo voz', 'activar modo voz'):
            self.activa = True
            return 'Modo voz activado.', None, False
        if n in ('desactiva modo voz', 'desactivar modo voz'):
            self.activa = False
            self.tts.cerrar()
            return 'Modo voz desactivado.', None, False
        if n == 'estado de voz':
            return f"Modo voz {'activo' if self.activa else 'inactivo'}. TTS: Supertonic; voz {self.config.voz}; idioma {self.config.idioma}; velocidad {self.config.velocidad}.", None, False
        if n in ('audita la voz', 'auditar la voz'):
            return self.auditar(), None, True
        if re.match(r'^(decime|lee) esto en voz alta\s*:', n):
            texto = mensaje.split(':', 1)[1].strip()
            return texto or 'Indicá un texto después de los dos puntos.', texto or None, False
        return None

    def turno(self, mensaje, procesar, mostrar=print):
        """Único límite de entrada/salida; procesar es el flujo textual original."""
        es_captura = normalizar(mensaje) == 'escuchame'
        if es_captura:
            self.tiempos = {}
            mensaje = self.escuchar(mostrar)
            if not mensaje:
                return True
            if normalizar(mensaje) == 'escuchame':
                mostrar('Hermes: Para otra captura, escribí Escuchame.')
                return True
        if mensaje.lower().strip() == 'salir':
            return False
        control = self.comando(mensaje)
        if control is None:
            if not es_captura and self.activa:
                self.tiempos = {}
            if es_captura or self.activa:
                with self.medir('Procesamiento'):
                    respuesta = procesar(mensaje)
            else:
                respuesta = procesar(mensaje)
            explicito, silencioso = None, False
        else:
            respuesta, explicito, silencioso = control
        mostrar(f'\nHermes: {respuesta}\n')
        if not silencioso and (explicito or self.activa):
            if explicito and not es_captura:
                self.tiempos = {}
            anteriores = self.tiempos.copy()
            try:
                self.hablar(explicito or respuesta, mostrar)
            finally:
                # Consultar estado o cambiar modo no pisa el diagnóstico del turno.
                if control is not None and not explicito:
                    self.tiempos = anteriores
        return True

    def cerrar(self):
        self.tts.cerrar()

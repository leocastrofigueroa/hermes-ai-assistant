"""Worker Supertonic local; ejecutar con el Python de su instalación separada."""
import contextlib
import json
import os
from pathlib import Path
import sys


def servir(cache, entrada, salida, modelo='supertonic-3'):
    motor = None
    estilos = {}
    for linea in entrada:
        try:
            pedido = json.loads(linea)
            with contextlib.redirect_stdout(sys.stderr):
                if motor is None:
                    from supertonic import TTS
                    motor = TTS(model=modelo, model_dir=cache, auto_download=False)
                nombre = pedido['voz']
                if nombre not in estilos:
                    estilos[nombre] = motor.get_voice_style(nombre)
                audio, _ = motor.synthesize(
                    text=pedido['texto'], voice_style=estilos[nombre],
                    lang=pedido['idioma'], speed=pedido['velocidad'], total_steps=8)
                ruta = Path(pedido['carpeta']) / 'voz.wav'
                motor.save_audio(audio, str(ruta))
            respuesta = {'ruta': str(ruta)}
        except Exception as exc:
            # No enviar texto privado ni excepciones de biblioteca que lo incluyan.
            respuesta = {'error': f'Supertonic: {type(exc).__name__}; revisá Auditá la voz'}
        salida.write(json.dumps(respuesta) + '\n')
        salida.flush()


if __name__ == '__main__':
    # Aislar también mensajes nativos de ONNX escritos directamente al descriptor 1.
    with os.fdopen(os.dup(sys.stdout.fileno()), 'w', buffering=1) as protocolo:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        servir(Path(sys.argv[1]).resolve(), sys.stdin, protocolo, sys.argv[2])

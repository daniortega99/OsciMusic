import threading
import time
import numpy as np
import keyboard
import sounddevice as sd
import mido



def midi_note_to_frequency(note):
    """
    Convierte una nota MIDI a su frecuencia correspondiente.
    """
    return 440.0 * (2.0 ** ((note - 69) / 12.0))

def analyze_midi_melody(midi_file, max_frequency=2000.0):
    """
    Analiza un archivo MIDI y devuelve una lista de tuplas (frecuencia, duración).
    Limita la frecuencia máxima para evitar sonidos agudos desagradables.
    """
    MAX_NOTE_DURATION = 5.0
    MIN_NOTE_DURATION = 0.05
    MAX_SILENCE_DURATION = 0.3
    DEFAULT_TEMPO = 500000

    melody_data = []
    active_notes = {}
    midi_data = mido.MidiFile(midi_file)
    tempo = DEFAULT_TEMPO
    ticks_per_beat = midi_data.ticks_per_beat
    ticks_to_seconds = (tempo / 1_000_000) / ticks_per_beat

    current_time = 0
    last_event_time = 0
    current_frequency = 0

    main_track = max(midi_data.tracks, key=lambda track: sum(1 for msg in track if msg.type == 'note_on'))

    for msg in main_track:
        if msg.type == 'set_tempo':
            tempo = msg.tempo
            ticks_to_seconds = (tempo / 1_000_000) / ticks_per_beat

        current_time += msg.time * ticks_to_seconds

        if msg.type == 'note_on' and msg.velocity > 0:
            note = msg.note
            frequency = midi_note_to_frequency(note)

            # Limitar la frecuencia máxima
            if frequency > max_frequency:
                frequency = max_frequency

            if frequency != current_frequency or current_time - last_event_time > MIN_NOTE_DURATION:
                if current_frequency != 0:
                    duration = current_time - last_event_time
                    melody_data.append((current_frequency, max(MIN_NOTE_DURATION, min(duration, MAX_NOTE_DURATION))))

                current_frequency = frequency
                last_event_time = current_time

        elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            if current_frequency != 0:
                duration = current_time - last_event_time
                melody_data.append((current_frequency, max(MIN_NOTE_DURATION, min(duration, MAX_NOTE_DURATION))))
                current_frequency = 0
                last_event_time = current_time

    if current_frequency != 0:
        duration = current_time - last_event_time
        melody_data.append((current_frequency, max(MIN_NOTE_DURATION, min(duration, MAX_NOTE_DURATION))))

    cleaned_melody = []
    for frequency, duration in melody_data:
        if frequency == 0 and duration > MAX_SILENCE_DURATION:
            continue
        cleaned_melody.append((frequency, duration))

    return cleaned_melody



"""
------------ DECLARACIÓN DE PARÁMETROS Y VARIABLES -----------------
"""

# Diccionario de archivos
files_npz = {
    'peli': 'peli_redimensionado.npz',
    'text': 'text_redimensionado.npz',
    'break1': 'break1_redimensionado.npz',
    'car2': 'car2_redimensionado.npz',
    'gameboy'   : 'gameboy_redimensionado.npz',
    'cube': 'cube_redimensionado.npz'
}

AUDIO_MODE = "COMPLEX" # ORDENADOR O COMPLEX

# Paramétros de reproducción de audio.
midi_parameters = {
    "frequency": 50.0,  # Frecuencia MIDI inicial (A4)
    "selected_animation": 1,  # Animación seleccionada inicialmente
    "phasor" : 0,
    "n_bits_phasor": 12,
    "TABLE_SIZE": 2 ** 12,
    "audio_buffer_len": 512, 
    "FREQ_SAMPLE": 44100,
    "AUDIO_DEVICE": 34,
    "song_mode": False,
    "song_notes": [],
    "current_note_idx": 0,
    "note_duration": 0.5,
    "pause_mode": False
}

# Parámetros de reproducción por defecto del vídeo
video_parameters = {
    "fps": 25,              # Número de frames por segundo (velocidad de reproducción)
    "selected_animation": 2, # Animación que va a reproducirse (0: primera animación)
    "effect": "none"        # Efecto aplicado a los datos (por ejemplo, "none", "echo", "distortion")
}

# Archivo MIDI 
midi_file = "Techno-3.MID"  # Nombre del archivo MIDI predefinido

# Analizar la canción y almacenar las notas
try:
    midi_parameters["song_notes"] = analyze_midi_melody(midi_file)
    print(f"[INFO] Canción '{midi_file}' analizada y lista para reproducción.")
except Exception as e:
    print(f"[ERROR] No se pudo analizar la canción '{midi_file}': {e}")
    midi_parameters["song_notes"] = []


# Inicialización de variables de audio
phasor = 0
frame_idx = 0
rotation = 0
distortion = 0
increment = 0
scale = 1.0
paused_frame_idx = 0  # Índice del frame pausado
last_note_change_time = 0  # Tiempo de la última actualización de nota en el modo canción

# Variables para almacenar el último valor de rotación y la matriz de rotación cacheada
last_rotation = None
rotation_matrix = None

current_wave = np.zeros((midi_parameters["TABLE_SIZE"], 2), dtype=np.float64)  # Tabla para la animación actual
sd.default.samplerate = midi_parameters["FREQ_SAMPLE"]
sd.default.device = midi_parameters["AUDIO_DEVICE"]

# Variable para controlar la finalización del programa
exit_flag = False

# Diccionario para almacenar la caché de animaciones
animation_cache = {}

# Evento para notificar que la caché está creada
data_processed_event = threading.Event()

# Evento para notificar que ha comenzado la reproducción
data_playback_event = threading.Event()

# Configuración de dispositivos y canales según el modo
if AUDIO_MODE == "ORDENADOR":
    midi_parameters["NUM_CHANNELS"] = 2  # Estéreo para altavoces del ordenador
elif AUDIO_MODE == "COMPLEX":
    midi_parameters["NUM_CHANNELS"] = 8   # Salida multicanal para osciloscopio y altavoces externos
else:
    raise ValueError("Dispositivo de audio no válido.")




"""
---------------------------- FUNCIONES ----------------------------
"""


def play_song():
    """
    Reproduce la melodía cargada, actualizando la frecuencia según las notas.
    """
    global increment, last_note_change_time

    current_time = time.time()
    MAX_DURATION = 2.0  # Duración máxima para cualquier nota, en segundos

    if midi_parameters["song_mode"] and midi_parameters["song_notes"]:
        # Verificar si es momento de cambiar a la siguiente nota
        if current_time - last_note_change_time >= min(midi_parameters["note_duration"], MAX_DURATION):
            current_idx = midi_parameters["current_note_idx"]
            note, duration = midi_parameters["song_notes"][current_idx]

            # Actualizar la frecuencia según la nota MIDI
            frequency = note
            midi_parameters["frequency"] = frequency

            # Calcular el incremento basado en la frecuencia actual
            increment = compute_incremento(midi_parameters["frequency"])

            # Limitar la duración de la nota a un máximo de MAX_DURATION
            midi_parameters["note_duration"] = min(duration, MAX_DURATION)
            last_note_change_time = current_time

            print(f"[INFO] Nota actual: {note} - Frecuencia: {frequency:.2f} Hz")

            # Avanzar al siguiente índice de nota
            midi_parameters["current_note_idx"] += 1

            # Reiniciar el índice si se llega al final de la canción
            if midi_parameters["current_note_idx"] >= len(midi_parameters["song_notes"]):
                midi_parameters["current_note_idx"] = 0



def midi_note_to_frequency(note):
    """
    Convierte una nota MIDI a su frecuencia correspondiente.
    """
    return 440.0 * (2.0 ** ((note - 69) / 12.0))

def handle_control_change(control, value):
    """
    Maneja los controles MIDI (knobs y sliders). Los cambios serán permanentes.
    """
    print(control, value)
    global increment
    
    if control == 72:
        # Knob 1: Ajuste de escala
        adjust_scale(value)
    elif control == 16:
        # Knob 2: Ajuste de rotación
        adjust_rotation(value)
    elif control == 79:
        # Knob 3: Ajuste de distorsión
        adjust_distortion(value)
    elif control == 19:
        # Knob 4: Ajuste de FPS
        adjust_fps(value)
    elif control == 91:
        # Knob 5: Efecto adicional (reserva para futuro)
        pass
    elif control == 18:
        # Knob 6: Efecto adicional (reserva para futuro)
        pass
    elif control == 17:
        # Knob 7: Efecto adicional (reserva para futuro)
        pass
    elif control == 114:
        # Knob 8: Efecto adicional (reserva para futuro)
        pass

    # Slider 1 (control 75): Modo pausa
    elif control == 75:
        if value >= 64 and not midi_parameters["pause_mode"]:
            midi_parameters["pause_mode"] = True
            global paused_frame_idx
            paused_frame_idx = frame_idx  # Almacenar el índice del frame actual
            print(f"[INFO] Modo de pausa activado en el índice de frame: {paused_frame_idx}")
        elif value < 64 and midi_parameters["pause_mode"]:
            midi_parameters["pause_mode"] = False
            print("[INFO] Modo de pausa desactivado.")

    # Slider 2 (control 73): Modo canción
    elif control == 73:
        if value >= 64:
            midi_parameters["song_mode"] = True
            midi_parameters["current_note_idx"] = 0
            print("[INFO] Modo canción activado.")
        else:
            midi_parameters["song_mode"] = False
            print("[INFO] Modo canción desactivado. Volviendo al modo normal.")

    # Sliders 3 a 8 para seleccionar animaciones
    elif control == 93:  # Slider 3
        if value >= 64:
            video_parameters["selected_animation"] = 0
            print("[INFO] Animación 1 seleccionada (baile1).")
    elif control == 77:  # Slider 4
        if value >= 64:
            video_parameters["selected_animation"] = 1
            print("[INFO] Animación 2 seleccionada (baile2).")
    elif control == 76:  # Slider 5
        if value >= 64:
            video_parameters["selected_animation"] = 2
            print("[INFO] Animación 3 seleccionada (break1).")
    elif control == 71:  # Slider 6
        if value >= 64:
            video_parameters["selected_animation"] = 3
            print("[INFO] Animación 4 seleccionada (break2).")
    elif control == 74:  # Slider 7
        if value >= 64:
            video_parameters["selected_animation"] = 4
            print("[INFO] Animación 5 seleccionada (stand).")
    elif control == 7:  # Slider 8
        if value >= 64:
            video_parameters["selected_animation"] = 5
            print("[INFO] Animación 6 seleccionada (Triangulo).")
    else:
        # Rango de frecuencias
        FREQ_MIN = 0.2  # Hz
        FREQ_MAX = 2000  # Hz
        frequency = FREQ_MIN * (FREQ_MAX / FREQ_MIN) ** (value / 127)
        midi_parameters['frequency'] = frequency
        increment = compute_incremento(midi_parameters["frequency"])
        print(f"Frecuencia ajustada a: {frequency} Hz")


def adjust_fps(value):
    """
    Ajusta los FPS de la animación utilizando el Knob 4.
    El rango de FPS es de 10 a 70.
    """
    # Mapea el valor del controlador (0-127) al rango de FPS (10-70)
    min_fps = 10
    max_fps = 120
    fps = min_fps + (max_fps - min_fps) * (value / 127.0)
    video_parameters["fps"] = int(fps)
    print(f"[INFO] FPS ajustado a: {video_parameters['fps']}")

def adjust_scale(value):
    """
    Ajusta el escalado de la señal (visual y de audio).
    """
    global scale
    # Escalar entre un mínimo (0.1) y un máximo (2.0)
    scale = 0.1 + (1.9 * value) / 127
    print(f"[INFO] Escalado ajustado a: {scale:.2f}")



def adjust_rotation(value):
    """
    Ajusta la rotación de la animación.
    """
    global rotation
    # Rotar de 0 a 360 grados según el valor del controlador
    rotation = (value / 127.0) * 360.0
    print(f"[INFO] Rotación ajustada a: {rotation:.2f} grados")



def adjust_distortion(value):
    """
    Ajusta la distorsión de la señal.
    """
    global distortion
    # Distorsión ajustada entre 0 (sin distorsión) y 0.8 (máxima distorsión controlada)
    distortion = (value / 127.0) * 0.8
    print(f"[INFO] Distorsión ajustada a: {distortion:.2f}")


def apply_effects(frame, scale_factor=1.0, rotation_degrees=0, distortion_level=0):
    """
    Aplica escalado, rotación, inversión del eje Y, distorsión y normalización a un frame con optimizaciones.
    """
    global last_rotation, rotation_matrix

    # 1. Aplicar escalado con un valor mínimo
    frame_scaled = frame * scale_factor

    # 2. Invertir el eje Y para corregir la orientación
    frame_scaled[:, 1] *= -1

    # 3. Calcular la matriz de rotación solo si el ángulo ha cambiado
    if rotation_degrees != last_rotation:
        radians = np.deg2rad(rotation_degrees)
        cos_theta = np.cos(radians)
        sin_theta = np.sin(radians)
        rotation_matrix = np.array([[cos_theta, -sin_theta], [sin_theta, cos_theta]])
        last_rotation = rotation_degrees

    # 4. Aplicar rotación usando la matriz cacheada
    frame_rotated = np.dot(frame_scaled, rotation_matrix)

    # 5. Aplicar distorsión suavizada
    if distortion_level > 0:
        gain = 5 * distortion_level
        frame_distorted = np.tanh(gain * frame_rotated)
    else:
        frame_distorted = frame_rotated

    # 6. Normalizar la señal para evitar cambios en el volumen
    max_val = np.max(np.abs(frame_distorted))
    if max_val > 0:
        frame_normalized = frame_distorted / max_val
    else:
        frame_normalized = frame_distorted

    return frame_normalized




def normalize(frame):
    """
    Normaliza un frame
    """

    max_val = np.max(np.abs(frame))  # Encuentra el valor máximo absoluto en los datos
    if max_val > 0:  # Evita división por cero
        frame_normalized = ((frame / max_val)-0.5)*2  # Normaliza los datos a un rango de [-1, 1]
    else:
        frame_normalized = frame

    return frame_normalized

def load_animation(file):
    """
    Carga un archivo .npz, aplica una rotación inicial de 90 grados y convierte los datos en float64.
    """
    # Matriz de rotación para 90 grados en el sentido de las agujas del reloj
    radians_90 = np.deg2rad(90)
    rotation_matrix_90 = np.array([[np.cos(radians_90), -np.sin(radians_90)],
                                    [np.sin(radians_90), np.cos(radians_90)]])

    data = np.load(file)
    animation = {}

    for key in data.files:
        frame = np.array(data[key], dtype=np.float64)
        # Aplicar la rotación inicial a cada frame
        animation[key] = np.dot(frame, rotation_matrix_90)

    return animation


def get_audio_buffer_from_wave(bits_idx, incr, tabla_datos_xy):
    """
    LLena el buffer de audio desde la tabla de ondas.
    Si el programa está terminando, llena el buffer con ceros.
    """
    global phasor
    lr_channel = np.zeros((midi_parameters["audio_buffer_len"], 2))
    
    if tabla_datos_xy is not None and len(tabla_datos_xy) > 0:
        max_val = np.max(np.abs(tabla_datos_xy))
        if max_val > 0:
            tabla_datos_xy = tabla_datos_xy / max_val

        bit_shift = 32 - bits_idx  # Calcular fuera del ciclo
        for i in range(midi_parameters["audio_buffer_len"]):
            idx = phasor >> bit_shift
            
            # Asegúrate de que el índice no exceda los límites de tabla_datos_xy
            if idx >= len(tabla_datos_xy):
                idx = idx % len(tabla_datos_xy)  # Envolver el índice si es mayor

            lr_channel[i, :] = tabla_datos_xy[idx, :]
            phasor += incr
            phasor = (phasor & 0xFFFFFFFF)
    else:
        # Si no hay datos en la tabla, devuelve silencio (buffer lleno de ceros)
        lr_channel = np.zeros((midi_parameters["audio_buffer_len"], 2))
    
    return lr_channel

def callback(outdata, frames, time, status):
    """
    Callback para el stream de audio.
    """
    if status:
        print(status)

    if exit_flag:
        outdata.fill(0)
    else:
        # Actualizar el incremento según la frecuencia actual
        global increment
        increment = compute_incremento(midi_parameters["frequency"])

        # Obtener el buffer de audio normalizado
        audio_buffer = normalize(get_audio_buffer_from_wave(midi_parameters["n_bits_phasor"], increment, current_wave))

        if midi_parameters["NUM_CHANNELS"] == 2:
            # Modo PC_SPEAKERS: Salida estéreo
            outdata[:, 0] = audio_buffer[:, 0]  # Canal izquierdo
            outdata[:, 1] = audio_buffer[:, 1]  # Canal derecho

        elif midi_parameters["NUM_CHANNELS"] == 8:
            # Modo AUDIO_INTERFACE: Salida multicanal
            multi_channel_output = np.zeros((frames, 8))
            multi_channel_output[:, 0:2] = audio_buffer  # Canales 1 y 2 (osciloscopio)
            multi_channel_output[:, 2:4] = audio_buffer  # Canales 3 y 4 (altavoces)
            outdata[:] = multi_channel_output

        else:
            raise ValueError("Número de canales no válido.")





def stop_program():
    """
    Detiene todos los hilos y el programa principal
    """
    global exit_flag
    exit_flag = True
    print("[INFO] El programa se está cerrando...")
    try:
        # Detener el stream sin comprobar si está activo
        sd.stop()
    except Exception as e:
        print(f"[ERROR] No se pudo detener el stream de audio: {e}")


def compute_incremento(freq):
    """
    Calcula el incremento del fasor basado en la frecuencia deseada.
    """
    incremento = int(pow(2, 32) * float(freq) / midi_parameters["FREQ_SAMPLE"])
    return incremento



"""
---------------------------- ESTRUCTURA DE HILOS -----------------------------
"""

def analysis_thread(files_npz):
    """
    Hilo que carga las animaciones y crea la caché.
    """
    global animation_cache

    while not exit_flag:
        try:
            print("[INFO] Cargando animaciones...")
            start_time = time.time()

            for name, file in files_npz.items():
                # Cargar cada archivo y almacenarlo en la caché
                animation_cache[name] = load_animation(file)
                print(f"[INFO] Animación '{name}' cargada exitosamente.")

            # Notificar que la caché está lista
            elapsed_time = time.time() - start_time
            print(f"[INFO] Caché creada exitosamente en {elapsed_time:.2f} segundos.")
            data_processed_event.set()  # Activar el evento para notificar que la caché está lista
            break

        except Exception as e:
            print(f"[ERROR] Error en el hilo de análisis: {e}")
            break

    
def playback_thread():
    """
    Hilo de reproducción de audio, que reproduce los frames de la animación en el osciloscopio.
    """
    global exit_flag, current_wave, frame_idx, increment, paused_frame_idx

    increment = compute_incremento(midi_parameters["frequency"])
    data_processed_event.wait()

    # Inicializar el stream de audio solo una vez
    try:
        stream = sd.OutputStream(
            channels=midi_parameters["NUM_CHANNELS"],
            callback=callback,
            samplerate=midi_parameters["FREQ_SAMPLE"],
            blocksize=midi_parameters["audio_buffer_len"],
            device=midi_parameters["AUDIO_DEVICE"]
        )
        with stream:
            previous_animation = video_parameters["selected_animation"]

            while not exit_flag:
                # Recalcular el intervalo de tiempo para los FPS dinámicamente
                fps_interval = 1.0 / video_parameters["fps"]

                # Obtener el nombre de la animación seleccionada dinámicamente
                selected_animation_name = list(files_npz.keys())[video_parameters["selected_animation"]]

                # Verificar si la animación ha cambiado
                if video_parameters["selected_animation"] != previous_animation:
                    print(f"[INFO] Cambio de animación detectado. Nueva animación: {selected_animation_name}")
                    frame_idx = 0  # Reiniciar el índice de frame
                    previous_animation = video_parameters["selected_animation"]

                # Verificar si la animación está en la caché
                if selected_animation_name in animation_cache:
                    animation_data = animation_cache[selected_animation_name]
                    frames = [np.array(frame, dtype=np.float64) for frame in animation_data.values()]

                    # Verificar que frame_idx no exceda el número de frames
                    if frame_idx >= len(frames):
                        frame_idx = 0

                    if midi_parameters["pause_mode"]:
                        # Reproducir el frame pausado
                        current_wave = apply_effects(frames[paused_frame_idx], scale_factor=scale, rotation_degrees=rotation, distortion_level=distortion)
                    else:
                        # Modo canción: actualizar la frecuencia automáticamente
                        if midi_parameters["song_mode"]:
                            play_song()

                        # Reproducción normal de la animación
                        current_wave = apply_effects(frames[frame_idx], scale_factor=scale, rotation_degrees=rotation, distortion_level=distortion)
                        frame_idx += 1

                else:
                    print(f"[ERROR] La animación '{selected_animation_name}' no está disponible en la caché.")

                # Esperar el intervalo calculado para el nuevo FPS
                time.sleep(fps_interval)

    except Exception as e:
        print(f"[ERROR] Error al iniciar la reproducción de audio: {e}")

    print("[INFO] Hilo de reproducción terminado.")



def parameters_thread(port_name):
    """
    Hilo que recibe mensajes MIDI y ajusta los parámetros globales.
    """
    global increment

    data_processed_event.wait() # Esperar a que
    print(f"Abriendo puerto MIDI: {port_name}")
    inport = mido.open_input(port_name)

    try:
        while not exit_flag:
            fps_interval = 1.0/video_parameters["fps"]
            for msg in inport.iter_pending():
                if msg.type == 'note_on' and msg.velocity > 0:
                    # Ajustar frecuencia según la nota tocada
                    frequency = midi_note_to_frequency(msg.note)
                    midi_parameters['frequency'] = frequency
                    increment = compute_incremento(midi_parameters["frequency"])
                    print(f"Frecuencia ajustada a: {frequency} Hz")
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    pass
                elif msg.type == 'control_change':
                    control = msg.control
                    value = msg.value
                    handle_control_change(control, value)
                else: 
                    pass
            time.sleep(fps_interval)

    except KeyboardInterrupt:
        print("Interrumpido por el usuario. Cerrando el puerto MIDI.")
    finally:
        inport.close()
        print(f"[INFO] Puerto MIDI {port_name} cerrado.")

def keyboard_listener_thread():
    """
    Hilo para detectar la pulsación de 'Escape' y otras teclas del teclado
    """

    global exit_flag
    print("[INFO] Presiona 'Esc' para finalizar el programa.")
    keyboard.add_hotkey('esc', stop_program)

    while not exit_flag:
        time.sleep(0.1)




"""
------------ EJECUCIÓN DEL PROGRAMA PRINCIPAL ------------ 
"""

def main():
    start_time = time.time()

    # Creación de los hilos
    analysis = threading.Thread(target=analysis_thread, args=(files_npz,))
    playback = threading.Thread(target=playback_thread)
    keyboard_listener = threading.Thread(target=keyboard_listener_thread, daemon=True)
    midi_listener = threading.Thread(target=parameters_thread, args=('WORLDE    0',), daemon=True)

    keyboard_listener.start()
    midi_listener.start()
    analysis.start()
    playback.start()

    # Esperar a que los hilos terminen
    analysis.join()
    playback.join()

    if exit_flag:
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"[INFO] Programa finalizado en {elapsed_time} segundos.")

if __name__ == "__main__":
    main()

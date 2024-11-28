import numpy as np
import xml.etree.ElementTree as ET
import os

# Ruta de los archivos SVG subidos
svg_files = [
    "cube.svg"
]

# Convierte una cadena de coordenadas en una lista de coordenadas numéricas
def string_a_lista(coordenadas_str):
    coordenadas_lista = coordenadas_str.split()
    coordenadas = []
    for i in range(0, len(coordenadas_lista), 2):
        coordenada_x = float(coordenadas_lista[i].split(',')[0])
        coordenada_y = float(coordenadas_lista[i+1])
        coordenadas.append([coordenada_x, coordenada_y])
    return np.array(coordenadas, dtype=np.float32)

# Obtiene los frames de un archivo SVG
def obtener_frames(nombre):
    lista_total = []
    tree = ET.parse(nombre)
    root = tree.getroot()
    namespaces = {
        'svg': 'http://www.w3.org/2000/svg',
        'inkscape': 'http://www.inkscape.org/namespaces/inkscape'
    }

    # Encuentra los frames que contienen grupos de paths
    frames = root.findall(".//svg:g[@inkscape:groupmode='frame']", namespaces)
    for f in frames:
        lista_de_paths = []
        paths = f.findall(".//svg:path", namespaces)
        for p in paths:
            path = p.get('d')
            path_sinM = path[3:]
            lista_de_coordenadas = string_a_lista(path_sinM)
            lista_de_paths.append(lista_de_coordenadas)
        lista_total.append(lista_de_paths)

    return lista_total

# Calcula las distancias entre puntos en un path
def calcular_distancias(path_list):
    distancias_list = []
    for path in path_list:
        path = np.array(path)
        num_puntos = len(path)
        distancias = np.zeros(num_puntos - 1)
        for i in range(num_puntos - 1):
            distancia = np.sqrt((path[i + 1][0] - path[i][0])**2 + (path[i + 1][1] - path[i][1])**2)
            distancias[i] = distancia
        distancias_list.append(distancias)
    return distancias_list

# Redimensiona un vector a la nueva longitud deseada
def redimensiona(vector, nueva_longitud, distancias):
    if nueva_longitud <= len(vector):
        return vector

    puntos = nueva_longitud - len(vector)
    distancia_total = np.sum(distancias)
    fracciones = distancias / distancia_total
    redimensionado = []
    resto = 0
    num_puntos = np.zeros_like(distancias)
    num_puntos_real = fracciones * puntos

    for i in range(len(num_puntos) - 1):
        npt = num_puntos_real[i]
        npr = round(npt)
        resto += npt - npr
        if resto >= 1:
            npr += 1
            resto -= 1
        elif resto <= -1:
            npr -= 1
            resto += 1
        num_puntos[i] = max(npr + 1, 1)

    num_puntos[-1] = nueva_longitud - (num_puntos.sum() - num_puntos[-1])
    num_puntos[-1] = max(num_puntos[-1], 1)

    for i in range(len(vector) - 1):
        punto1 = vector[i]
        punto2 = vector[i + 1]
        intermedios = np.linspace(punto1, punto2, int(num_puntos[i]), endpoint=False)
        redimensionado = np.concatenate((redimensionado, intermedios))

    redimensionado = np.concatenate((redimensionado, [vector[-1]]))

    return redimensionado

# Redimensiona y concatena paths de un frame
def redimensiona_y_concatena(path_list, nueva_longitud):
    distancias_list = calcular_distancias(path_list)
    distancia_total = sum(np.sum(dist) for dist in distancias_list)

    total_points = 0
    all_points = []
    for path, distancias in zip(path_list, distancias_list):
        path = np.array(path)
        n = int(round(nueva_longitud * np.sum(distancias) / distancia_total))
        concatenado_x = redimensiona(path[:, 0], n, distancias)
        concatenado_y = redimensiona(path[:, 1], n, distancias)
        narr = np.column_stack((concatenado_x, concatenado_y))
        all_points.append(narr)
        total_points += len(narr)

    if total_points > nueva_longitud:
        redimensionado = np.vstack(all_points)[:nueva_longitud]
    else:
        redimensionado = np.vstack(all_points)
        indices_originales = np.linspace(0, len(redimensionado) - 1, len(redimensionado))
        indices_nuevos = np.linspace(0, len(redimensionado) - 1, nueva_longitud)
        redimensionado_x = np.interp(indices_nuevos, indices_originales, redimensionado[:, 0])
        redimensionado_y = np.interp(indices_nuevos, indices_originales, redimensionado[:, 1])
        redimensionado = np.column_stack((redimensionado_x, redimensionado_y))

    return redimensionado

# Procesa y guarda las animaciones redimensionadas
def procesa_multiples_animaciones(archivos_svg, nueva_longitud, verbose=False):
    for archivo in archivos_svg:
        if verbose:
            print(f"Procesando archivo: {archivo}")
        frame_list = obtener_frames(archivo)

        frames_dict = {}
        for frame_idx, path_list in enumerate(frame_list):
            if not path_list:  # Si el frame está vacío, rellenarlo con ceros
                if verbose:
                    print(f"Frame {frame_idx + 1} está vacío. Se rellenará con ceros.")
                redimensionado = np.zeros((nueva_longitud, 2), dtype=np.float32)
            else:
                redimensionado = redimensiona_y_concatena(path_list, nueva_longitud)

            frames_dict[f"frame_{frame_idx + 1}"] = redimensionado

            if verbose:
                print(f"Frame {frame_idx + 1} redimensionado con {len(redimensionado)} puntos.")

        nombre_archivo = f"{os.path.splitext(archivo)[0]}_redimensionado.npz"
        np.savez_compressed(nombre_archivo, **frames_dict)

        if verbose:
            print(f"Archivo guardado: {nombre_archivo}")


# Ejecutar el preprocesado para todos los archivos SVG
NUEVA_LONGITUD = 4096
procesa_multiples_animaciones(svg_files, NUEVA_LONGITUD, verbose = True)

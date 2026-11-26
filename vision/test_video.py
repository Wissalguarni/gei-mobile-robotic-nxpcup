"""Test image par image du code actuel, sans suivi temporel ni classification."""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from threshold import thresholding_noise_removal
from track_center_detection import (find_regions, find_region_centers, track_boundaries, compute_track_centers,)

def draw_points(image, coordinates, color, cross=False):#fonction pour dessiner les points sur l'image
    if not len(coordinates):#si la liste des coordonnées est vide, on ne fait rien
        return 
    points = np.rint(coordinates).astype(np.int32).reshape(-1, 2) #np.rint arrondit les coordonnées à l'entier le plus proche, astype(np.int32) convertit les coordonnées en entiers 32 bits, reshape(-1, 2) transforme le tableau en une forme de (n, 2) pour représenter les points
    cv2.polylines(image, [points], False, color, 2, cv2.LINE_AA)#polylines dessine des lignes reliant les points dans l'ordre, False signifie que la ligne n'est pas fermée, color est la couleur de la ligne, 2 est l'épaisseur de la ligne, cv2.LINE_AA est le type de ligne (antialiasing)
    for x, y in points: #pour chaque point, on dessine un marqueur ou un cercle selon la valeur de cross
        if cross: #si cross est vrai, on dessine un marqueur en forme de croix, sinon on dessine un cercle rempli
            cv2.drawMarker(image, (int(x), int(y)), color, cv2.MARKER_CROSS, 10, 2)
        else:
            cv2.circle(image, (int(x), int(y)), 3, color, -1)


def main():
    parser = argparse.ArgumentParser(description=__doc__) #argparse est un module qui permet de gérer les arguments passés en ligne de commande, ici on crée un parser avec une description qui est le docstring du fichier
    parser.add_argument('video', type=Path, nargs='?',
                        default=Path(__file__).resolve().parent / 'src_img_piste' / 'Movie on 23-11-2026 at 19.35.mov',
                        help='Vidéo source (par défaut : la vidéo du 23-11-2026).')
    parser.add_argument('--output', type=Path,help='Vidéo MP4 de sortie (CSV au même emplacement).')#l'argument '--output' est optionnel et doit être un chemin vers un fichier vidéo de sortie, si non précisé, il sera généré automatiquement
    args = parser.parse_args()#parse_args() analyse les arguments passés en ligne de commande et les stocke dans l'objet args, on peut ensuite accéder aux valeurs des arguments avec args.video et args.output
    source = args.video.resolve()#resolve() convertit le chemin relatif en chemin absolu, ce qui permet de travailler avec des chemins complets et d'éviter les problèmes liés aux chemins relatifs
    output = (args.output or Path(__file__).resolve().parent / 'dest_img_piste'/ 'test_video.mp4').resolve() #si l'argument '--output' n'est pas précisé, on crée un chemin par défaut dans le dossier 'dest_img_piste' avec le nom du script et l'extension .mp4
    if args.output is None:
        default_output = output
        suffix = 2
        while output.exists() or output.with_suffix('.csv').exists():
            output = default_output.with_name(f'{default_output.stem}_{suffix}.mp4')
            suffix += 1
    report = output.with_suffix('.csv')#on crée un chemin pour le fichier CSV de sortie en remplaçant l'extension du fichier vidéo de sortie par .csv, ce fichier contiendra les diagnostics pour chaque image de la vidéo
    if output.suffix.lower() != '.mp4': #gestion des erreurs : si l'extension du fichier de sortie n'est pas .mp4, on affiche un message d'erreur et on arrête le programme
        parser.error('La sortie doit avoir une extension .mp4.')
    if source in (output, report):
        parser.error('La sortie doit être différente de la source.')
    if output.exists() or report.exists():
        parser.error('La sortie existe déjà : choisir un autre --output.')

    capture = cv2.VideoCapture(str(source)) #videoCapture est une classe de OpenCV qui permet de lire des vidéos, on crée un objet capture en lui passant le chemin de la vidéo source converti en chaîne de caractères
    writer = None #writer est un objet qui sera utilisé pour écrire la vidéo de sortie, on l'initialise à None pour le moment
    count = 0 #initialisation du compteur d'images, on commence à 0 et on l'incrémente à chaque image traitée
    try: #gestion des erreurs : on utilise un bloc try pour s'assurer que les ressources sont libérées correctement même en cas d'erreur
        if not capture.isOpened():
            raise RuntimeError(f'Impossible de lire {source}')
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError('Cadence vidéo invalide.')
        ok, frame = capture.read()
        if not ok:
            raise ValueError('Aucune image lisible dans la vidéo.')
        height, width = frame.shape[:2]
        if height <= 300:
            raise ValueError('La vidéo doit avoir une hauteur supérieure à 300 px pour ce test.')
        lines = np.linspace(int(0.20 * height), int(0.90 * height), 50, dtype=int) #50 lignes sur une zone plus large, adaptée à la hauteur
        output.parent.mkdir(parents=True, exist_ok=True)#on crée le dossier parent du fichier de sortie s'il n'existe pas déjà, parents=True permet de créer tous les dossiers parents nécessaires, exist_ok=True permet de ne pas lever d'erreur si le dossier existe déjà
        # Le bandeau et les éventuels pixels de remplissage ne changent pas les calculs.
        video_size = (width, height + 100 + height % 2) #une seule vue avec un bandeau
        writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*'mp4v'),fps, video_size) #on crée un objet writer pour écrire la vidéo de sortie, on lui passe le chemin du fichier de sortie converti en chaîne de caractères, le codec vidéo mp4v, la cadence fps et la taille de la vidéo video_size
        if not writer.isOpened():
            raise RuntimeError(f'Impossible de créer {output}')
        with report.open('x', newline='', encoding='utf-8') as handle:#on ouvre le fichier CSV de sortie en mode 'x' pour créer un nouveau fichier, newline='' permet de gérer correctement les sauts de ligne, encoding='utf-8' permet d'utiliser l'encodage UTF-8 pour le texte
            log = csv.writer(handle)#on crée un objet log pour écrire dans le fichier CSV, on peut ensuite utiliser log.writerow() pour écrire des lignes dans le fichier
            log.writerow(['frame', 'time_s', 'boundaries', 'left_points', 'right_points', 'track_centers'])
            while ok:#tant que la lecture de l'image est réussie, on traite l'image
                if frame.shape[:2] != (height, width): #erreur si la taille de l'image lue est différente de la taille attendue, cela peut se produire si la vidéo change de résolution en cours de lecture
                    raise ValueError(f'Dimensions différentes à l’image {count}.')
                #traitement par image
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)#on convertit l'image en niveaux de gris pour simplifier le traitement, cv2.COLOR_BGR2GRAY est le code de conversion de couleur de BGR (format par défaut de OpenCV) à gris
                mask = thresholding_noise_removal(gray, blocksize=101, MIN_AREA=1000)#on applique la fonction de seuillage et de suppression du bruit sur l'image en niveaux de gris, avec un blocksize de 101 et une surface minimale de 1000 pixels pour les contours détectés, cela permet d'obtenir un masque binaire où la piste est mise en évidence
                all_centers = [find_region_centers(find_regions(mask, line)) for line in lines]#on trouve les centres des régions détectées pour chaque ligne y définie dans lines, find_regions() détecte les régions blanches dans le masque pour une ligne donnée, et find_region_centers() calcule le centre de chaque région détectée, on obtient ainsi une liste de listes de centres pour chaque ligne
                left, right = track_boundaries(lines, all_centers, max_distance=50)#on détermine les bords gauche et droit de la piste en utilisant les centres détectés pour chaque ligne, track_boundaries() relie les centres entre les lignes pour former des bords continus, max_distance=50 limite la distance maximale entre les centres pour qu'ils soient considérés comme appartenant au même bord
                centers = compute_track_centers(left, right)#on calcule les centres de la piste en prenant la moyenne des coordonnées x des bords gauche et droit pour chaque ligne y, compute_track_centers() retourne une liste de points représentant le centre de la piste pour chaque ligne
                # Vérifier que les centres retournés utilisent les deux bords à la même hauteur.
                left_by_y, right_by_y = dict((y, x) for x, y in left), dict((y, x) for x, y in right)#on crée deux dictionnaires pour associer chaque coordonnée y à la coordonnée x correspondante pour les bords gauche et droit, cela permet de vérifier que les centres calculés sont bien alignés avec les bords détectés
                assert all(y in left_by_y and y in right_by_y
                           and np.isclose(x, (left_by_y[y] + right_by_y[y]) / 2)
                           for x, y in centers)#on vérifie que pour chaque centre calculé, la coordonnée y est présente dans les deux dictionnaires de bords et que la coordonnée x du centre est proche de la moyenne des coordonnées x des bords gauche et droit pour cette ligne y, np.isclose() permet de vérifier si deux valeurs sont proches l'une de l'autre avec une certaine tolérance

                normal_view = frame.copy() #dessins sur une copie couleur
                for line in (lines[0], lines[-1]):#on dessine les lignes horizontales correspondant aux premières et dernières lignes définies dans lines pour visualiser la zone de détection de la piste
                    cv2.line(normal_view, (0, int(line)), (width - 1, int(line)), (255, 255, 0), 1)
                # Dessiner les points détectés sur les images de sortie
                draw_points(normal_view, left, (0, 255, 255))
                draw_points(normal_view, right, (255, 0, 255))
                draw_points(normal_view, centers, (255, 0, 0), cross=True)
                boundaries = int(bool(left)) + int(bool(right))#boundaries est le nombre de bords détectés, on compte 1 pour le bord gauche s'il existe et 1 pour le bord droit s'il existe, ce qui donne un total de 0, 1 ou 2 bords détectés
                stamp = count / fps
                diagnostic = (f'Image {count} | {stamp:.2f}s | Bords {boundaries}/2 '
                              f'(G:{len(left)} D:{len(right)}) | Centres {len(centers)}')
                canvas = np.full((video_size[1], video_size[0], 3), 245, dtype=np.uint8)
                canvas[100:100 + height, :width] = normal_view
                for text, origin in [(diagnostic, (12, 25)),
                                     (f'Gauche: jaune | Droite: magenta | Centres: bleu | Zone y={lines[0]}..{lines[-1]} (50 lignes)', (12, 55)),
                                     ('Traitement independant par image', (12, 82))]:
                    cv2.putText(canvas, text, origin, cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (20, 20, 20), 1, cv2.LINE_AA)
                writer.write(canvas)
                log.writerow([count, f'{stamp:.6f}', boundaries, len(left), len(right),
                              len(centers)])
                print(diagnostic, flush=True)
                count += 1
                ok, frame = capture.read()
        print(f'Terminé : {count} images\nVidéo : {output}\nDiagnostics : {report}')
    finally:
        capture.release()
        if writer is not None:
            writer.release()


if __name__ == '__main__':
    main()

import numpy as np

def find_track_center(bin_img, line):
    left_side = None
    right_side = None

    is_left = True
    is_in_region = False

    for col_idx, pixel in enumerate(bin_img[line]):
        if not is_in_region and pixel == 255:
            is_in_region = True

            if is_left:
                left_side = col_idx
                is_left = False
            else:
                right_side = col_idx
                break

        if pixel == 0:
            is_in_region = False

    if left_side == None or right_side == None:
        print("Warning, no center detected, None returned")
        return None
    
    center_col = (left_side + right_side) // 2

    return center_col
#Fonction qui reenvoie les regions blanches de l'image binaire sur la ligne donnée, elle renvoie une liste de tuples (region_start, region_end) pour chaque region detectée
def find_regions(bin_img, line):

    regions = []
    is_in_region = False 

    for col_idx, pixel in enumerate(bin_img[line]):
        # Détecter le début d'une région et enregistrer region_start
        if not is_in_region and pixel==255:
            is_in_region = True;
            region_start = col_idx;
    
        #Détecter la fin d'une région et enregistrer region_end, c'est le premier pixel noir après une région blanche, fin de detection d'une région indépendante
        if is_in_region and pixel==0:
            is_in_region = False;
            region_end = col_idx - 1;
            regions.append((region_start, region_end))
    # Gérer une région blanche  qui atteint le bord droit de l'image et qui n'est pas suivie d'un pixel noir, donc pas de region_end detecté
    if is_in_region:
        region_end = len(bin_img[line]) - 1
        regions.append((region_start, region_end))

    return regions

def find_region_centers(regions_line):
    centers = []

    for start, end in regions_line:
        # Calculer le centre
        center = (start + end) / 2
        # Ajouter le centre à centers
        centers.append(center)

    return centers


def find_closest_center(previous_center, new_centers):

    closest_center = None
    min_distance = float('inf')

    for center in new_centers:

        distance = abs(center - previous_center)

        if distance < min_distance:
            min_distance = distance
            closest_center = center

    return closest_center


# Cette fonction sert à trouver les premiers points des bordures gauche et droite de la piste.
#
# Pour l'instant, on a déjà détecté les régions blanches sur plusieurs
# lignes horizontales de l'image et calculé leurs centres.
# Maintenant, le but est de relier ces centres pour reconstruire
# les deux bordures de la piste.

# Mais avant de pouvoir suivre les bordures, il faut savoir
# par où commencer. On cherche donc une ligne qui contient
# exactement deux centres.
#
# On parcourt l'image du bas vers le haut, car le bas de l'image
# correspond généralement à la partie de la piste la plus proche
# de la voiture.
#
# Dès qu'on trouve une ligne avec deux centres, on prend :
# - le centre le plus à gauche comme début de la bordure gauche
# - le centre le plus à droite comme début de la bordure droite
#
# On retourne les coordonnées (x, y) de ces deux points pour
# pouvoir ensuite chercher leurs continuations sur les autres lignes.
#
# Si on ne trouve aucune ligne avec deux centres, on retourne None.
#
# Attention : pour l'instant, on suppose que ces deux centres
# correspondent aux bordures de la piste, mais ce n'est pas
# forcément vrai, surtout au niveau des intersections.
# Il faudra donc vérifier cette hypothèse par la suite.
def find_initial_boundaries(lines, all_centers):

    # Parcourir les lignes du bas vers le haut
    for line, centers in zip(reversed(lines), reversed(all_centers)):

        # Trouver une ligne avec exactement deux centres
        if len(centers) == 2:
            left_center, right_center = sorted(centers)

            # Retourner les coordonnées (x, y)
            return (left_center, line), (right_center, line)

    # Aucune paire trouvée
    return None
lines = [100, 120, 140, 160]


# Cette fonction sert à suivre les bordures gauche et droite de la piste
# à partir des centres des régions détectées sur plusieurs lignes.
#
# On commence par chercher deux points de départ avec
# find_initial_boundaries(). Ensuite, on parcourt les lignes
# au-dessus pour retrouver la suite de chaque bordure.
#
# Pour chaque nouvelle ligne, on cherche les centres les plus proches
# des points précédents. On vérifie aussi qu'on ne donne pas le même
# centre aux deux bordures et que les points ne sont pas trop éloignés.
#
# Si une bordure n'est pas retrouvée, on garde les points déjà détectés
# sans inventer de nouveau point.
#
# Pour l'instant, c'est une première méthode basée sur la proximité.
# Elle pourra se tromper dans les virages ou aux intersections.

def track_boundaries(lines, all_centers, max_distance=50):

    initial_points = find_initial_boundaries(lines, all_centers)

    if initial_points is None:
        return [], []

    left_point, right_point = initial_points

    left_boundary = [left_point]
    right_boundary = [right_point]

    start_line = left_point[1]

    # On remonte l'image à partir de la ligne d'initialisation
    for line, centers in zip(reversed(lines), reversed(all_centers)):

        if line >= start_line:
            continue

        # On construit les associations possibles avec les deux bordures
        candidates = []

        for center in centers:
            left_distance = abs(center - left_point[0])
            right_distance = abs(center - right_point[0])

            if left_distance <= max_distance:
                candidates.append((left_distance, "left", center))

            if right_distance <= max_distance:
                candidates.append((right_distance, "right", center))

        # On commence par les associations avec la plus petite distance
        candidates.sort()

        used_centers = set()
        assigned_sides = set()

        for distance, side, center in candidates:

            # Chaque centre et chaque bordure ne peuvent être utilisés qu'une seule fois sur cette ligne
            if center in used_centers or side in assigned_sides:
                continue

            if side == "left":
                # Le point doit rester à gauche de la bordure droite
                if center >= right_point[0]:
                    continue

                left_point = (center, line)
                left_boundary.append(left_point)

            else:
                # Le point doit rester à droite de la bordure gauche
                if center <= left_point[0]:
                    continue

                right_point = (center, line)
                right_boundary.append(right_point)

            used_centers.add(center)
            assigned_sides.add(side)

    return left_boundary, right_boundary

# Cette fonction permet de calculer les centres de la piste
# à partir des bordures gauche et droite qu'on a reconstruites.
#
# Comme certaines régions peuvent ne pas être détectées,
# les deux bordures n'ont pas forcément les mêmes hauteurs.
# On associe donc les points en fonction de leur coordonnée y.
#
# Si les deux bordures sont présentes à une même hauteur,
# on calcule le milieu entre les deux.
#
# Si une bordure est manquante, on ne calcule pas de centre
# pour cette ligne pour l'instant.
#
# Le but est d'obtenir plusieurs points qui représentent
# la trajectoire centrale que la voiture devra suivre.

def compute_track_centers(left_boundary, right_boundary):

    track_centers = []

    # Associer chaque hauteur à la position de la bordure
    left_dict = {y: x for x, y in left_boundary}#on utilise un dictionnaire pour associer chaque hauteur à la position de la bordure gauche
    right_dict = {y: x for x, y in right_boundary}

    # Récupérer les hauteurs communes aux deux bordures
    common_lines = left_dict.keys() & right_dict.keys()# les hauteurs communes sont celles qui sont présentes dans les deux dictionnaires, pour lesquelles on a détecté à la fois une bordure gauche et une bordure droite

    # Parcourir les lignes du bas vers le haut
    for line in sorted(common_lines, reverse=True):

        left_x = left_dict[line]
        right_x = right_dict[line]

        if left_x < right_x: #on vérifie que la bordure gauche est bien à gauche de la bordure droite, sinon on ignore cette ligne
            center = (left_x + right_x) / 2# on calcule le centre de la piste comme la moyenne des positions des deux bordures
            track_centers.append((center, line))

    return track_centers




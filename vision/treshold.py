import cv2
import numpy as np
from matplotlib import pyplot as plt 


def tresholding_noise_removal(img,
                              blocksize=61, c=10,
                              kernel_dilate=cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3)),
                              kernel_opening=np.ones((5,5), dtype=np.uint8),
                              MIN_AREA=7000, MAX_AREA=10000000):
    """
    Applique un pipeline de traitement d'image pour extraire une ligne claire (ou foncée inversée) 
    de son environnement en s'adaptant aux variations de luminosité et en éliminant le bruit.

    La fonction procède par un lissage, un seuillage adaptatif local (pour annuler l'effet des ombres), 
    des opérations morphologiques pour nettoyer les parasites, et enfin un filtrage géométrique basé 
    sur la surface des régions détectées.

    Args:
        img (numpy.ndarray): L'image source, impérativement en niveaux de gris.
        blocksize (int, optionnel): Taille du voisinage (carré) observé pour le calcul du seuil adaptatif. 
            Il doit être impair et impérativement supérieur à l'épaisseur de la ligne en pixels pour 
            ne pas créer de "trous" au milieu de celle-ci. Par défaut: 61.
        c (int, optionnel): Constante soustraite au seuil local trouvé par la moyenne gaussienne. 
            Agit comme un filtre anti-bruit pour éviter que les micro-variations du fond blanc ne soient 
            considérées comme des lignes. Par défaut: 10.
        kernel_dilate (numpy.ndarray, optionnel): L'élément structurant (noyau) utilisé pour la dilatation. 
            Permet de combler les éventuels trous ou fissures dans la ligne. Par défaut: Croix de 3x3.
        kernel_opening (numpy.ndarray, optionnel): L'élément structurant (noyau) utilisé pour l'ouverture. 
            L'ouverture (érosion suivie d'une dilatation) supprime les petites zones blanches parasites (bruit). 
            Par défaut: Carré de 5x5.
        MIN_AREA (int, optionnel): Surface minimum en pixels. Les contours ayant une aire inférieure à 
            cette valeur seront considérés comme du bruit résiduel et supprimés. Par défaut: 7000.
        MAX_AREA (int, optionnel): Surface maximum en pixels. Permet d'éliminer les régions excessivement 
            grandes qui ne correspondraient pas à la piste. Par défaut: 10000000.

    Returns:
        numpy.ndarray: L'image binaire filtrée et nettoyée. La ligne valide apparaît parfaitement 
        pleine et blanche (255) sur un fond totalement noir (0).
    """

    # On applique un flou qui aide pour déterminer le seuil dynamiquement
    img = cv2.medianBlur(img, 5)

    # Les 2 paramètres importants:
    # - block size qui détermine la taille du voisinage observé, il faut qu'il soit supérieur 
    #   à l'épaisseur de la ligne pour ne pas créer un trou
    # - C correspond à la contrainte soustraite au seuil trouvé par la moyenne gaussienne, 
    #   c'est ce qui permet d'éviter que les zones sans lignes soient considérées comme des lignes 
    img_treshold = cv2.adaptiveThreshold(
        img, 255, 
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV, 
        blocksize, c
    )

    # L'ouverture (MORPH_OPEN) va supprimer les petites zones blanches du bruit (Ouverture = erosion puis dilation)
    img_morpho = cv2.morphologyEx(img_treshold, cv2.MORPH_OPEN, kernel_opening)

    # La dilatation (MORPH_DILATE) permet de combler les éventuels trous dans la ligne 
    # (même s'ils devraient déjà être rattrapés par l'ouverture)
    img_morpho = cv2.morphologyEx(img_morpho, cv2.MORPH_DILATE, kernel_dilate)

    # 1. Trouver tous les contours (les groupes de pixels contigus)
    # RETR_EXTERNAL = on ne cherche que les contours extérieurs (pas les trous à l'intérieur de la ligne)
    # RETR_TREE = on cherche tous les contours: plus long, pas forcément nécessaire dans notre cas, il faut tester
    borders, hierarchie = cv2.findContours(img_morpho, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)


    # 2. Créer une image de destination toute noire, de la même taille que l'on remplira ensuite
    image_cleaned = np.zeros_like(img_morpho)

    # A TESTER, peut être utile pour éliminer ce qui est en dehors de la piste si la caméra voit trop large
    # plus_grand_contour = max(contours, key=cv2.contourArea)
    # image_filtree = np.full_like(image_propre, 255)
    # cv2.drawContours(image_filtree, [plus_grand_contour], 0, 0, thickness=cv2.FILLED)
    # image_filtree = cv2.bitwise_not(image_filtree)

    borders_filtered = []

    # 4. Analyser chaque région trouvée
    for border in borders:
        # Calculer l'aire de la région (contourArea est déjà très rapide car exécuté en C++ par OpenCV)
        area = cv2.contourArea(border)
        
        # Si la région est plus grande que notre seuil, c'est la ligne !
        if area > MIN_AREA and area < MAX_AREA:
            # On l'ajoute a notre liste de région à traiter
            borders_filtered.append(border)

    # On redessine en blanc (255) sur notre nouvelle image toutes les regions après filtrage
    # Le thickness=cv2.FILLED (équivalent à -1) signifie "remplir l'intérieur du contour"
    cv2.drawContours(image_cleaned, borders_filtered, -1, 255, thickness=cv2.FILLED)

    return image_cleaned

DIRECTORY_SRC = "vision/src_img_piste"
DIRECTORY_DEST = "vision/dest_img_piste"

FILE_NAME = 'piste'

img = cv2.imread(f"{DIRECTORY_SRC}/{FILE_NAME}.jpg", cv2.IMREAD_GRAYSCALE)

img_cleaned = tresholding_noise_removal(img)

cv2.imwrite(f"{DIRECTORY_DEST}/{FILE_NAME}_filtered.jpg", img_cleaned)

plt.imshow(img_cleaned, cmap='gray')
plt.axis('off')
plt.show()
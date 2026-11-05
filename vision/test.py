import cv2
from threshold import *
from track_center_detection import *

DIRECTORY_SRC = "vision/src_img_piste"
DIRECTORY_DEST = "vision/dest_img_piste"

FILE_NAME = 'piste1'

img = cv2.imread(f"{DIRECTORY_SRC}/{FILE_NAME}.jpg", cv2.IMREAD_GRAYSCALE)

img_cleaned = thresholding_noise_removal(img, blocksize=101, MIN_AREA=1000)

center_line = 80

center_col = find_track_center(img_cleaned, center_line)

# print(center_line)
# print(center_col)

size_cross = 20
width_cross = 3

img_cleaned[center_line-size_cross:center_line+size_cross, center_col-width_cross:center_col+width_cross] = 255
img_cleaned[center_line-width_cross:center_line+width_cross, center_col-size_cross:center_col+size_cross] = 255

cv2.imwrite(f"{DIRECTORY_DEST}/{FILE_NAME}_filtered.jpg", img_cleaned)

plt.imshow(img_cleaned, cmap='gray')
plt.axis('off')
plt.show()
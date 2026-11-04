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



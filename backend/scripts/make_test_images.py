"""
Make bad-quality variants of one of YOUR OWN card photos, to test the quality gate.

    python scripts/make_test_images.py path/to/my_aadhaar.jpg

Writes next to the original: *_blurry.jpg, *_dark.jpg, *_glare.jpg, *_small.jpg.
Do not commit real ID photos to git.
"""
import sys
from pathlib import Path

import cv2
import numpy as np


def main(path: str) -> None:
    src = Path(path)
    img = cv2.imread(str(src))
    if img is None:
        sys.exit(f"Could not read {src}")
    h, w = img.shape[:2]

    variants = {
        "blurry": cv2.GaussianBlur(img, (0, 0), 8),
        "dark": (img.astype(np.float32) * 0.2).astype(np.uint8),
        "small": cv2.resize(img, (max(w // 5, 1), max(h // 5, 1)), interpolation=cv2.INTER_AREA),
    }
    glare = img.copy()
    cv2.circle(glare, (w // 2, h // 2), min(h, w) // 3, (255, 255, 255), -1)
    variants["glare"] = glare

    for name, im in variants.items():
        out = src.with_name(f"{src.stem}_{name}.jpg")
        cv2.imwrite(str(out), im)
        print("wrote", out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

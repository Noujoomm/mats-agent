"""Build web/img/shamsa.webp: a full Ottoman shamsa (rosette) from the half-medallion
illumination in assets/, by kaleidoscopic mirroring of one 20-degree wedge around the
true centre, with the paper turned into transparency so it works on light and dark.

Usage: python3 scripts/build_shamsa.py   (needs numpy + Pillow; not a runtime dependency)"""
import numpy as np
from PIL import Image
ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "ottoman-illumination.jpg"
OUT = ROOT / "web" / "img" / "shamsa.webp"
A0, SIZE = 45.0, 1100
WEDGE = 20.0
CX, CY, RMAX = -77.0, 1225.0, 1330.0
src = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
H, W, _ = src.shape
paper = np.array([228, 218, 206], np.float32)

n = SIZE; c = (n - 1) / 2
yy, xx = np.mgrid[0:n, 0:n]
dx, dy = (xx - c) / c, (c - yy) / c
r = np.hypot(dx, dy) * RMAX
ang = np.degrees(np.arctan2(dy, dx)) % 360
k = np.floor(ang / WEDGE); t = ang - k * WEDGE
t = np.where(k % 2 == 1, WEDGE - t, t)          # mirror every other wedge
a = np.radians(A0 + t)
sx = CX + r * np.cos(a); sy = CY - r * np.sin(a)
inside = (sx >= 0) & (sx < W - 1) & (sy >= 0) & (sy < H - 1) & (r < RMAX)
# bilinear sample
x0 = np.clip(np.floor(sx).astype(int), 0, W - 2); y0 = np.clip(np.floor(sy).astype(int), 0, H - 2)
fx = (np.clip(sx, 0, W - 1) - x0)[..., None]; fy = (np.clip(sy, 0, H - 1) - y0)[..., None]
p = (src[y0, x0] * (1 - fx) * (1 - fy) + src[y0, x0 + 1] * fx * (1 - fy)
     + src[y0 + 1, x0] * (1 - fx) * fy + src[y0 + 1, x0 + 1] * fx * fy)
# paper -> alpha (distance from paper colour), then un-premultiply against paper
d = np.linalg.norm(p - paper, axis=-1)
alpha = np.clip((d - 20) / 40, 0, 1)
alpha = np.where(inside, alpha, 0)
alpha *= np.clip((RMAX - r) / 60, 0, 1)          # soft outer edge
rgb = np.where(alpha[..., None] > 0.02,
               paper + (p - paper) / np.maximum(alpha[..., None], 0.02), p)
out = np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8)
Image.fromarray(out, "RGBA").save(OUT, "WEBP", quality=76, method=6)
print(f"wrote {OUT}")

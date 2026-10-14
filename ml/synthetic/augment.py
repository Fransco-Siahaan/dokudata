"""Degradations that imitate phone photos, office scans and faded thermal paper (PRD 10.3)."""

from __future__ import annotations

import random

import cv2
import numpy as np


def _background(h: int, w: int, rng: np.random.Generator) -> np.ndarray:
    base = rng.integers(60, 170, size=3)
    bg = np.ones((h, w, 3), np.float32) * base
    noise = cv2.GaussianBlur(rng.normal(0, 25, (h // 8 + 1, w // 8 + 1)).astype(np.float32), (0, 0), 2)
    bg += cv2.resize(noise, (w, h))[..., None]
    return np.clip(bg, 0, 255).astype(np.uint8)


def photo(img: np.ndarray, rng: np.random.Generator, severity: float) -> np.ndarray:
    """Paper on a table, shot at an angle: perspective, rotation, uneven light."""
    h, w = img.shape[:2]
    pad_x, pad_y = int(w * 0.15), int(h * 0.08)
    H, W = h + 2 * pad_y, w + 2 * pad_x
    canvas = _background(H, W, rng)
    jitter = 0.06 * severity
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([
        [pad_x + rng.uniform(-jitter, jitter) * w, pad_y + rng.uniform(-jitter, jitter) * h],
        [pad_x + w + rng.uniform(-jitter, jitter) * w, pad_y + rng.uniform(-jitter, jitter) * h],
        [pad_x + w + rng.uniform(-jitter, jitter) * w, pad_y + h + rng.uniform(-jitter, jitter) * h],
        [pad_x + rng.uniform(-jitter, jitter) * w, pad_y + h + rng.uniform(-jitter, jitter) * h],
    ])  # fmt: skip
    m = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, m, (W, H), borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (W, H))
    out = np.where(mask[..., None] > 0, warped, canvas)
    angle = rng.uniform(-8, 8) * severity
    rot = cv2.getRotationMatrix2D((W / 2, H / 2), angle, 1.0)
    out = cv2.warpAffine(out, rot, (W, H), borderMode=cv2.BORDER_REFLECT)
    return _lighting(out, rng, 0.45 * severity)


def scan(img: np.ndarray, rng: np.random.Generator, severity: float) -> np.ndarray:
    """Flatbed scan: slight skew, grey cast, speckle noise."""
    h, w = img.shape[:2]
    angle = rng.uniform(-4, 4) * severity
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(img, rot, (w, h), borderValue=(245, 245, 245))
    out = (
        (out.astype(np.float32) * rng.uniform(0.85, 0.97) + rng.uniform(5, 25)).clip(0, 255).astype(np.uint8)
    )
    speckle = rng.random(out.shape[:2]) < 0.002 * severity
    out[speckle] = 0
    return out


def thermal_fade(img: np.ndarray, rng: np.random.Generator, severity: float) -> np.ndarray:
    """Faded thermal print: low contrast and lighter vertical bands."""
    f = img.astype(np.float32)
    contrast = 1 - 0.55 * severity * rng.uniform(0.6, 1.0)
    f = 255 - (255 - f) * contrast
    w = f.shape[1]
    band = 1 - 0.25 * severity * np.abs(np.sin(np.linspace(0, rng.uniform(2, 6) * np.pi, w)))
    f = 255 - (255 - f) * band[None, :, None]
    return f.clip(0, 255).astype(np.uint8)


def _lighting(img: np.ndarray, rng: np.random.Generator, strength: float) -> np.ndarray:
    h, w = img.shape[:2]
    cx, cy = rng.uniform(0, w), rng.uniform(0, h)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / np.hypot(w, h)
    light = 1 - strength * dist
    return (img.astype(np.float32) * light[..., None]).clip(0, 255).astype(np.uint8)


def blur_noise_jpeg(img: np.ndarray, rng: np.random.Generator, severity: float) -> np.ndarray:
    sigma = rng.uniform(0.3, 1.3) * severity
    if sigma > 0.35:
        img = cv2.GaussianBlur(img, (0, 0), sigma)
    noise = rng.normal(0, 6 * severity, img.shape)
    img = (img.astype(np.float32) + noise).clip(0, 255).astype(np.uint8)
    q = int(rng.uniform(35, 75) if severity > 0.5 else rng.uniform(60, 90))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else img


def degrade(img: np.ndarray, seed: int, doc_type: str) -> tuple[np.ndarray, dict[str, object]]:
    """Apply one randomly chosen capture condition plus blur/noise/JPEG. Returns image and recipe."""
    py = random.Random(seed)
    rng = np.random.default_rng(seed)
    severity = py.uniform(0.4, 1.0)
    modes = ["photo", "scan"] + (["thermal"] if doc_type == "receipt" else [])
    mode = py.choice(modes)
    if mode == "photo":
        out = photo(img, rng, severity)
    elif mode == "scan":
        out = scan(img, rng, severity)
    else:
        out = thermal_fade(img, rng, severity)
        if py.random() < 0.5:
            out = photo(out, rng, severity * 0.6)
    out = blur_noise_jpeg(out, rng, severity)
    return out, {"mode": mode, "severity": round(severity, 3)}

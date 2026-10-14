"""Loading and cleaning page images (PRD 8.1): orientation, perspective, deskew, contrast, noise."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps

PDF_DPI = 200
MAX_SIDE = 2200
MIN_WIDTH = 600


class DocumentLoadError(ValueError):
    pass


@dataclass(slots=True)
class PreprocessOptions:
    perspective: bool = True
    deskew: bool = True
    clahe: bool = True
    denoise: bool = True


@dataclass(slots=True)
class PreprocessInfo:
    steps: list[str] = field(default_factory=list)
    skew_angle: float = 0.0
    perspective_corrected: bool = False
    scale: float = 1.0


def load_images(data: bytes, mime: str, max_pages: int = 10, dpi: int = PDF_DPI) -> list[np.ndarray]:
    """Decode an upload into BGR page images. PDFs are rendered, never executed."""
    if mime == "application/pdf":
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # pymupdf raises several error types for corrupt files
            raise DocumentLoadError(f"PDF tidak dapat dibuka: {exc}") from exc
        if doc.needs_pass:
            raise DocumentLoadError("PDF terkunci kata sandi")
        if doc.page_count == 0:
            raise DocumentLoadError("PDF tidak memiliki halaman")
        if doc.page_count > max_pages:
            raise DocumentLoadError(f"PDF memiliki {doc.page_count} halaman (maksimal {max_pages})")
        pages = []
        for i in range(doc.page_count):
            page = doc[i]
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            pages.append(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
        return pages
    try:
        img: Image.Image = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # phone photos carry orientation in EXIF
        img = img.convert("RGB")
    except Exception as exc:
        raise DocumentLoadError(f"Gambar tidak dapat dibaca: {exc}") from exc
    return [cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)]


def _resize(img: np.ndarray, info: PreprocessInfo) -> np.ndarray:
    h, w = img.shape[:2]
    scale = 1.0
    if max(h, w) > MAX_SIDE:
        scale = MAX_SIDE / max(h, w)
    elif w < MIN_WIDTH:
        scale = MIN_WIDTH / w
    if abs(scale - 1.0) > 1e-3:
        img = cv2.resize(
            img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        )
        info.steps.append(f"resize x{scale:.2f}")
    info.scale = scale
    return img


def _order_corners(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32
    )


def correct_perspective(img: np.ndarray) -> tuple[np.ndarray, bool]:
    """Find a paper-shaped quadrilateral (a receipt photographed on a table) and flatten it."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < 0.25 * h * w or area > 0.97 * h * w:
            continue
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) != 4:
            continue
        tl, tr, br, bl = _order_corners(approx)
        width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        if width < 100 or height < 100:
            continue
        dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
        m = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl]), dst)
        return cv2.warpPerspective(img, m, (width, height), borderMode=cv2.BORDER_REPLICATE), True
    return img, False


def estimate_skew(gray: np.ndarray) -> float:
    """Median angle of text-line blobs, in degrees (positive = counter-clockwise)."""
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, gray.shape[1] // 40), 3))
    merged = cv2.dilate(binary, kernel, iterations=1)
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    angles: list[float] = []
    weights: list[float] = []
    for c in contours:
        (_, _), (rw, rh), angle = cv2.minAreaRect(c)
        long_side, short_side = max(rw, rh), min(rw, rh)
        if long_side < gray.shape[1] * 0.1 or short_side < 4 or long_side / short_side < 4:
            continue
        if rw < rh:
            angle -= 90
        if angle < -45:
            angle += 90
        elif angle > 45:
            angle -= 90
        angles.append(angle)
        weights.append(long_side)
    if len(angles) < 3:
        return 0.0
    order = np.argsort(angles)
    a = np.asarray(angles)[order]
    cw = np.cumsum(np.asarray(weights)[order])
    return float(a[np.searchsorted(cw, cw[-1] / 2)])  # weighted median


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess(img: np.ndarray, opts: PreprocessOptions | None = None) -> tuple[np.ndarray, PreprocessInfo]:
    """Return a cleaned BGR image ready for OCR plus a record of what was applied."""
    opts = opts or PreprocessOptions()
    info = PreprocessInfo()
    img = _resize(img, info)
    if opts.perspective:
        img, corrected = correct_perspective(img)
        if corrected:
            info.perspective_corrected = True
            info.steps.append("perspective")
            img = _resize(img, info)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if opts.deskew:
        angle = estimate_skew(gray)
        if 0.3 <= abs(angle) <= 15:
            gray = rotate(gray, angle)
            info.skew_angle = angle
            info.steps.append(f"deskew {angle:.1f}deg")
    if opts.denoise:
        gray = cv2.medianBlur(gray, 3) if _noise_level(gray) > 6 else gray
        info.steps.append("denoise")
    if opts.clahe:
        gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        info.steps.append("clahe")
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), info


def _noise_level(gray: np.ndarray) -> float:
    """Rough noise estimate: std of the high-frequency residual on flat regions."""
    residual = gray.astype(np.float32) - cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    return float(np.median(np.abs(residual)) * 1.4826 * 3)


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("PNG encoding failed")
    return buf.tobytes()


def encode_jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


def decode_image(data: bytes) -> np.ndarray:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise DocumentLoadError("Gambar tidak dapat didekode")
    return arr

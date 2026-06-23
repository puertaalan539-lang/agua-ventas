"""
ocr_extractor.py
Arquitectura de 2 pasos para leer pantallas LCD dot-matrix de dispensadores.

PASO A — Volcado OCR: imagen → texto crudo → debug_ocr_crudo.txt
PASO B — Parser:      txt → regex ultra-tolerantes → datos estructurados

Requiere: pip install pytesseract pillow opencv-python-headless
Tesseract instalado en: C:\\Program Files\\Tesseract-OCR\\tesseract.exe
"""

import re
import io
import os
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

# ── Tesseract ──────────────────────────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
    import platform, shutil

    if platform.system() == "Windows":
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    else:
        # Linux: buscar tesseract en rutas comunes
        rutas_linux = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
        ]
        ruta_auto = shutil.which("tesseract")
        if ruta_auto:
            pytesseract.pytesseract.tesseract_cmd = ruta_auto
        else:
            for ruta in rutas_linux:
                if os.path.exists(ruta):
                    pytesseract.pytesseract.tesseract_cmd = ruta
                    break

    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

# ── Google Vision (opcional) ───────────────────────────────────────────────────
try:
    from google.cloud import vision as gvision
    GOOGLE_VISION_OK = True
except ImportError:
    GOOGLE_VISION_OK = False

# ── Configuración ──────────────────────────────────────────────────────────────
DEBUG_TXT = Path("debug_ocr_crudo.txt")   # archivo de volcado (se sobrescribe)
MAPEO_PRODUCTO = {1: "garrafon", 2: "medio_garrafon", 3: "galon"}


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class LecturaPantalla:
    texto_crudo:     str        = ""
    producto_num:    int | None = None
    producto_nombre: str        = ""
    no_venta:        int        = 0
    dinero:          float      = 0.0
    confianza:       str        = "baja"   # 'alta' | 'media' | 'baja'
    errores:         list[str]  = field(default_factory=list)


@dataclass
class ResultadoLocal:
    garrafon_no_venta: int   = 0
    garrafon_dinero:   float = 0.0
    medio_no_venta:    int   = 0
    medio_dinero:      float = 0.0
    galon_no_venta:    int   = 0
    galon_dinero:      float = 0.0
    lecturas:          list  = field(default_factory=list)
    advertencias:      list  = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# PASO A — PREPROCESAMIENTO + EXTRACCIÓN + VOLCADO A TXT
# ══════════════════════════════════════════════════════════════════════════════

def _preprocesar_opencv(imagen_bytes: bytes) -> np.ndarray:
    """
    Preprocesamiento minimalista y estable en Windows y Linux:
    1. Decodifica bytes → BGR
    2. Escala de grises
    3. Upscale 3× con interpolación cúbica
    4. Aumento de contraste adaptativo (CLAHE) — robusto con fondos de color
    """
    arr = np.frombuffer(imagen_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    # 1. Escala de grises
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # 2. Upscale 3×
    h, w = gray.shape
    upscaled = cv2.resize(gray, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)

    # 3. CLAHE — aumenta contraste localmente sin destruir el texto
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    resultado = clahe.apply(upscaled)

    return resultado


def _volcar_txt(texto: str, filepath: Path = DEBUG_TXT) -> None:
    """Guarda el texto crudo OCR en un archivo TXT con timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    contenido = f"=== OCR Dump [{ts}] ===\n{texto}\n"
    filepath.write_text(contenido, encoding="utf-8")


def extraer_texto_tesseract(imagen_bytes: bytes) -> str:
    """PASO A con Tesseract: preprocesa → OCR → vuelca a TXT → retorna string."""
    if not TESSERACT_OK:
        raise RuntimeError("pytesseract no instalado.")

    img_cv  = _preprocesar_opencv(imagen_bytes)
    img_pil = Image.fromarray(img_cv)

    # psm 6 = bloque de texto uniforme | oem 3 = LSTM (mejor para ruido)
    config = "--oem 3 --psm 6"
    texto  = pytesseract.image_to_string(img_pil, config=config)

    _volcar_txt(texto)
    return texto


def extraer_texto_google_vision(imagen_bytes: bytes) -> str:
    """PASO A con Google Vision: llama API → vuelca a TXT → retorna string."""
    if not GOOGLE_VISION_OK:
        raise RuntimeError("google-cloud-vision no instalado.")

    # Google Vision es robusto, no necesita preprocesamiento agresivo
    client = gvision.ImageAnnotatorClient()
    image  = gvision.Image(content=imagen_bytes)
    resp   = client.text_detection(image=image)

    if resp.error.message:
        raise RuntimeError(f"Google Vision error: {resp.error.message}")

    texto = resp.text_annotations[0].description if resp.text_annotations else ""
    _volcar_txt(texto)
    return texto


# ══════════════════════════════════════════════════════════════════════════════
# PASO B — PARSER INDEPENDIENTE (regex ultra-tolerantes)
# ══════════════════════════════════════════════════════════════════════════════

# ── Regex para "PRODUCTO N" ────────────────────────────────────────────────────
# Soporta: PRODUCTO, PR0DUCT0, P R O D U C T O, PRQDUCTO, PROD., PRODU, etc.
# Seguido opcionalmente de espacios/puntos y luego el dígito del producto.
RE_PRODUCTO = re.compile(
    r"P\s*[R8]\s*[O0Q]\s*[D0]\s*[U\|]\s*[C6]\s*[T7]\s*[O0Q]"  # PRODUCTO completo (tolerante)
    r"[\s\.\-:]*"                                                  # separador opcional
    r"(\d)",                                                       # número de producto
    re.IGNORECASE
)
# Respaldo si la palabra queda truncada: "PROD" seguido de dígito cercano
RE_PRODUCTO_FALLBACK = re.compile(
    r"PR[O0Q][D0][\w\s\.\-]{0,8}?(\d)\s",
    re.IGNORECASE
)

# ── Regex para "NO.venta =N" ──────────────────────────────────────────────────
# Soporta: NO.venta, H0.venta, ND. venta, N0 . v e n t a, NOventa, etc.
# El separador (= - :) puede faltar o variar.
RE_VENTA = re.compile(
    r"[NH]\s*[O0D]\s*[\.\,]?\s*"          # NO. / H0. / ND.
    r"v\s*e\s*n\s*t\s*a"                   # v e n t a (con posibles espacios)
    r"\s*[=\-:\.]*\s*"                     # separador tolerante
    r"(\d+)",                              # cantidad
    re.IGNORECASE
)
# Respaldo: cualquier línea con "enta" seguido de separador y número
RE_VENTA_FALLBACK = re.compile(
    r"enta[\s=\-:\.]*(\d+)",
    re.IGNORECASE
)

# ── Regex para "Dinero =N" ────────────────────────────────────────────────────
# Soporta: Dinero, D1nero, Dlnero, Dinero, dinero
RE_DINERO = re.compile(
    r"[D0]\s*[I1L|]\s*[N]\s*[E3]\s*[R]\s*[O0]"   # D i n e r o tolerante
    r"\s*[=\-:\.]*\s*"                              # separador
    r"(\d+(?:[.,]\d+)?)",                           # monto (entero o decimal)
    re.IGNORECASE
)
# Respaldo: línea con "nero" o "iner" + separador + número
RE_DINERO_FALLBACK = re.compile(
    r"[ni]ner[o0]?\s*[=\-:\.]*\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE
)

# ── Respaldo nuclear: extrae pares "=NUM" por orden de aparición ──────────────
RE_IGUAL_NUM = re.compile(r"[=\-:]\s*(\d+(?:[.,]\d+)?)")


def parsear_archivo_txt(filepath: Path = DEBUG_TXT) -> LecturaPantalla:
    """
    PASO B — Lee el archivo TXT volcado y extrae datos con regex ultra-tolerantes.

    Args:
        filepath: Ruta al TXT generado por el Paso A (por defecto debug_ocr_crudo.txt)

    Returns:
        LecturaPantalla con los datos extraídos.
    """
    if not filepath.exists():
        res = LecturaPantalla()
        res.errores.append(f"Archivo {filepath} no encontrado.")
        return res

    texto = filepath.read_text(encoding="utf-8")
    return parsear_texto(texto)


def parsear_texto(texto: str) -> LecturaPantalla:
    """
    Aplica las regex al texto crudo y retorna LecturaPantalla.
    Se puede llamar directamente con un string (útil para tests).
    """
    res = LecturaPantalla(texto_crudo=texto)
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    campos_ok = 0

    # ── 1. PRODUCTO ────────────────────────────────────────────────────────────
    m = RE_PRODUCTO.search(texto)
    if not m:
        m = RE_PRODUCTO_FALLBACK.search(texto)

    if m:
        num = int(m.group(1))
        if num in MAPEO_PRODUCTO:
            res.producto_num    = num
            res.producto_nombre = MAPEO_PRODUCTO[num]
            campos_ok += 1
        else:
            res.errores.append(f"Número de producto '{num}' fuera de rango (1-3).")
    else:
        res.errores.append("No se detectó PRODUCTO N.")

    # ── 2. NO.venta ────────────────────────────────────────────────────────────
    m = RE_VENTA.search(texto)
    if not m:
        m = RE_VENTA_FALLBACK.search(texto)

    if m:
        res.no_venta = int(m.group(1))
        campos_ok += 1
    else:
        # Respaldo nuclear: segundo número después de "=" en el texto
        nums = RE_IGUAL_NUM.findall(texto)
        if len(nums) >= 2:
            try:
                res.no_venta = int(nums[1].replace(",", ""))
                campos_ok += 1
            except ValueError:
                pass
        if campos_ok < 2:
            res.errores.append("No se detectó NO.venta.")

    # ── 3. Dinero ──────────────────────────────────────────────────────────────
    m = RE_DINERO.search(texto)
    if not m:
        m = RE_DINERO_FALLBACK.search(texto)

    if m:
        res.dinero = float(m.group(1).replace(",", "."))
        campos_ok += 1
    else:
        # Respaldo nuclear: tercer número después de "=" en el texto
        nums = RE_IGUAL_NUM.findall(texto)
        if len(nums) >= 3:
            try:
                res.dinero = float(nums[2].replace(",", "."))
                campos_ok += 1
            except ValueError:
                pass
        if res.dinero == 0.0:
            res.errores.append("No se detectó Dinero.")

    # ── Evaluación de confianza ────────────────────────────────────────────────
    if campos_ok == 3:
        res.confianza = "alta"
        res.errores   = []
    elif campos_ok == 2:
        res.confianza = "media"
    else:
        res.confianza = "baja"

    return res


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL — orquesta Paso A + Paso B
# ══════════════════════════════════════════════════════════════════════════════

def procesar_imagen(imagen_bytes: bytes, motor: str = "tesseract") -> LecturaPantalla:
    """
    Paso A + Paso B en una sola llamada.

    Args:
        imagen_bytes: Bytes de la imagen (jpg/png/webp).
        motor: "tesseract" | "google"

    Returns:
        LecturaPantalla con los datos finales.
    """
    try:
        if motor == "google":
            extraer_texto_google_vision(imagen_bytes)
        else:
            extraer_texto_tesseract(imagen_bytes)
        return parsear_archivo_txt(DEBUG_TXT)
    except Exception as e:
        res = LecturaPantalla()
        res.errores.append(str(e))
        res.confianza = "baja"
        return res


def procesar_local_completo(
    imagenes: dict[int, bytes],
    motor: str = "tesseract"
) -> ResultadoLocal:
    """
    Procesa las 3 fotos de un local y combina los resultados.

    Args:
        imagenes: {1: bytes_prod1, 2: bytes_prod2, 3: bytes_prod3}
        motor: "tesseract" | "google"
    """
    out = ResultadoLocal()

    for num_esperado, img_bytes in imagenes.items():
        lectura = procesar_imagen(img_bytes, motor=motor)
        out.lecturas.append(lectura)

        producto_usar = lectura.producto_num or num_esperado

        if lectura.producto_num is None:
            out.advertencias.append(
                f"Foto {num_esperado}: no se detectó número de producto — "
                f"se asume PRODUCTO {num_esperado}."
            )
        elif lectura.producto_num != num_esperado:
            out.advertencias.append(
                f"⚠️ Foto subida como Producto {num_esperado} "
                f"pero la pantalla dice Producto {lectura.producto_num}. Verifica el orden."
            )

        if producto_usar == 1:
            out.garrafon_no_venta = lectura.no_venta
            out.garrafon_dinero   = lectura.dinero
        elif producto_usar == 2:
            out.medio_no_venta = lectura.no_venta
            out.medio_dinero   = lectura.dinero
        elif producto_usar == 3:
            out.galon_no_venta = lectura.no_venta
            out.galon_dinero   = lectura.dinero

        if lectura.confianza != "alta":
            out.advertencias += [f"Producto {num_esperado}: {e}" for e in lectura.errores]

    return out

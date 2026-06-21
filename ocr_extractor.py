"""
ocr_extractor.py
Extracción de datos de ventas desde fotos de la pantalla LCD del dispensador.

Formato real de la pantalla (uno por producto, 3 fotos por local):
    PRODUCTO 1      Sig.->
    NO.venta =52
    Dinero   =728
    btn menos = borrar

Mapeo fijo (igual en los 7 locales):
    PRODUCTO 1 -> Garrafón
    PRODUCTO 2 -> Medio Garrafón
    PRODUCTO 3 -> Galón
"""

import re
import io
from dataclasses import dataclass, field

# pip install pytesseract pillow
try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

# pip install google-cloud-vision  (opcional)
try:
    from google.cloud import vision
    GOOGLE_VISION_OK = True
except ImportError:
    GOOGLE_VISION_OK = False


# Mapeo fijo PRODUCTO N -> nombre interno
MAPEO_PRODUCTO = {
    1: "garrafon",
    2: "medio_garrafon",
    3: "galon",
}


# ──────────────────────────────────────────────
# DATACLASS DE RESULTADO OCR (una sola pantalla)
# ──────────────────────────────────────────────
@dataclass
class LecturaPantalla:
    texto_crudo: str = ""
    producto_num: int | None = None     # 1, 2 o 3
    producto_nombre: str = ""           # garrafon / medio_garrafon / galon
    no_venta: int = 0                   # cantidad de unidades vendidas
    dinero: float = 0.0                 # total en $ de ese producto
    confianza: str = "baja"             # 'alta' | 'media' | 'baja'
    errores: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────
# EXTRACCIÓN DE TEXTO
# ──────────────────────────────────────────────
def _preprocesar_imagen(img: "Image.Image") -> "Image.Image":
    """
    Mejora una foto de pantalla LCD para OCR:
    - Escala de grises
    - Aumenta tamaño (Tesseract lee mejor texto grande)
    - Aumenta contraste (sin binarizar a umbral fijo, que destruye texto variable)
    """
    img = img.convert("L")  # escala de grises

    # Escalar 2.5x — Tesseract funciona mucho mejor con texto grande
    w, h = img.size
    img = img.resize((int(w * 2.5), int(h * 2.5)), Image.LANCZOS)

    # Aumentar contraste de forma adaptativa (no destructiva)
    img = ImageOps.autocontrast(img, cutoff=1)

    return img


def extraer_texto_tesseract(imagen_bytes: bytes) -> str:
    if not TESSERACT_OK:
        raise RuntimeError("pytesseract no instalado. Ejecuta: pip install pytesseract pillow")
    img = Image.open(io.BytesIO(imagen_bytes))
    img = _preprocesar_imagen(img)
    # psm 6 = bloque uniforme de texto, ideal para pantallas LCD
    config = "--oem 3 --psm 6"
    return pytesseract.image_to_string(img, config=config)


def extraer_texto_google_vision(imagen_bytes: bytes) -> str:
    if not GOOGLE_VISION_OK:
        raise RuntimeError("google-cloud-vision no instalado.")
    client = vision.ImageAnnotatorClient()
    image  = vision.Image(content=imagen_bytes)
    resp   = client.text_detection(image=image)
    if resp.error.message:
        raise RuntimeError(f"Google Vision error: {resp.error.message}")
    return resp.text_annotations[0].description if resp.text_annotations else ""


# ──────────────────────────────────────────────
# PARSEO DEL TEXTO DE LA PANTALLA LCD
# ──────────────────────────────────────────────
# OCR de pantallas LCD suele confundir: O<->0, l<->1, S<->5, B<->8
# Por eso los patrones son flexibles con esos caracteres.

# OCR de pantallas LCD suele confundir: O<->0, l<->1, S<->5, B<->8, N<->H
# Por eso los patrones son MUY flexibles, casi solo anclados en los números.

PATRON_PRODUCTO = r"[PF][R8][O0][D0][U0][C0][T7][O0]\D{0,6}(\d)"
PATRON_VENTA    = r"[NH][O0]\W{0,4}venta\W{0,3}[=:-]?\W{0,2}(\d+)"
PATRON_DINERO   = r"[D0]iner[o0]\W{0,3}[=:-]?\W{0,2}(\d+(?:[.,]\d+)?)"

# Patrón de respaldo: si lo anterior falla, busca "=NUM" en cualquier línea
PATRON_NUM_GENERICO = r"=\W{0,2}(\d+)"


def _corregir_ocr_basico(texto: str) -> str:
    """Normaliza espacios y caracteres comunes mal leídos en contexto numérico."""
    # No reemplazamos globalmente O/0 porque rompería palabras; los patrones
    # de arriba ya contemplan ambas variantes donde importa.
    return texto


def parsear_lectura(texto: str) -> LecturaPantalla:
    """Convierte el texto crudo de una foto de pantalla en datos estructurados."""
    res = LecturaPantalla(texto_crudo=texto)
    texto_norm = _corregir_ocr_basico(texto)
    lineas = [l for l in texto_norm.split("\n") if l.strip()]

    m_prod = re.search(PATRON_PRODUCTO, texto_norm, re.IGNORECASE)
    m_vta  = re.search(PATRON_VENTA,    texto_norm, re.IGNORECASE)
    m_din  = re.search(PATRON_DINERO,   texto_norm, re.IGNORECASE)

    campos_ok = 0

    if m_prod:
        num = int(m_prod.group(1))
        if num in MAPEO_PRODUCTO:
            res.producto_num    = num
            res.producto_nombre = MAPEO_PRODUCTO[num]
            campos_ok += 1
        else:
            res.errores.append(f"Número de producto '{num}' fuera de rango (1-3).")
    else:
        res.errores.append("No se detectó la línea 'PRODUCTO N'.")

    # Si falla el patrón estricto de venta, intenta línea por línea con "=NUM"
    if m_vta:
        res.no_venta = int(m_vta.group(1))
        campos_ok += 1
    else:
        for linea in lineas:
            if "venta" in linea.lower() or re.search(r"[NH][O0]\W", linea, re.IGNORECASE):
                m_fallback = re.search(PATRON_NUM_GENERICO, linea)
                if m_fallback:
                    res.no_venta = int(m_fallback.group(1))
                    campos_ok += 1
                    break
        else:
            res.errores.append("No se detectó 'NO.venta ='.")

    # Igual respaldo para Dinero
    if m_din:
        res.dinero = float(m_din.group(1).replace(",", "."))
        campos_ok += 1
    else:
        for linea in lineas:
            if "iner" in linea.lower():
                m_fallback = re.search(PATRON_NUM_GENERICO, linea)
                if m_fallback:
                    res.dinero = float(m_fallback.group(1).replace(",", "."))
                    campos_ok += 1
                    break
        else:
            res.errores.append("No se detectó 'Dinero ='.")

    if campos_ok == 3:
        res.confianza = "alta"
        res.errores = []
    elif campos_ok == 2:
        res.confianza = "media"
    else:
        res.confianza = "baja"

    return res


# ──────────────────────────────────────────────
# FUNCIÓN PRINCIPAL — una sola foto/pantalla
# ──────────────────────────────────────────────
def procesar_imagen(imagen_bytes: bytes, motor: str = "tesseract") -> LecturaPantalla:
    """
    Extrae y parsea los datos de UNA pantalla (un producto).

    Args:
        imagen_bytes: Contenido binario de la imagen.
        motor: "tesseract" | "google"

    Returns:
        LecturaPantalla con producto, no_venta y dinero detectados.
    """
    try:
        if motor == "google":
            texto = extraer_texto_google_vision(imagen_bytes)
        else:
            texto = extraer_texto_tesseract(imagen_bytes)
        return parsear_lectura(texto)
    except Exception as e:
        res = LecturaPantalla()
        res.errores.append(str(e))
        res.confianza = "baja"
        return res


# ──────────────────────────────────────────────
# FUNCIÓN COMBINADA — las 3 fotos de un local
# ──────────────────────────────────────────────
@dataclass
class ResultadoLocal:
    garrafon_no_venta: int = 0
    garrafon_dinero: float = 0.0
    medio_no_venta: int = 0
    medio_dinero: float = 0.0
    galon_no_venta: int = 0
    galon_dinero: float = 0.0
    lecturas: list[LecturaPantalla] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)


def procesar_local_completo(
    imagenes: dict[int, bytes],   # {1: bytes_producto1, 2: bytes_producto2, 3: bytes_producto3}
    motor: str = "tesseract"
) -> ResultadoLocal:
    """
    Procesa las 3 fotos de un local (una por PRODUCTO) y combina resultados.

    Args:
        imagenes: dict con las claves 1, 2, 3 -> bytes de cada foto.
        motor: motor OCR a usar.

    Returns:
        ResultadoLocal con los 3 productos ya combinados.
    """
    out = ResultadoLocal()

    for num_esperado, img_bytes in imagenes.items():
        lectura = procesar_imagen(img_bytes, motor=motor)
        out.lecturas.append(lectura)

        if lectura.producto_num is None:
            out.advertencias.append(
                f"Foto subida como Producto {num_esperado}: no se pudo leer el número de producto."
            )
            # Usamos el número esperado como respaldo si el OCR falló en detectarlo
            producto_usar = num_esperado
        else:
            producto_usar = lectura.producto_num
            if lectura.producto_num != num_esperado:
                out.advertencias.append(
                    f"⚠️ Subiste la foto en la casilla 'Producto {num_esperado}' "
                    f"pero la pantalla dice 'Producto {lectura.producto_num}'. Verifica el orden."
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
            out.advertencias.extend(
                [f"Producto {num_esperado}: {e}" for e in lectura.errores]
            )

    return out
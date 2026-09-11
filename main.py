import asyncio
import os
import hashlib
from typing import Literal, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Response
import redis.asyncio as aioredis
from deep_translator import GoogleTranslator, MyMemoryTranslator
import fitz  # PyMuPDF
from fpdf import FPDF

# Environment & Cache Configuration
ENABLE_REDIS = os.getenv("ENABLE_REDIS", "true").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_VERSION = "v2"  # Increment to invalidate stale cache entries
CACHE_TTL_SECONDS = 86400  # Cache results for 24 hours
FONTS_DIR = "fonts"

redis_client: Optional[aioredis.Redis] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    if ENABLE_REDIS:
        try:
            redis_client = aioredis.from_url(REDIS_URL, decode_responses=False)
            await redis_client.ping()
            print("Redis cache connected successfully.")
        except Exception as e:
            print(f"Redis connection failed ({e}). Proceeding without caching.")
            redis_client = None
    else:
        print("Redis caching is explicitly DISABLED via ENABLE_REDIS=false.")

    yield

    if redis_client:
        await redis_client.close()


app = FastAPI(title="PDF Editor APIs", lifespan=lifespan)


# Helper Functions
def hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        raise ValueError("Invalid hex color")
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def generate_cache_key(prefix: str, file_bytes: bytes, **params) -> str:
    hasher = hashlib.sha256(file_bytes)
    for key in sorted(params.keys()):
        hasher.update(f":{key}={params[key]}".encode("utf-8"))
    return f"pdf_cache:{CACHE_VERSION}:{prefix}:{hasher.hexdigest()}"


async def get_cached_response(key: str, cache_control: Optional[str] = None) -> Optional[bytes]:
    if not ENABLE_REDIS or redis_client is None:
        return None
    if cache_control and "no-cache" in cache_control.lower():
        return None
    try:
        return await redis_client.get(key)
    except Exception as e:
        print(f"Redis GET error: {e}")
        return None


async def set_cached_response(key: str, value: bytes, ttl: int = CACHE_TTL_SECONDS) -> None:
    if not ENABLE_REDIS or redis_client is None:
        return
    try:
        await redis_client.setex(key, ttl, value)
    except Exception as e:
        print(f"Redis SET error: {e}")
async def safe_translate_chunk(text: str, src_lang: str, tgt_lang: str) -> str:
    """Translates text with automatic fallback if the primary engine fails."""
    # Attempt 1: GoogleTranslator
    try:
        translated = GoogleTranslator(source=src_lang, target=tgt_lang).translate(text)
        if translated and translated.strip():
            return translated
    except Exception as e:
        print(f"[Warning] GoogleTranslator failed: {e}. Attempting MyMemoryTranslator fallback...")

    # Attempt 2: MyMemoryTranslator Fallback
    try:
        translated = MyMemoryTranslator(source=src_lang, target=tgt_lang).translate(text)
        if translated and translated.strip():
            return translated
    except Exception as e:
        print(f"[Error] MyMemoryTranslator failed: {e}")

    raise Exception("All translation backends (Google & MyMemory) failed to translate this block.")

# Endpoint A: Translate PDF
@app.post("/api/translate-pdf")
async def translate_pdf(
    file: UploadFile = File(...),
    source_language: str = Form(...),
    target_language: str = Form(...),
    cache_control: Optional[str] = Header(None)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    pdf_bytes = await file.read()
    src_lang = source_language.lower().strip()
    tgt_lang = target_language.lower().strip()

    # 1. Check Redis Cache
    cache_key = generate_cache_key("translate", pdf_bytes, src=src_lang, tgt=tgt_lang)
    cached_pdf = await get_cached_response(cache_key, cache_control)

    if cached_pdf:
        return Response(
            content=cached_pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="translated_{file.filename}"',
                "X-Cache": "HIT"
            }
        )

    # 2. Extract Text Page by Page
    source_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_text = ""
    for page in source_doc:
        extracted_text += page.get_text() + "\n\n"
    source_doc.close()

    clean_text = extracted_text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Could not extract text from the PDF")

    # 3. Clean and Translate Text with Fallback Pipeline
    try:
        paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
        translated_parts = []
        current_chunk = ""

        for paragraph in paragraphs:
            # Keep chunks under 2500 chars to satisfy both translation engines
            if len(current_chunk) + len(paragraph) + 2 > 2500:
                chunk_result = await safe_translate_chunk(current_chunk, src_lang, tgt_lang)
                translated_parts.append(chunk_result)
                current_chunk = paragraph
                await asyncio.sleep(0.3)  # Rate limiting delay
            else:
                current_chunk = f"{current_chunk}\n\n{paragraph}" if current_chunk else paragraph

        if current_chunk:
            chunk_result = await safe_translate_chunk(current_chunk, src_lang, tgt_lang)
            translated_parts.append(chunk_result)

        translated_text = "\n\n".join(translated_parts)

        if not translated_text or not translated_text.strip():
            raise HTTPException(status_code=500, detail="All translation engines returned empty output.")

    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Translation pipeline failed ({source_language} -> {target_language}): {str(e)}"
        )

    # 4. Generate Multipage PDF with fpdf2 + Auto Page Breaks
    pdf = FPDF()
    pdf.set_text_shaping(True)
    
    # CRITICAL: Enable auto page break so long text flows across multiple pages
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    font_path = os.path.join(FONTS_DIR, "NotoSansBengali.ttf")
    if not os.path.exists(font_path):
        raise HTTPException(
            status_code=500, 
            detail="Font file 'NotoSansBengali.ttf' missing from fonts/ directory."
        )

    pdf.add_font("NotoBangla", fname=font_path)
    pdf.set_font("NotoBangla", size=12)

    # multi_cell automatically creates new pages as needed
    pdf.multi_cell(0, 8, translated_text)
    result_pdf_bytes = bytes(pdf.output())

    # 5. Cache Result & Return
    await set_cached_response(cache_key, result_pdf_bytes)

    return Response(
        content=result_pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="translated_{file.filename}"',
            "X-Cache": "MISS"
        }
    )


# Endpoint B: Watermark Processing
@app.post("/editor/pdf/watermark")
async def watermark_pdf(
    file: UploadFile = File(...),
    text: str = Form(...),
    position: Literal["top-left", "top-center", "top-right", "center", "bottom-left", "bottom-center", "bottom-right"] = Form(...),
    opacity: float = Form(...),
    color: str = Form(...),
    cache_control: Optional[str] = Header(None)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    if not (0.0 <= opacity <= 1.0):
        raise HTTPException(status_code=400, detail="Opacity must be between 0.0 and 1.0")

    try:
        rgb_color = hex_to_rgb(color)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid color hex code. Use format #RRGGBB")

    pdf_bytes = await file.read()

    # 1. Check Redis Cache
    cache_key = generate_cache_key("watermark", pdf_bytes, text=text, pos=position, opacity=opacity, color=color, font="hebo")
    cached_pdf = await get_cached_response(cache_key, cache_control)

    if cached_pdf:
        return Response(
            content=cached_pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="watermarked_{file.filename}"',
                "X-Cache": "HIT"
            }
        )

    # 2. Process Watermark with Rotation & Matrix Angle Adjustments
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    font_size = 46
    margin = 70

    for page in doc:
        page.clean_contents()
        page_rotation = page.rotation

        w, h = page.rect.width, page.rect.height
        text_length = fitz.get_text_length(text, fontname="hebo", fontsize=font_size)

        positions = {
            "top-left": (margin, margin + font_size),
            "top-center": ((w - text_length) / 2, margin + font_size),
            "top-right": (w - text_length - margin, margin + font_size),
            "center": ((w - text_length) / 2, (h + font_size) / 2),
            "bottom-left": (margin, h - margin),
            "bottom-center": ((w - text_length) / 2, h - margin),
            "bottom-right": (w - text_length - margin, h - margin),
        }

        pos_x, pos_y = positions.get(position, positions["center"])
        pos_pt = fitz.Point(pos_x, pos_y)

        # Apply specific tilt depending on header vs body/center positions
        if position in ("top-left", "top-center", "top-right"):
            tilt_angle = 10
        else:
            tilt_angle = 30

        total_angle = page_rotation + tilt_angle

        page.insert_text(
            point=pos_pt,
            text=text,
            fontsize=font_size,
            fontname="hebo",
            color=rgb_color,
            fill_opacity=opacity,
            morph=(pos_pt, fitz.Matrix(total_angle))
        )

    output_bytes = doc.tobytes()
    doc.close()

    # 3. Store in Cache and Return
    await set_cached_response(cache_key, output_bytes)

    return Response(
        content=output_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="watermarked_{file.filename}"',
            "X-Cache": "MISS"
        }
    )
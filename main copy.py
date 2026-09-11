import os
import uuid
from typing import Literal
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from deep_translator import GoogleTranslator
import fitz  # PyMuPDF
from fpdf import FPDF

app = FastAPI(title="PDF Editor APIs")

TEMP_DIR = "temp"
FONTS_DIR = "fonts"
os.makedirs(TEMP_DIR, exist_ok=True)

def hex_to_rgb(hex_color: str):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))

@app.post("/api/translate-pdf")
async def translate_pdf(
    file: UploadFile = File(...),
    source_language: str = Form(...),
    target_language: str = Form(...)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # 1. Read source PDF and extract text
    pdf_bytes = await file.read()
    source_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_text = ""
    for page in source_doc:
        extracted_text += page.get_text() + "\n"
    source_doc.close()

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from the PDF")

    # 2. Translate text
    try:
        translator = GoogleTranslator(source=source_language, target=target_language)
        # Deep-translator has a 5k char limit per request; chunking applied for safety
        chunk_size = 4000
        text_chunks = [extracted_text[i:i+chunk_size] for i in range(0, len(extracted_text), chunk_size)]
        translated_text = ""
        for chunk in text_chunks:
            translated_text += translator.translate(chunk) + "\n"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")

    # 3. Generate new PDF
    output_filename = os.path.join(TEMP_DIR, f"translated_{uuid.uuid4().hex}.pdf")
    pdf = FPDF()
    pdf.add_page()
    
    # Handle Bangla / Unicode via custom font
    font_path = os.path.join(FONTS_DIR, "NotoSansBengali.ttf")
    if os.path.exists(font_path):
        pdf.add_font("UnicodeFont", style="", fname=font_path)
        pdf.set_font("UnicodeFont", size=12)
    else:
        pdf.set_font("Arial", size=12)

    pdf.multi_cell(0, 8, translated_text)
    pdf.output(output_filename)

    return FileResponse(
        path=output_filename, 
        filename=f"translated_{file.filename}", 
        media_type="application/pdf"
    )

@app.post("/editor/pdf/watermark")
async def watermark_pdf(
    file: UploadFile = File(...),
    text: str = Form(...),
    position: Literal["top-left", "top-center", "top-right", "center", "bottom-left", "bottom-center", "bottom-right"] = Form(...),
    opacity: float = Form(...),
    color: str = Form(...)
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
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    font_size = 36
    margin = 50

    for page in doc:
        w, h = page.rect.width, page.rect.height
        text_length = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
        
        # Calculate coordinates (PyMuPDF's x,y represents the bottom-left of the text string)
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

        page.insert_text(
            point=(pos_x, pos_y),
            text=text,
            fontsize=font_size,
            fontname="helv",
            color=rgb_color,
            fill_opacity=opacity
        )

    output_filename = os.path.join(TEMP_DIR, f"watermarked_{uuid.uuid4().hex}.pdf")
    doc.save(output_filename)
    doc.close()

    return FileResponse(
        path=output_filename, 
        filename=f"watermarked_{file.filename}", 
        media_type="application/pdf"
    )
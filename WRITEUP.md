# Technical Write-up & Architecture Design Choices

## 1. Stack Selection & Layout Strategy
- **FastAPI:** Chosen for non-blocking async execution, standard OpenAPI request validation, and lightweight binary streaming.
- **PyMuPDF (`fitz`):** Powers raw text extraction and watermark matrix insertion. Chosen over `PyPDF2` for superior execution speed and accurate coordinate manipulation (`morph`, `clean_contents`).
- **`fpdf2` + `uharfbuzz`:** Reconstructs translated documents containing complex scripts (such as Bangla). Standard engines fail to shape conjunct characters, rendering broken ligatures. `fpdf2` integrates `uharfbuzz` to handle OpenType Complex Text Layout (CTL).

---

## 2. Solving Bangla Unicode & Text Shaping Issues
Standard PDF generation applies naive left-to-right character placement. In Bangla, vowel modifiers (*kar*) and combined consonants (*juktakkhor*) require contextual glyph substitution.

- **Solution:** We configured `pdf.set_text_shaping(True)` in `fpdf2` alongside `uharfbuzz`. During PDF compilation, HarfBuzz processes the character stream, calculating exact visual glyph boundaries and ligature joins before writing output streams.
- **Multipage Flow:** Enabled `pdf.set_auto_page_break(auto=True, margin=15)` so long translated text automatically overflows into multi-page documents without clipping.

---

## 3. Watermark Orientation & Matrix Tilting
- **The Upside-Down Bug:** Many PDFs contain internal metadata orientation tags (`/Rotate 180`). Standard raw coordinate drawing ignores viewer orientation, resulting in inverted watermarks.
- **Orientation Normalization:** Called `page.clean_contents()` to reset transformation matrices, read `page.rotation`, and combined it with our target tilt angle (`total_angle = page_rotation + tilt_angle`).
- **Matrix Tilting (`morph`):** Used `morph=(pos_pt, fitz.Matrix(total_angle))` to pivot text directly around its insertion point (`pos_pt`). We set a 10° slope for top header watermarks to prevent clipping and a 30° angle for center/body watermarks. Bold Helvetica (`hebo`) was enforced for high contrast.

---

## 4. Translation Resiliency & Fallback Pipeline
To eliminate translation failures on multipage documents:
1. **Chunking & Rate Limiting:** Large text bodies are broken into paragraph chunks under 3,500 characters, separated by `await asyncio.sleep(0.3)` delays to prevent IP rate-limiting from free translation endpoints.
2. **Multi-Engine Fallback (`safe_translate_chunk`):** If `GoogleTranslator` encounters blocked requests or unhandled text blocks, the request automatically falls back to `MyMemoryTranslator` before returning an error.

---

## 5. High-Traffic Caching Architecture
- **SHA-256 Fingerprinting:** Keys combine PDF binary hashes with all normalized form inputs (`prefix + SHA256(file_bytes) + params`).
- **Versioning (`CACHE_VERSION`):** Changing `CACHE_VERSION = "v2"` invalidates all prior Redis entries instantly when backend styling or font files change.
- **Environment Toggle & Header Control:** Caching can be turned off entirely via `ENABLE_REDIS=false` or bypassed per-request via the `Cache-Control: no-cache` header.
# PDF Editor APIs

A high-performance FastAPI service for PDF translation with native Bangla (Unicode/CTL) text shaping, customizable rotated watermarking, and an async Redis caching layer with environment toggles.

---

## Features

- **Translation API (`POST /api/translate-pdf`):** 
  - Extracts text and translates across language pairs using a resilient multi-engine fallback pipeline (`GoogleTranslator` -> `MyMemoryTranslator`).
  - Supports Bangla (`bn`) and complex scripts using `fpdf2` with `uharfbuzz` OpenType shaping.
  - Multipage-ready with automatic page breaks and async request throttling to avoid translation rate limits.

- **Watermark API (`POST /editor/pdf/watermark`):**
  - Applies custom text watermarks across all pages with bold typography (`hebo`), custom hex colors, and opacity.
  - Fixes upside-down page orientations by reading internal `/Rotate` tags and applying `page.clean_contents()`.
  - Supports matrix rotation tilting (10° for header positions, 30° for center/body positions).

- **Resilient Caching Strategy:**
  - SHA-256 binary fingerprinting for fast Redis lookup.
  - Supports cache versioning (`CACHE_VERSION`), client bypass (`Cache-Control: no-cache`), and environment toggle (`ENABLE_REDIS`).

---

## Prerequisites & Installation

### Dependencies

Install the required packages from `requirements.txt`:

```text
fastapi==0.109.2
uvicorn==0.27.1
python-multipart==0.0.9
PyMuPDF==1.23.21
deep-translator==1.11.4
fpdf2==2.7.7
redis==5.0.1
uharfbuzz==0.39.0
```

### Font Setup

Ensure `NotoSansBengali.ttf` or `NotoSansBengali-Regular.ttf` is placed inside the `fonts/` directory:

```text
graphics_cycle_task/
├── main.py
├── requirements.txt
├── README.md
└── fonts/
    └── NotoSansBengali.ttf
```

## Running the Server

### Normal Execution (with Redis)

```bash
uvicorn main:app --reload
```

### Disabling Redis (development mode)

#### Windows PowerShell

```powershell
$env:ENABLE_REDIS="false"; uvicorn main:app --reload
```

#### Windows Command Prompt

```bat
set ENABLE_REDIS=false && uvicorn main:app --reload
```

#### Linux, macOS, or Git Bash

```bash
ENABLE_REDIS=false uvicorn main:app --reload
```

## Postman Testing Guide

### 1. Translate a PDF

| Setting | Value |
| --- | --- |
| Method | `POST` |
| URL | `http://127.0.0.1:8000/api/translate-pdf` |
| Body | `form-data` |

| Field | Value |
| --- | --- |
| `file` | Select a PDF document |
| `source_language` | `en` |
| `target_language` | `bn` |

### 2. Add a watermark to a PDF

| Setting | Value |
| --- | --- |
| Method | `POST` |
| URL | `http://127.0.0.1:8000/editor/pdf/watermark` |
| Body | `form-data` |

| Field | Value |
| --- | --- |
| `file` | Select a PDF document |
| `text` | `CONFIDENTIAL` |
| `position` | `center` |
| `opacity` | `0.3` |
| `color` | `#FF0000` |

Supported positions: `top-left`, `top-center`, `top-right`, `center`, `bottom-left`, `bottom-center`, and `bottom-right`.

## Bypassing the Redis Cache

To force a re-render during testing, add this HTTP header:

```http
Cache-Control: no-cache
```
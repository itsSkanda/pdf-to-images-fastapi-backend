from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import fitz  # PyMuPDF
import os
import re
import io
from PIL import Image
from uuid import uuid4

app = FastAPI()

# ✅ Allow CORS for frontend access (e.g., from Next.js)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Setup output directory for generated images
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ✅ Serve the output directory at /output
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# --- ADD THIS CONFIGURATION BLOCK ---
# Get the base URL from an environment variable or default to local
# Make sure to set BACKEND_BASE_URL=https://pdf-to-images-srmproject.onrender.com
# when deploying to Render.com
BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000") # Default to localhost
# --- END ADDITION ---


@app.post("/split-pdf")
async def split_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    pdf = fitz.open(stream=contents, filetype="pdf")

    student_chunks = []
    current_chunk = []
    current_reg = None

    # Pattern to detect registration numbers like RAXXXXXXXX
    regno_pattern = re.compile(r"Registration\s*Number\s*:\s*(RA\d+)", re.IGNORECASE)

    # ✅ Group pages by registration number
    for page_num in range(len(pdf)):
        page = pdf[page_num]
        text = page.get_text()

        match = regno_pattern.search(text)
        if match:
            if current_chunk and current_reg:
                student_chunks.append((current_reg, current_chunk.copy()))
            current_reg = match.group(1)
            current_chunk = [page_num]
        else:
            if current_reg:
                current_chunk.append(page_num)

    # Append the last chunk if any
    if current_chunk and current_reg:
        student_chunks.append((current_reg, current_chunk.copy()))

    result = []
    MAX_FILE_SIZE_BYTES = 80 * 1024  # 80 KB
    IMAGE_DPI = 90
    JPEG_QUALITY = 70

    for reg_no, pages in student_chunks:
        images = []

        for p in pages:
            pix = pdf[p].get_pixmap(dpi=IMAGE_DPI)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)

        if not images:
            continue

        total_height = sum(img.height for img in images)
        combined = Image.new("RGB", (images[0].width, total_height), (255, 255, 255))

        y_offset = 0
        for img in images:
            combined.paste(img, (0, y_offset))
            y_offset += img.height

        # Crop vertically to reduce size (optional, here crops half)
        cropped_height = int(combined.height* 1.2/ 2)
        combined = combined.crop((0, 0, combined.width, cropped_height))

        filename = f"{reg_no}_{uuid4().hex[:6]}.jpg"
        path = os.path.join(OUTPUT_DIR, filename)

        # Save to buffer to check file size
        img_byte_arr = io.BytesIO()
        combined.save(img_byte_arr, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        img_byte_arr_size = img_byte_arr.tell()

        # If too large, retry with lower quality
        if img_byte_arr_size > MAX_FILE_SIZE_BYTES:
            print(f"Warning: {filename} is too large ({img_byte_arr_size} bytes). Retrying with lower quality.")
            img_byte_arr = io.BytesIO()
            combined.save(img_byte_arr, format="JPEG", quality=50, optimize=True)
            img_byte_arr_size = img_byte_arr.tell()
            print(f"New size for {filename}: {img_byte_arr_size} bytes")

        # Write image to file
        with open(path, "wb") as f:
            f.write(img_byte_arr.getvalue())

        # MODIFIED LINE: Use the dynamic BASE_URL
        public_url = f"{BASE_URL}/output/{filename}" # CHANGE THIS LINE
        result.append({ "regNo": reg_no, "imagePath": public_url })

    return JSONResponse(content={ "status": "success", "images": result })


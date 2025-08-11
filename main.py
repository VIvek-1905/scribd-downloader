import json
import os
import sys

# --- Safety check: ensure PyMuPDF (pymupdf) is installed and not the old 'fitz' package ---
try:
    import fitz  # PyMuPDF exposes itself as "fitz"
    # quick sanity checks:
    if not hasattr(fitz, "open") or "PyMuPDF" not in (getattr(fitz, "__doc__", "") or ""):
        raise ImportError("Detected a wrong 'fitz' package. Please run: pip uninstall fitz && pip install pymupdf")
except Exception as e:
    raise SystemExit(f"❌ {e}")

# --- now the rest of the imports ---
import aiohttp
import asyncio
import glob
import fitz  # safe now (PyMuPDF)
from PIL import Image
import json

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# Extract config values
TEMP_DIR = CONFIG["temp_directory"]
OUTPUT_DIR = CONFIG["output_directory"]
CLEANUP = CONFIG.get("cleanup_temp_files", True)
PDF_NAME_FORMAT = CONFIG.get("pdf_filename_format", "{scribd_title}.pdf")

OCR_ENABLED = CONFIG["ocr"].get("enabled", True)
OCR_LANG = CONFIG["ocr"].get("language", "eng")
OCR_PATH = CONFIG["ocr"].get("tesseract_path", "")
OCR_FONT_SIZE = CONFIG["ocr"].get("font_size_overlay", 8)
OCR_POSITION = tuple(CONFIG["ocr"].get("overlay_position", [20, 20]))

TIMEOUT = CONFIG["network"].get("timeout_seconds", 15)
RETRIES = CONFIG["network"].get("retry_attempts", 3)

PB_ENABLED = CONFIG["progress_bar"].get("enabled", True)
PB_STYLE = CONFIG["progress_bar"].get("style", {})
PB_FILLED = PB_STYLE.get("filled", "⬢")
PB_EMPTY = PB_STYLE.get("empty", "⬡")
PB_WIDTH = PB_STYLE.get("width", 60)

# Tesseract
if OCR_ENABLED:
    try:
        import pytesseract
        if OCR_PATH:
            pytesseract.pytesseract.tesseract_cmd = OCR_PATH
        _ = pytesseract.get_tesseract_version()
    except Exception as e:
        print(f"⚠️ OCR initialization failed: {e}")
        OCR_ENABLED = False

os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


class ProgressBar:
    def __init__(self, total):
        self.total = max(1, total)
        self.symbol = PB_FILLED
        self.empty = PB_EMPTY
        self.width = PB_WIDTH
        self.current = 0

    def update(self, step=1):
        if not PB_ENABLED:
            return
        self.current += step
        filled = int((self.current / self.total) * self.width)
        bar = self.symbol * filled + self.empty * (self.width - filled)
        print(f"\r[{bar}] {self.current}/{self.total} ({(self.current/self.total)*100:.0f}%)", end="")
        if self.current >= self.total:
            print("\n✅ Download Complete")


async def fetch_links(url):
    for attempt in range(RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Failed to fetch page: {resp.status}")
                    html = await resp.text()
            lines = html.split("\n")
            links = [
                line.split('"')[1].replace("scribdassets", "scribd").replace("pages", "images").replace("jsonp", "jpg")
                for line in lines if 'contentUrl: "https://' in line
            ]
            if not links:
                # try a looser parse if the precise token wasn't found
                links2 = [part for part in html.split('"') if part.startswith("https://") and ("pages" in part or "images" in part)]
                links = links2
            print("🔗 Links fetched.")
            return links
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
    raise Exception("All attempts to fetch links failed.")


def sort_key(x):
    # expects filenames that start with a page number like "001-....jpg"
    try:
        return int(os.path.basename(x).split("-")[0])
    except Exception:
        return 0


async def download_image(session, link, prog):
    try:
        async with session.get(link) as resp:
            if resp.status != 200:
                print(f"Failed to download {link}: {resp.status}")
                return
            img_data = await resp.read()
            file_name = os.path.join(TEMP_DIR, link.split("/")[-1].split("?")[0].split("-")[0] + ".jpg")
            with open(file_name, "wb") as f:
                f.write(img_data)
            prog.update()
    except Exception as e:
        print(f"Error downloading {link}: {e}")


async def download_images(links):
    prog = ProgressBar(len(links))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as session:
        tasks = [download_image(session, link, prog) for link in links]
        await asyncio.gather(*tasks)


def extract_text_from_image(image_path):
    if not OCR_ENABLED:
        return ""
    try:
        img = Image.open(image_path)
        return pytesseract.image_to_string(img, lang=OCR_LANG)
    except Exception as e:
        print(f"OCR failed on {image_path}: {e}")
        return ""


def create_text_image_pdf(output_file):
    pdf_path = os.path.abspath(output_file)
    doc = fitz.open()
    image_files = sorted(glob.glob(os.path.join(TEMP_DIR, "*.jpg")), key=sort_key)

    for image_path in image_files:
        try:
            # open image as pixmap via PyMuPDF-friendly method
            img_doc = fitz.open(image_path)
            pix = img_doc[0].get_pixmap()
            page = doc.new_page(width=pix.width, height=pix.height)
            page.insert_image(page.rect, filename=image_path)

            text = extract_text_from_image(image_path)
            if text.strip():
                page.insert_text(OCR_POSITION, text.strip(), fontsize=OCR_FONT_SIZE, color=(0, 0, 0))
        except Exception as e:
            print(f"Failed to process {image_path}: {e}")

    doc.set_metadata({
        "title": os.path.basename(pdf_path),
        "author": "Scribd Converter",
        "subject": "Converted from Scribd images",
    })

    doc.save(pdf_path)
    doc.close()


async def main():
    if len(sys.argv) != 2:
        print("Usage: python main.py <Scribd_URL>")
        return

    url = sys.argv[1]
    try:
        links = await fetch_links(url)
        if not links:
            raise Exception("No image links found on the provided page.")
        await download_images(links)

        scribd_title = url.split("/")[-1].replace("-", " ")
        output_name = PDF_NAME_FORMAT.format(scribd_title=scribd_title)
        output_path = os.path.join(OUTPUT_DIR, output_name)

        print("\n🛠️ Converting to PDF...")
        create_text_image_pdf(output_path)

        if CLEANUP:
            for f in glob.glob(os.path.join(TEMP_DIR, "*.jpg")):
                try:
                    os.remove(f)
                except Exception:
                    pass
            # remove temp dir if empty
            try:
                if os.path.isdir(TEMP_DIR) and not os.listdir(TEMP_DIR):
                    os.rmdir(TEMP_DIR)
            except Exception:
                pass

        print(f"\n✅ Done: {output_path}")

    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())

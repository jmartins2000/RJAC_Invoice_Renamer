import fitz  # PyMuPDF
from PIL import Image
import io

class PDFService:
    """Service to handle PDF operations including preview generation"""
    
    @staticmethod
    def get_pdf_images(pdf_path, zoom=2.0):
        """
        Convert PDF pages to a list of PIL Images.
        zoom=2.0 ~ 144 DPI (Standard 72 DPI * 2)
        """
        images = []
        try:
            doc = fitz.open(pdf_path)
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                # Create matrix for higher resolution (zoom x zoom)
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                images.append(img)
            doc.close()
            return images
        except Exception as e:
            print(f"Error generating preview for {pdf_path}: {e}")
            return []


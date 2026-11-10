import pymupdf as fitz  # PyMuPDF
from PIL import Image
import io

class PDFService:
    """Service to handle PDF operations including preview generation"""
    
    @staticmethod
    def get_pdf_images(pdf_path, target_width=550):
        """
        Convert PDF pages to a list of PIL Images.
        Automatically adjusts DPI based on page size for optimal quality/performance.
        
        Args:
            pdf_path: Path to PDF file
            target_width: Target display width in pixels (default 550)
        """
        from src.services.file_types import is_image
        if is_image(pdf_path):  # photos / scans / screenshots: show as-is, upright
            try:
                from PIL import ImageOps
                return [ImageOps.exif_transpose(Image.open(pdf_path)).convert("RGB")]
            except Exception as e:
                print(f"Error opening image {pdf_path}: {e}")
                return []
        images = []
        try:
            doc = fitz.open(pdf_path)
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                
                # Get page dimensions in points (1 point = 1/72 inch)
                page_width = page.rect.width
                page_height = page.rect.height
                
                # Calculate required zoom to achieve target_width at good quality
                # We want at least 2.5x the target width for sharp rendering (more aggressive)
                min_render_width = target_width * 2.5
                
                # Calculate zoom factor needed
                zoom = min_render_width / page_width
                
                # Clamp zoom between reasonable bounds
                # Min 2.5 (180 DPI) for already large pages
                # Max 10.0 (720 DPI) for very small/zoomed-out pages
                zoom = max(2.5, min(10.0, zoom))
                
                # Create matrix and render
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convert to PIL Image
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                images.append(img)
                
            doc.close()
            return images
        except Exception as e:
            print(f"Error generating preview for {pdf_path}: {e}")
            return []


import os
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GLOG_minloglevel'] = '2'

import google.generativeai as genai
from src.config import APP_CONFIG
import json
import time
import typing_extensions

# Define schema for structured output
class InvoiceData(typing_extensions.TypedDict):
    date: str
    total_value: float
    supplier: str

class GeminiService:
    """Service to handle interaction with Gemini API"""
    def __init__(self):
        api_key = APP_CONFIG["GEMINI_API_KEY"]
        if not api_key:
            print("Warning: GEMINI_API_KEY not found in .env")
        
        genai.configure(api_key=api_key)
        
        # Using 1.5 Pro as requested (mapped to the latest stable Pro model)
        # Note: If 2.5 becomes available, update the model_name
        self.model = genai.GenerativeModel(
            model_name='gemini-2.5-pro',
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": InvoiceData
            }
        )

    def extract_invoice_data(self, file_path):
        """
        Uploads PDF and extracts date and total value.
        Returns: {'date': 'YYYY-MM-DD', 'total_value': 123.45, 'supplier': 'Company'} or None on error.
        """
        import os
        filename = os.path.basename(file_path)
        
        try:
            print(f"[START] {filename}")
            
            # Upload the file
            sample_file = genai.upload_file(path=file_path, display_name="Invoice")
            
            # Wait for file to be active
            while sample_file.state.name == "PROCESSING":
                time.sleep(1)
                sample_file = genai.get_file(sample_file.name)

            if sample_file.state.name == "FAILED":
                print(f"[FAILED] {filename}")
                return None

            prompt = """
            Extract the following information from this invoice:
            
            1. Invoice date - Format as YYYY-MM-DD. If multiple dates exist, prefer the main 'Invoice Date' or 'Issue Date'.
            2. Total value - The grand total as a number (float), e.g., 123.45.
            3. Supplier - The name of the company/supplier issuing the invoice. Use the most prominent business name at the top of the invoice.
            """
            
            response = self.model.generate_content([sample_file, prompt])
            
            # Parse JSON response
            data = json.loads(response.text)
            
            # Cleanup
            try:
                genai.delete_file(sample_file.name)
            except:
                pass

            print(f"[DONE] {filename}")
            return data

        except Exception as e:
            print(f"[ERROR] {filename}: {e}")
            return None

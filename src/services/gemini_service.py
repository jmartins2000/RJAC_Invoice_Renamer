import google.generativeai as genai
from src.config import APP_CONFIG
import json
import time
import typing_extensions

# Define schema for structured output
class InvoiceData(typing_extensions.TypedDict):
    date: str
    total_value: float

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
        Returns: {'date': 'YYYY-MM-DD', 'total_value': 123.45} or None on error.
        """
        try:
            print(f"Uploading {file_path} to Gemini...")
            # Upload the file
            sample_file = genai.upload_file(path=file_path, display_name="Invoice")
            
            # Wait for file to be active
            while sample_file.state.name == "PROCESSING":
                time.sleep(1)
                sample_file = genai.get_file(sample_file.name)

            if sample_file.state.name == "FAILED":
                print("File upload failed.")
                return None

            print(f"Analyzing {file_path}...")
            prompt = """
            Extract the invoice date and the total value (grand total) from this invoice.
            
            - Format the date as YYYY-MM-DD.
            - The total value should be a number (float), e.g., 123.45.
            - If there are multiple dates, prefer the main 'Invoice Date' or 'Issue Date'.
            """
            
            response = self.model.generate_content([sample_file, prompt])
            
            # Parse JSON response
            data = json.loads(response.text)
            
            # Cleanup: Delete file from Gemini storage to save space/quota
            # (Optional but good practice)
            try:
                genai.delete_file(sample_file.name)
            except:
                pass

            return data

        except Exception as e:
            print(f"Gemini Error: {e}")
            return None

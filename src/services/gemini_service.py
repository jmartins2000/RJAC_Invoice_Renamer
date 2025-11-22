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
    
    # Pricing for Gemini 2.5 Pro (Standard tier, prompts <= 200k tokens)
    # Source: https://ai.google.dev/gemini-api/docs/pricing
    # Input: $1.25 per 1M tokens
    # Output: $10.00 per 1M tokens
    PRICE_PER_1M_INPUT = 1.25
    PRICE_PER_1M_OUTPUT = 10.00
    
    def __init__(self):
        api_key = APP_CONFIG["GEMINI_API_KEY"]
        if not api_key:
            print("Warning: GEMINI_API_KEY not found in .env")
        
        genai.configure(api_key=api_key)
        
        self.model = genai.GenerativeModel(
            model_name='gemini-2.5-pro',
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": InvoiceData
            }
        )
        
        # Track usage
        self.total_input_tokens = 0
        self.total_output_tokens = 0

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
            
            # Track token usage
            if hasattr(response, 'usage_metadata'):
                self.total_input_tokens += response.usage_metadata.prompt_token_count
                self.total_output_tokens += response.usage_metadata.candidates_token_count
            
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
            # Extract clean error message
            error_msg = str(e)
            if 'returned "' in error_msg and '".' in error_msg:
                # Extract message between 'returned "' and '".'
                start = error_msg.find('returned "') + len('returned "')
                end = error_msg.find('".', start)
                if start > 0 and end > start:
                    error_msg = error_msg[start:end]
            
            print(f"[ERROR] {filename}: {error_msg}")
            return {'error': error_msg}  # Return error dict instead of None
    
    def get_total_cost_usd(self):
        """Calculate total cost in USD"""
        input_cost = (self.total_input_tokens / 1_000_000) * self.PRICE_PER_1M_INPUT
        output_cost = (self.total_output_tokens / 1_000_000) * self.PRICE_PER_1M_OUTPUT
        return input_cost + output_cost

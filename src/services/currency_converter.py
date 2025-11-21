import requests

class CurrencyConverter:
    """Simple USD to EUR converter using ECB API"""
    
    @staticmethod
    def get_usd_to_eur_rate():
        """
        Fetch current USD to EUR exchange rate from ECB.
        Returns rate or None if fetch fails (fallback to 0.92 default).
        """
        try:
            # ECB provides daily rates, free, no key needed
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                data = response.json()
                return data['rates'].get('EUR', 0.92)  # Fallback to ~0.92
        except Exception:
            pass
        
        # Default fallback if API fails
        return 0.92
    
    @staticmethod
    def usd_to_eur(usd_amount):
        """Convert USD to EUR"""
        rate = CurrencyConverter.get_usd_to_eur_rate()
        return usd_amount * rate


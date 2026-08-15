import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Supabase
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    
    # Shopify
    SHOPIFY_SHOP_DOMAIN = os.getenv('SHOPIFY_SHOP_DOMAIN')
    SHOPIFY_ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')
    SHOPIFY_WEBHOOK_SECRET = os.getenv('SHOPIFY_WEBHOOK_SECRET')
    
    # App Settings
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    DEFAULT_COMMISSION_RATE = float(os.getenv('DEFAULT_COMMISSION_RATE', 5))
    COOKIE_DAYS = int(os.getenv('COOKIE_DAYS', 30))
    MIN_PAYOUT_JPY = int(os.getenv('MIN_PAYOUT_JPY', 20000))
    
    # 短網址設定
    SHORT_URL_DOMAIN = os.getenv('SHORT_URL_DOMAIN', 'https://go.goyoulink.com')
    REDIRECT_TARGET = os.getenv('REDIRECT_TARGET', 'https://goyoutati.com')
    
    # Admin
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')

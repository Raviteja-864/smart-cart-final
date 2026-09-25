import os
from dotenv import load_dotenv

# Load environment variables from .env file if available
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Flask Secret Key
SECRET_KEY = os.getenv("SECRET_KEY", "smartcart_super_secret_key_2026_prod")

# Database Configuration
# Default to SQLite for 1-click deployment & standalone execution
USE_MYSQL = os.getenv("USE_MYSQL", "False").lower() in ("true", "1", "t")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ravi")
DB_NAME = os.getenv("DB_NAME", "smartcart_db")
SQLITE_DB_PATH = os.path.join(BASE_DIR, "smartcart.db")

# Email SMTP Settings (Gmail)
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ("true", "1", "t")
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "ravitejaneeli12@gmail.com")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "hfzb ieom ztng nxqz")

# Razorpay Test / Production Keys
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_TcBFv9vujqInxt")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "OR8lpMjQqxP201Xk4L85qRzN")

# Upload Folder Configuration
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "product_images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
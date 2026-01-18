import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'database.db')
    ADMIN_PASSWORD = 'admin123'

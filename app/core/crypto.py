from cryptography.fernet import Fernet
import base64
import os
from app.core.config import settings

# In production, this should be a 32-byte string encoded in base64
# We use a fallback for dev, but we should always use the setting
def get_cipher():
    return Fernet(settings.ENCRYPTION_KEY.encode())

def encrypt_secret(plain_text: str) -> str:
    """Encrypts a string and returns the base64 encoded cipher text."""
    if not plain_text:
        return plain_text
    cipher = get_cipher()
    return cipher.encrypt(plain_text.encode()).decode()

def decrypt_secret(cipher_text: str) -> str:
    """Decrypts a base64 encoded cipher text and returns the plain text."""
    if not cipher_text:
        return cipher_text
    try:
        cipher = get_cipher()
        return cipher.decrypt(cipher_text.encode()).decode()
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e) if str(e) else 'Invalid token signature or key mismatch'}"
        raise ValueError(f"Failed to decrypt stored credential: {err_msg}")

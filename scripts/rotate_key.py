from cryptography.fernet import Fernet

def encrypt_with_key(text: str, key: str) -> str:
    f = Fernet(key.encode() if isinstance(key, str) else key)
    return f.encrypt(text.encode()).decode()

def decrypt_with_key(token: str, key: str) -> str:
    f = Fernet(key.encode() if isinstance(key, str) else key)
    return f.decrypt(token.encode()).decode()

import base64

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import os
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
 
def decrypt(encrypted_text):
    key_bytes = ENCRYPTION_KEY.encode("utf-8")
    iv = bytes(16)
 
    cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
 
    decrypted_bytes = unpad(
        cipher.decrypt(base64.b64decode(encrypted_text)),
        AES.block_size
    )
 
    return decrypted_bytes.decode("utf-8")
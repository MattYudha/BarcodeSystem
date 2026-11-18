import hashlib
import secrets
import string

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()  # argon2id
# Hash dummy untuk menyamakan waktu respons saat email tidak terdaftar (anti user-enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Return (cocok, hash_baru_jika_perlu_rehash)."""
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False, None
    try:
        return _hasher.verify_and_update(password, password_hash)
    except Exception:  # hash rusak/format tak dikenal -> anggap gagal
        return False, None


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def generate_temp_password(length: int = 12) -> str:
    """Password sementara mudah dibacakan: tanpa karakter mirip (0/O, 1/l/I)."""
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(length))

"""Password helpers for fixtures; browser authentication is implemented in Java."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

password_hash = PasswordHash.recommended()


def hash_password(value: str) -> str:
    return password_hash.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return password_hash.verify(value, hashed)
    except (ValueError, TypeError, UnknownHashError):
        # Existing Spring installations may still contain BCrypt hashes.
        # Unsupported legacy hashes are treated as invalid credentials.
        return False

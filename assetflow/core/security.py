import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("scrypt$"):
        try:
            _, salt, expected = encoded.split("$", 2)
            digest = hashlib.scrypt(
                password.encode(), salt=salt.encode(), n=2**14, r=8, p=1
            ).hex()
            return hmac.compare_digest(digest, expected)
        except (TypeError, ValueError):
            return False
    try:
        return password_context.verify(password, encoded)
    except (TypeError, ValueError):
        return False


def password_needs_rehash(encoded: str) -> bool:
    return encoded.startswith("scrypt$") or password_context.needs_update(encoded)


def create_access_token(
    user_id: int,
    secret_key: str,
    algorithm: str,
    ttl_minutes: int,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=ttl_minutes),
        },
        secret_key,
        algorithm=algorithm,
    )


def decode_access_token(token: str, secret_key: str, algorithm: str) -> int | None:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        return None


def new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, token_hash(raw)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def expires_at(hours: int) -> datetime:
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=hours)

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Perfil, Usuario

password_hash = PasswordHash.recommended()
bearer = HTTPBearer()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_token(user: Usuario) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)
    return jwt.encode(
        {"sub": str(user.id), "perfil": user.perfil.value, "exp": expires},
        settings.jwt_secret,
        algorithm="HS256",
    )


def authenticate_token(token: str, db: Session) -> Usuario:
    error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise error
    user = db.get(Usuario, user_id)
    if not user or not user.ativo:
        raise error
    return user


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    return authenticate_token(credentials.credentials, db)


def require_roles(*roles: Perfil):
    def dependency(user: Usuario = Depends(current_user)) -> Usuario:
        if user.perfil not in roles:
            raise HTTPException(status_code=403, detail="Perfil sem permissão para esta operação")
        return user

    return dependency

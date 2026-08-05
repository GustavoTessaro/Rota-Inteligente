from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import LoginIn, TokenOut, UsuarioOut
from ..security import create_token, current_user, verify_password
from ..models import Usuario

router = APIRouter()


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(Usuario).where(Usuario.email == data.email.lower()))
    if not user or not user.ativo or not verify_password(data.senha, user.senha_hash):
        raise HTTPException(401, "E-mail ou senha inválidos")
    return {"token": create_token(user), "usuario": user}


@router.get("/auth/me", response_model=UsuarioOut)
def me(user: Usuario = Depends(current_user)):
    return user


@router.post("/auth/logout")
def logout(_: Usuario = Depends(current_user)):
    return {"mensagem": "Sessão encerrada. Remova o token armazenado no aplicativo."}

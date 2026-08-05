from datetime import datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import Perfil, Prioridade, StatusEntrega, StatusPedido, StatusVeiculo, TipoVeiculo


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: EmailStr
    senha: str


class UsuarioOut(ORMModel):
    id: int
    nome: str
    email: EmailStr
    telefone: str | None
    perfil: Perfil
    ativo: bool
    organizacao_id: int | None


class TokenOut(BaseModel):
    token: str
    usuario: UsuarioOut


class UsuarioCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    email: EmailStr
    senha: str = Field(min_length=6)
    telefone: str | None = None
    perfil: Perfil
    organizacao_id: int | None = None

    @field_validator("nome", "telefone", mode="before")
    @classmethod
    def strip_user_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class UsuarioUpdate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    email: EmailStr
    senha: str | None = Field(default=None, min_length=6)
    telefone: str | None = None
    perfil: Perfil
    organizacao_id: int | None = None

    @field_validator("nome", "senha", "telefone", mode="before")
    @classmethod
    def strip_user_update_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class StatusIn(BaseModel):
    ativo: bool


class OrganizacaoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    cnpj: str
    email: EmailStr
    telefone: str | None = None
    endereco: str = Field(min_length=5, max_length=255)
    ativo: bool = True

    @field_validator("nome", "endereco", mode="before")
    @classmethod
    def strip_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("cnpj")
    @classmethod
    def validate_cnpj(cls, value):
        digits = re.sub(r"\D", "", value or "")
        if len(digits) != 14:
            raise ValueError("CNPJ deve ter 14 dígitos")
        return digits

    @field_validator("telefone", mode="before")
    @classmethod
    def normalize_phone(cls, value):
        if value is None:
            return None
        digits = re.sub(r"\D", "", value)
        if digits == "":
            return None
        if not 10 <= len(digits) <= 11:
            raise ValueError("Telefone deve ter 10 ou 11 dígitos")
        return digits


class OrganizacaoOut(OrganizacaoCreate, ORMModel):
    id: int
    criado_em: datetime
    atualizado_em: datetime


class VeiculoCreate(BaseModel):
    placa: str = Field(min_length=5, max_length=10)
    modelo: str = Field(min_length=2, max_length=150)
    marca: str = Field(min_length=2, max_length=150)
    ano: int = Field(ge=1900, le=datetime.now().year + 1)
    cor: str = Field(min_length=2, max_length=50)
    capacidade_carga: Decimal = Field(default=Decimal("0"), ge=0)
    capacidade_volume: Decimal = Field(default=Decimal("0"), ge=0)
    tipo: TipoVeiculo
    status: StatusVeiculo = StatusVeiculo.DISPONIVEL
    quilometragem: int = Field(default=0, ge=0)
    ativo: bool = True
    organizacao_id: int | None = None
    motorista_id: int | None = None

    @field_validator("placa", "modelo", "marca", "cor", mode="before")
    @classmethod
    def strip_vehicle_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("placa")
    @classmethod
    def validate_plate(cls, value):
        if not isinstance(value, str):
            raise ValueError("Placa inválida")
        plate = re.sub(r"[^A-Za-z0-9]", "", value).upper()
        if len(plate) < 5 or len(plate) > 10:
            raise ValueError("Placa deve conter entre 5 e 10 caracteres alfanuméricos")
        return plate


class VeiculoUpdate(VeiculoCreate):
    pass


class VeiculoOut(ORMModel):
    id: int
    placa: str
    modelo: str
    marca: str
    ano: int
    cor: str
    capacidade_carga: Decimal
    capacidade_volume: Decimal
    tipo: TipoVeiculo
    status: StatusVeiculo
    quilometragem: int
    ativo: bool
    organizacao_id: int
    motorista_id: int | None
    criado_em: datetime
    atualizado_em: datetime


class ClienteCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    cpf_cnpj: str | None = None
    email: EmailStr | None = None
    telefone: str | None = None
    observacoes: str | None = None

    @field_validator("nome", mode="before")
    @classmethod
    def strip_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("cpf_cnpj", "email", "telefone", "observacoes", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("cpf_cnpj")
    @classmethod
    def validate_document(cls, value):
        if value is None:
            return value
        digits = re.sub(r"\D", "", value)
        if len(digits) not in (11, 14):
            raise ValueError("CPF/CNPJ deve ter 11 ou 14 dígitos")
        return digits

    @field_validator("telefone")
    @classmethod
    def validate_phone(cls, value):
        if value is None:
            return value
        digits = re.sub(r"\D", "", value)
        if not 10 <= len(digits) <= 11:
            raise ValueError("Telefone deve ter 10 ou 11 dígitos")
        return digits


class ClienteOut(ClienteCreate, ORMModel):
    id: int
    ativo: bool


class EnderecoCreate(BaseModel):
    logradouro: str = Field(min_length=2, max_length=150)
    numero: str = Field(min_length=1, max_length=20)
    complemento: str | None = None
    bairro: str = Field(min_length=2, max_length=100)
    cidade: str = Field(min_length=2, max_length=100)
    estado: str = Field(min_length=2, max_length=2)
    cep: str = Field(min_length=8, max_length=10)
    referencia: str | None = None
    tipo: str = "OUTRO"

    @field_validator("logradouro", "numero", "complemento", "bairro", "cidade", "estado", "cep", "referencia", "tipo", mode="before")
    @classmethod
    def strip_address_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("estado")
    @classmethod
    def normalize_state(cls, value):
        return value.upper()

    @field_validator("cep")
    @classmethod
    def normalize_zip_code(cls, value):
        digits = re.sub(r"\D", "", value)
        if len(digits) != 8:
            raise ValueError("CEP deve ter 8 dígitos")
        return digits

    @field_validator("tipo")
    @classmethod
    def validate_address_type(cls, value):
        value = value.upper()
        if value not in {"ORIGEM", "DESTINO", "OUTRO"}:
            raise ValueError("Tipo deve ser ORIGEM, DESTINO ou OUTRO")
        return value


class EnderecoOut(EnderecoCreate, ORMModel):
    id: int
    cliente_id: int


class ProdutoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=150)
    descricao: str | None = None
    peso: Decimal = Field(default=Decimal("0"), ge=0)
    volume: Decimal = Field(default=Decimal("0"), ge=0)
    valor_declarado: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("nome", "descricao", mode="before")
    @classmethod
    def strip_product_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ProdutoOut(ProdutoCreate, ORMModel):
    id: int
    ativo: bool


class PedidoItemIn(BaseModel):
    produto_id: int
    quantidade: int = Field(ge=1)
    valor_unitario: Decimal = Field(ge=0)
    observacoes: str | None = None


class PedidoItemOut(PedidoItemIn, ORMModel):
    id: int
    pedido_id: int


class PedidoCreate(BaseModel):
    cliente_id: int
    prioridade: Prioridade = Prioridade.NORMAL
    forma_pagamento: str | None = None
    observacoes: str | None = None
    itens: list[PedidoItemIn] = Field(min_length=1)


class PedidoOut(ORMModel):
    id: int
    cliente_id: int
    numero_pedido: str
    status: StatusPedido
    prioridade: Prioridade
    forma_pagamento: str | None
    valor_total: Decimal
    observacoes: str | None
    criado_em: datetime


class PedidoStatusIn(BaseModel):
    status: StatusPedido


class EntregaCreate(BaseModel):
    pedido_id: int
    entregador_id: int | None = None
    endereco_origem_id: int
    endereco_destino_id: int
    previsao_saida: datetime | None = None
    previsao_entrega: datetime | None = None
    observacoes: str | None = None


class EntregaOut(ORMModel):
    id: int
    pedido_id: int
    entregador_id: int | None
    endereco_origem_id: int
    endereco_destino_id: int
    status: StatusEntrega
    previsao_saida: datetime | None
    previsao_entrega: datetime | None
    data_coleta: datetime | None
    data_entrega: datetime | None
    observacoes: str | None
    criado_em: datetime


class AtribuirIn(BaseModel):
    entregador_id: int


class EntregaStatusIn(BaseModel):
    status: StatusEntrega
    observacao: str | None = None


class OcorrenciaIn(BaseModel):
    tipo: str = Field(min_length=2, max_length=100)
    descricao: str = Field(min_length=5)

    @field_validator("tipo", "descricao", mode="before")
    @classmethod
    def strip_incident_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class OcorrenciaOut(OcorrenciaIn, ORMModel):
    id: int
    entrega_id: int
    registrado_por: int
    criado_em: datetime


class ComprovanteIn(BaseModel):
    nome_recebedor: str = Field(min_length=2)
    documento_recebedor: str = Field(min_length=3)
    observacao: str | None = None


class ComprovanteOut(ComprovanteIn, ORMModel):
    id: int
    entrega_id: int
    criado_por: int
    criado_em: datetime

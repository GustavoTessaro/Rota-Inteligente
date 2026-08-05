import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now()


class Perfil(str, enum.Enum):
    ADMIN = "ADMIN"
    GESTOR = "GESTOR"
    MOTORISTA = "MOTORISTA"
    CLIENTE = "CLIENTE"


class StatusPedido(str, enum.Enum):
    ABERTO = "ABERTO"
    EM_PROCESSAMENTO = "EM_PROCESSAMENTO"
    FINALIZADO = "FINALIZADO"
    CANCELADO = "CANCELADO"


class Prioridade(str, enum.Enum):
    BAIXA = "BAIXA"
    NORMAL = "NORMAL"
    ALTA = "ALTA"
    URGENTE = "URGENTE"


class StatusEntrega(str, enum.Enum):
    AGUARDANDO_COLETA = "AGUARDANDO_COLETA"
    COLETADA = "COLETADA"
    EM_ROTA = "EM_ROTA"
    ENTREGUE = "ENTREGUE"
    NAO_ENTREGUE = "NAO_ENTREGUE"
    CANCELADA = "CANCELADA"


class TimestampMixin:
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Usuario(TimestampMixin, Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    telefone: Mapped[str | None] = mapped_column(String(20))
    perfil: Mapped[Perfil] = mapped_column(Enum(Perfil))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    organizacao_id: Mapped[int | None] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    organizacao: Mapped["Organizacao" | None] = relationship(back_populates="usuarios")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="motorista")


class Organizacao(TimestampMixin, Base):
    __tablename__ = "organizacoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150), index=True)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(150))
    telefone: Mapped[str | None] = mapped_column(String(20))
    endereco: Mapped[str] = mapped_column(String(255))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="organizacao", cascade="all, delete-orphan")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="organizacao", cascade="all, delete-orphan")


class TipoVeiculo(str, enum.Enum):
    CARRO = "CARRO"
    VAN = "VAN"
    UTILITARIO = "UTILITARIO"
    CAMINHAO = "CAMINHAO"
    CARRETA = "CARRETA"
    OUTRO = "OUTRO"


class StatusVeiculo(str, enum.Enum):
    DISPONIVEL = "DISPONIVEL"
    EM_ROTTA = "EM_ROTTA"
    MANUTENCAO = "MANUTENCAO"


class Veiculo(TimestampMixin, Base):
    __tablename__ = "veiculos"
    id: Mapped[int] = mapped_column(primary_key=True)
    organizacao_id: Mapped[int] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    motorista_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    placa: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    modelo: Mapped[str] = mapped_column(String(150))
    marca: Mapped[str] = mapped_column(String(150))
    ano: Mapped[int] = mapped_column()
    cor: Mapped[str] = mapped_column(String(50))
    capacidade_carga: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    capacidade_volume: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    tipo: Mapped[TipoVeiculo] = mapped_column(Enum(TipoVeiculo))
    status: Mapped[StatusVeiculo] = mapped_column(Enum(StatusVeiculo), default=StatusVeiculo.DISPONIVEL)
    quilometragem: Mapped[int] = mapped_column(default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    organizacao: Mapped[Organizacao] = relationship(back_populates="veiculos")
    motorista: Mapped[Usuario | None] = relationship(back_populates="veiculos")


class Cliente(TimestampMixin, Base):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150), index=True)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(150))
    telefone: Mapped[str | None] = mapped_column(String(20))
    observacoes: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    enderecos: Mapped[list["Endereco"]] = relationship(cascade="all, delete-orphan")


class Endereco(TimestampMixin, Base):
    __tablename__ = "enderecos"
    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    logradouro: Mapped[str] = mapped_column(String(150))
    numero: Mapped[str] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str] = mapped_column(String(100))
    cidade: Mapped[str] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(2))
    cep: Mapped[str] = mapped_column(String(10))
    referencia: Mapped[str | None] = mapped_column(String(255))
    tipo: Mapped[str] = mapped_column(String(20), default="OUTRO")


class Produto(TimestampMixin, Base):
    __tablename__ = "produtos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150))
    descricao: Mapped[str | None] = mapped_column(Text)
    peso: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    volume: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    valor_declarado: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Pedido(TimestampMixin, Base):
    __tablename__ = "pedidos"
    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    numero_pedido: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    status: Mapped[StatusPedido] = mapped_column(Enum(StatusPedido), default=StatusPedido.ABERTO)
    prioridade: Mapped[Prioridade] = mapped_column(Enum(Prioridade), default=Prioridade.NORMAL)
    forma_pagamento: Mapped[str | None] = mapped_column(String(50))
    valor_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    observacoes: Mapped[str | None] = mapped_column(Text)
    criado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    cliente: Mapped[Cliente] = relationship()
    itens: Mapped[list["PedidoItem"]] = relationship(cascade="all, delete-orphan")


class PedidoItem(Base):
    __tablename__ = "pedido_itens"
    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    quantidade: Mapped[int] = mapped_column(default=1)
    valor_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    observacoes: Mapped[str | None] = mapped_column(Text)


class Entrega(TimestampMixin, Base):
    __tablename__ = "entregas"
    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    entregador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    endereco_origem_id: Mapped[int] = mapped_column(ForeignKey("enderecos.id"))
    endereco_destino_id: Mapped[int] = mapped_column(ForeignKey("enderecos.id"))
    status: Mapped[StatusEntrega] = mapped_column(Enum(StatusEntrega), default=StatusEntrega.AGUARDANDO_COLETA)
    previsao_saida: Mapped[datetime | None] = mapped_column(DateTime)
    previsao_entrega: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    data_coleta: Mapped[datetime | None] = mapped_column(DateTime)
    data_entrega: Mapped[datetime | None] = mapped_column(DateTime)
    observacoes: Mapped[str | None] = mapped_column(Text)
    pedido: Mapped[Pedido] = relationship()
    entregador: Mapped[Usuario | None] = relationship()
    historico: Mapped[list["HistoricoEntrega"]] = relationship(cascade="all, delete-orphan")
    ocorrencias: Mapped[list["Ocorrencia"]] = relationship(cascade="all, delete-orphan")
    comprovante: Mapped["ComprovanteEntrega | None"] = relationship(cascade="all, delete-orphan")


class HistoricoEntrega(Base):
    __tablename__ = "historico_entregas"
    id: Mapped[int] = mapped_column(primary_key=True)
    entrega_id: Mapped[int] = mapped_column(ForeignKey("entregas.id"), index=True)
    status_anterior: Mapped[str | None] = mapped_column(String(50))
    status_novo: Mapped[str] = mapped_column(String(50))
    observacao: Mapped[str | None] = mapped_column(Text)
    alterado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)


class Ocorrencia(Base):
    __tablename__ = "ocorrencias"
    id: Mapped[int] = mapped_column(primary_key=True)
    entrega_id: Mapped[int] = mapped_column(ForeignKey("entregas.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(100))
    descricao: Mapped[str] = mapped_column(Text)
    registrado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)


class ComprovanteEntrega(Base):
    __tablename__ = "comprovantes_entrega"
    __table_args__ = (UniqueConstraint("entrega_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entrega_id: Mapped[int] = mapped_column(ForeignKey("entregas.id"), index=True)
    nome_recebedor: Mapped[str] = mapped_column(String(150))
    documento_recebedor: Mapped[str] = mapped_column(String(50))
    observacao: Mapped[str | None] = mapped_column(Text)
    criado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)

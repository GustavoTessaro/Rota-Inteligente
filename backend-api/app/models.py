import enum
import json
from datetime import datetime
from decimal import Decimal
from typing import Optional

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
    organizacao: Mapped[Optional["Organizacao"]] = relationship(back_populates="usuarios")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="motorista")


class Organizacao(TimestampMixin, Base):
    __tablename__ = "organizacoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150), index=True)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(150))
    telefone: Mapped[str | None] = mapped_column(String(20))
    # Legacy free-text address kept for compatibility. Prefer endereco_id.
    endereco: Mapped[str] = mapped_column(String(255))
    endereco_id: Mapped[int | None] = mapped_column(ForeignKey("enderecos.id"), index=True)
    endereco_rel: Mapped[Endereco | None] = relationship("Endereco", foreign_keys=[endereco_id])
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="organizacao", cascade="all, delete-orphan")
    veiculos: Mapped[list["Veiculo"]] = relationship(back_populates="organizacao", cascade="all, delete-orphan")
    enderecos: Mapped[list["Endereco"]] = relationship(
        "Endereco",
        back_populates="organizacao",
        foreign_keys="[Endereco.organizacao_id]",
        cascade="all, delete-orphan",
    )


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


class StatusRota(str, enum.Enum):
    RASCUNHO = "RASCUNHO"
    OTIMIZANDO = "OTIMIZANDO"
    PRONTA = "PRONTA"
    AGUARDANDO_ACEITE = "AGUARDANDO_ACEITE"
    EM_EXECUCAO = "EM_EXECUCAO"
    PAUSADA = "PAUSADA"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"
    PLANEJADA = "PLANEJADA"
    AGUARDANDO_MOTORISTA = "AGUARDANDO_MOTORISTA"
    AGUARDANDO_VEICULO = "AGUARDANDO_VEICULO"
    FINALIZADA = "FINALIZADA"


class CriterioAlternativaRota(str, enum.Enum):
    MAIS_RAPIDA = "MAIS_RAPIDA"
    MAIS_CURTA = "MAIS_CURTA"


class TipoEventoRota(str, enum.Enum):
    PARTIDA = "PARTIDA"
    PAUSA = "PAUSA"
    RETOMADA = "RETOMADA"
    ABASTECIMENTO = "ABASTECIMENTO"
    DESVIO = "DESVIO"
    MANUTENCAO = "MANUTENCAO"
    ENTREGA_REALIZADA = "ENTREGA_REALIZADA"
    ENTREGA_FALHOU = "ENTREGA_FALHOU"
    FINALIZADA = "FINALIZADA"
    CANCELAMENTO = "CANCELAMENTO"
    ALTERNATIVA_RECOMENDADA = "ALTERNATIVA_RECOMENDADA"
    ALTERNATIVA_SELECIONADA = "ALTERNATIVA_SELECIONADA"


class Rota(TimestampMixin, Base):
    __tablename__ = "rotas"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150), index=True)
    descricao: Mapped[str | None] = mapped_column(Text)
    organizacao_id: Mapped[int] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    veiculo_id: Mapped[int | None] = mapped_column(ForeignKey("veiculos.id"), index=True)
    motorista_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    status: Mapped[StatusRota] = mapped_column(Enum(StatusRota), default=StatusRota.PLANEJADA)
    data_planejada: Mapped[datetime | None] = mapped_column(DateTime)
    data_inicio: Mapped[datetime | None] = mapped_column(DateTime)
    data_conclusao: Mapped[datetime | None] = mapped_column(DateTime)
    origem_endereco_id: Mapped[int | None] = mapped_column(ForeignKey("enderecos.id"), index=True)
    destino_endereco_id: Mapped[int | None] = mapped_column(ForeignKey("enderecos.id"), index=True)
    carga_confirmada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    distancia_prevista: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    duracao_prevista: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    distancia_real: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    duracao_real: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    progresso_percentual: Mapped[int] = mapped_column(default=0)
    quilometragem_inicial: Mapped[int | None] = mapped_column()
    quilometragem_final: Mapped[int | None] = mapped_column()
    combustivel_inicial: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    combustivel_final: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    google_route_id: Mapped[str | None] = mapped_column(String(255))
    google_optimization_request_id: Mapped[str | None] = mapped_column(String(255))
    route_geometry: Mapped[str | None] = mapped_column(Text)
    observacoes: Mapped[str | None] = mapped_column(Text)
    alternativa_recomendada_id: Mapped[int | None] = mapped_column(ForeignKey("rota_alternativas.id"), index=True)
    alternativa_escolhida_id: Mapped[int | None] = mapped_column(ForeignKey("rota_alternativas.id"), index=True)
    alternativa_escolhida_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    alternativa_escolhida_em: Mapped[datetime | None] = mapped_column(DateTime)
    organizacao: Mapped[Organizacao] = relationship()
    veiculo: Mapped[Veiculo | None] = relationship()
    motorista: Mapped[Usuario | None] = relationship(foreign_keys=[motorista_id])
    origem_endereco: Mapped[Endereco | None] = relationship(foreign_keys=[origem_endereco_id])
    destino_endereco: Mapped[Endereco | None] = relationship(foreign_keys=[destino_endereco_id])
    entregas: Mapped[list["RotaEntrega"]] = relationship(back_populates="rota", cascade="all, delete-orphan")
    historico: Mapped[list["RotaHistorico"]] = relationship(back_populates="rota", cascade="all, delete-orphan")
    posicoes: Mapped[list["RotaPosicao"]] = relationship(back_populates="rota", cascade="all, delete-orphan")
    alternativas: Mapped[list["RotaAlternativa"]] = relationship(
        "RotaAlternativa", back_populates="rota", foreign_keys="RotaAlternativa.rota_id", cascade="all, delete-orphan"
    )
    alternativa_recomendada: Mapped[Optional["RotaAlternativa"]] = relationship(
        "RotaAlternativa", foreign_keys=[alternativa_recomendada_id], post_update=True
    )
    alternativa_escolhida: Mapped[Optional["RotaAlternativa"]] = relationship(
        "RotaAlternativa", foreign_keys=[alternativa_escolhida_id], post_update=True
    )

    @property
    def alternativas_equivalentes(self) -> bool:
        if len(self.alternativas) < 2:
            return False
        first, second = self.alternativas[:2]
        return (
            first.sequencia == second.sequencia
            and first.distancia_prevista == second.distancia_prevista
            and first.duracao_prevista == second.duracao_prevista
            and first.route_geometry == second.route_geometry
        )

    @property
    def pode_iniciar(self) -> bool:
        return self.alternativa_escolhida_id is not None


class RotaAlternativa(TimestampMixin, Base):
    __tablename__ = "rota_alternativas"
    __table_args__ = (UniqueConstraint("rota_id", "criterio", name="uq_rota_alternativas_rota_criterio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rota_id: Mapped[int] = mapped_column(ForeignKey("rotas.id"), index=True)
    criterio: Mapped[CriterioAlternativaRota] = mapped_column(Enum(CriterioAlternativaRota), nullable=False)
    distancia_prevista: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    duracao_prevista: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    route_geometry: Mapped[str | None] = mapped_column(Text)
    sequencia_json: Mapped[str] = mapped_column(Text, nullable=False)
    rota: Mapped[Rota] = relationship("Rota", back_populates="alternativas", foreign_keys=[rota_id])

    @property
    def sequencia(self) -> list[int]:
        try:
            return json.loads(self.sequencia_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []

    @property
    def recomendada(self) -> bool:
        return bool(self.rota and self.rota.alternativa_recomendada_id == self.id)

    @property
    def selecionada(self) -> bool:
        return bool(self.rota and self.rota.alternativa_escolhida_id == self.id)

    @property
    def equivalente(self) -> bool:
        return bool(self.rota and self.rota.alternativas_equivalentes)


class RotaEntrega(Base):
    __tablename__ = "rota_entregas"
    id: Mapped[int] = mapped_column(primary_key=True)
    rota_id: Mapped[int] = mapped_column(ForeignKey("rotas.id"), index=True)
    entrega_id: Mapped[int] = mapped_column(ForeignKey("entregas.id"), index=True)
    ordem_visita: Mapped[int] = mapped_column(default=0)
    sequencia_otimizada: Mapped[int | None] = mapped_column()
    prioridade: Mapped[Prioridade | None] = mapped_column(Enum(Prioridade))
    janela_inicio: Mapped[datetime | None] = mapped_column(DateTime)
    janela_fim: Mapped[datetime | None] = mapped_column(DateTime)
    tempo_estacionamento: Mapped[int | None] = mapped_column()
    peso: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    rota: Mapped[Rota] = relationship(back_populates="entregas")
    entrega: Mapped[Entrega] = relationship()

    @property
    def status(self):
        return self.entrega.status.value if self.entrega and self.entrega.status else None


class RotaHistorico(Base):
    __tablename__ = "rota_historico"
    id: Mapped[int] = mapped_column(primary_key=True)
    rota_id: Mapped[int] = mapped_column(ForeignKey("rotas.id"), index=True)
    evento: Mapped[TipoEventoRota] = mapped_column(Enum(TipoEventoRota))
    status_anterior: Mapped[str | None] = mapped_column(String(50))
    status_novo: Mapped[str | None] = mapped_column(String(50))
    observacao: Mapped[str | None] = mapped_column(Text)
    entrega_id: Mapped[int | None] = mapped_column(ForeignKey("entregas.id"), index=True)
    alterado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)
    rota: Mapped[Rota] = relationship(back_populates="historico")


class RotaPosicao(Base):
    __tablename__ = "rota_posicoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    rota_id: Mapped[int] = mapped_column(ForeignKey("rotas.id"), index=True)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 8), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(11, 8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    velocidade: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    heading: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    accuracy: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    endereco: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(50))
    motorista_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    veiculo_id: Mapped[int | None] = mapped_column(ForeignKey("veiculos.id"), index=True)
    rota: Mapped[Rota] = relationship(back_populates="posicoes")
    motorista: Mapped[Usuario | None] = relationship()
    veiculo: Mapped[Veiculo | None] = relationship()


class Cliente(TimestampMixin, Base):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(150), index=True)
    cpf_cnpj: Mapped[str | None] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(150))
    telefone: Mapped[str | None] = mapped_column(String(20))
    observacoes: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    enderecos: Mapped[list["Endereco"]] = relationship(
        "Endereco",
        back_populates="cliente",
        foreign_keys="[Endereco.cliente_id]",
        cascade="all, delete-orphan",
    )


class Endereco(TimestampMixin, Base):
    __tablename__ = "enderecos"
    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), index=True, nullable=True)
    organizacao_id: Mapped[int | None] = mapped_column(ForeignKey("organizacoes.id"), index=True, nullable=True)
    logradouro: Mapped[str] = mapped_column(String(150))
    numero: Mapped[str] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str] = mapped_column(String(100))
    cidade: Mapped[str] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(2))
    cep: Mapped[str] = mapped_column(String(10))
    referencia: Mapped[str | None] = mapped_column(String(255))
    tipo: Mapped[str] = mapped_column(String(20), default="OUTRO")
    # Geolocation and formatted address fields
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    pais: Mapped[str | None] = mapped_column(String(100))
    endereco_formatado: Mapped[str | None] = mapped_column(Text)
    place_id: Mapped[str | None] = mapped_column(String(255))
    principal: Mapped[bool] = mapped_column(Boolean, default=False)
    cliente: Mapped[Cliente | None] = relationship(back_populates="enderecos", foreign_keys=[cliente_id])
    organizacao: Mapped[Organizacao | None] = relationship(back_populates="enderecos", foreign_keys=[organizacao_id])


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
    organizacao_id: Mapped[int | None] = mapped_column(ForeignKey("organizacoes.id"), index=True)
    endereco_entrega_id: Mapped[int | None] = mapped_column(ForeignKey("enderecos.id"), index=True)
    numero_pedido: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    status: Mapped[StatusPedido] = mapped_column(Enum(StatusPedido), default=StatusPedido.ABERTO)
    prioridade: Mapped[Prioridade] = mapped_column(Enum(Prioridade), default=Prioridade.NORMAL)
    forma_pagamento: Mapped[str | None] = mapped_column(String(50))
    valor_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    observacoes: Mapped[str | None] = mapped_column(Text)
    criado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    cliente: Mapped[Cliente] = relationship()
    organizacao: Mapped[Organizacao | None] = relationship()
    endereco_entrega: Mapped[Endereco | None] = relationship(foreign_keys=[endereco_entrega_id])
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
    comprovante: Mapped[Optional["ComprovanteEntrega"]] = relationship(cascade="all, delete-orphan")


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
    documento_recebedor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text)
    criado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)

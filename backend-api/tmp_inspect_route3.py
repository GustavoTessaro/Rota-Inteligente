import os
import sys
from sqlalchemy import select

sys.path.insert(0, os.path.abspath("."))
from app.database import SessionLocal
from app.models import Rota, Entrega, Pedido, Endereco, Organizacao

with SessionLocal() as db:
    rota = db.get(Rota, 3)
    print("rota_found", bool(rota))
    if rota:
        print("rota_id", rota.id)
        print("nome", rota.nome)
        print("descricao", rota.descricao)
        print("status", rota.status)
        print("organizacao_id", rota.organizacao_id)
        print("veiculo_id", rota.veiculo_id)
        print("motorista_id", rota.motorista_id)
        print("data_planejada", rota.data_planejada)
        print("origem_endereco_id", rota.origem_endereco_id)
        print("destino_endereco_id", rota.destino_endereco_id)
        print("distancia_prevista", rota.distancia_prevista)
        print("duracao_prevista", rota.duracao_prevista)
        print("distancia_real", rota.distancia_real)
        print("duracao_real", rota.duracao_real)
        print("progresso_percentual", rota.progresso_percentual)
        print("google_route_id", rota.google_route_id)
        print("google_optimization_request_id", rota.google_optimization_request_id)
        print("route_geometry", rota.route_geometry)
        print("observacoes", rota.observacoes)
        print("origem_endereco", rota.origem_endereco)
        print("destino_endereco", rota.destino_endereco)
        print("entregas_count", len(rota.entregas))

        for re in rota.entregas:
            entrega = db.get(Entrega, re.entrega_id)
            pedido = db.get(Pedido, entrega.pedido_id) if entrega else None
            print("-- rota_entrega --")
            print("rota_entrega_id", re.id, "ordem_visita", re.ordem_visita, "sequencia_otimizada", re.sequencia_otimizada, "entrega_id", re.entrega_id)
            if entrega:
                print("entrega_id", entrega.id, "status", entrega.status, "pedido_id", entrega.pedido_id, "endereco_origem_id", entrega.endereco_origem_id, "endereco_destino_id", entrega.endereco_destino_id)
                origem = db.get(Endereco, entrega.endereco_origem_id) if entrega.endereco_origem_id else None
                destino = db.get(Endereco, entrega.endereco_destino_id) if entrega.endereco_destino_id else None
                if origem:
                    print("origem_endereco", origem.id, origem.logradouro, origem.numero, origem.bairro, origem.cidade, origem.estado, origem.cep, "lat=", origem.latitude, "lng=", origem.longitude, "place_id=", origem.place_id)
                if destino:
                    print("destino_endereco", destino.id, destino.logradouro, destino.numero, destino.bairro, destino.cidade, destino.estado, destino.cep, "lat=", destino.latitude, "lng=", destino.longitude, "place_id=", destino.place_id)
                if pedido:
                    print("pedido_endereco_entrega_id", pedido.endereco_entrega_id)

        org = db.scalar(select(Organizacao).where(Organizacao.nome == "Operação Norte"))
        print("operacao_norte found", bool(org))
        if org:
            print("org id", org.id, "endereco_id", org.endereco_id, "endereco", org.endereco)
            if org.endereco_rel:
                e = org.endereco_rel
                print("org endereco_rel", e.id, e.logradouro, e.numero, e.bairro, e.cidade, e.estado, e.cep, e.latitude, e.longitude, e.endereco_formatado, e.place_id)
            else:
                print("org no endereco_rel")

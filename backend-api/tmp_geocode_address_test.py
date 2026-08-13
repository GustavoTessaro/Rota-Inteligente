from app.deps import geocode_address
from app.models import Endereco

if __name__ == '__main__':
    endereco = Endereco(
        cliente_id=1,
        logradouro='Rua Heitor Villa Lobos',
        numero='225',
        complemento=None,
        bairro='São Francisco',
        cidade='Lages',
        estado='SC',
        cep='88506400'
    )
    print('Endereco object:', endereco)
    result = geocode_address(None, endereco)
    import json
    print('Geocode result:', json.dumps(result, ensure_ascii=False, indent=2))
    print('Endereco updated:', endereco.endereco_formatado, endereco.latitude, endereco.longitude, endereco.place_id)

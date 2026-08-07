import httpx

base = 'http://127.0.0.1:8000/api'
auth = httpx.post(base + '/auth/login', json={'email': 'admin@sistema.com', 'senha': '123456'}, timeout=20)
print('login', auth.status_code)
assert auth.status_code == 200

token = auth.json()['token']
headers = {'Authorization': f'Bearer {token}'}

vehicles = httpx.get(base + '/veiculos?limit=20&offset=0', headers=headers, timeout=20).json()
users = httpx.get(base + '/usuarios?limit=50&offset=0', headers=headers, timeout=20).json()
deliveries = httpx.get(base + '/entregas?limit=50&offset=0', headers=headers, timeout=20).json()
vehicle = next(v for v in vehicles if v['ativo'])
driver = next(u for u in users if u['perfil'] == 'MOTORISTA' and u['ativo'])
delivery = next(d for d in deliveries if d['status'] != 'CANCELADA')

payload = {
    'nome': 'Rota validação integrada',
    'descricao': 'Rota criada para validação',
    'organizacao_id': vehicle['organizacao_id'],
    'veiculo_id': vehicle['id'],
    'motorista_id': driver['id'],
    'status': 'PLANEJADA',
    'entregas': [{'entrega_id': delivery['id'], 'ordem_visita': 1}],
}
create = httpx.post(base + '/rotas', headers=headers, json=payload, timeout=20)
print('create', create.status_code)
print(create.text)
route = create.json()

opt = httpx.post(base + f'/rotas/{route["id"]}/otimizar', headers=headers, timeout=20)
print('opt', opt.status_code)
print(opt.text)

status = httpx.patch(
    base + f'/rotas/{route["id"]}/status',
    headers=headers,
    json={'status': 'EM_EXECUCAO', 'evento': 'PARTIDA', 'observacao': 'Iniciada pela validação'},
    timeout=20,
)
print('status', status.status_code)
print(status.text)

final = httpx.patch(
    base + f'/rotas/{route["id"]}/status',
    headers=headers,
    json={'status': 'FINALIZADA', 'evento': 'FINALIZADA', 'observacao': 'Concluída pela validação'},
    timeout=20,
)
print('final', final.status_code)
print(final.text)

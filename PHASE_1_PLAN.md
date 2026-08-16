# 📋 PHASE 1 - Backend do Motorista: Plano Detalhado

**Status:** ✅ Pronto para Implementação  
**Data:** 2026-08-16  
**Estratégia:** TDD (Testes → Código → Validação)

---

## 1. Resumo Executivo

### Objetivo
Criar endpoints específicos do motorista sem alterar o fluxo do gestor, preservando 100% de compatibilidade.

### Abordagem
1. ✅ Escrever testes PRIMEIRO (TDD)
2. 🔧 Implementar código mínimo
3. 🧪 Validar testes passam
4. 🔍 Homologação manual
5. 📊 Antes de Phase 2

---

## 2. Análise de Arquivos

### ✅ Arquivos EXISTENTES que FUNCIONAM já

| Arquivo | Status | Motivo |
|---------|--------|--------|
| `models.py` - Rota | ✅ OK | `motorista_id`, `route_geometry` já existem |
| `models.py` - RotaEntrega | ✅ OK | `ordem_visita`, `sequencia_otimizada` existem |
| `models.py` - Entrega | ✅ OK | Status enum completo |
| `schemas.py` - RotaOut | ✅ OK | Inclui route_geometry e entregas |
| `schemas.py` - RotaEntregaOut | ✅ OK | Inclui ordem_visita e sequencia_otimizada |
| `routers/rotas.py - GET ""` | ✅ OK | Já filtra por motorista_id (linha 223) |
| `routers/rotas.py - GET "/{id}"` | ✅ OK | Já valida acesso (ensure_route_access_scope) |
| `routers/entregas.py` | ✅ OK | Endpoints prontos para reutilizar |

### 📝 Arquivos que SERÃO MODIFICADOS

| Arquivo | Modificação | Tipo | Por quê |
|---------|------------|------|---------|
| `routers/rotas.py` | Adicionar 2 novos endpoints | **Nova função** | Driver endpoints específicos |
| `tests/test_*.py` | Criar novo arquivo de teste | **Novo arquivo** | TDD - testes primeiro |

### ❌ Arquivos QUE NÃO SERÃO TOCADOS

- `models.py` - Sem migração necessária
- `schemas.py` - Campos já existem
- `routers/entregas.py` - Reutiliza existente
- `routers/organizacoes.py`, `usuarios.py`, `veiculos.py`, etc.
- `frontend-flet/app/application.py` - Separado em Phase 2
- `database.py`, `deps.py`, `security.py`

---

## 3. Novos Endpoints a Criar

### Endpoint 1: GET /rotas/motorista/atual

**Caminho:** `/rotas/motorista/atual`

**Método:** GET

**Autenticação:** ✅ Requer usuário MOTORISTA

**Objetivo:** Retornar a rota "ativa" do motorista (próxima a executar ou em execução)

**Lógica:**
1. Pega `user_id` do usuário autenticado
2. Busca rota com `motorista_id == user.id` e status em [EM_EXECUCAO, PRONTA, AGUARDANDO_ACEITE]
3. Se encontrar: retorna essa rota
4. Se não encontrar: retorna 404
5. Se encontrar múltiplas: retorna a primeira (ordem: EM_EXECUCAO > PRONTA > AGUARDANDO_ACEITE)

**Query SQL Esperada:**
```sql
SELECT * FROM rotas 
WHERE motorista_id = ?
  AND status IN ('EM_EXECUCAO', 'PRONTA', 'AGUARDANDO_ACEITE')
ORDER BY 
  CASE status 
    WHEN 'EM_EXECUCAO' THEN 1
    WHEN 'PRONTA' THEN 2
    WHEN 'AGUARDANDO_ACEITE' THEN 3
  END,
  criado_em DESC
LIMIT 1
```

**Response (200 OK):**
```json
{
  "id": 1,
  "nome": "Rota A",
  "status": "EM_EXECUCAO",
  "motorista_id": 5,
  "organizacao_id": 2,
  "veiculo_id": 3,
  "origem_endereco_id": 10,
  "destino_endereco_id": 11,
  "route_geometry": "_p~iF~ps|U_ulLnnqC...",
  "distancia_prevista": 42.5,
  "duracao_prevista": 1200,
  "distancia_real": null,
  "duracao_real": null,
  "data_inicio": "2026-08-16T08:00:00",
  "data_conclusao": null,
  "progresso_percentual": 45,
  "entregas": [
    { "id": 1, "entrega_id": 100, "ordem_visita": 1, "sequencia_otimizada": 3 },
    { "id": 2, "entrega_id": 101, "ordem_visita": 2, "sequencia_otimizada": 2 },
    { "id": 3, "entrega_id": 102, "ordem_visita": 3, "sequencia_otimizada": 1 }
  ]
}
```

**Response (404 Not Found):**
```json
{ "detail": "Nenhuma rota ativa encontrada para este motorista" }
```

**Response (403 Forbidden):**
```json
{ "detail": "Apenas motoristas podem acessar este endpoint" }
```

---

### Endpoint 2: GET /rotas/{rota_id}/sequencia-carregamento

**Caminho:** `/rotas/{rota_id}/sequencia-carregamento`

**Método:** GET

**Autenticação:** ✅ Requer usuário MOTORISTA ou GESTOR

**Objetivo:** Retornar entregas em ordem INVERSA (última a ser entregue carrega primeiro)

**Lógica:**
1. Valida acesso (motorista só acessa sua rota, gestor acessa da sua org)
2. Busca todas as RotaEntrega com `rota_id`
3. Ordena por `ordem_visita` DESC (inverso)
4. Retorna como lista

**Query SQL Esperada:**
```sql
SELECT * FROM rota_entregas 
WHERE rota_id = ?
ORDER BY ordem_visita DESC
```

**Response (200 OK):**
```json
[
  {
    "id": 3,
    "rota_id": 1,
    "entrega_id": 102,
    "ordem_visita": 3,
    "sequencia_otimizada": 1,
    "prioridade": "NORMAL",
    "peso": 5.5,
    "volume": 2.1
  },
  {
    "id": 2,
    "rota_id": 1,
    "entrega_id": 101,
    "ordem_visita": 2,
    "sequencia_otimizada": 2,
    "prioridade": "NORMAL",
    "peso": 3.2,
    "volume": 1.0
  },
  {
    "id": 1,
    "rota_id": 1,
    "entrega_id": 100,
    "ordem_visita": 1,
    "sequencia_otimizada": 3,
    "prioridade": "ALTA",
    "peso": 2.1,
    "volume": 0.5
  }
]
```

**Response (404 Not Found):**
```json
{ "detail": "Rota não encontrada" }
```

**Response (403 Forbidden - Motorista tenta acessar rota de outro):**
```json
{ "detail": "Acesso negado a esta rota" }
```

---

## 4. Validações de Segurança

### Para Endpoint 1: GET /rotas/motorista/atual

- ✅ Validar `user.perfil == Perfil.MOTORISTA`
- ✅ Buscar APENAS rota com `motorista_id == user.id`
- ✅ Retornar 403 se não é motorista
- ✅ Retornar 404 se não tem rota ativa

### Para Endpoint 2: GET /rotas/{rota_id}/sequencia-carregamento

- ✅ Validar `rota_id` existe
- ✅ Se user é MOTORISTA: validar `rota.motorista_id == user.id`
- ✅ Se user é GESTOR: validar `rota.organizacao_id == user.organizacao_id`
- ✅ Se user é ADMIN: permitir qualquer rota
- ✅ Retornar 403 se acesso negado
- ✅ Retornar 404 se rota não existe

---

## 5. Testes a Criar

**Arquivo:** `backend-api/tests/test_driver_endpoints.py` (NOVO)

### Teste 1: GET /rotas/motorista/atual - Sucesso

```
Scenario: Motorista autenticado busca rota ativa
  Given motorista_id=5 está autenticado
    And motorista tem rota com status=EM_EXECUCAO
  When GET /rotas/motorista/atual
  Then Status 200
    And response.motorista_id == 5
    And response.status == EM_EXECUCAO
    And response.route_geometry is not null
```

### Teste 2: GET /rotas/motorista/atual - Nenhuma Rota Ativa

```
Scenario: Motorista sem rota ativa
  Given motorista_id=7 está autenticado
    And motorista não tem nenhuma rota ativa
  When GET /rotas/motorista/atual
  Then Status 404
    And response.detail contains "Nenhuma rota ativa"
```

### Teste 3: GET /rotas/motorista/atual - Acesso Negado (não motorista)

```
Scenario: Usuário não-motorista tenta acessar
  Given user.perfil == GESTOR está autenticado
  When GET /rotas/motorista/atual
  Then Status 403
    And response.detail contains "Apenas motoristas"
```

### Teste 4: GET /rotas/{rota_id}/sequencia-carregamento - Sucesso

```
Scenario: Motorista solicita sequência de carregamento
  Given motorista_id=5 autenticado
    And rota_id=1 pertence ao motorista_id=5
    And rota tem 3 entregas com ordem_visita=[1,2,3]
  When GET /rotas/1/sequencia-carregamento
  Then Status 200
    And len(response) == 3
    And response[0].ordem_visita == 3  (invertido!)
    And response[1].ordem_visita == 2
    And response[2].ordem_visita == 1
```

### Teste 5: GET /rotas/{rota_id}/sequencia-carregamento - Acesso Negado

```
Scenario: Motorista tenta acessar rota de outro motorista
  Given motorista_id=5 autenticado
    And rota_id=99 pertence a motorista_id=8
  When GET /rotas/99/sequencia-carregamento
  Then Status 403
    And response.detail contains "Acesso negado"
```

### Teste 6: GET /rotas/{rota_id}/sequencia-carregamento - Rota Não Existe

```
Scenario: Motorista tenta acessar rota inexistente
  Given motorista_id=5 autenticado
  When GET /rotas/99999/sequencia-carregamento
  Then Status 404
```

### Teste 7: GET /rotas/motorista/atual - Prioridade de Status

```
Scenario: Motorista tem múltiplas rotas, busca a correta
  Given motorista_id=5 autenticado
    And motorista tem:
      - rota_id=1 com status=EM_EXECUCAO
      - rota_id=2 com status=PRONTA
      - rota_id=3 com status=PLANEJADA
  When GET /rotas/motorista/atual
  Then Status 200
    And response.id == 1  (EM_EXECUCAO tem prioridade)
```

---

## 6. Dados de Teste (Seed)

Para os testes funcionarem, precisamos de fixtures com:

```python
# Motorista
usuario_motorista = Usuario(
    id=5,
    nome="João da Silva",
    email="joao@empresa.com",
    perfil=Perfil.MOTORISTA,
    telefone="11999999999",
    organizacao_id=2
)

# Rota Ativa
rota_ativa = Rota(
    id=1,
    nome="Rota A",
    status=StatusRota.EM_EXECUCAO,
    motorista_id=5,
    organizacao_id=2,
    veiculo_id=3,
    origem_endereco_id=10,
    destino_endereco_id=11,
    route_geometry="_p~iF~ps|U_ulLnnqC_mqNvxq`@",
    distancia_prevista=Decimal("42.5"),
    duracao_prevista=Decimal("1200")
)

# Entregas
rota_entrega_1 = RotaEntrega(
    id=1,
    rota_id=1,
    entrega_id=100,
    ordem_visita=1,
    sequencia_otimizada=3
)
rota_entrega_2 = RotaEntrega(
    id=2,
    rota_id=1,
    entrega_id=101,
    ordem_visita=2,
    sequencia_otimizada=2
)
rota_entrega_3 = RotaEntrega(
    id=3,
    rota_id=1,
    entrega_id=102,
    ordem_visita=3,
    sequencia_otimizada=1
)
```

---

## 7. Mudanças no Código

### ❌ NÃO MODIFICAR

```python
# models.py - Zero mudanças
# schemas.py - Zero mudanças
# deps.py - Reutilizar ensure_route_access_scope existente
# security.py - Reutilizar current_user existente
```

### ✅ MODIFICAR `routers/rotas.py`

**Adicionar 2 funções novas:**

**Função 1:**
```python
@router.get("/motorista/atual", response_model=RotaOut)
def get_motorista_rota_atual(
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    """Retorna a rota ativa do motorista autenticado."""
    
    # Validação
    if user.perfil != Perfil.MOTORISTA:
        raise HTTPException(403, "Apenas motoristas podem acessar este endpoint")
    
    # Lógica
    # ... (implementar)
```

**Função 2:**
```python
@router.get("/{rota_id}/sequencia-carregamento", response_model=list[RotaEntregaOut])
def get_rota_sequencia_carregamento(
    rota_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    """Retorna sequência de carregamento (entregas em ordem inversa)."""
    
    # Validação de acesso
    # ... (implementar)
```

### ✅ CRIAR `tests/test_driver_endpoints.py` (NOVO)

**Arquivo novo** com 7 testes TDD

---

## 8. Checklist de Implementação

### Testes
- [ ] Criar arquivo `tests/test_driver_endpoints.py`
- [ ] Escrever 7 testes (antes do código!)
- [ ] Executar e verificar que FALHAM (red phase)

### Implementação
- [ ] Adicionar função 1: `get_motorista_rota_atual()`
- [ ] Adicionar função 2: `get_rota_sequencia_carregamento()`
- [ ] Executar testes até PASSAREM (green phase)

### Validação
- [ ] Todos 7 testes passando
- [ ] Sem quebra em endpoints existentes
- [ ] Verificar segurança (403 quando apropriado)
- [ ] Verificar dados retornados (JSON válido)

### Homologação Manual
- [ ] Testar com Postman/API
- [ ] Confirmar acesso por motorista real
- [ ] Confirmar rejeição de outro motorista
- [ ] Confirmar route_geometry incluído
- [ ] Confirmar sequência invertida corretamente

### Antes de Phase 2
- [ ] Documentação de API atualizada
- [ ] Commit com mensagem: `feat(backend): driver endpoints fase 1`
- [ ] Code review aprovado
- [ ] Merge para main/develop

---

## 9. Estimativas de Tempo

| Tarefa | Tempo | Status |
|--------|-------|--------|
| Escrever testes | 1h | ⏳ |
| Implementar endpoints | 1.5h | ⏳ |
| Debugar/ajustar | 1h | ⏳ |
| Homologação manual | 0.5h | ⏳ |
| **Total Phase 1** | **4h** | ⏳ |

---

## 10. Comando para Executar Testes

```bash
cd backend-api

# Executar apenas testes de driver
pytest tests/test_driver_endpoints.py -v

# Executar com cobertura
pytest tests/test_driver_endpoints.py -v --cov=app.routers.rotas

# Executar tudo (garante sem quebra)
pytest tests/ -v
```

---

## 11. Confirmação Final Antes de Codificar

✅ **Arquivos a modificar:**
- `backend-api/app/routers/rotas.py` (adicionar 2 funções)
- `backend-api/tests/test_driver_endpoints.py` (novo arquivo)

✅ **Arquivos a criar:**
- `backend-api/tests/test_driver_endpoints.py` (7 testes TDD)

✅ **Endereços (endpoints):**
1. `GET /rotas/motorista/atual`
2. `GET /rotas/{rota_id}/sequencia-carregamento`

✅ **Nada será quebrado:**
- Endpoints existentes não são modificados
- Schemas não são alterados
- Models não necessitam migração
- Gestor continua usando `GET /rotas` com filtros

✅ **Segurança:**
- Motorista só vê sua rota
- Gestor vê rotas da sua organização
- Admin vê todas as rotas

**Pronto para começar a codificar? 🚀**


# 🎯 PHASE 1 - CONFIRMAÇÃO FINAL DO ESCOPO

---

## ✅ O QUE SERÁ FEITO

### Backend - 2 Novos Endpoints

```
┌────────────────────────────────────────────────────┐
│ Endpoint 1: GET /rotas/motorista/atual             │
├────────────────────────────────────────────────────┤
│ Propósito: Retorna rota ativa do motorista logado  │
│                                                    │
│ Input:  Usuário autenticado (tipo MOTORISTA)       │
│ Output: 1 Rota com status=[EM_EXECUCAO|PRONTA|...]│
│                                                    │
│ Segurança: Motorista SÓ vê sua própria rota        │
│            Retorna 403 se não é motorista          │
│            Retorna 404 se não tem rota ativa       │
└────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────┐
│ Endpoint 2: GET /rotas/{id}/sequencia-carregamento │
├────────────────────────────────────────────────────┤
│ Propósito: Entregas em ordem INVERSA para carregar│
│                                                    │
│ Input:  rota_id + usuário autenticado              │
│ Output: Lista de RotaEntrega [C, B, A]             │
│         (último a entregar carrega primeiro)       │
│                                                    │
│ Segurança: Motorista acessa APENAS sua rota        │
│            Gestor acessa rotas da sua org          │
│            Retorna 403 se acesso negado            │
│            Retorna 404 se rota não existe          │
└────────────────────────────────────────────────────┘
```

### Testes - 7 Casos de Teste (TDD)

```
📝 test_driver_endpoints.py (novo arquivo)
   
   ✅ test_get_motorista_rota_atual_sucesso
      → Motorista tem rota ativa → Retorna 200 + dados
   
   ✅ test_get_motorista_rota_atual_sem_rota
      → Motorista sem rota ativa → Retorna 404
   
   ✅ test_get_motorista_rota_atual_acesso_negado
      → Gestor tenta acessar → Retorna 403
   
   ✅ test_get_sequencia_carregamento_sucesso
      → Entregas [1,2,3] → Retorna [3,2,1] (invertido)
   
   ✅ test_get_sequencia_carregamento_acesso_negado
      → Motorista A tenta acessar rota de Motorista B → 403
   
   ✅ test_get_sequencia_carregamento_nao_existe
      → rota_id=99999 → Retorna 404
   
   ✅ test_get_motorista_rota_atual_prioridade_status
      → Múltiplas rotas → Retorna EM_EXECUCAO primeiro
```

---

## 📁 ARQUIVOS MODIFICADOS

### Arquivo 1: `backend-api/app/routers/rotas.py`

**O que muda:** Adicionar 2 funções novas no fim do arquivo

```python
# Linha 500+ (fim do arquivo)

@router.get("/motorista/atual", response_model=RotaOut)
def get_motorista_rota_atual(
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    """
    Retorna a rota ativa (EM_EXECUCAO, PRONTA, AGUARDANDO_ACEITE) 
    do motorista autenticado.
    
    - Apenas MOTORISTA pode chamar
    - Retorna 403 se perfil != MOTORISTA
    - Retorna 404 se não tem rota ativa
    """
    # ... (implementação)

@router.get("/{rota_id}/sequencia-carregamento", response_model=list[RotaEntregaOut])
def get_rota_sequencia_carregamento(
    rota_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    """
    Retorna entregas em ordem INVERSA (última a ser entregue carrega primeiro).
    
    - Motorista acessa APENAS sua rota
    - Gestor acessa rotas da sua organização
    - Admin acessa todas as rotas
    - Retorna 403 se acesso negado
    - Retorna 404 se rota não existe
    """
    # ... (implementação)
```

**O que NÃO muda:**
- Outros endpoints (`GET "", `GET "/{id}"`, `POST "/gerar"`, etc.) 
- Imports (nenhum novo necessário)
- Lógica existente

---

### Arquivo 2: `backend-api/tests/test_driver_endpoints.py` (NOVO)

**Conteúdo:** 7 testes TDD

```python
import pytest
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.main import app
from app.models import (Usuario, Rota, RotaEntrega, Entrega, Endereco, 
                        Organizacao, Veiculo, Perfil, StatusRota, StatusEntrega)
from app.schemas import RotaOut, RotaEntregaOut

client = TestClient(app)

class TestMotoristaRotaAtual:
    def test_get_motorista_rota_atual_sucesso(self, db: Session):
        # ARRANGE: Motorista com rota ativa
        # ACT: GET /rotas/motorista/atual
        # ASSERT: Status 200 + dados corretos
        pass
    
    def test_get_motorista_rota_atual_sem_rota(self, db: Session):
        # ARRANGE: Motorista sem rota ativa
        # ACT: GET /rotas/motorista/atual
        # ASSERT: Status 404
        pass
    
    def test_get_motorista_rota_atual_acesso_negado(self, db: Session):
        # ARRANGE: Usuário é GESTOR
        # ACT: GET /rotas/motorista/atual
        # ASSERT: Status 403 "Apenas motoristas"
        pass
    
    def test_get_motorista_rota_atual_prioridade_status(self, db: Session):
        # ARRANGE: Motorista com 3 rotas (EM_EXECUCAO, PRONTA, PLANEJADA)
        # ACT: GET /rotas/motorista/atual
        # ASSERT: Status 200 + retorna EM_EXECUCAO (maior prioridade)
        pass

class TestSequenciaCarregamento:
    def test_get_sequencia_carregamento_sucesso(self, db: Session):
        # ARRANGE: Rota com 3 entregas (ordem_visita: 1,2,3)
        # ACT: GET /rotas/{id}/sequencia-carregamento
        # ASSERT: Status 200 + retorna ordem [3,2,1]
        pass
    
    def test_get_sequencia_carregamento_acesso_negado(self, db: Session):
        # ARRANGE: Motorista A, rota de Motorista B
        # ACT: GET /rotas/{id}/sequencia-carregamento
        # ASSERT: Status 403 "Acesso negado"
        pass
    
    def test_get_sequencia_carregamento_nao_existe(self, db: Session):
        # ARRANGE: rota_id = 99999
        # ACT: GET /rotas/99999/sequencia-carregamento
        # ASSERT: Status 404
        pass
```

---

## ❌ ARQUIVOS QUE NÃO SERÃO ALTERADOS

```
✅ models.py          → Nenhuma mudança (campos já existem)
✅ schemas.py         → Nenhuma mudança (schemas já temos)
✅ database.py        → Nenhuma mudança (DB já pronto)
✅ deps.py            → Nenhuma mudança (vamos reutilizar)
✅ security.py        → Nenhuma mudança (autenticação já existe)
✅ requirements.txt   → Nenhuma mudança (imports já têm tudo)
✅ routers/entregas.py        → Nenhuma mudança
✅ routers/usuarios.py        → Nenhuma mudança
✅ routers/organizacoes.py    → Nenhuma mudança
✅ frontend-flet/     → Nenhuma mudança (Phase 2)
```

---

## 🔒 SEGURANÇA GARANTIDA

| Cenário | Validação | Resultado |
|---------|-----------|-----------|
| Motorista acessa `/rotas/motorista/atual` | ✅ user.perfil == MOTORISTA | 200 + dados |
| Gestor acessa `/rotas/motorista/atual` | ❌ user.perfil == GESTOR | 403 Forbidden |
| Motorista A acessa rota de Motorista B | ❌ rota.motorista_id != user.id | 403 Forbidden |
| Gestor A acessa rota da Org B | ❌ rota.org_id != user.org_id | 403 Forbidden |
| Admin acessa qualquer rota | ✅ user.perfil == ADMIN | 200 + dados |
| Motorista acessa rota inexistente | ❌ rota_id não existe | 404 Not Found |

---

## 📊 RESUMO DE MUDANÇAS

| Item | Modificação | Impacto |
|------|------------|---------|
| Endpoints novos | +2 | Zero quebra existente |
| Testes novos | +7 | Cobertura de driver endpoints |
| Linhas de código | ~80-100 | Mínimo necessário |
| Dependências novas | 0 | Reutiliza imports existentes |
| Migrações DB | 0 | Nenhuma necessária |
| Compatibilidade | ✅ 100% | Etapas 1, 2, 3 não afetadas |

---

## 🚀 PRÓXIMA AÇÃO

✅ Você confirmou o plano?  
✅ Mudanças estão claras?  
✅ Segurança está coberta?  

**Se SIM:** Vou começar Phase 1 com:
1. 📝 Escrever 7 testes (TDD - red phase)
2. 🔧 Implementar 2 endpoints (green phase)
3. 🧪 Validar todos testes passam
4. 🔍 Homologação manual no Postman
5. ✅ Merge quando validado

**Confirme e começamos! 🎯**


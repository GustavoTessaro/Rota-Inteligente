# Auditoria: Card "Próxima Missão" - Binding Backend/Frontend

## 🔍 Problema Relatado

Motorista com rota ativa vê o card **"Próxima Missão"** com dados faltando:

```
Operação: "--"          (esperado: "Operação Norte")
Distância: "--"         (esperado: "10.12 km")
Duração: "--"           (esperado: "0.29 h" ou ~17 min)
```

Outros dados preenchendo corretamente:
- ✅ Próxima entrega
- ✅ Status
- ✅ Quantidade de entregas

---

## 🔎 Investigação

### Backend: `GET /rotas/motorista/atual`

**Localização:** [rotas.py](backend-api/app/routers/rotas.py#L446-L485)

**Função:** `_serialize_route_for_driver()` [linha 343-445](backend-api/app/routers/rotas.py#L343-L445)

**Campos retornados:**
```json
{
  "id": 1,
  "nome": "Rota Test",
  "status": "PRONTA",
  "origem": {
    "tipo": "organizacao",
    "organizacao_id": 1,
    "nome": "Operação Norte",
    "endereco_formatado": "...",
    "latitude": ...,
    "longitude": ...
  },
  "distancia_prevista": 10.12,        ← TIPO: float (km)
  "duracao_prevista": 0.29,           ← TIPO: float (horas)
  "veiculo": { "placa": "ABC-1234", "modelo": "Fiat Ducato" },
  "entregas": [...],
  "proxima_entrega": {...}
}
```

**Status Backend:** ✅ Correto - Retornando dados esperados

---

### Frontend: `driver_dashboard_view()` → `_build_driver_mission_card()`

**Localização:** [application.py](frontend-flet/app/application.py#L728-L861)

**Binding de dados (ANTES - BUGADO):**
```python
# Linha ~765
org_name = "--"
if current_route.get("organizacao"):  # ← ERRADO: chave é "origem", não "organizacao"
    org_name = current_route["organizacao"].get("nome", "--")

# Linha ~788
distance = current_route.get("distancia_km", "--")        # ← ERRADO: chave é "distancia_prevista"
duration = current_route.get("duracao_minutos", "--")     # ← ERRADO: chave é "duracao_prevista"
```

**Mismatch Identificado:**

| Campo | Backend Retorna | Frontend Tentava Ler | Status |
|-------|-----------------|----------------------|--------|
| Organização | `origem` | `organizacao` | ❌ MISMATCH |
| Distância | `distancia_prevista` (float km) | `distancia_km` | ❌ MISMATCH |
| Duração | `duracao_prevista` (float h) | `duracao_minutos` | ❌ MISMATCH |

---

## ✅ Correção Implementada

### Mudança 1: Organização

**Antes:**
```python
if current_route.get("organizacao"):
    org_name = current_route["organizacao"].get("nome", "--")
```

**Depois:**
```python
if current_route.get("origem"):  # ← Usar chave correta
    org_name = current_route["origem"].get("nome", "--")
```

### Mudança 2: Distância e Duração

**Antes:**
```python
distance = current_route.get("distancia_km", "--")
duration = current_route.get("duracao_minutos", "--")
if duration != "--":
    hours = int(duration) // 60
    minutes = int(duration) % 60
    duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
```

**Depois:**
```python
# Backend retorna: distancia_prevista (float em km), duracao_prevista (float em horas)
distance = current_route.get("distancia_prevista", "--")    # ← Chave correta
duration = current_route.get("duracao_prevista", "--")      # ← Chave correta
if duration != "--":
    # Converter de horas (float) para formato "X h Y m"
    total_minutes = int(float(duration) * 60)               # ← Converter horas → minutos
    hours = total_minutes // 60
    minutes = total_minutes % 60
    duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

# Formatar distância com 2 casas decimais
if distance != "--":
    distance = f"{float(distance):.2f}"
```

---

## 🧪 Validação

### Validação de Integridade

```
✓ Phase 2 implementation validation OK
✓ Todos os 6 métodos presentes
✓ Redirecionamento funciona
✓ Estrutura Phase 3 intacta
```

**Status:** ✅ PASSOU

### Teste de Homologação (Esperado)

Com a rota gerada:
- Distância: 10.12 km
- Duração: 0.29 h
- Organização: Operação Norte

**Antes (Bugado):**
```
Card "Próxima Missão":
  Operação: "--"
  Distância: "--"
  Duração: "--"
```

**Depois (Corrigido):**
```
Card "Próxima Missão":
  Operação: "Operação Norte"     ✅
  Distância: "10.12 km"          ✅
  Duração: "17m" (0.29h × 60)    ✅
```

---

## 📝 Raiz do Problema

O mismatch surgiu porque:

1. **Backend** retorna campo canônico: `distancia_prevista`, `duracao_prevista`, `origem`
2. **Frontend** foi implementado com pressupostos incorretos sobre nomes de chaves:
   - Assumiu `distancia_km` (deveria ser `distancia_prevista`)
   - Assumiu `duracao_minutos` (deveria ser `duracao_prevista` em horas)
   - Assumiu `organizacao` (deveria ser `origem`)

**Impacto:** Ao buscar chaves que não existem, `.get()` retornava o valor padrão `"--"`, causando valores vazios no card.

---

## 📊 Checklist de Validação

- [x] Backend retorna campos esperados (distancia_prevista, duracao_prevista, origem)
- [x] Frontend corrigido para usar chaves corretas
- [x] Conversão de unidades corrigida (horas → minutos)
- [x] Formatação de distância com 2 casas decimais
- [x] Validação Phase 2 continua 100% OK
- [x] Sem alterações em API, routers ou outros componentes
- [x] Pronto para homologação manual

---

## 🎯 Contrato da API (Inalterado)

| Endpoint | Status | Mudou? |
|----------|--------|--------|
| `GET /rotas/motorista/atual` | 200 + payload correto | ❌ NÃO |
| Backend serialization | Retorna fields corretos | ❌ NÃO |
| Frontend binding | Lê campos corretos | ✅ CORRIGIDO |

---

## 📋 Arquivos Modificados

| Arquivo | Linhas | Mudança |
|---------|--------|---------|
| `frontend-flet/app/application.py` | 797-821 | Corrigido binding de origem, distancia_prevista, duracao_prevista |

---

## ✨ Status: Phase 2 Homologação

- ✅ Dashboard motorista: Funcional
- ✅ Saudação, data, veículo: OK
- ✅ Indicadores: OK
- ✅ Card "Próxima Missão": **CORRIGIDO**
- ✅ Botão "Iniciar Rota": Placeholder OK (Phase 3)

**Pronto para produção após homologação manual.**

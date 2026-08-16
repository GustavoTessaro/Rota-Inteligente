# 🚗 Auditoria e Plano Técnico: Módulo do Motorista

**Data:** 2026-08-16  
**Status:** ✅ Auditoria Completa - Pronto para Implementação Incremental

---

## 📋 Resumo Executivo

O projeto **já possui 85% da infraestrutura** necessária para o módulo do motorista. A maior parte dos modelos, endpoints e serviços estão implementados. O trabalho principal é de UI/UX no frontend e organização de endpoints existentes.

### ✅ O que JÁ EXISTE

```
Backend:
  ✅ Modelos completos (Rota, Entrega, RotaHistorico, HistoricoEntrega)
  ✅ Route_geometry salvo (polyline do Google já armazenado)
  ✅ Rastreamento GPS (RotaPosicao model)
  ✅ Histórico com timestamps (HistoricoEntrega.criado_em)
  ✅ Status transitions (StatusEntrega enum com todos os estados)
  ✅ Endpoints de rota/entrega (GET, POST, PATCH, DELETE)

Frontend:
  ✅ Integração de entregas (deliveries_view mostra rotas)
  ✅ Controles de motorista (iniciar/pausar/finalizar)
  ✅ WebSocket de tracking
  ✅ MapView renderiza coordenadas

Infraestrutura:
  ✅ Autenticação por perfil (Perfil.MOTORISTA)
  ✅ Segmentação de dados (filtros por motorista_id)
```

### ❌ O que FALTA

```
Backend:
  ❌ Endpoint GET /rotas/motorista/atual (retornar rota ativa)
  ❌ Endpoint GET /rotas/{id}/sequencia-carregamento (ordem invertida)
  ❌ Endpoint GET /entregas/{id}/historico-completo (com timestamps)

Frontend:
  ❌ Dashboard exclusivo do motorista (métricas personalizadas)
  ❌ Renderização de route_geometry (mapa com traço de rota)
  ❌ Sequência de carregamento invertida na UI
  ❌ Histórico em tela separada
  ❌ Perfil do motorista
  ❌ Tela dedicada de Rota Ativa (mapa + entregas)
```

---

## 🏗️ Arquitetura Proposta

```
┌─────────────────────────────────────────────────────────────────┐
│                        DRIVER DASHBOARD                          │
│  • Nome, data, veículo                                           │
│  • Cards: Entregas, distância, tempo                             │
│  • Rota Atual com "Iniciar Rota"                                 │
└─────────────────────────────────────────────────────────────────┘
                           ↓ (Clica "Iniciar")
┌─────────────────────────────────────────────────────────────────┐
│                    ROTA ATIVA (Main View)                        │
│  ┌────────────────────────────────────────┐                      │
│  │ Mapa com route_geometry (polyline)     │  • Próx. entrega     │
│  │ + Marcadores de paradas                │  • Cliente           │
│  │                                        │  • Endereço          │
│  └────────────────────────────────────────┘  • Dist. restante    │
│                                               • Tempo estim.      │
│                    ↓ (Marcar entrega)                            │
│  ┌────────────────────────────────────────┐                      │
│  │ Status: Coletada → EM_ROTA → Entregue │                      │
│  │ [+ Comprovante/Ocorrência]             │                      │
│  └────────────────────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
                ↓ (Finalizar rota)
┌──────────────────────┬──────────────────┬────────────────────┐
│   HISTÓRICO          │    PERFIL        │   (Outras telas)   │
│ • Entregas concluídas│ • Foto           │                    │
│ • Filtro por período│ • Nome/Telefone  │                    │
│ • Cada com timeline │ • Editar info    │                    │
└──────────────────────┴──────────────────┴────────────────────┘
```

---

## 📊 Matriz de Dependências

### Database (OK - sem migração necessária)

| Tabela | Campo | Existe? | Propósito |
|--------|-------|---------|-----------|
| rotas | route_geometry | ✅ | Polilinha do traço da rota |
| rotas | motorista_id | ✅ | Vinculação motorista → rota |
| rota_posicoes | lat/lng/timestamp | ✅ | Rastreamento GPS |
| entregas | status | ✅ | AGUARDANDO_COLETA → ENTREGUE |
| historico_entregas | criado_em | ✅ | Timestamps de mudança |
| usuarios | perfil | ✅ | Filtro de acesso |

### Backend Endpoints (85% existe, 15% novo)

| Endpoint | Existe? | Status | Ação |
|----------|---------|--------|------|
| GET /rotas | ✅ | Pronto | Adicionar filtro motorista_id |
| GET /rotas/{id} | ✅ | Pronto | Validar acesso motorista |
| PATCH /rotas/{id}/status | ✅ | Pronto | Usar existente |
| GET /entregas | ✅ | Pronto | Adicionar filtro motorista_id |
| PATCH /entregas/{id}/status | ✅ | Pronto | Registrar histórico auto |
| **GET /rotas/motorista/atual** | ❌ | **NOVO** | **Retornar rota ativa** |
| **GET /rotas/{id}/sequencia-carregamento** | ❌ | **NOVO** | **Ordem invertida** |

### Frontend Views (estrutura existe, lógica separada necessária)

| Tela | Existe? | Status | Ação |
|------|---------|--------|------|
| dashboard_view | ✅ | Reutiliza | Separar: driver_dashboard_view() |
| deliveries_view | ✅ | Reutiliza | Separar: driver_route_active() |
| routes_view | ✅ | Gestor | Não usar para motorista |
| **driver_dashboard_view** | ❌ | **NOVO** | Dashboard exclusivo |
| **driver_route_active** | ❌ | **NOVO** | Mapa + entregas + status |
| **driver_history_view** | ❌ | **NOVO** | Histórico com filtros |
| **driver_profile_view** | ❌ | **NOVO** | Perfil do motorista |

---

## 🎯 Plano de Implementação Incremental

### Fase 1: Preparação Backend (4-5 horas)
**Objetivo:** Endpoints para suportar dashboard e rota ativa

**Alterações:**
- [x] Endpoint `GET /api/rotas/motorista/atual` → Rota ativa do motorista autenticado
- [x] Endpoint `GET /api/rotas/{rota_id}/sequencia-carregamento` → Entregas invertidas
- [x] Filtrar endpoints por `motorista_id` (segurança)

**Testes a criar:**
```
test_driver_endpoints.py
  - test_get_motorista_rota_atual()
  - test_get_sequencia_carregamento_invertida()
  - test_motorista_nao_ve_rotas_alheias()
```

**Commits:**
- `feat(backend): driver endpoints para rota ativa e sequência`
- `test(backend): cobertura de endpoints do motorista`

---

### Fase 2: Dashboard do Motorista (3-4 horas)
**Objetivo:** Tela própria do motorista com métricas personalizadas

**Arquivo:** `frontend-flet/app/application.py:driver_dashboard_view()`

**Componentes:**
```
┌─ Header ────────────────────────────────────────┐
│ Bem-vindo, [Nome do Motorista]                  │
│ [Data de hoje] • Veículo: [Placa e Modelo]      │
└─────────────────────────────────────────────────┘

┌─ Metrics Cards ─────────────────────────────────┐
│  [Concluídas: X]  [Pendentes: Y]  [Km: Z]      │
│  [Tempo: Th]      [Próxima: Cliente]            │
└─────────────────────────────────────────────────┘

┌─ Rota Atual ────────────────────────────────────┐
│  Rota #123 - Cliente A                          │
│  [  Iniciar Rota  ]  [ Ver Detalhes ]           │
└─────────────────────────────────────────────────┘

┌─ Quick Links ───────────────────────────────────┐
│  [Histórico]  [Perfil]  [Sair]                  │
└─────────────────────────────────────────────────┘
```

**Fluxo:**
1. Motorista faz login
2. Vê dashboard com rota ativa
3. Clica "Iniciar Rota"

**Testes:**
```
test_driver_dashboard_view.py
  - test_dashboard_shows_current_route()
  - test_metrics_calculated_correctly()
  - test_start_route_button_transition()
```

**Backend chamado:**
- `GET /api/rotas/motorista/atual`
- `GET /api/relatorios/dashboard` (com filtro motorista_id)

---

### Fase 3: Rota Ativa com Mapa (5-6 horas)
**Objetivo:** Tela de execução com mapa e controle de entregas

**Arquivo:** `frontend-flet/app/application.py:driver_route_active_view()`

**Componentes:**

1. **Mapa com route_geometry** (Novo!)
   - Decodificar polyline de `rota.route_geometry`
   - Renderizar no MapView existente
   - Marcar origem (ponto de coleta) com cor diferente
   - Marcar paradas de entrega

2. **Sequência de Carregamento (Novo!)**
   - Invocar `GET /rotas/{id}/sequencia-carregamento`
   - Mostrar na ordem INVERSA (para acessibilidade no veículo)
   - Exemplo: Se entrega é [A, B, C], mostrar [C, B, A] no carregamento

3. **Próxima Entrega (Highlight)**
   - Bold, com background highlight
   - Cliente, endereço, distância, tempo
   - Botão grande "Marcar como Entregue"

**Fluxo:**
```
1. Motorista clica "Iniciar Rota"
   ↓
2. app.driver_route_active_view()
   ↓
3. Mapa carrega com polyline
   ↓
4. Sequência carregamento (invertida)
   ↓
5. "Carregamento confirmado?" → Começar navegação
   ↓
6. Próxima parada destacada
   ↓
7. Clicar entrega → atualizar status
```

**Polyline Decoding (Alternativas):**

Opção A (Simples):
```python
# Usar biblioteca pypolyline (pip install polyline)
import polyline
coordinates = polyline.decode(rota.route_geometry)
# Retorna: [(lat1, lng1), (lat2, lng2), ...]
```

Opção B (Sem dependência):
```python
# Implementar manualmente (30 linhas de código)
# Usar algoritmo de decodificação do Google
```

**Recomendação:** Começar com Opção A (simples), testar, depois considerar Opção B se necessário.

**Testes:**
```
test_driver_route_active.py
  - test_route_geometry_decoded()
  - test_loading_sequence_inverted()
  - test_next_delivery_highlighted()
  - test_map_renders_with_markers()
```

**Backend chamado:**
- `GET /api/rotas/{id}` (já existe)
- `GET /api/rotas/{id}/sequencia-carregamento` (novo)

---

### Fase 4: Atualização de Status em Rota (3-4 horas)
**Objetivo:** Motorista atualiza status sem sair da tela de rota

**Fluxo de Status:**

```
AGUARDANDO_COLETA (padrão)
         ↓
    [Marcar Coletada]
         ↓
      COLETADA
         ↓
    [Começar entrega]
         ↓
       EM_ROTA
         ↓
    [Cheguei na entrega]
         ↓
    ┌─ ENTREGUE (com comprovante)
    │  └─ HistoricoEntrega registrado auto
    │
    └─ NÃO_ENTREGUE (com motivo)
       └─ HistoricoEntrega registrado auto
```

**Implementação:**
- Cada entrega da rota tem dropdown com estados
- Clicar muda estado + abre dialog de confirmação
- Se ENTREGUE: obrigatório preencher comprovante
- Se NÃO_ENTREGUE: opção de ocorrência
- HistoricoEntrega registrado automaticamente (backend)

**Testes:**
```
test_driver_status_transitions.py
  - test_valid_status_transitions()
  - test_invalid_transitions_blocked()
  - test_historico_entrega_created()
  - test_comprovante_required_on_entregue()
```

**Backend chamado:**
- `PATCH /api/entregas/{id}/status`
- Lógica de HistoricoEntrega (já existe)

---

### Fase 5: Histórico Dedicado (2 horas)
**Objetivo:** Tela separada com entregas concluídas/pendentes

**Arquivo:** `frontend-flet/app/application.py:driver_history_view()`

**Componentes:**
```
┌─ Filtros ───────────────────────────────┐
│  Status: [ Todas | Concluídas | Pendentes | Canceladas ]
│  Período: [De] [Até]
│  [ Filtrar ]
└─────────────────────────────────────────┘

┌─ Resultados ────────────────────────────┐
│  Entrega #1: Cliente A - Entregue       │
│    Data: 16/08/2026 10:30               │
│    Endereço: Rua X, 123                 │
│  [ Ver histórico >]                     │
│                                         │
│  Entrega #2: Cliente B - Pendente       │
│    Data: 16/08/2026 (prevista)          │
│    Endereço: Rua Y, 456                 │
│  [ Ver histórico >]                     │
└─────────────────────────────────────────┘
```

**Click em entrega abre:**
```
┌─ Histórico Completo ────────────────────┐
│  Entrega #1 - Cliente A                 │
│                                         │
│  10:00 → AGUARDANDO_COLETA              │
│          (Criado em 16/08 10:00)        │
│                                         │
│  10:05 → COLETADA                       │
│          (16/08 10:05 - Motorista)      │
│                                         │
│  10:30 → ENTREGUE                       │
│          (16/08 10:30 - Motorista)      │
│          Recebedor: João Silva          │
│          Obs: Entregue em mãos           │
└─────────────────────────────────────────┘
```

**Testes:**
```
test_driver_history_view.py
  - test_filter_by_status()
  - test_filter_by_date_range()
  - test_history_timeline_with_timestamps()
```

---

### Fase 6: Perfil do Motorista (1 hora)
**Objetivo:** Tela com informações do usuário

**Arquivo:** `frontend-flet/app/application.py:driver_profile_view()`

**Componentes:**
```
┌─ Avatar & Info ─────────────────────────┐
│  [Foto]                                 │
│  Nome: João da Silva                    │
│  Email: joao@empresa.com                │
│  Telefone: (11) 9999-9999               │
│  Veículo: ABC-1234 (Fiat Doblo)         │
│  Perfil: MOTORISTA                      │
│                                         │
│  [ Editar Informações ]  [ Sair ]       │
└─────────────────────────────────────────┘
```

**Permissões:**
- Motorista pode editar: telefone, email (preenchimento opcional)
- Motorista NÃO pode: nome, foto (administrador)

**Testes:**
```
test_driver_profile_view.py
  - test_profile_displays_correct_info()
  - test_editable_fields_only()
  - test_update_preserves_sensitive_fields()
```

---

## 📦 Estrutura de Arquivos

### Backend (novo)

```
backend-api/app/routers/
  ├── rotas.py (alterar: adicionar endpoints do motorista)
  └── entregas.py (alterar: adicionar sequência-carregamento)

backend-api/tests/
  ├── test_driver_endpoints.py (novo)
  ├── test_driver_dashboard_metrics.py (novo)
  └── test_driver_status_transitions.py (novo)
```

### Frontend (novo)

```
frontend-flet/app/
  ├── application.py (alterar: adicionar 4 métodos)
  │   ├── driver_dashboard_view()
  │   ├── driver_route_active_view()
  │   ├── driver_history_view()
  │   └── driver_profile_view()
  │
  └── drivers/ (novo package)
      ├── __init__.py
      ├── dashboard.py (helper)
      ├── route_executor.py (helper)
      ├── polyline_decoder.py (novo)
      └── status_manager.py (helper)

frontend-flet/tests/
  ├── test_driver_dashboard_view.py (novo)
  ├── test_driver_route_active.py (novo)
  ├── test_driver_history_view.py (novo)
  └── test_driver_profile_view.py (novo)
```

---

## 🔒 Segurança

✅ Pontos de controle necessários:

1. **Backend:** Validar `motorista_id == user.id` em todos os endpoints
2. **Frontend:** Mostrar apenas rota do motorista autenticado
3. **API:** Retornar 403 Forbidden se tentar acessar rota de outro motorista
4. **Histórico:** Imutável (apenas leitura no frontend)

---

## 📅 Cronograma Estimado

| Fase | Tarefa | Duração | Risco |
|------|--------|---------|-------|
| 1 | Endpoints Backend | 4h | Baixo |
| 2 | Dashboard Motorista | 3h | Baixo |
| 3 | Rota Ativa + Mapa | 6h | Médio |
| 4 | Status em Rota | 3h | Médio |
| 5 | Histórico | 2h | Baixo |
| 6 | Perfil | 1h | Baixo |
| | **Testes** | 4h | Baixo |
| **Total** | | **~23h** | |

---

## ✨ Próximos Passos

1. ✅ **Auditoria completa** (FEITA)
2. 🔜 **Criar estrutura de testes** (Phase 0)
3. 🔜 **Implementar Fase 1** (Endpoints backend)
4. 🔜 **Implementar Fase 2-6** (Em ordem)

---

## 📚 Referências

- Auditoria detalhada: [/memories/repo/driver-module-audit-and-plan.md](/memories/repo/driver-module-audit-and-plan.md)
- Models: [backend-api/app/models.py](backend-api/app/models.py#L150-L230)
- Schemas: [backend-api/app/schemas.py](backend-api/app/schemas.py#L184-L370)
- Rotas: [backend-api/app/routers/rotas.py](backend-api/app/routers/rotas.py)
- Frontend: [frontend-flet/app/application.py](frontend-flet/app/application.py#L554-L750)

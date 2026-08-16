# Auditoria Técnica – Phase 2 Dashboard do Motorista

## Contexto Atual

### 1. Estrutura de Navegação (show_shell)

**Arquivo**: `frontend-flet/app/application.py` (linhas ~300-330)

**Comportamento Atual**:
- Menu lateral (`NavigationRail`) com destinos diferentes por perfil
- Para **MOTORISTA**: apenas 3 itens
  1. Dashboard → chama `dashboard_view()`
  2. Gestão de Entregas → chama `delivery_management_view()`
  3. Rotas → chama `routes_view()`
- Para **GESTOR/ADMIN**: 9+ itens (mais opções de CRUD)

**Desvio Atual**: 
- Linha 387: `if self.user["perfil"] == "MOTORISTA": self.deliveries_view(); return`
- Quando motorista clica em "Dashboard", é redirecionado para `deliveries_view()` em vez de um dashboard real.

### 2. Componentes e Helpers Reutilizáveis

**Em `application.py`**:

| Helper | Assinatura | Uso |
|--------|-----------|-----|
| `header_bar(title, subtitle="", actions=None)` | Cabeçalho com título, subtítulo e ações | Todas as views |
| `heading(title, subtitle="")` | Apenas título+subtítulo | Dentro de componentes |
| `notify(message, error=False)` | Mostra SnackBar ou AlertDialog | Feedback ao usuário |
| `page_controls(prev_cb, next_cb, can_prev, can_next)` | Paginação | Listas |
| `option(value)` | Cria `ft.dropdown.Option` | Dropdowns |

**Em `dashboard_utils.py`**:

| Helper | Assinatura | Uso |
|--------|-----------|-----|
| `DASHBOARD_INDICATORS` | Lista de tuplas (label, key) | Gestão de indicadores |
| `get_dashboard_indicator_values(data: dict)` | Extrai valores de dict | Parsing de dados |
| `DashboardRefreshController` | Classe com `start()`, `stop()`, `refresh_once()` | Atualização periódica em thread |

### 3. Padrão de Views Atual

**Estrutura Comum**:
```python
def view_name(self, param1=value1, ...):
    try:
        # Carregar dados via API
        data = self.api.request("GET", "/endpoint?params")
        
        # Montar componentes (cards, listas, etc)
        cards = [...]
        rows = [...]
        
        # Atribuir ao content e update
        self.content.controls = [
            self.header_bar("Título", "Subtítulo", [ações]),
            ft.Container(...),
            ft.Container(...),
        ]
        self.page.update()
    except ApiError as exc:
        self.notify(str(exc), True)
```

**Exemplo Real**: 
- `dashboard_view()` (linhas 387–545): Gestão com cards, gráficos, mapa
- `deliveries_view()` (linhas 547–620): Lista paginada com status
- `routes_view()` (linhas 622–700): Lista com ações por perfil

### 4. Acesso à API

**Classe**: `ApiClient` em `api_client.py`

**Métodos Principais**:
```python
self.api.request("GET", "/endpoint", params={...})
self.api.request("POST", "/endpoint", json={...})
self.api.request("PATCH", "/endpoint", json={...})
self.api.login(email, password)
```

**Endpoints Relevantes para Phase 2**:
- `GET /relatorios/dashboard` → indicadores gerais (GESTOR/ADMIN)
- `GET /rotas/motorista/atual` → **nova** rota ativa do motorista (Phase 1)
- `GET /rotas?limit=...&offset=...` → lista de rotas (filtrado por motorista automaticamente)
- `GET /entregas?limit=...&offset=...` → entregas (motorista vê apenas as suas)
- `PATCH /rotas/{id}/status` → atualizar status da rota

### 5. Dados Disponíveis no `self.user`

Após login:
```json
{
  "id": int,
  "nome": str,
  "email": str,
  "perfil": "MOTORISTA" | "GESTOR" | "ADMIN" | "CLIENTE",
  "ativo": bool,
  "organizacao_id": int | null
}
```

---

## Proposta Phase 2 – Dashboard do Motorista

### Escopo Precisamente Definido

**Somente esta view**:
- Tela inicial do motorista (substitui o redirecionamento atual para `deliveries_view()`)
- Sem mudanças em outras views

**Nome da Nova View**: `driver_dashboard_view()`

### Dados a Exibir

| Seção | Dados | Endpoint | Fallback |
|-------|-------|----------|----------|
| Saudação + Data | Nome do motorista, data atual | `self.user["nome"]`, Python `datetime` | Hardcoded |
| Veículo | Placa, modelo, marca | `GET /rotas/motorista/atual` → `veiculo` | "-" |
| Indicadores | 4 cards com métricas | Calcular com filtros locais ou novo endpoint | 0 / "—" |
| Próxima Missão | Rota ativa completa | `GET /rotas/motorista/atual` | Card vazio com mensagem |

### Layout Estruturado

```
┌─────────────────────────────────────────────────────────────────────┐
│ Bom dia, Gustavo                                                    │
│ Sexta-feira, 16 de agosto de 2026                                    │
│ 🚗 Veículo: Fiat Ducato (ABC-1234)                                  │
│ 🔔 [Notificações]                                                    │
├─────────────────────────────────────────────────────────────────────┤
│ [Card Entregas Concluídas: 5]                                        │
│ [Card Entregas Pendentes: 8]                                         │
│ [Card Distância Hoje: 45,2 km]                                       │
│ [Card Tempo em Rota: 3h 22min]                                       │
├─────────────────────────────────────────────────────────────────────┤
│ 📍 PRÓXIMA MISSÃO                                                    │
│ Operação Norte (Ponto de Coleta)                                    │
│ 10 entregas • Próxima: Cliente ABC, Rua X, 100                      │
│ Distância: 12,5 km • Duração: 1h 15min                              │
│ Status: EM_EXECUCAO [Iniciar Rota ▶]                                │
└─────────────────────────────────────────────────────────────────────┘
```

### Alterações Necessárias

#### 1. **Modificar `dashboard_view()` (application.py, linha 387)**

**Antes**:
```python
def dashboard_view(self):
    if self.user["perfil"] == "MOTORISTA":
        self.deliveries_view()  # ← Redirecionamento
        return
    # ... resto do código para GESTOR/ADMIN
```

**Depois**:
```python
def dashboard_view(self):
    if self.user["perfil"] == "MOTORISTA":
        self.driver_dashboard_view()  # ← Novo método
        return
    # ... resto para GESTOR/ADMIN (sem mudanças)
```

#### 2. **Criar nova view: `driver_dashboard_view()`**

**Localização**: `application.py`, após `dashboard_view()` (sugiro linha ~545)

**Estrutura**:
```python
def driver_dashboard_view(self):
    """
    Dashboard exclusivo para MOTORISTA.
    
    Componentes:
    - Saudação com data
    - Veículo vinculado (extraído de /rotas/motorista/atual)
    - 4 indicadores em cards (não estão no /relatorios/dashboard)
    - Card "Próxima Missão" com botão "Iniciar Rota"
    """
    try:
        # 1. Buscar rota ativa (Phase 1 endpoint)
        current_route = self.api.request("GET", "/rotas/motorista/atual")
        has_active_route = True
    except ApiError:
        current_route = None
        has_active_route = False
    
    # 2. Montar saudação
    greeting = self._build_greeting()  # Helper para saudação por hora
    
    # 3. Montar vehicle card
    vehicle_card = self._build_vehicle_card(current_route)
    
    # 4. Montar indicadores
    indicator_cards = self._build_driver_indicators(current_route)
    
    # 5. Montar card "Próxima Missão"
    mission_card = self._build_next_mission_card(current_route)
    
    # 6. Atualizar view
    self.content.controls = [
        self.header_bar("Dashboard", "Sua operação de hoje"),
        greeting,
        vehicle_card,
        ft.Container(ft.Row(indicator_cards, wrap=True, spacing=12), padding=20),
        mission_card,
    ]
    self.page.update()
```

#### 3. **Helpers Internos (novos métodos em DeliveryApp)**

- `_build_greeting() -> ft.Container`
  - Data, saudação dinâmica ("Bom dia", "Boa tarde", "Boa noite")
- `_build_vehicle_card(route) -> ft.Container`
  - Mostra placa, modelo, marca extraído de `route["veiculo"]`
- `_build_driver_indicators(route) -> list[ft.Container]`
  - 4 cards com (a) entregas concluídas, (b) pendentes, (c) distância, (d) tempo
  - Dados extraídos localmente ou via `GET /entregas/minhas` filtrado
- `_build_next_mission_card(route) -> ft.Container`
  - Card principal com botão "Iniciar Rota"
  - Se `route` é `None`, mostra mensagem "Nenhuma rota ativa"
  - Se ativo, mostra dados da `route["origem"]`, número de entregas, próxima

### Componentes Reutilizados

| Componente | Origem | Modificação |
|-----------|--------|------------|
| `header_bar()` | Existente | Sem mudança |
| `notify()` | Existente | Sem mudança |
| Cards (layout) | `dashboard_view()` gestor | Mesmo padrão (Container + Column + padding) |
| Container/Row/Column | Flet | Padrão já usado |

### Componentes Novos

Apenas helpers internos, **sem novos arquivos**.

### Dados não Necessários Agora

- Mapa de motoristas (só em `/relatorios/dashboard`)
- Gráficos de evolução (só em `/relatorios/dashboard`)
- Últimas entregas (pode ser adicionado na Phase 3)

---

## Resumo das Mudanças

### Arquivos Modificados

1. **`frontend-flet/app/application.py`**
   - **Linha ~387**: Substituir redirecionamento por chamada a `driver_dashboard_view()`
   - **Após linha ~545**: Adicionar novo método `driver_dashboard_view()`
   - **Logo após**: Adicionar 4 novos helpers internos (`_build_*`)

### Arquivos **NÃO** Modificados

- `main.py` — sem mudanças
- `api_client.py` — sem mudanças
- `dashboard_utils.py` — sem mudanças
- `map_view.py` — sem mudanças
- `tracking_client.py` — sem mudanças
- Nenhum outro arquivo

### Endpoints Acionados

**Novos (Phase 1)**:
- `GET /rotas/motorista/atual` — rota ativa (trata 404 com fallback)

**Existentes**:
- `GET /entregas/minhas` — entregas do motorista (já funciona)
- Opcionalmente: `GET /rotas?motorista_id={user.id}` — lista completa

### Regras de Negócio

- **Nenhuma** alteração em rotas, entregas ou organização de dados
- Apenas exibição de dados já existentes
- Se rota ativa não existir, mostrar card vazio com mensagem "Nenhuma rota agendada"
- Botão "Iniciar Rota" será placeholder — navegação implementada em Phase 3

---

## Pronto para Implementação

Todos os dados necessários já existem. A view é **puramente visual** e **sem lógica de negócio nova**.

Estimativa de código:
- `driver_dashboard_view()`: ~50–80 linhas
- 4 helpers internos: ~20–30 linhas cada = ~100 linhas
- **Total**: ~180–210 linhas de novo código
- **Modificações existentes**: 2 linhas (redirecionamento)

✅ Compatível com restante do sistema
✅ Sem quebra de endpoints
✅ Pronto para iteração

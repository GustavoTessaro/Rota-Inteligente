# 🔧 Guia Técnico de Implementação - Módulo do Motorista

**Versão:** 1.0  
**Data:** 2026-08-16

---

## 1. POLYLINE DECODING (Route Geometry)

### O que é?

Google Maps retorna rotas otimizadas como **encoded polyline** (formato comprimido):

```
"_p~iF~ps|U_ulLnnqC_mqNvxq`@"  ← Isso é uma rota completa comprimida
```

Quando decodificado:

```python
[
    (37.4419, -122.1430),  # Ponto 1
    (37.4521, -122.1430),  # Ponto 2
    (37.4625, -122.1507),  # Ponto 3
    ...
]
```

### Armazenamento

✅ **JÁ SALVO NO DB**

```python
# Em rotas.py:_persist_route_optimization() [linha 184]
rota.route_geometry = optimization.get("encoded_polyline")
```

### Decodificação - Opção A (Recomendada)

**Instalação:**
```bash
cd backend-api
pip install polyline
pip freeze > requirements.txt
```

**Uso no Backend (novo endpoint):**
```python
# app/services/polyline_service.py (novo)
import polyline

def decode_route_geometry(encoded: str | None) -> list[dict]:
    """Decodifica polyline em lista de coordenadas."""
    if not encoded:
        return []
    try:
        coords = polyline.decode(encoded)
        return [{"lat": lat, "lng": lng} for lat, lng in coords]
    except Exception:
        return []

def get_route_geometry_bounds(coordinates: list[dict]) -> dict:
    """Retorna limites do mapa para centralizar."""
    if not coordinates:
        return {"min_lat": 0, "max_lat": 0, "min_lng": 0, "max_lng": 0}
    
    lats = [c["lat"] for c in coordinates]
    lngs = [c["lng"] for c in coordinates]
    return {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lng": min(lngs),
        "max_lng": max(lngs),
    }
```

**Novo Endpoint:**
```python
# app/routers/rotas.py (novo)
@router.get("/{rota_id}/geometry", response_model=list[dict])
def get_route_geometry(
    rota_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user)
):
    """Retorna coordenadas decodificadas da rota."""
    rota = get_or_404(db, Rota, rota_id)
    
    # Validar acesso (motorista só vê sua rota)
    if user.perfil == Perfil.MOTORISTA and rota.motorista_id != user.id:
        raise HTTPException(403, "Acesso negado")
    
    from ..services.polyline_service import decode_route_geometry
    return decode_route_geometry(rota.route_geometry)
```

### Decodificação - Opção B (Sem dependência)

Se não quiser adicionar `polyline`, use implementação manual:

```python
def decode_polyline(encoded: str) -> list[tuple]:
    """Decodifica polyline usando algoritmo do Google."""
    inv = 1.0 / 1e5
    decoded = []
    previous = [0, 0]
    i = 0
    
    while i < len(encoded):
        ll = [0, 0]
        for j in [0, 1]:
            shift = 0
            result = 0
            while True:
                byte = ord(encoded[i]) - 63
                i += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if not byte >= 0x20:
                    break
            if result & 1:
                ll[j] = previous[j] + ~(result >> 1)
            else:
                ll[j] = previous[j] + (result >> 1)
            previous[j] = ll[j]
        decoded.append((ll[0] * inv, ll[1] * inv))
    
    return decoded
```

**Recomendação:** Começar com Opção A, testar em produção. Se performance/package size é problema, migrar para B depois.

---

## 2. SEQUÊNCIA DE CARREGAMENTO (Loading Sequence)

### Conceito

Quando motorista precisa carregar pedidos no veículo, ele **não** quer pegar o primeiro a ser entregue primeiro (ocuparia toda carga).

**Exemplo Real:**

Entrega Planejada:
```
1. Cliente A (Rua 1)
2. Cliente B (Rua 2)
3. Cliente C (Rua 3)
```

Sequência de Carregamento:
```
1. Cliente C (Rua 3)  ← Carrega por último, entrega primeiro
2. Cliente B (Rua 2)
3. Cliente A (Rua 1)  ← Carrega primeiro, entrega por último
```

### Implementação Backend

**Novo Endpoint:**
```python
# app/routers/rotas.py (novo)
@router.get("/{rota_id}/sequencia-carregamento", response_model=list[RotaEntregaOut])
def get_loading_sequence(
    rota_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user)
):
    """Retorna entregas em ordem INVERSA (para carregamento)."""
    rota = get_or_404(db, Rota, rota_id)
    
    # Validar acesso
    if user.perfil == Perfil.MOTORISTA and rota.motorista_id != user.id:
        raise HTTPException(403, "Acesso negado")
    
    # Buscar entregas ordenadas por ordem_visita
    entregas = db.query(RotaEntrega)\
        .filter(RotaEntrega.rota_id == rota_id)\
        .order_by(RotaEntrega.ordem_visita)\
        .all()
    
    # Reverter (IMPORTANTE: no código, não no DB!)
    entregas_invertidas = list(reversed(entregas))
    
    return entregas_invertidas
```

### Uso no Frontend

```python
# frontend-flet/app/application.py:driver_route_active_view()

def driver_route_active_view(self):
    try:
        rota_id = self.selected_route_id
        rota = self.api.request("GET", f"/rotas/{rota_id}")
        
        # Buscar sequência de carregamento (invertida)
        loading_seq = self.api.request("GET", f"/rotas/{rota_id}/sequencia-carregamento")
        
        # loading_seq já vem invertida do backend
        # Não alterar a ordem aqui
        
        # Renderizar na UI
        self.content.controls = [
            self.header_bar("Rota Ativa", f"#{rota['id']} - {rota['nome']}"),
            ft.Column([
                # Mapa aqui
                # Lista de entregas na ordem invertida
                *[self._build_entrega_card(e) for e in loading_seq],
            ])
        ]
    except ApiError as exc:
        self.notify(str(exc), True)
```

### Teste Backend

```python
# tests/test_driver_endpoints.py
def test_get_loading_sequence_inverted():
    # Setup: Rota com 3 entregas [A, B, C] em ordem_visita [1, 2, 3]
    
    resp = client.get(f"/api/rotas/{rota_id}/sequencia-carregamento")
    
    # Esperado: [C, B, A] (revertido)
    assert len(resp.json()) == 3
    assert resp.json()[0]["entrega_id"] == 3  # C
    assert resp.json()[1]["entrega_id"] == 2  # B
    assert resp.json()[2]["entrega_id"] == 1  # A
```

---

## 3. HISTÓRICO COM TIMESTAMPS

### Modelo Existente

```python
# models.py:363-372
class HistoricoEntrega(Base):
    __tablename__ = "historico_entregas"
    id: Mapped[int] = mapped_column(primary_key=True)
    entrega_id: Mapped[int] = mapped_column(ForeignKey("entregas.id"), index=True)
    status_anterior: Mapped[str | None] = mapped_column(String(50))
    status_novo: Mapped[str] = mapped_column(String(50))
    observacao: Mapped[str | None] = mapped_column(Text)
    alterado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=now)  # ✅ TIMESTAMP
```

### Criação Automática (Backend)

Quando motorista atualiza status:

```python
# app/routers/entregas.py (alterar método de atualizar status)
@router.patch("/{entrega_id}/status", response_model=EntregaOut)
def update_delivery_status(
    entrega_id: int,
    data: EntregaStatusIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user)
):
    entrega = get_or_404(db, Entrega, entrega_id)
    
    # Registrar histórico ANTES de alterar
    historico = HistoricoEntrega(
        entrega_id=entrega.id,
        status_anterior=entrega.status.value,
        status_novo=data.status.value,
        observacao=data.observacao or f"Alterado por {user.nome}",
        alterado_por=user.id,
        criado_em=now()  # Timestamp automático
    )
    db.add(historico)
    
    # Depois alterar status
    entrega.status = data.status
    if data.status == StatusEntrega.ENTREGUE:
        entrega.data_entrega = now()
    elif data.status == StatusEntrega.COLETADA:
        entrega.data_coleta = now()
    
    db.commit()
    return entrega
```

### Leitura no Frontend

```python
# Novo método em application.py
def view_delivery_history(self, entrega_id):
    """Abre timeline completo da entrega."""
    try:
        historia = self.api.request("GET", f"/entregas/{entrega_id}/historico")
        
        timeline = ft.Column([
            ft.Text(f"Histórico - Entrega #{entrega_id}", weight=ft.FontWeight.BOLD, size=18),
            ft.Divider(),
        ])
        
        for evento in historia:
            # evento = {
            #   "status_anterior": "AGUARDANDO_COLETA",
            #   "status_novo": "COLETADA",
            #   "criado_em": "2026-08-16T10:30:00",
            #   "observacao": "Motorista confirmou coleta",
            #   "alterado_por": "João da Silva"
            # }
            
            dt = evento.get("criado_em", "")
            horario = dt.split("T")[1][:5] if "T" in dt else dt
            
            timeline.controls.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(f"{horario} → {evento['status_novo']}", 
                               weight=ft.FontWeight.BOLD, 
                               color=ft.Colors.INDIGO),
                        ft.Text(evento.get("observacao", ""), size=12, color=ft.Colors.GREY_700),
                        ft.Text(f"Por: {evento.get('alterado_por', 'Sistema')}", 
                               size=10, color=ft.Colors.GREY_500),
                    ], spacing=4),
                    padding=12,
                    border_radius=8,
                    bgcolor=ft.Colors.GREY_100,
                )
            )
        
        dialog = ft.AlertDialog(
            title=ft.Text("Histórico da Entrega"),
            content=ft.Column([timeline], scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Fechar", on_click=lambda _: self.page.close(dialog))]
        )
        
        self.page.open(dialog)
    except ApiError as exc:
        self.notify(str(exc), True)
```

### Novo Endpoint (se necessário)

```python
@router.get("/{entrega_id}/historico", response_model=list[HistoricoEntregaOut])
def get_delivery_history(
    entrega_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user)
):
    """Retorna histórico completo da entrega com timestamps."""
    entrega = get_or_404(db, Entrega, entrega_id)
    
    historico = db.query(HistoricoEntrega)\
        .filter(HistoricoEntrega.entrega_id == entrega_id)\
        .order_by(HistoricoEntrega.criado_em)\
        .all()
    
    return historico
```

---

## 4. FSM DE STATUS (State Machine)

### Estados Válidos

```python
# models.py:41-47
class StatusEntrega(str, enum.Enum):
    AGUARDANDO_COLETA = "AGUARDANDO_COLETA"
    COLETADA = "COLETADA"
    EM_ROTA = "EM_ROTA"
    ENTREGUE = "ENTREGUE"
    NAO_ENTREGUE = "NAO_ENTREGUE"
    CANCELADA = "CANCELADA"
```

### Transições Válidas

```
AGUARDANDO_COLETA
        ↓
    COLETADA
        ↓
    EM_ROTA
        ↓
    ├─ ENTREGUE (sucesso)
    ├─ NAO_ENTREGUE (falha)
    └─ CANCELADA (cancelado)

Em qualquer estado:
    → CANCELADA (cancelar rota)
```

### Implementação Backend

```python
# app/services/delivery_service.py (novo)
from enum import Enum
from ..models import StatusEntrega

VALID_TRANSITIONS = {
    StatusEntrega.AGUARDANDO_COLETA: [StatusEntrega.COLETADA, StatusEntrega.CANCELADA],
    StatusEntrega.COLETADA: [StatusEntrega.EM_ROTA, StatusEntrega.CANCELADA],
    StatusEntrega.EM_ROTA: [StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA],
    StatusEntrega.ENTREGUE: [StatusEntrega.CANCELADA],  # Apenas cancelar
    StatusEntrega.NAO_ENTREGUE: [StatusEntrega.CANCELADA],
    StatusEntrega.CANCELADA: [],  # Terminal
}

def can_transition(current: StatusEntrega, target: StatusEntrega) -> bool:
    """Verifica se transição é válida."""
    return target in VALID_TRANSITIONS.get(current, [])

def validate_transition(current: StatusEntrega, target: StatusEntrega) -> str | None:
    """Retorna mensagem de erro ou None se válido."""
    if not can_transition(current, target):
        return f"Não é possível ir de {current} para {target}"
    return None
```

### Usar em Endpoint

```python
@router.patch("/{entrega_id}/status", response_model=EntregaOut)
def update_delivery_status(
    entrega_id: int,
    data: EntregaStatusIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user)
):
    from ..services.delivery_service import validate_transition
    
    entrega = get_or_404(db, Entrega, entrega_id)
    
    # Validar transição
    error = validate_transition(entrega.status, data.status)
    if error:
        raise HTTPException(422, error)
    
    # ... resto do código ...
```

### Teste

```python
def test_valid_status_transitions():
    assert can_transition(AGUARDANDO_COLETA, COLETADA) == True
    assert can_transition(AGUARDANDO_COLETA, ENTREGUE) == False
    assert can_transition(COLETADA, EM_ROTA) == True
    assert can_transition(ENTREGUE, AGUARDANDO_COLETA) == False
```

---

## 5. MAPVIEW COM POLYLINE

### Classe Existente (map_view.py)

```python
class MapView:
    def build(self):
        # Já renderiza marcadores em Canvas CSS
        # Vamos adicionar polyline
```

### Alteração Proposta

```python
# frontend-flet/app/map_view.py (adicionar)
class MapView:
    def __init__(self, markers=None, height=320, width=680, 
                 on_marker_click=None, selected_marker_id=None, 
                 title=None, route_coordinates=None):
        self.markers = markers or []
        self.route_coordinates = route_coordinates or []  # Novo!
        # ... resto ...
    
    def _draw_polyline(self, canvas, min_lat, max_lat, min_lng, max_lng):
        """Desenha a rota como linha no mapa."""
        if not self.route_coordinates:
            return
        
        padding = 16
        available_width = (self.width - 24) - padding * 2
        available_height = (self.height - 24) - padding * 2
        
        path_points = []
        for coord in self.route_coordinates:
            lat = float(coord.get("lat", 0))
            lng = float(coord.get("lng", 0))
            
            x = padding + int((lng - min_lng) / (max_lng - min_lng) * available_width)
            y = padding + int((max_lat - lat) / (max_lat - min_lat) * available_height)
            path_points.append((x, y))
        
        # Retorna SVG path ou linha no canvas
        return self._build_polyline_path(path_points)
    
    def _build_polyline_path(self, points):
        """Constrói SVG com a polilinha."""
        if not points:
            return None
        
        path_data = f"M {points[0][0]} {points[0][1]}"
        for x, y in points[1:]:
            path_data += f" L {x} {y}"
        
        return ft.Container(
            content=ft.Stack([
                ft.Svg(
                    svg_content=f"""
                    <svg width="100%" height="100%">
                        <polyline points="{' '.join(f'{x},{y}' for x,y in points)}"
                                  stroke="blue" stroke-width="2" fill="none"/>
                    </svg>
                    """
                )
            ])
        )
```

---

## 6. CHECKLIST DE IMPLEMENTAÇÃO

### Pré-requisitos
- [ ] Audit concluída ✅
- [ ] Plano técnico definido ✅
- [ ] Testes escritos (antes do código)
- [ ] Branch criado: `feature/driver-module`

### Phase 1: Backend Endpoints
- [ ] Criar `test_driver_endpoints.py`
- [ ] Implementar `GET /rotas/motorista/atual`
- [ ] Implementar `GET /rotas/{id}/sequencia-carregamento`
- [ ] Implementar `GET /rotas/{id}/geometry`
- [ ] Adicionar `polyline` em requirements.txt
- [ ] Testes passando

### Phase 2: Dashboard
- [ ] Criar `test_driver_dashboard_view.py`
- [ ] Implementar `driver_dashboard_view()`
- [ ] Testes passando

### Phase 3: Rota Ativa
- [ ] Criar `test_driver_route_active.py`
- [ ] Implementar polyline decoding
- [ ] Implementar `driver_route_active_view()`
- [ ] Integrar MapView com route_geometry
- [ ] Testes passando

### Phase 4: Status em Rota
- [ ] Criar `test_driver_status_transitions.py`
- [ ] Implementar FSM de transições
- [ ] Validar status em `PATCH /entregas/{id}/status`
- [ ] Testes passando

### Phase 5: Histórico
- [ ] Criar `test_driver_history_view.py`
- [ ] Implementar `driver_history_view()`
- [ ] Testes passando

### Phase 6: Perfil
- [ ] Criar `test_driver_profile_view.py`
- [ ] Implementar `driver_profile_view()`
- [ ] Testes passando

### Validação Final
- [ ] Testes UI com motorista real
- [ ] Compatibilidade com Etapas 1, 2, 3
- [ ] Documentação atualizada
- [ ] Code review + merge

---

## 7. DEPENDÊNCIAS A ADICIONAR

```bash
# backend-api/requirements.txt
polyline>=2.0.0  # Para decodificação de polyline

# frontend-flet/requirements.txt
# (nenhuma nova)
```

---

## 8. Variáveis de Ambiente

Nenhuma variável nova necessária (reutiliza existentes).

---

## 9. Migração de Database

❌ **NENHUMA NECESSÁRIA**

Todos os campos já existem:
- ✅ `rota.route_geometry`
- ✅ `rota.motorista_id`
- ✅ `entrega.status`
- ✅ `historico_entrega.criado_em`
- ✅ `usuario.perfil`


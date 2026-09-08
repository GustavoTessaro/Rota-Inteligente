# 🚚 Rota Inteligente

![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)
![Flet](https://img.shields.io/badge/Flet-Frontend-02569B)
![Azure](https://img.shields.io/badge/Azure-App%20Service%20%2B%20SQL-0078D4?logo=microsoftazure&logoColor=white)
![SQL Server](https://img.shields.io/badge/SQL%20Server-Azure%20SQL-CC2927?logo=microsoftsqlserver&logoColor=white)
![Status](https://img.shields.io/badge/Status-Em%20desenvolvimento-yellow)

**Rota Inteligente** é uma plataforma para gerenciamento de entregas, veículos, motoristas e rotas, com backend em FastAPI, frontend em Flet, rastreamento por WebSocket, mapas e integração opcional com serviços Google para geocodificação, cálculo e otimização de rotas.

O projeto foi desenvolvido com foco em planejamento logístico e acompanhamento operacional de entregas, separando o fluxo de gestão do fluxo do motorista.

> **Autores:** Gustavo Tessaro e Nickael Arruda

---

## 📌 Navegação rápida

- [Visão geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Perfis de usuário](#perfis-de-usuário)
- [Fluxo de uma rota](#fluxo-de-uma-rota)
- [Tecnologias](#tecnologias)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Banco de dados](#banco-de-dados)
- [Configuração local](#configuração-do-ambiente-local)
- [Execução](#executando-o-backend)
- [Testes](#testes)
- [Deploy no Azure](#deploy-no-azure)
- [Autores](#autores)

---

## 🧭 Visão geral

O sistema possui dois componentes principais:

- **Backend API**
  - FastAPI
  - SQLAlchemy
  - Alembic
  - JWT
  - WebSocket
  - Azure SQL / SQL Server

- **Frontend**
  - Flet
  - MapTiler
  - integração com API REST
  - tracking em tempo real
  - preparação para execução desktop e Android

Arquitetura simplificada:

```text
┌──────────────────────┐
│    Frontend Flet     │
│ Desktop / Android    │
└──────────┬───────────┘
           │
           │ HTTP / HTTPS
           │ WebSocket / WSS
           ▼
┌──────────────────────┐
│   FastAPI Backend    │
│                      │
│ Auth / CRUD / Rotas  │
│ Tracking / Relatórios│
└──────────┬───────────┘
           │
           │ SQLAlchemy
           ▼
┌──────────────────────┐
│ SQL Server / Azure   │
│ SQL Database         │
└──────────────────────┘
```

Integrações opcionais:

```text
FastAPI
 ├─ Google Geocoding
 ├─ Google Routes API
 ├─ Google Route Optimization
 └─ Nominatim

Frontend
 └─ MapTiler
```

---

## ✨ Funcionalidades

O sistema possui suporte para:

### Autenticação

- login;
- consulta do usuário autenticado;
- logout;
- autenticação Bearer com JWT;
- hash de senha com Argon2;
- autorização baseada em perfil.

### Usuários

- cadastro;
- edição;
- ativação e desativação;
- associação com organização;
- controle de permissões por perfil.

### Organizações

- cadastro e manutenção;
- gerenciamento de endereços;
- definição de endereço principal.

### Clientes

- cadastro;
- edição;
- endereços;
- associação com pedidos e entregas.

### Produtos

- cadastro;
- atualização;
- utilização em itens de pedido.

### Pedidos

- criação;
- itens;
- prioridade;
- associação com organização;
- integração com o fluxo de entregas.

### Entregas

- geração a partir dos pedidos;
- status operacional;
- histórico;
- ocorrências;
- comprovante de entrega;
- entrega concluída ou não realizada;
- vínculo com rotas.

### Veículos

- cadastro;
- tipo;
- status;
- associação com organização;
- associação com motorista e rota.

### Rotas

- criação de rota;
- seleção de pedidos e entregas;
- atribuição de motorista;
- atribuição de veículo;
- geração e otimização;
- alternativas de rota;
- alternativa recomendada;
- seleção da alternativa;
- confirmação de carga;
- início;
- pausa e retomada;
- progresso;
- próxima entrega;
- finalização;
- cancelamento;
- histórico operacional.

### Dashboard e relatórios

- visão operacional;
- informações de entregas;
- informações de rotas;
- acompanhamento de veículos;
- resumo diário do motorista;
- relatórios disponíveis pela API.

### Rastreamento

- envio de posições GPS pelo motorista;
- armazenamento das posições;
- WebSocket para atualização em tempo real;
- atualização de marcadores no frontend.

---

## 👥 Perfis de usuário

Os perfis definidos atualmente no sistema são:

### ADMIN

Possui acesso administrativo global, incluindo:

- usuários;
- organizações;
- clientes;
- produtos;
- pedidos;
- entregas;
- veículos;
- rotas;
- relatórios.

### GESTOR

Opera principalmente dentro da própria organização:

- usuários não administradores;
- veículos;
- pedidos;
- entregas;
- rotas;
- relatórios da organização.

### MOTORISTA

Possui fluxo operacional específico:

- consultar rota atual;
- visualizar sequência de carregamento;
- confirmar carga;
- iniciar rota;
- consultar próxima entrega;
- atualizar entregas;
- enviar posição GPS;
- acompanhar progresso.

### CLIENTE

O perfil existe no domínio atual, porém não possui um fluxo operacional completo equivalente aos demais perfis.

---

## 🛣️ Fluxo de uma rota

O fluxo principal de rota é:

```text
Pedidos
  │
  ▼
Seleção das entregas
  │
  ▼
Criação da rota
  │
  ▼
Geração / otimização
  │
  ▼
Alternativas
  │
  ├─ MAIS_RAPIDA
  └─ MAIS_CURTA
  │
  ▼
Alternativa recomendada
  │
  ▼
Seleção da alternativa
  │
  ▼
Motorista + veículo
  │
  ▼
Confirmação da carga
  │
  ▼
Execução
  │
  ▼
Entregas / tracking / progresso
  │
  ▼
Conclusão da rota
```

### Status de rota

```text
RASCUNHO
OTIMIZANDO
PRONTA
AGUARDANDO_ACEITE
EM_EXECUCAO
PAUSADA
CONCLUIDA
CANCELADA
PLANEJADA
AGUARDANDO_MOTORISTA
AGUARDANDO_VEICULO
FINALIZADA
```

### Status de entrega

```text
AGUARDANDO_COLETA
COLETADA
EM_ROTA
ENTREGUE
NAO_ENTREGUE
CANCELADA
```

---

## 🧠 Otimização de rotas

O backend possui integração com serviços Google para cálculo e otimização de rotas.

### Google Routes API

Pode ser utilizada para:

- distância;
- duração;
- polyline;
- avaliação das rotas.

### Google Route Optimization

Quando habilitada e configurada, utiliza:

- Google Cloud Project;
- Service Account;
- OAuth;
- `optimizeTours`.

### Alternativas atuais

O sistema trabalha com:

```text
MAIS_RAPIDA
MAIS_CURTA
```

### Fallback

Quando o serviço externo não está disponível ou não está configurado, existe um fallback determinístico que:

- mantém a ordem recebida;
- calcula distância por Haversine;
- estima duração;
- produz polyline determinística;
- identifica o provedor como `FALLBACK`.

---

## 🗺️ Mapas e geocodificação

O projeto possui suporte para:

- Google Geocoding;
- Nominatim/OpenStreetMap;
- Google Routes;
- MapTiler no frontend.

O provedor de geocodificação pode ser configurado por variável de ambiente.

---

## 🧰 Tecnologias

### Backend

- Python 3
- FastAPI
- Uvicorn
- SQLAlchemy 2.x
- Alembic
- Pydantic
- pydantic-settings
- PyJWT
- pwdlib / Argon2
- httpx
- requests
- pyodbc

### Banco

- SQL Server
- Azure SQL Database
- ODBC Driver 18 for SQL Server
- SQLite nos testes

### 🖥️ Frontend

- Flet 0.27.3
- flet-map
- flet-geolocator
- httpx
- websockets

### Infraestrutura

- Azure App Service
- Azure SQL Database
- GitHub Actions
- GitHub Actions OIDC para autenticação com Azure

---

## 🗂️ Estrutura do projeto

```text
Rota-Inteligente/
├── backend-api/
│   ├── app/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── security.py
│   │   ├── seed.py
│   │   └── tracking.py
│   ├── migrations/
│   │   └── versions/
│   ├── tests/
│   ├── alembic.ini
│   └── requirements.txt
│
├── frontend-flet/
│   ├── app/
│   ├── main.py
│   ├── pyproject.toml
│   └── requirements.txt
│
├── tools/
├── docs/
├── .github/
│   └── workflows/
├── run.py
└── README.md
```

---

## 🗄️ Banco de dados

O projeto utiliza SQLAlchemy como ORM e Alembic para versionamento do schema.

### Desenvolvimento local

Pode utilizar SQL Server LocalDB.

Exemplo de banco:

```text
RotaInteligenteLocal
```

### Produção

O ambiente de produção utiliza:

```text
Azure SQL Database
```

por meio de:

```text
SQLAlchemy
   +
pyodbc
   +
ODBC Driver 18 for SQL Server
```

---

## 🔄 Migrations

O projeto possui migrations de `0001` até `0014`.

```text
0001_initial_schema
0002_create_organizacoes
0003_create_veiculos
0004_create_rotas
0005_add_address_geolocation
0006_add_organizacao_enderecos
0007_add_principal_address
0008_add_organizacao_id_to_pedidos
0009_add_carga_confirmada_to_rotas
0010_make_receipt_document_optional
0011_add_organizacao_id_to_usuarios
0012_align_schema_with_current_models
0013_add_route_alternatives
0014_align_postgresql_enums
```

O nome da migration `0014_align_postgresql_enums` é histórico. O código atual foi adaptado para funcionar de forma portável com SQL Server.

Head esperado:

```text
0014_align_postgresql_enums
```

### Consultar estado

```powershell
cd backend-api
.\.venv\Scripts\Activate.ps1

alembic current
```

### Aplicar migrations

```powershell
alembic upgrade head
```

---

## 🌱 Seed

Existe um seed de demonstração que cria dados como:

- usuários;
- organizações;
- clientes;
- endereços;
- produtos;
- pedidos;
- entregas;
- veículos;
- rotas;
- alternativas;
- históricos.

O seed foi desenvolvido para ser idempotente.

Executar manualmente:

```powershell
python -c "from app.database import SessionLocal; from app.seed import seed_database; db=SessionLocal(); seed_database(db); db.close()"
```

> As credenciais de usuários de demonstração não devem ser documentadas em repositório público.

---

## 🔐 Variáveis de ambiente

Use o `.env.example` como referência.

### Backend

```text
APP_NAME
APP_ENV
DATABASE_URL
JWT_SECRET
JWT_EXPIRES_MINUTES
CORS_ORIGINS
SEED_DATABASE

GOOGLE_MAPS_API_KEY
GOOGLE_MAPS_RESTRICTED_KEY
GEOCODING_PROVIDER
NOMINATIM_EMAIL
MAPS_DEFAULT_CENTER

USE_GOOGLE_ROUTE_OPTIMIZATION
GOOGLE_ROUTE_OPTIMIZATION_SERVICE_ACCOUNT_FILE
GOOGLE_ROUTE_OPTIMIZATION_ENDPOINT
GOOGLE_ROUTE_OPTIMIZATION_PROJECT_ID
GOOGLE_ROUTE_OPTIMIZATION_LOCATION
GOOGLE_ROUTE_OPTIMIZATION_SCOPE
```

### 🖥️ Frontend

```text
API_BASE_URL
MAPTILER_API_KEY
ROTA_DESKTOP_LOCAL
```

### Produção

Nunca versionar:

- `.env`;
- senhas;
- JWT secrets;
- chaves Google;
- Service Account JSON;
- connection strings;
- tokens.

No Azure App Service, as configurações devem ser fornecidas por **Application Settings** ou solução equivalente de secrets.

---

## ⚙️ Instalação de dependências

Além da instalação manual por `requirements.txt`, o repositório também possui o arquivo:

```text
InstalarDependencias.py
```

Ele foi criado para facilitar a preparação do ambiente local e centralizar a instalação das dependências necessárias ao projeto.

> Recomenda-se revisar o conteúdo do script antes da execução e utilizá-lo somente em um ambiente de desenvolvimento controlado.

### Opção 1 — instalação automatizada

Na raiz do projeto:

```powershell
python InstalarDependencias.py
```

### Opção 2 — instalação manual

Backend:

```powershell
cd backend-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Frontend:

```powershell
cd frontend-flet
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 🧪 Configuração do ambiente local

### Backend

```powershell
cd backend-api

python -m venv .venv

.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item .env.example .env
```

Depois configure o `.env` local.

---

## 🖥️ Frontend

```powershell
cd frontend-flet

python -m venv .venv

.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

---

## ▶️ Executando o backend

```powershell
cd backend-api

.\.venv\Scripts\Activate.ps1

uvicorn app.main:app --reload
```

API:

```text
http://127.0.0.1:8000
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

---

## ▶️ Executando o frontend

```powershell
cd frontend-flet

.\.venv\Scripts\Activate.ps1

flet run main.py
```

---

## 🚀 Executando o projeto pelo launcher

O projeto possui um launcher na raiz:

```powershell
python run.py
```

Ele é utilizado para iniciar backend e frontend durante o desenvolvimento local.

---

## 🔌 API

A documentação interativa fica disponível em:

```text
/docs
```

OpenAPI:

```text
/openapi.json
```

ReDoc:

```text
/redoc
```

Principais grupos:

```text
/api/auth
/api/usuarios
/api/organizacoes
/api/clientes
/api/produtos
/api/pedidos
/api/entregas
/api/veiculos
/api/rotas
/api/relatorios
/api/maps
```

WebSocket:

```text
/ws/tracking
```

A API utiliza autenticação:

```text
Bearer JWT
```

---

## 🖥️ Frontend Flet

O frontend possui navegação adaptada de acordo com o perfil.

### ADMIN / GESTOR

Entre as telas existentes:

- Dashboard
- Gestão de Entregas
- Rotas
- Pedidos
- Clientes
- Produtos
- Veículos
- Organizações
- Relatórios
- Usuários

### MOTORISTA

- Dashboard
- Minhas Rotas
- Perfil
- sequência de carregamento
- execução da rota
- tracking GPS

O frontend consome a API através de `API_BASE_URL`.

A URL de WebSocket é derivada automaticamente:

```text
http  -> ws
https -> wss
```

---

## ✅ Testes

O backend utiliza `pytest`.

A suíte atual possui aproximadamente:

```text
29 arquivos de teste
209 funções test_*
```

Cobertura funcional inclui:

- autenticação;
- CRUD;
- organizações;
- clientes;
- pedidos;
- entregas;
- veículos;
- rotas;
- alternativas;
- otimização;
- geocodificação;
- Google Maps;
- tracking;
- WebSocket;
- seed;
- segurança;
- regras operacionais.

Executar:

```powershell
cd backend-api

.\.venv\Scripts\Activate.ps1

pytest -q
```

Os testes utilizam SQLite temporário para isolamento.

> A suíte completa não deve ser descrita como 100% aprovada sem uma execução recente que confirme esse estado.

---

## ☁️ Deploy no Azure

O backend possui deploy automatizado com GitHub Actions.

Workflow:

```text
.github/workflows/main_rota-inteligente-api.yml
```

O processo:

```text
Push na main
      ↓
GitHub Actions
      ↓
Python 3.14
      ↓
Instala dependências
      ↓
Gera artefato somente do backend
      ↓
Login OIDC no Azure
      ↓
Azure App Service
```

O workflow publica somente:

```text
backend-api/
```

O frontend não possui deploy automático no workflow atual.

### Não automatizado

Atualmente não são executados automaticamente durante o deploy:

- `alembic upgrade head`;
- seed;
- criação do Azure SQL;
- configuração de Application Settings;
- build/publicação Android;
- deploy do frontend.

---

## 🛡️ Segurança

O projeto possui:

- hash de senha com Argon2;
- JWT;
- expiração configurável de token;
- autorização por perfil;
- validação de usuário ativo;
- isolamento por organização;
- validações entre motorista, veículo e organização;
- proteção de secrets por variáveis de ambiente;
- exclusão de `.env`, JSON de credenciais e bancos locais dos artefatos de deploy.

Em produção é obrigatório utilizar um `JWT_SECRET` próprio e seguro.

As chaves de serviços externos devem possuir restrições adequadas ao ambiente onde forem utilizadas.

---

## 📱 Android

O frontend possui preparação para Android no `pyproject.toml`, incluindo permissões de:

- Internet;
- localização.

Também existem ferramentas auxiliares para preparação de build.

A existência dessa configuração não significa que um APK final esteja publicado atualmente.

---

## 📝 Observações

Algumas documentações antigas do projeto ainda podem mencionar tecnologias utilizadas em fases anteriores, como MySQL ou PostgreSQL.

O estado atual do projeto utiliza:

```text
SQL Server / Azure SQL
```

como banco principal.

---

## 🧭 Próximos passos

Entre os próximos passos possíveis:

- finalizar a configuração local x produção do frontend;
- gerar APK apontando para a API pública;
- realizar testes completos ponta a ponta;
- adicionar screenshots ao README;
- revisar documentação acadêmica;
- corrigir documentação antiga ainda baseada em MySQL;
- automatizar migrations de produção de forma segura, se desejado.

---

## 📊 Status atual

```text
Backend:           Implementado
Frontend:          Implementado
Azure App Service: Configurado
Azure SQL:         Configurado
Migrations:        0014 (head)
WebSocket:         Implementado
JWT:               Implementado
Tracking:          Implementado
Google APIs:       Configuráveis
Android:           Preparado para build
Frontend deploy:   Manual / ainda não automatizado
```

---

## 📄 Licença

Este projeto está licenciado sob a **MIT License**.

Copyright (c) 2026 **Edinilson Vida**.

A licença permite o uso, cópia, modificação, distribuição e sublicenciamento do software, desde que o aviso de copyright e os termos da licença sejam preservados.

Consulte o arquivo [`LICENSE`](LICENSE) para obter os termos completos da licença.

---

## 👨‍💻 Autores

Projeto desenvolvido por:

- **Gustavo Tessaro**
- **Nickael Arruda**

Projeto acadêmico desenvolvido no contexto do trabalho **Rota Inteligente**.

---

> Projeto em evolução contínua. A documentação deve acompanhar as alterações de arquitetura, banco de dados, integração com Azure e processo de build do frontend.

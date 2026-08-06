# Sistema de Gerenciamento de Entregas

Aplicação full-stack para gestão de entregas com FastAPI no backend, Flet no frontend e integração com Google Maps para visualização e otimização de rotas.

## Visão geral

- Backend: FastAPI + SQLAlchemy + Alembic + JWT
- Frontend: Flet
- Banco: MySQL 8 (padrão) ou SQLite para testes
- Funcionalidades: autenticação, CRUDs, entregas, rotas, dashboard, mapas e otimização de rotas

## Estrutura do projeto

- `backend-api`: API, modelos, schemas, rotas, migrações e testes
- `frontend-flet`: interface desktop em Flet
- `docs/SETUP.md`: guia passo a passo de instalação e execução

## Requisitos

- Python 3.10+ (validado com 3.14)
- MySQL 8 ou MariaDB compatível
- Git
- Opcional: conta Google Cloud para uso real da otimização de rotas

## 1. Clonar e preparar o ambiente

```powershell
git clone <url-do-repositorio>
cd Rota-Inteligente
```

## 2. Banco de dados

Crie o banco e o usuário antes de iniciar a API:

```sql
CREATE DATABASE entregas_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'entregas'@'localhost' IDENTIFIED BY 'senha';
GRANT ALL PRIVILEGES ON entregas_db.* TO 'entregas'@'localhost';
FLUSH PRIVILEGES;
```

O backend usa a variável `DATABASE_URL` para conectar-se ao banco.

## 3. Configuração de ambiente

Copie o arquivo de exemplo e ajuste os valores:

```powershell
cd backend-api
Copy-Item .env.example .env
```

Conteúdo mínimo recomendado para o arquivo `backend-api/.env`:

```env
APP_ENV=development
DATABASE_URL=mysql+pymysql://entregas:senha@localhost:3306/entregas_db?charset=utf8mb4
JWT_SECRET=troque-este-segredo-em-producao-com-mais-de-32-bytes
JWT_EXPIRES_MINUTES=480
CORS_ORIGINS=*
SEED_DATABASE=true
GOOGLE_MAPS_API_KEY=
GOOGLE_MAPS_RESTRICTED_KEY=
USE_GOOGLE_ROUTE_OPTIMIZATION=false
GOOGLE_ROUTE_OPTIMIZATION_SERVICE_ACCOUNT_FILE=
GOOGLE_ROUTE_OPTIMIZATION_ENDPOINT=
```

## 4. Instalar dependências

### Backend

```powershell
cd backend-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Frontend

```powershell
cd frontend-flet
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 5. Executar a API

```powershell
cd backend-api
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

A API ficará disponível em:
- http://localhost:8000/docs
- http://localhost:8000/health

## 6. Executar o frontend Flet

Em outro terminal:

```powershell
cd frontend-flet
.\.venv\Scripts\Activate.ps1
flet run main.py
```

## 7. Credenciais iniciais

Ao iniciar a aplicação com `SEED_DATABASE=true`, o sistema cria um usuário inicial:

- E-mail: `admin@sistema.com`
- Senha: `123456`

## 8. Google Maps

As funcionalidades de mapa dependem das variáveis abaixo:

- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_MAPS_RESTRICTED_KEY`

Se essas variáveis não forem configuradas, o mapa pode não carregar corretamente. O backend também expõe endpoints de apoio em:
- `/api/maps/config`
- `/api/maps/directions`
- `/api/maps/optimize`

## 9. Otimização de rotas

Para usar a otimização real via Google Route Optimization, defina:

- `USE_GOOGLE_ROUTE_OPTIMIZATION=true`
- `GOOGLE_ROUTE_OPTIMIZATION_SERVICE_ACCOUNT_FILE`
- `GOOGLE_ROUTE_OPTIMIZATION_ENDPOINT`

Se essas opções não estiverem configuradas, o sistema usa um modo stub para testes e demonstração.

## 10. Migrações Alembic

Em ambientes de desenvolvimento ou teste, a API cria tabelas automaticamente na inicialização. Para ambientes mais controlados, use Alembic:

```powershell
cd backend-api
alembic revision --autogenerate -m "descricao"
alembic upgrade head
```

## 11. Testes

```powershell
cd backend-api
.\.venv\Scripts\Activate.ps1
pytest -q
```

## 12. Observações importantes

- Não há implementação de WebSocket de rastreamento em tempo real no backend atual.
- O modelo `RotaPosicao` existe, mas não há endpoints públicos de rastreamento em tempo real.
- Para apresentação, mantenha `USE_GOOGLE_ROUTE_OPTIMIZATION=false` se não houver uma integração real configurada.
- Antes de publicar, troque `JWT_SECRET` e a senha inicial do usuário administrador.

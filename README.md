# Sistema de Gerenciamento de Entregas

MVP com API REST em FastAPI e aplicativo em Flet.

## Estrutura

- `backend-api`: autenticacao JWT, regras de negocio, CRUDs, dashboard e relatorios.
- `frontend-flet`: interface para login, dashboard, clientes, enderecos, produtos, usuarios, pedidos e entregas.

## Banco MySQL

O projeto usa MySQL 8 por padrao:

```env
DATABASE_URL=mysql+pymysql://entregas:senha@localhost:3306/entregas_db?charset=utf8mb4
```

Crie o banco e o usuario antes de iniciar a API:

```sql
CREATE DATABASE entregas_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'entregas'@'localhost' IDENTIFIED BY 'senha';
GRANT ALL PRIVILEGES ON entregas_db.* TO 'entregas'@'localhost';
FLUSH PRIVILEGES;
```

## Execucao local

### API

```powershell
cd backend-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Documentacao: `http://localhost:8000/docs`

### Migracoes

Para criar uma nova migracao depois de alterar os models:

```powershell
cd backend-api
alembic revision --autogenerate -m "descricao"
alembic upgrade head
```

Em `APP_ENV=development` ou `APP_ENV=test`, a API ainda cria tabelas automaticamente na inicializacao para facilitar testes locais. Em outros ambientes, use Alembic.

### Aplicativo Flet

```powershell
cd frontend-flet
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flet run main.py
```

Credenciais iniciais:

- E-mail: `admin@sistema.com`
- Senha: `123456`

Altere a senha e o segredo JWT antes de publicar.

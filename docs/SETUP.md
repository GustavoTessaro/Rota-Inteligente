# Guia de configuração rápida

Este guia descreve os passos mínimos para executar o projeto em uma máquina nova.

## 1. Requisitos

- Python 3.10+ (o projeto foi validado com Python 3.14)
- MySQL 8 ou MariaDB compatível
- Git
- (Opcional) Google Cloud account para otimização de rotas real

## 2. Clonar o projeto

```powershell
git clone <repo-url>
cd Rota-Inteligente
```

## 3. Criar o banco de dados

No MySQL, execute:

```sql
CREATE DATABASE entregas_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'entregas'@'localhost' IDENTIFIED BY 'senha';
GRANT ALL PRIVILEGES ON entregas_db.* TO 'entregas'@'localhost';
FLUSH PRIVILEGES;
```

## 4. Criar ambientes virtuais

```powershell
cd backend-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env

cd ..\frontend-flet
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 5. Configurar variáveis de ambiente

Edite o arquivo `backend-api/.env` com, no mínimo:

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

## 6. Executar a API

```powershell
cd backend-api
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

A API ficará disponível em:
- http://localhost:8000/docs
- http://localhost:8000/health

## 7. Configuracao do frontend

Para desktop, use um arquivo local `frontend-flet/.env`:

```env
API_BASE_URL=http://127.0.0.1:8000/api
MAPTILER_API_KEY=
```

Para um build Android de desenvolvimento, gere uma configuracao local com o
IP LAN da maquina, sem gravar o valor no Git:

```powershell
$env:MAPTILER_API_KEY="sua-chave-publica-restrita"
python tools/prepare_android_build.py --api-base-url "http://<IP_LAN>:8000/api"
```

O arquivo gerado e `frontend-flet/app/generated_config.py` e e ignorado pelo
Git. Em producao, use uma URL HTTPS publica; a URL WSS do tracking e derivada
automaticamente. A chave MapTiler do cliente deve ser publica/restrita e nao
deve ser confundida com segredos do servidor.

## 8. Executar o frontend Flet

Em outro terminal:

```powershell
cd frontend-flet
.\.venv\Scripts\Activate.ps1
flet run main.py
```

## 8. Credenciais iniciais

- E-mail: `admin@sistema.com`
- Senha: `123456`

## 9. Google Maps

Para habilitar mapa e rotas em produção, configure:

- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_MAPS_RESTRICTED_KEY`

Se deixadas vazias, o mapa pode não carregar corretamente.

## 10. Otimização de rotas

Para usar a otimização real via Google Route Optimization, defina:

- `USE_GOOGLE_ROUTE_OPTIMIZATION=true`
- `GOOGLE_ROUTE_OPTIMIZATION_SERVICE_ACCOUNT_FILE`
- `GOOGLE_ROUTE_OPTIMIZATION_ENDPOINT`

Se essas variáveis não estiverem configuradas, o projeto cai para o modo stub, que ainda funciona para testes.

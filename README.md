# Automação DJEN CNJ - Consulta de Comunicações Processuais

Automação em Python para consultar e extrair intimações do **Diário de Justiça Eletrônico Nacional** (DJEN) através do site [comunica.pje.jus.br](https://comunica.pje.jus.br).

## Funcionalidades

- Consulta por número da OAB e período (data início / data fim)
- Extração automática de todas as intimações encontradas
- Salvamento em JSON e CSV
- Screenshot da página para conferência
- Modo headless (sem abrir janela do navegador)

## Requisitos

- Python 3.8+
- Google Chrome instalado

## Instalação

```bash
pip install -r requirements.txt
```

## Uso

### Modo interativo (sem argumentos)
```bash
python main.py
```

### Modo com argumentos
```bash
python main.py <OAB> <DATA_INICIO> <DATA_FIM> [headless] [UF_OAB]
```

**Exemplo:**
```bash
python main.py 165230 2026-01-20 2026-01-20
python main.py 165230 2026-01-20 2026-01-20 true
python main.py 12402 2026-03-07 2026-03-10 false PI
```

O parâmetro `UF_OAB` filtra por estado da OAB (ex: SP, RJ, PI). Se omitido, busca em todas as UFs.

## API REST

A API roda com FastAPI e expõe a automação como serviço.

### Rodar localmente

```bash
pip install -r requirements.txt
python api.py
```

Acesse:
- **Painel Web**: http://localhost:8080
- **Swagger/Docs**: http://localhost:8080/docs

### Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/consultar` | Inicia consulta assíncrona. Retorna `job_id` |
| `GET` | `/api/status/{job_id}` | Status do job (queued/running/completed/error) |
| `GET` | `/api/resultado/{job_id}` | Resultado completo com intimações |
| `POST` | `/api/consultar/sync` | Consulta síncrona (bloqueia até concluir) |
| `GET` | `/api/jobs` | Lista todos os jobs |
| `GET` | `/api/arquivos` | Lista arquivos de resultados salvos |
| `GET` | `/api/health` | Health check |

### Exemplo de uso via API

```bash
# Iniciar consulta assíncrona
curl -X POST http://localhost:8080/api/consultar \
  -H "Content-Type: application/json" \
  -d '{"oab":"165230","data_inicio":"2026-03-01","data_fim":"2026-03-10","uf_oab":"SP"}'

# Verificar status
curl http://localhost:8080/api/status/{job_id}

# Obter resultado
curl http://localhost:8080/api/resultado/{job_id}

# Consulta síncrona (aguarda resultado)
curl -X POST http://localhost:8080/api/consultar/sync \
  -H "Content-Type: application/json" \
  -d '{"oab":"165230","data_inicio":"2026-03-01","data_fim":"2026-03-10"}'
```

## Deploy com Docker (EasyPanel)

```bash
docker compose up -d --build
```

### EasyPanel

1. Crie um serviço **App** com fonte GitHub: `reinaldosoh/api_intimacao`, branch `main`
2. **Caminho de Build**: deixe **vazio** ou use `.` (raiz). Se der "Invalid", tente `Dockerfile`
3. **Arquivo** (na seção Construção): `Dockerfile`
4. Porta: **8080**
5. **Importante**: Chrome precisa de mais memória compartilhada. Em **Deploy** > **Resources** (ou configurações avançadas), adicione:
   - **shm_size** ou **Shared memory**: `2g` (ou 2048 MB)

   Se não houver opção para shm_size, use **Docker Compose** como fonte (o `docker-compose.yml` na raiz já inclui `shm_size: "2gb"`).

## Saída

Os resultados são salvos na pasta `resultados/`:
- `intimacoes_OAB{numero}_{datas}_{timestamp}.json` - Dados estruturados
- `intimacoes_OAB{numero}_{datas}_{timestamp}.csv` - Planilha
- `intimacoes_OAB{numero}_{datas}_{timestamp}_raw.txt` - Texto bruto da página
- Screenshots `.png` da página carregada

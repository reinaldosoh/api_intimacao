"""
JurisRapido API - Automação DJEN CNJ
API REST para consulta de intimações do DJEN via automação Selenium.
Pronta para deploy em Docker/EasyPanel.
"""

import os
import json
import uuid
import threading
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from main import consultar_intimacoes, OUTPUT_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("jurisrapido")

app = FastAPI(
    title="JurisRapido API",
    description="API para consulta de intimações do Diário de Justiça Eletrônico Nacional (DJEN)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Estado dos jobs em memória
# ──────────────────────────────────────────────

jobs: dict = {}
jobs_lock = threading.Lock()


class ConsultaRequest(BaseModel):
    oab: str = Field(..., min_length=1, description="Número da OAB")
    data_inicio: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Data início (YYYY-MM-DD)")
    data_fim: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Data fim (YYYY-MM-DD)")
    uf_oab: Optional[str] = Field("", max_length=2, description="UF da OAB (ex: SP, RJ, PI). Vazio = todas.")


# ──────────────────────────────────────────────
# Execução da automação em background
# ──────────────────────────────────────────────

def executar_job(job_id: str, oab: str, data_inicio: str, data_fim: str, uf_oab: str):
    """Roda a automação em thread separada e atualiza o estado do job."""
    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["inicio"] = datetime.now().isoformat()

    try:
        logger.info(f"Job {job_id}: iniciando consulta OAB={oab} UF={uf_oab or 'todas'} {data_inicio} a {data_fim}")
        resultados = consultar_intimacoes(
            oab=oab,
            data_inicio=data_inicio,
            data_fim=data_fim,
            headless=True,
            uf_oab=uf_oab or "",
        )

        with jobs_lock:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["fim"] = datetime.now().isoformat()
            jobs[job_id]["total"] = len(resultados)
            jobs[job_id]["intimacoes"] = resultados

        logger.info(f"Job {job_id}: concluído com {len(resultados)} intimação(ões)")

    except Exception as e:
        logger.error(f"Job {job_id}: erro - {e}")
        with jobs_lock:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["fim"] = datetime.now().isoformat()
            jobs[job_id]["erro"] = str(e)


# ──────────────────────────────────────────────
# Endpoints da API
# ──────────────────────────────────────────────

@app.post("/api/consultar", summary="Iniciar consulta de intimações")
def iniciar_consulta(req: ConsultaRequest):
    """
    Inicia uma consulta assíncrona de intimações no DJEN.
    Retorna um `job_id` para acompanhar o progresso via `/api/status/{job_id}`.
    """
    job_id = str(uuid.uuid4())[:8]

    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "oab": req.oab,
            "uf_oab": (req.uf_oab or "").upper(),
            "data_inicio": req.data_inicio,
            "data_fim": req.data_fim,
            "criado_em": datetime.now().isoformat(),
            "inicio": None,
            "fim": None,
            "total": 0,
            "intimacoes": [],
            "erro": None,
        }

    t = threading.Thread(target=executar_job, args=(job_id, req.oab, req.data_inicio, req.data_fim, req.uf_oab or ""), daemon=True)
    t.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "mensagem": "Consulta iniciada. Use /api/status/{job_id} para acompanhar.",
    }


@app.get("/api/status/{job_id}", summary="Status de uma consulta")
def status_consulta(job_id: str):
    """Retorna o status atual de um job de consulta."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    info = {k: v for k, v in job.items() if k != "intimacoes"}
    return info


@app.get("/api/resultado/{job_id}", summary="Resultado completo de uma consulta")
def resultado_consulta(job_id: str):
    """Retorna as intimações extraídas de um job concluído."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    if job["status"] == "running" or job["status"] == "queued":
        return {"status": job["status"], "mensagem": "Consulta ainda em andamento. Aguarde."}
    if job["status"] == "error":
        return {"status": "error", "erro": job["erro"]}
    return {
        "status": "completed",
        "consulta": {
            "oab": job["oab"],
            "uf_oab": job["uf_oab"],
            "data_inicio": job["data_inicio"],
            "data_fim": job["data_fim"],
        },
        "total": job["total"],
        "intimacoes": job["intimacoes"],
    }


@app.post("/api/consultar/sync", summary="Consulta síncrona (aguarda resultado)")
def consulta_sincrona(req: ConsultaRequest):
    """
    Executa a consulta e retorna o resultado diretamente (bloqueia até concluir).
    Use para integrações simples. Timeout recomendado: 120s.
    """
    try:
        resultados = consultar_intimacoes(
            oab=req.oab,
            data_inicio=req.data_inicio,
            data_fim=req.data_fim,
            headless=True,
            uf_oab=req.uf_oab or "",
        )
        return {
            "status": "completed",
            "consulta": {
                "oab": req.oab,
                "uf_oab": (req.uf_oab or "").upper(),
                "data_inicio": req.data_inicio,
                "data_fim": req.data_fim,
            },
            "total": len(resultados),
            "intimacoes": resultados,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/jobs", summary="Listar todos os jobs")
def listar_jobs():
    """Lista todos os jobs de consulta (sem inteiro teor para economizar banda)."""
    with jobs_lock:
        lista = []
        for job in jobs.values():
            info = {k: v for k, v in job.items() if k != "intimacoes"}
            lista.append(info)
    lista.sort(key=lambda j: j.get("criado_em", ""), reverse=True)
    return lista


@app.get("/api/arquivos", summary="Listar arquivos de resultados salvos")
def listar_arquivos():
    """Lista os arquivos JSON de resultados já salvos em disco."""
    arquivos = []
    if not os.path.exists(OUTPUT_DIR):
        return arquivos
    for f in sorted(os.listdir(OUTPUT_DIR), reverse=True):
        if f.endswith(".json") and f.startswith("intimacoes_"):
            caminho = os.path.join(OUTPUT_DIR, f)
            try:
                with open(caminho, "r", encoding="utf-8") as fp:
                    dados = json.load(fp)
                consulta = dados.get("consulta", {})
                arquivos.append({
                    "arquivo": f,
                    "oab": consulta.get("oab", ""),
                    "uf_oab": consulta.get("uf_oab", ""),
                    "data_inicio": consulta.get("data_inicio", ""),
                    "data_fim": consulta.get("data_fim", ""),
                    "data_extracao": consulta.get("data_extracao", ""),
                    "total": consulta.get("total_intimacoes", 0),
                })
            except:
                pass
    return arquivos


@app.get("/api/arquivo/{nome}", summary="Carregar um arquivo de resultado")
def carregar_arquivo(nome: str):
    """Carrega o conteúdo de um arquivo JSON de resultado."""
    nome = os.path.basename(nome)
    caminho = os.path.join(OUTPUT_DIR, nome)
    if not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    with open(caminho, "r", encoding="utf-8") as fp:
        return json.load(fp)


@app.get("/api/health", summary="Health check")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ──────────────────────────────────────────────
# Endpoints de compatibilidade com o painel web (viewer.py)
# O painel HTML usa /api/todas, /api/buscar, /api/status, /api/deletar
# ──────────────────────────────────────────────

from viewer import listar_todas_intimacoes, listar_arquivos_json, carregar_json

painel_status = {"rodando": False, "log": "", "erro": None, "arquivo_resultado": None, "zero_resultados": False}
painel_lock = threading.Lock()


def _limpar_resultados_antigos():
    """Remove todos os JSONs/CSVs de resultados anteriores para evitar leak entre buscas."""
    if not os.path.exists(OUTPUT_DIR):
        return
    for f in os.listdir(OUTPUT_DIR):
        if f.startswith("intimacoes_") and (f.endswith(".json") or f.endswith(".csv")):
            try:
                os.remove(os.path.join(OUTPUT_DIR, f))
            except OSError:
                pass


def _executar_painel(oab, data_inicio, data_fim, uf_oab=""):
    """Executa automação e atualiza painel_status para polling do frontend."""
    global painel_status
    with painel_lock:
        painel_status = {"rodando": True, "log": "Iniciando automação...\n", "erro": None, "arquivo_resultado": None, "zero_resultados": False}

    _limpar_resultados_antigos()

    try:
        import io, contextlib
        log_buffer = io.StringIO()
        with contextlib.redirect_stdout(log_buffer):
            resultados = consultar_intimacoes(
                oab=oab, data_inicio=data_inicio, data_fim=data_fim,
                headless=True, uf_oab=uf_oab,
            )
        with painel_lock:
            painel_status["log"] = log_buffer.getvalue()

        if not resultados:
            with painel_lock:
                painel_status["zero_resultados"] = True
        else:
            arquivos = listar_arquivos_json()
            with painel_lock:
                if arquivos:
                    painel_status["arquivo_resultado"] = arquivos[0]["arquivo"]

    except Exception as e:
        with painel_lock:
            painel_status["erro"] = str(e)
            painel_status["log"] += f"\nERRO: {e}\n"
    finally:
        with painel_lock:
            painel_status["rodando"] = False


@app.get("/api/todas", include_in_schema=False)
def api_todas():
    return JSONResponse(content=listar_todas_intimacoes())


@app.get("/api/lista", include_in_schema=False)
def api_lista():
    return JSONResponse(content=listar_arquivos_json())


@app.get("/api/consulta", include_in_schema=False)
def api_consulta(arquivo: str = ""):
    if not arquivo:
        return JSONResponse(content={"erro": "Parâmetro 'arquivo' obrigatório"}, status_code=400)
    dados = carregar_json(arquivo)
    if not dados:
        return JSONResponse(content={"erro": "Arquivo não encontrado"}, status_code=404)
    return JSONResponse(content=dados)


@app.get("/api/status", include_in_schema=False)
def api_painel_status():
    with painel_lock:
        return JSONResponse(content=dict(painel_status))


@app.post("/api/buscar", include_in_schema=False)
async def api_buscar(req: dict):
    oab = req.get("oab", "").strip()
    uf_oab = req.get("uf_oab", "").strip().upper()
    data_inicio = req.get("data_inicio", "").strip()
    data_fim = req.get("data_fim", "").strip()

    if not oab or not data_inicio or not data_fim:
        return JSONResponse(content={"erro": "Campos obrigatórios: oab, data_inicio, data_fim"}, status_code=400)

    with painel_lock:
        if painel_status.get("rodando"):
            return JSONResponse(content={"erro": "Já existe uma busca em andamento. Aguarde."}, status_code=409)

    t = threading.Thread(target=_executar_painel, args=(oab, data_inicio, data_fim, uf_oab), daemon=True)
    t.start()

    return JSONResponse(content={"ok": True, "mensagem": "Busca iniciada"})


@app.post("/api/deletar", include_in_schema=False)
async def api_deletar(req: dict):
    arquivo = os.path.basename(req.get("arquivo", "").strip())
    if not arquivo:
        return JSONResponse(content={"erro": "Campo 'arquivo' obrigatório"}, status_code=400)
    removidos = []
    for ext in [".json", ".csv"]:
        nome = arquivo if arquivo.endswith(ext) else arquivo.replace(".json", ext).replace(".csv", ext)
        caminho = os.path.join(OUTPUT_DIR, nome)
        if os.path.exists(caminho):
            os.remove(caminho)
            removidos.append(os.path.basename(caminho))
    if not removidos:
        caminho_json = os.path.join(OUTPUT_DIR, arquivo)
        caminho_csv = os.path.join(OUTPUT_DIR, arquivo.replace('.json', '.csv'))
        for c in [caminho_json, caminho_csv]:
            if os.path.exists(c):
                os.remove(c)
                removidos.append(os.path.basename(c))
    if removidos:
        return JSONResponse(content={"ok": True, "removidos": removidos})
    return JSONResponse(content={"erro": "Arquivo não encontrado"}, status_code=404)


# ──────────────────────────────────────────────
# Painel Web (SPA) servido na raiz
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def painel_web():
    """Serve o painel web JurisRapido."""
    from viewer import HTML_PAGE
    return HTML_PAGE


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False, log_level="info")

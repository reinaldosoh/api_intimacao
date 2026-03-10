#!/usr/bin/env python3
"""
JurisRapido - Monitoramento de Intimações
Servidor web local para buscar, visualizar e navegar pelas intimações extraídas.
Uso: python3 viewer.py [porta]
"""

import http.server
import json
import os
import sys
import subprocess
import threading
import urllib.parse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTADOS_DIR = os.path.join(BASE_DIR, "resultados")
MAIN_PY = os.path.join(BASE_DIR, "main.py")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

# Estado global da automação
automacao_status = {"rodando": False, "log": "", "erro": None, "arquivo_resultado": None}


def listar_arquivos_json():
    """Lista todos os arquivos JSON de resultados."""
    arquivos = []
    if not os.path.exists(RESULTADOS_DIR):
        return arquivos
    for f in sorted(os.listdir(RESULTADOS_DIR), reverse=True):
        if f.endswith(".json") and f.startswith("intimacoes_"):
            caminho = os.path.join(RESULTADOS_DIR, f)
            try:
                with open(caminho, "r", encoding="utf-8") as fp:
                    dados = json.load(fp)
                consulta = dados.get("consulta", {})
                arquivos.append({
                    "arquivo": f,
                    "oab": consulta.get("oab", ""),
                    "data_inicio": consulta.get("data_inicio", ""),
                    "data_fim": consulta.get("data_fim", ""),
                    "data_extracao": consulta.get("data_extracao", ""),
                    "total": consulta.get("total_intimacoes", 0),
                })
            except:
                pass
    return arquivos


def carregar_json(arquivo):
    """Carrega um arquivo JSON de resultados."""
    caminho = os.path.join(RESULTADOS_DIR, arquivo)
    if not os.path.exists(caminho):
        return None
    with open(caminho, "r", encoding="utf-8") as fp:
        return json.load(fp)


def listar_todas_intimacoes():
    """Carrega todas as intimações de todos os arquivos, deduplica e retorna."""
    todas = []
    vistos = set()
    if not os.path.exists(RESULTADOS_DIR):
        return []
    for f in sorted(os.listdir(RESULTADOS_DIR), reverse=True):
        if f.endswith(".json") and f.startswith("intimacoes_"):
            try:
                caminho = os.path.join(RESULTADOS_DIR, f)
                with open(caminho, "r", encoding="utf-8") as fp:
                    dados = json.load(fp)
                consulta = dados.get("consulta", {})
                for intim in dados.get("intimacoes", []):
                    chave = (
                        intim.get("numero_processo", ""),
                        intim.get("tribunal", ""),
                        intim.get("data_disponibilizacao", "")
                    )
                    if chave not in vistos:
                        vistos.add(chave)
                        intim["_arquivo"] = f
                        intim["_oab"] = consulta.get("oab", "")
                        todas.append(intim)
            except:
                pass
    return todas


def executar_automacao(oab, data_inicio, data_fim, uf_oab=""):
    """Executa main.py em background e atualiza o status global."""
    global automacao_status
    automacao_status = {"rodando": True, "log": "Iniciando automação...\n", "erro": None, "arquivo_resultado": None, "zero_resultados": False}

    try:
        cmd = [sys.executable, MAIN_PY, oab, data_inicio, data_fim]
        if uf_oab:
            cmd.extend(["false", uf_oab.upper()])
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=BASE_DIR,
        )

        for line in proc.stdout:
            automacao_status["log"] += line

        proc.wait()

        if proc.returncode != 0:
            automacao_status["erro"] = f"Processo encerrou com código {proc.returncode}"
        else:
            # Verificar se encontrou 0 resultados (main.py não salva JSON nesse caso)
            log_text = automacao_status["log"]
            if "Nenhuma intimação" in log_text or "Nenhum resultado" in log_text:
                automacao_status["zero_resultados"] = True
            else:
                # Encontrar o JSON mais recente gerado
                arquivos = listar_arquivos_json()
                if arquivos:
                    automacao_status["arquivo_resultado"] = arquivos[0]["arquivo"]
                else:
                    automacao_status["zero_resultados"] = True

    except Exception as e:
        automacao_status["erro"] = str(e)
        automacao_status["log"] += f"\nERRO: {e}\n"
    finally:
        automacao_status["rodando"] = False


HTML_PAGE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JurisRapido</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script>tailwind.config={theme:{extend:{fontFamily:{sans:['Inter','sans-serif']}}}}</script>
    <style>
        body{font-family:'Inter',sans-serif}
        .fade-in{animation:fadeIn .2s ease}
        @keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
        .toast{animation:slideIn .3s ease,slideOut .3s ease 2.7s}
        @keyframes slideIn{from{transform:translateY(-100%);opacity:0}to{transform:translateY(0);opacity:1}}
        @keyframes slideOut{from{opacity:1}to{opacity:0}}
        @keyframes spin{to{transform:rotate(360deg)}}
        .spinner{animation:spin 1s linear infinite}
        @keyframes dots{0%,20%{content:'.'}40%{content:'..'}60%,100%{content:'...'}}
        .loading-dots::after{content:'';animation:dots 1.5s infinite}
        .log-box{font-family:'Courier New',monospace;font-size:11px;white-space:pre-wrap;max-height:200px;overflow-y:auto}
        .inteiro-teor-text{white-space:pre-wrap;word-wrap:break-word;line-height:1.8}
        .tab-active{color:#111;border-bottom:2px solid #111;font-weight:600}
        .tab-inactive{color:#9CA3AF;border-bottom:2px solid transparent}
        .tab-inactive:hover{color:#6B7280}
        .row-new{border-left:3px solid #3B82F6}
    </style>
</head>
<body class="bg-gray-50 min-h-screen">

    <!-- Header -->
    <header class="bg-white border-b sticky top-0 z-30">
        <div class="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
            <div class="flex items-center gap-2.5 cursor-pointer" onclick="voltarHome()">
                <div class="w-8 h-8 bg-black rounded-lg flex items-center justify-center">
                    <span class="text-white font-bold text-sm">J</span>
                </div>
                <span class="font-semibold text-gray-900 text-sm">JurisRapido</span>
            </div>
            <button onclick="toggleBusca()" id="btnNovaBusca" class="bg-black text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-gray-800 transition flex items-center gap-1.5">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
                Nova Busca
            </button>
        </div>
    </header>

    <!-- Toast -->
    <div id="toast" class="fixed top-4 right-4 z-50 hidden">
        <div class="toast bg-gray-900 text-white px-4 py-2.5 rounded-lg shadow-lg flex items-center gap-2 text-sm">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
            <span id="toastMsg"></span>
        </div>
    </div>

    <main class="max-w-6xl mx-auto px-6 py-6">

        <!-- Search Panel (collapsible) -->
        <div id="painelBusca" class="hidden mb-6 fade-in">
            <div class="bg-white rounded-xl border p-5">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-sm font-semibold text-gray-900">Nova Consulta</h2>
                    <button onclick="toggleBusca()" class="text-gray-400 hover:text-gray-600">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                </div>
                <form onsubmit="iniciarBusca(event)" class="flex items-end gap-3 flex-wrap">
                    <div class="flex-1 min-w-[120px]">
                        <label class="block text-xs text-gray-500 mb-1">N. da OAB</label>
                        <input type="text" id="inputOAB" name="consulta_oab_jurisrapido" required placeholder="Digite a OAB" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" class="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-gray-900 focus:border-transparent outline-none font-semibold">
                    </div>
                    <div class="min-w-[80px] max-w-[100px]">
                        <label class="block text-xs text-gray-500 mb-1">UF da OAB</label>
                        <input type="text" id="inputUfOab" maxlength="2" placeholder="Ex: SP" autocomplete="off" class="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-gray-900 focus:border-transparent outline-none uppercase" style="text-transform:uppercase">
                    </div>
                    <div class="flex-1 min-w-[140px]">
                        <label class="block text-xs text-gray-500 mb-1">Data Início</label>
                        <input type="date" id="inputDataInicio" required class="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-gray-900 focus:border-transparent outline-none">
                    </div>
                    <div class="flex-1 min-w-[140px]">
                        <label class="block text-xs text-gray-500 mb-1">Data Fim</label>
                        <input type="date" id="inputDataFim" required class="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-gray-900 focus:border-transparent outline-none">
                    </div>
                    <button type="submit" id="btnBuscar" class="bg-black text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-gray-800 transition flex items-center gap-2">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                        Buscar
                    </button>
                </form>
            </div>
        </div>

        <!-- Loading -->
        <div id="loadingAutomacao" class="hidden mb-6">
            <div class="bg-blue-50 border border-blue-100 rounded-xl p-5">
                <div class="flex items-center gap-3 mb-2">
                    <svg class="w-5 h-5 text-blue-600 spinner" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                    <h3 class="text-sm font-semibold text-blue-900 loading-dots">Buscando nos tribunais e diários oficiais</h3>
                </div>
                <p class="text-blue-700 text-xs mb-3">Nossa inteligência está rastreando as intimações. Isso pode levar alguns instantes.</p>
                <details class="text-xs">
                    <summary class="text-blue-400 cursor-pointer hover:text-blue-600">Log técnico</summary>
                    <div id="logAutomacao" class="log-box bg-white border rounded-lg p-2 mt-2 text-gray-600"></div>
                </details>
            </div>
        </div>

        <!-- Error -->
        <div id="erroAutomacao" class="hidden mb-6">
            <div class="bg-red-50 border border-red-100 rounded-xl p-4 flex items-start gap-3">
                <svg class="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                <div><p class="text-sm font-medium text-red-800">Erro na busca</p><p id="erroMsg" class="text-red-600 text-xs mt-0.5"></p></div>
            </div>
        </div>

        <!-- ========== HOME ========== -->
        <div id="telaHome">
            <!-- Filter Tabs -->
            <div class="flex items-center gap-6 border-b mb-5">
                <button onclick="setFiltro('todas')" id="tabTodas" class="pb-3 text-sm transition tab-active">Todas <span id="cntTodas" class="ml-1 text-[10px] bg-gray-100 px-1.5 py-0.5 rounded-full">0</span></button>
                <button onclick="setFiltro('novas')" id="tabNovas" class="pb-3 text-sm transition tab-inactive">Novas <span id="cntNovas" class="ml-1 text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">0</span></button>
                <button onclick="setFiltro('visualizadas')" id="tabVistas" class="pb-3 text-sm transition tab-inactive">Visualizadas <span id="cntVistas" class="ml-1 text-[10px] bg-gray-100 px-1.5 py-0.5 rounded-full">0</span></button>
            </div>

            <!-- Toolbar -->
            <div class="flex items-center justify-between mb-4">
                <p class="text-xs text-gray-400" id="resumoTotal"></p>
                <div class="relative">
                    <svg class="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                    <input type="text" id="filtroGlobal" placeholder="Filtrar por processo, parte, órgão..." oninput="renderizar()" class="pl-9 pr-4 py-1.5 border rounded-lg text-sm w-64 focus:ring-2 focus:ring-gray-900 focus:border-transparent outline-none">
                </div>
            </div>

            <!-- OAB Sections -->
            <div id="listaOABs" class="space-y-6"></div>
            <div id="tabelaVazia" class="hidden text-center py-16 text-gray-400">
                <svg class="w-12 h-12 mx-auto mb-3 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                <p class="font-medium text-sm">Nenhuma intimação encontrada</p>
                <p class="text-xs mt-1">Clique em "Nova Busca" para começar</p>
            </div>
        </div>

        <!-- ========== DETALHE ========== -->
        <div id="detalheView" class="hidden fade-in">
            <div class="mb-4">
                <button onclick="voltarHome()" class="text-sm text-gray-500 hover:text-gray-900 flex items-center gap-1 transition">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
                    Voltar
                </button>
            </div>
            <div id="detalheContent"></div>
        </div>
    </main>

    <script>
    // ===================== STATE =====================
    let todasIntimacoes = [];
    let filtroAtual = 'todas';
    let pollingInterval = null;

    // ===================== READ/UNREAD (localStorage) =====================
    function getChave(i) { return (i.numero_processo||'')+'|'+(i.tribunal||'')+'|'+(i.data_disponibilizacao||''); }
    function isVista(i) { return localStorage.getItem('jr_'+getChave(i))==='1'; }
    function marcarVista(i) { localStorage.setItem('jr_'+getChave(i),'1'); }

    // ===================== DATA =====================
    async function carregarTodas() {
        const resp = await fetch('/api/todas');
        todasIntimacoes = await resp.json();
        renderizar();
    }

    // ===================== SORTING =====================
    function toSortDate(d) {
        if (!d) return '';
        const p = d.split('/');
        return p.length===3 ? p[2]+p[1]+p[0] : d;
    }

    // ===================== FILTERS =====================
    function setFiltro(f) {
        filtroAtual = f;
        document.getElementById('tabTodas').className = 'pb-3 text-sm transition ' + (f==='todas'?'tab-active':'tab-inactive');
        document.getElementById('tabNovas').className = 'pb-3 text-sm transition ' + (f==='novas'?'tab-active':'tab-inactive');
        document.getElementById('tabVistas').className = 'pb-3 text-sm transition ' + (f==='visualizadas'?'tab-active':'tab-inactive');
        renderizar();
    }

    // ===================== RENDER (OAB → PROCESSO → INTIMAÇÕES) =====================
    function agruparPorOAB(ints) {
        const g = {};
        ints.forEach(i => {
            const oab = i._oab || 'Desconhecida';
            if (!g[oab]) g[oab] = [];
            g[oab].push(i);
        });
        return Object.entries(g).sort((a,b) => a[0].localeCompare(b[0]));
    }

    function processosDeOAB(ints) {
        const g = {};
        ints.forEach(i => {
            const k = i.numero_processo || 'desconhecido';
            if (!g[k]) g[k] = [];
            g[k].push(i);
        });
        Object.values(g).forEach(arr => arr.sort((a,b) => toSortDate(b.data_disponibilizacao).localeCompare(toSortDate(a.data_disponibilizacao))));
        return Object.entries(g).sort((a,b) => toSortDate(b[1][0].data_disponibilizacao).localeCompare(toSortDate(a[1][0].data_disponibilizacao)));
    }

    function renderizar() {
        let filtered = [...todasIntimacoes];
        const filtroTexto = (document.getElementById('filtroGlobal').value||'').toLowerCase();
        if (filtroAtual === 'novas') filtered = filtered.filter(i => !isVista(i));
        if (filtroAtual === 'visualizadas') filtered = filtered.filter(i => isVista(i));
        if (filtroTexto) {
            filtered = filtered.filter(i => [i.numero_processo,i.orgao,i.tribunal,i.tipo_comunicacao,i.inteiro_teor,i._oab,...(i.partes||[]),...(i.advogados||[])].filter(Boolean).join(' ').toLowerCase().includes(filtroTexto));
        }

        const totalNovas = todasIntimacoes.filter(i => !isVista(i)).length;
        const totalVistas = todasIntimacoes.filter(i => isVista(i)).length;
        document.getElementById('cntTodas').textContent = todasIntimacoes.length;
        document.getElementById('cntNovas').textContent = totalNovas;
        document.getElementById('cntVistas').textContent = totalVistas;

        const oabGroups = agruparPorOAB(filtered);
        const container = document.getElementById('listaOABs');
        const vazio = document.getElementById('tabelaVazia');
        const totalProcs = oabGroups.reduce((s, [,ints]) => s + processosDeOAB(ints).length, 0);
        document.getElementById('resumoTotal').textContent = oabGroups.length + ' OAB(s), ' + totalProcs + ' processo(s), ' + filtered.length + ' intimação(ões)';

        if (filtered.length === 0) { container.innerHTML=''; vazio.classList.remove('hidden'); return; }
        vazio.classList.add('hidden');

        container.innerHTML = oabGroups.map(([oab, oabInts]) => {
            const procs = processosDeOAB(oabInts);
            const novasOab = oabInts.filter(i => !isVista(i)).length;
            return `
            <div class="fade-in">
                <div class="flex items-center gap-3 mb-3">
                    <div class="w-9 h-9 bg-black rounded-lg flex items-center justify-center flex-shrink-0">
                        <span class="text-white font-bold text-xs">OAB</span>
                    </div>
                    <div class="flex-1">
                        <h3 class="text-sm font-bold text-gray-900">${oab}</h3>
                        <p class="text-[11px] text-gray-400">${procs.length} processo(s), ${oabInts.length} intimação(ões)</p>
                    </div>
                    ${novasOab>0?'<span class="text-[10px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-medium border border-blue-200">'+novasOab+' nova(s)</span>':''}
                </div>
                <div class="bg-white rounded-xl border overflow-hidden">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="border-b bg-gray-50/80">
                                <th class="text-left px-4 py-2.5 text-[10px] font-medium text-gray-400 uppercase tracking-wide w-8">#</th>
                                <th class="text-left px-4 py-2.5 text-[10px] font-medium text-gray-400 uppercase tracking-wide">Processo</th>
                                <th class="text-left px-4 py-2.5 text-[10px] font-medium text-gray-400 uppercase tracking-wide hidden md:table-cell">Tribunal</th>
                                <th class="text-left px-4 py-2.5 text-[10px] font-medium text-gray-400 uppercase tracking-wide hidden lg:table-cell">Órgão</th>
                                <th class="text-left px-4 py-2.5 text-[10px] font-medium text-gray-400 uppercase tracking-wide">Data</th>
                                <th class="text-left px-4 py-2.5 text-[10px] font-medium text-gray-400 uppercase tracking-wide w-24">Status</th>
                                <th class="w-8"></th>
                            </tr>
                        </thead>
                        <tbody>${procs.map(([proc, ints], idx) => {
                            const r = ints[0];
                            const allVistas = ints.every(i => isVista(i));
                            const fw = allVistas ? 'text-gray-500' : 'text-gray-900 font-semibold';
                            return `<tr onclick="verDetalhe('${proc}')" class="border-b last:border-0 hover:bg-gray-50 cursor-pointer transition group ${allVistas?'':'row-new'}">
                                <td class="px-4 py-3 text-xs text-gray-400">${idx+1}</td>
                                <td class="px-4 py-3">
                                    <span class="${fw} text-sm">${proc}</span>
                                    ${ints.length>1?'<span class="ml-2 text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-full">'+ints.length+' int.</span>':''}
                                </td>
                                <td class="px-4 py-3 hidden md:table-cell">${r.tribunal?'<span class="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-medium">'+r.tribunal+'</span>':''}</td>
                                <td class="px-4 py-3 text-gray-500 text-xs truncate max-w-[180px] hidden lg:table-cell">${r.orgao||''}</td>
                                <td class="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">${r.data_disponibilizacao||''}</td>
                                <td class="px-4 py-3">${allVistas?'<span class="text-[10px] text-gray-400">Visualizado</span>':'<span class="text-[10px] bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-medium border border-blue-200">Novo</span>'}</td>
                                <td class="px-4 py-3"><svg class="w-4 h-4 text-gray-300 group-hover:text-gray-500 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg></td>
                            </tr>`;
                        }).join('')}</tbody>
                    </table>
                </div>
            </div>`;
        }).join('');
    }

    // ===================== DETAIL =====================
    function verDetalhe(proc, subIdx) {
        const ints = todasIntimacoes.filter(i => i.numero_processo === proc);
        if (!ints.length) return;
        ints.sort((a,b) => toSortDate(b.data_disponibilizacao).localeCompare(toSortDate(a.data_disponibilizacao)));
        ints.forEach(i => marcarVista(i));
        const idx = subIdx || 0;
        const int = ints[idx];

        document.getElementById('telaHome').classList.add('hidden');
        document.getElementById('detalheView').classList.remove('hidden');

        const partesHtml = ((int.partes&&int.partes.length)||(int.advogados&&int.advogados.length)) ? `
            <details class="border rounded-lg overflow-hidden">
                <summary class="px-4 py-2.5 bg-gray-50 cursor-pointer hover:bg-gray-100 transition text-sm font-medium text-gray-600 flex items-center justify-between">
                    <span>Participantes</span>
                    <span class="text-xs text-gray-400">${(int.partes||[]).length+(int.advogados||[]).length}</span>
                </summary>
                <div class="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                    ${int.partes&&int.partes.length?'<div><p class="text-[10px] text-gray-400 font-medium uppercase mb-1.5 tracking-wide">Partes</p>'+int.partes.map(p=>'<p class="text-gray-700 py-0.5 text-sm">'+p+'</p>').join('')+'</div>':''}
                    ${int.advogados&&int.advogados.length?'<div><p class="text-[10px] text-gray-400 font-medium uppercase mb-1.5 tracking-wide">Advogados</p>'+int.advogados.map(a=>'<p class="text-gray-700 py-0.5 text-sm">'+a+'</p>').join('')+'</div>':''}
                </div>
            </details>` : '';

        const subTabs = ints.length > 1 ? `
            <div class="flex gap-1 px-5 py-2.5 bg-gray-50 border-b overflow-x-auto">
                ${ints.map((si,i) => `<button onclick="event.stopPropagation();verDetalhe('${proc}',${i})" class="text-xs px-3 py-1 rounded-lg transition whitespace-nowrap ${i===idx?'bg-gray-900 text-white':'bg-white border text-gray-500 hover:bg-gray-100'}">${si.data_disponibilizacao||'#'+(i+1)}${si.tribunal?' · '+si.tribunal:''}</button>`).join('')}
            </div>` : '';

        const arquivoSrc = int._arquivo || '';

        document.getElementById('detalheContent').innerHTML = `
            <div class="bg-white rounded-xl border overflow-hidden">
                <div class="px-5 py-4 border-b">
                    <div class="flex items-center justify-between">
                        <div>
                            <p class="text-[10px] text-gray-400 uppercase tracking-wide mb-1">Processo</p>
                            <h2 class="text-lg font-bold text-gray-900">${int.numero_processo||'N/A'}</h2>
                        </div>
                        <div class="flex items-center gap-2">
                            ${int.tribunal?'<span class="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded font-medium">'+int.tribunal+'</span>':''}
                            <button onclick="copiarElemento('inteiroTeorTexto')" class="text-xs bg-gray-100 hover:bg-gray-200 text-gray-600 px-3 py-1.5 rounded-lg font-medium transition flex items-center gap-1.5">
                                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
                                Copiar
                            </button>
                            ${arquivoSrc?'<button onclick="deletarArquivo(\''+arquivoSrc+'\')" class="text-xs bg-white border border-red-200 text-red-500 hover:bg-red-50 px-3 py-1.5 rounded-lg font-medium transition flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>Excluir</button>':''}
                        </div>
                    </div>
                </div>
                ${subTabs}
                <div class="px-5 py-3 border-b bg-gray-50/50 flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500">
                    ${int.orgao?'<span><b class="text-gray-600">Órgão:</b> '+int.orgao+'</span>':''}
                    ${int.data_disponibilizacao?'<span><b class="text-gray-600">Data:</b> '+int.data_disponibilizacao+'</span>':''}
                    ${int.tipo_comunicacao?'<span><b class="text-gray-600">Tipo:</b> '+int.tipo_comunicacao+'</span>':''}
                    ${int.meio?'<span><b class="text-gray-600">Meio:</b> '+int.meio+'</span>':''}
                    ${int._oab?'<span><b class="text-gray-600">OAB:</b> '+int._oab+'</span>':''}
                </div>
                ${partesHtml?'<div class="px-5 py-3 border-b">'+partesHtml+'</div>':''}
                <div class="px-5 py-4">
                    <h4 class="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-3">Conteúdo da Intimação</h4>
                    <div id="inteiroTeorTexto" class="inteiro-teor-text bg-gray-50 rounded-lg p-5 text-gray-800 text-sm border">${int.inteiro_teor||'<span class="text-gray-400 italic">Conteúdo não disponível</span>'}</div>
                </div>
            </div>`;
    }

    // ===================== SEARCH =====================
    function toggleBusca() { document.getElementById('painelBusca').classList.toggle('hidden'); }

    async function iniciarBusca(e) {
        e.preventDefault();
        const oab = document.getElementById('inputOAB').value.trim();
        const ufOab = (document.getElementById('inputUfOab').value||'').trim().toUpperCase();
        const dataInicio = document.getElementById('inputDataInicio').value;
        const dataFim = document.getElementById('inputDataFim').value;
        if (!oab||!dataInicio||!dataFim) { mostrarToast('Preencha todos os campos'); return; }
        const btn = document.getElementById('btnBuscar');
        btn.disabled = true; btn.textContent = 'Buscando...';
        document.getElementById('painelBusca').classList.add('hidden');
        document.getElementById('loadingAutomacao').classList.remove('hidden');
        document.getElementById('erroAutomacao').classList.add('hidden');
        const logEl = document.getElementById('logAutomacao');
        if (logEl) logEl.textContent = 'Iniciando...\n';
        try {
            const resp = await fetch('/api/buscar', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({oab,uf_oab:ufOab,data_inicio:dataInicio,data_fim:dataFim})});
            const data = await resp.json();
            if (data.erro) { mostrarErro(data.erro); resetarBotao(); return; }
            pollingInterval = setInterval(pollStatus, 1500);
        } catch(err) { mostrarErro('Erro: '+err.message); resetarBotao(); }
    }

    async function pollStatus() {
        try {
            const resp = await fetch('/api/status');
            const status = await resp.json();
            const logEl = document.getElementById('logAutomacao');
            if (logEl) { logEl.textContent = status.log; logEl.scrollTop = logEl.scrollHeight; }
            if (!status.rodando) {
                clearInterval(pollingInterval); pollingInterval = null;
                document.getElementById('loadingAutomacao').classList.add('hidden');
                if (status.erro) mostrarErro(status.erro);
                else if (status.zero_resultados) mostrarAlertaZero();
                else { mostrarToast('Busca concluída!'); await carregarTodas(); }
                resetarBotao();
            }
        } catch {}
    }

    function mostrarErro(msg) {
        document.getElementById('loadingAutomacao').classList.add('hidden');
        document.getElementById('erroAutomacao').classList.remove('hidden');
        document.getElementById('erroMsg').textContent = msg;
    }

    function mostrarAlertaZero() {
        const prev = document.getElementById('alertaZero'); if (prev) prev.remove();
        const a = document.createElement('div');
        a.id='alertaZero'; a.className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 fade-in';
        a.onclick=e=>{if(e.target===a)a.remove();};
        a.innerHTML=`<div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full mx-4 overflow-hidden fade-in">
            <div class="px-6 pt-8 pb-4 flex flex-col items-center text-center">
                <div class="bg-amber-50 rounded-full p-4 mb-4"><svg class="w-8 h-8 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg></div>
                <h3 class="text-base font-bold text-gray-800 mb-1">Nenhuma intimação encontrada</h3>
                <p class="text-sm text-gray-500">Nenhuma intimação localizada para os parâmetros informados.</p>
            </div>
            <div class="px-6 py-4 flex justify-center"><button onclick="document.getElementById('alertaZero').remove()" class="bg-gray-900 hover:bg-gray-800 text-white px-6 py-2 rounded-lg text-sm font-medium transition">Entendi</button></div>
        </div>`;
        document.body.appendChild(a);
    }

    function resetarBotao() { const b=document.getElementById('btnBuscar'); b.disabled=false; b.textContent='Buscar'; }

    // ===================== DELETE =====================
    async function deletarArquivo(arquivo) {
        const prev = document.getElementById('modalConfirm'); if(prev) prev.remove();
        const modal = document.createElement('div');
        modal.id='modalConfirm'; modal.className='fixed inset-0 z-50 flex items-center justify-center bg-black/40 fade-in';
        modal.innerHTML=`<div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full mx-4 overflow-hidden fade-in">
            <div class="bg-red-50 px-6 pt-6 pb-4 flex flex-col items-center text-center">
                <div class="bg-red-100 rounded-full p-3 mb-3"><svg class="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></div>
                <h3 class="text-base font-bold text-gray-800 mb-1">Excluir consulta?</h3>
                <p class="text-sm text-gray-500">Todas as intimações desta consulta serão removidas.</p>
            </div>
            <div class="px-6 py-4 flex gap-3 justify-center">
                <button id="btnCancelDel" class="px-5 py-2 rounded-lg border text-gray-600 hover:bg-gray-50 text-sm font-medium transition">Cancelar</button>
                <button id="btnConfirmDel" class="px-5 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium transition">Excluir</button>
            </div></div>`;
        document.body.appendChild(modal);
        modal.onclick=e=>{if(e.target===modal)modal.remove();};
        modal.querySelector('#btnCancelDel').onclick=()=>modal.remove();
        modal.querySelector('#btnConfirmDel').onclick=async()=>{
            modal.remove();
            try {
                const resp = await fetch('/api/deletar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({arquivo})});
                const data = await resp.json();
                if(data.ok){mostrarToast('Consulta excluída');voltarHome();await carregarTodas();}
                else mostrarToast('Erro: '+(data.erro||'falha'));
            } catch(err){mostrarToast('Erro: '+err.message);}
        };
    }

    // ===================== NAV & HELPERS =====================
    function voltarHome() {
        document.getElementById('telaHome').classList.remove('hidden');
        document.getElementById('detalheView').classList.add('hidden');
        renderizar();
    }

    async function copiarTexto(t) {
        try{await navigator.clipboard.writeText(t);}catch{const e=document.createElement('textarea');e.value=t;document.body.appendChild(e);e.select();document.execCommand('copy');document.body.removeChild(e);}
        mostrarToast('Copiado!');
    }
    function copiarElemento(id) { copiarTexto(document.getElementById(id).innerText); }
    function mostrarToast(msg) { const t=document.getElementById('toast');document.getElementById('toastMsg').textContent=msg;t.classList.remove('hidden');setTimeout(()=>t.classList.add('hidden'),3000); }

    // ===================== INIT =====================
    carregarTodas();
    </script>
</body>
</html>"""


class JurisRapidoHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/todas":
            self.responder_json(listar_todas_intimacoes())
        elif path == "/api/lista":
            self.responder_json(listar_arquivos_json())
        elif path == "/api/consulta":
            arquivo = params.get("arquivo", [None])[0]
            if arquivo:
                dados = carregar_json(arquivo)
                if dados:
                    self.responder_json(dados)
                else:
                    self.responder_json({"erro": "Arquivo não encontrado"}, 404)
            else:
                self.responder_json({"erro": "Parâmetro 'arquivo' obrigatório"}, 400)
        elif path == "/api/status":
            self.responder_json(automacao_status)
        else:
            self.responder_html(HTML_PAGE)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/deletar":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                dados = json.loads(body)
            except:
                self.responder_json({"erro": "JSON inválido"}, 400)
                return
            arquivo = dados.get("arquivo", "").strip()
            if not arquivo:
                self.responder_json({"erro": "Campo 'arquivo' obrigatório"}, 400)
                return
            # Segurança: apenas nome de arquivo, sem path traversal
            arquivo = os.path.basename(arquivo)
            caminho_json = os.path.join(RESULTADOS_DIR, arquivo)
            caminho_csv = os.path.join(RESULTADOS_DIR, arquivo.replace('.json', '.csv'))
            removidos = []
            for caminho in [caminho_json, caminho_csv]:
                if os.path.exists(caminho):
                    os.remove(caminho)
                    removidos.append(os.path.basename(caminho))
            if removidos:
                self.responder_json({"ok": True, "removidos": removidos})
            else:
                self.responder_json({"erro": "Arquivo não encontrado"}, 404)
            return

        if path == "/api/buscar":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                dados = json.loads(body)
            except:
                self.responder_json({"erro": "JSON inválido"}, 400)
                return

            oab = dados.get("oab", "").strip()
            uf_oab = dados.get("uf_oab", "").strip().upper()
            data_inicio = dados.get("data_inicio", "").strip()
            data_fim = dados.get("data_fim", "").strip()

            if not oab or not data_inicio or not data_fim:
                self.responder_json({"erro": "Campos obrigatórios: oab, data_inicio, data_fim"}, 400)
                return

            if automacao_status.get("rodando"):
                self.responder_json({"erro": "Já existe uma busca em andamento. Aguarde."}, 409)
                return

            # Lançar automação em thread separada
            t = threading.Thread(target=executar_automacao, args=(oab, data_inicio, data_fim, uf_oab), daemon=True)
            t.start()

            self.responder_json({"ok": True, "mensagem": "Busca iniciada"})
        else:
            self.responder_json({"erro": "Rota não encontrada"}, 404)

    def responder_json(self, dados, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(dados, ensure_ascii=False).encode("utf-8"))

    def responder_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def main():
    os.makedirs(RESULTADOS_DIR, exist_ok=True)
    server = http.server.HTTPServer(("0.0.0.0", PORT), JurisRapidoHandler)
    print(f"\n{'='*50}")
    print(f"  JurisRapido - Monitoramento de Intimações")
    print(f"{'='*50}")
    print(f"  Servidor: http://localhost:{PORT}")
    print(f"  Resultados: {RESULTADOS_DIR}")
    print(f"  Ctrl+C para parar")
    print(f"{'='*50}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Servidor encerrado.")
        server.server_close()


if __name__ == "__main__":
    main()

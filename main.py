"""
Automação DJEN CNJ - Consulta de Comunicações Processuais
Extrai intimações do site comunica.pje.jus.br por OAB e período.
"""

import os
import sys
import json
import time
import csv
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


# ──────────────────────────────────────────────
# Configurações
# ──────────────────────────────────────────────

BASE_URL = "https://comunica.pje.jus.br/consulta"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
TIMEOUT = 30  # segundos para esperar elementos


def criar_driver(headless: bool = False):
    """Cria e configura o driver do Chrome."""
    chrome_options = Options()

    is_docker = os.environ.get("DOCKER", "").lower() in ("1", "true") or os.path.exists("/.dockerenv")

    if headless or is_docker:
        chrome_options.add_argument("--headless=new")

    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    if is_docker:
        chrome_options.binary_location = os.environ.get("CHROME_BIN", "/usr/bin/google-chrome-stable")
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception:
            driver = webdriver.Chrome(options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    driver.maximize_window()
    return driver


def montar_url(oab: str, data_inicio: str, data_fim: str, uf_oab: str = "") -> str:
    """Monta a URL de consulta com os parâmetros."""
    url = f"{BASE_URL}?texto={oab}&dataDisponibilizacaoInicio={data_inicio}&dataDisponibilizacaoFim={data_fim}"
    if uf_oab:
        url += f"&ufOab={uf_oab.upper()}"
    return url


def aguardar_carregamento(driver, wait):
    """Aguarda o carregamento completo dos resultados na página Angular."""
    print("  Aguardando carregamento da página...")

    # Esperar o Angular terminar de carregar
    try:
        wait.until(lambda d: d.execute_script(
            "return document.readyState === 'complete'"
        ))
    except:
        pass

    # Aguardar spinner desaparecer (se existir)
    try:
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, ".spinner, .loading, mat-spinner, .mat-progress-spinner"))
        )
    except:
        pass

    # Aguardar conteúdo principal aparecer - tentar vários seletores possíveis
    seletores_resultado = [
        "app-consulta",
        ".resultado",
        ".resultados",
        ".lista-comunicacoes",
        ".comunicacao-item",
        "mat-card",
        "mat-expansion-panel",
        ".mat-expansion-panel",
        "table tbody tr",
        ".card",
        ".item-comunicacao",
        "app-root .container",
        "app-root main",
    ]

    for seletor in seletores_resultado:
        try:
            WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, seletor))
            )
            print(f"  Conteúdo encontrado via seletor: {seletor}")
            break
        except:
            continue

    # Espera extra para Angular renderizar completamente
    time.sleep(3)


def extrair_intimacoes(driver, inicio_num=1):
    """
    Extrai intimações da página ATUAL do DJEN.
    A página usa <article class="card"> para cada intimação, contendo:
      - <span class="numero-unico-formatado"> com o número do processo
      - <aside class="card-sumary"> com metadados (Órgão, Data, etc.)
      - O inteiro teor renderizado dentro do card-content

    Args:
        inicio_num: Número inicial para numerar as intimações (para continuidade entre páginas)
    """
    intimacoes = []
    body_text = driver.find_element(By.TAG_NAME, "body").text.strip()

    # Estratégia principal: encontrar os cards <article class="card">
    cards = driver.find_elements(By.CSS_SELECTOR, "article.card")

    if not cards:
        cards = driver.find_elements(By.CSS_SELECTOR, "article.card.fadeIn")

    if not cards:
        print("  Nenhum card <article> encontrado. Tentando fallback...")
        return extrair_intimacoes_fallback(driver, body_text)

    print(f"  Encontrados {len(cards)} card(s) de intimação")

    for idx, card in enumerate(cards):
        numero_global = inicio_num + idx

        try:
            card_data = driver.execute_script(r"""
                var card = arguments[0];
                var result = {};

                // Número do processo: <span class="numero-unico-formatado">
                var span = card.querySelector('.numero-unico-formatado, .numero-processo span');
                if (span) {
                    var m = (span.innerText || '').match(/(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})/);
                    if (m) result.num_processo = m[1];
                }
                if (!result.num_processo) {
                    var allText = card.innerText || '';
                    var m2 = allText.match(/Processo\s+(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})/);
                    if (m2) result.num_processo = m2[1];
                }

                // Metadados do aside.card-sumary
                var aside = card.querySelector('.card-sumary, aside');
                if (aside) result.sumario = aside.innerText.trim();

                // Inteiro teor: conteúdo do card SEM aside e SEM header
                var contentMain = card.querySelector('.card-content.main, .card-content');
                if (contentMain) {
                    // Clonar para manipular sem afetar a página
                    var clone = contentMain.cloneNode(true);
                    // Remover aside (metadados) do clone
                    var asides = clone.querySelectorAll('aside, .card-sumary');
                    for (var i = 0; i < asides.length; i++) asides[i].remove();
                    result.inteiro_teor = clone.innerText.trim();
                    result.inteiro_teor_len = result.inteiro_teor.length;
                }

                // Texto completo do card (fallback)
                result.card_text = card.innerText.trim();

                return result;
            """, card)
        except Exception as e:
            print(f"  [{idx + 1}] Erro ao extrair card via JS: {e}")
            continue

        num_processo = card_data.get("num_processo", f"desconhecido_{idx}")
        print(f"\n  [{idx + 1}/{len(cards)}] Processando: {num_processo}")

        intimacao = {
            "numero": numero_global,
            "numero_processo": num_processo,
        }

        # Extrair metadados do sumário
        sumario = card_data.get("sumario", "")
        if sumario:
            extrair_campos_do_bloco(sumario, intimacao)
        else:
            extrair_campos_do_bloco(card_data.get("card_text", ""), intimacao)

        # Inteiro teor do card-content (sem aside)
        inteiro_teor_raw = card_data.get("inteiro_teor", "")
        if inteiro_teor_raw and len(inteiro_teor_raw) > 50:
            inteiro_teor = _limpar_teor(inteiro_teor_raw)
            if inteiro_teor and len(inteiro_teor) > 50:
                intimacao["inteiro_teor"] = inteiro_teor
                print(f"    Inteiro teor: {len(inteiro_teor)} caracteres")
            else:
                print(f"    Inteiro teor após limpeza ficou vazio")
        else:
            # Fallback: tentar extrair do card_text completo
            card_text = card_data.get("card_text", "")
            inteiro_teor = extrair_inteiro_teor_do_texto(card_text, num_processo)
            if inteiro_teor:
                intimacao["inteiro_teor"] = inteiro_teor
                print(f"    Inteiro teor (fallback texto): {len(inteiro_teor)} caracteres")
            else:
                print(f"    Inteiro teor não encontrado")

        intimacoes.append(intimacao)

        # Screenshot do card
        try:
            salvar_screenshot(driver, f"card_processo_{idx + 1}")
        except:
            pass

    if not intimacoes:
        print("  Nenhuma intimação extraída dos cards. Tentando fallback...")
        return extrair_intimacoes_fallback(driver, body_text)

    body_text = driver.find_element(By.TAG_NAME, "body").text.strip()
    return intimacoes, body_text


def extrair_inteiro_teor_do_texto(card_text, num_processo):
    """Extrai o inteiro teor de um bloco de texto do card, removendo metadados."""
    if not card_text or len(card_text) < 100:
        return None

    # Procurar o início do inteiro teor (após "Inteiro teor: Clique aqui" ou após os advogados)
    markers = [
        r'(?:Advogado\(s\)\n(?:.*\n)*?)((?:PROCEDIMENTO|EDITAL|ATO ORDIN|DESPACHO|SENTENÇA|DECISÃO|CERTIDÃO|MANDADO|FAZ SABER).+)',
        r'Inteiro teor:\s*Clique aqui\n(.+)',
        r'(?:OAB\s+\w{2}-?\d+)\n(.+)',
    ]
    for pattern in markers:
        m = re.search(pattern, card_text, re.DOTALL)
        if m:
            resultado = _limpar_teor(m.group(1).strip())
            if resultado and len(resultado) > 100:
                return resultado

    return None


def extrair_metadados_card(driver, link_processo, intimacao):
    """
    Extrai metadados do card de intimação no lado esquerdo da página.
    Navega pelo DOM a partir do link do processo para encontrar o card pai.
    """
    try:
        # Buscar o container/card pai que contém os metadados
        card_text = driver.execute_script("""
            let el = arguments[0];
            // Subir no DOM até encontrar o container do card
            let parent = el.parentElement;
            for (let i = 0; i < 10; i++) {
                if (!parent) break;
                let text = parent.innerText || '';
                // O card tem "Órgão:", "Data de disponibilização:", etc.
                if (text.includes('Órgão:') && text.includes('Data de disponibilização:')) {
                    return text;
                }
                parent = parent.parentElement;
            }
            return '';
        """, link_processo)

        if card_text:
            extrair_campos_do_bloco(card_text, intimacao)

    except Exception as e:
        print(f"    Erro ao extrair metadados do card: {e}")


def clicar_menu_tres_pontos(driver):
    """
    Em telas menores, os botões Imprimir/Copiar ficam escondidos no menu ⋮.
    Clica nesse menu para revelar as opções.
    """
    # Tentar encontrar o botão ⋮ (more_vert) via JavaScript
    abriu = driver.execute_script("""
        // Procurar mat-icon com "more_vert" ou botão com ⋮
        let icons = document.querySelectorAll('mat-icon');
        for (let icon of icons) {
            if (icon.textContent.trim() === 'more_vert') {
                let btn = icon.closest('button') || icon.parentElement;
                if (btn) { btn.click(); return true; }
            }
        }
        // Fallback: procurar por aria-label ou class
        let btns = document.querySelectorAll('button[aria-label*="more"], button[aria-label*="mais"], button[aria-label*="menu"], button[aria-label*="opções"]');
        if (btns.length > 0) { btns[0].click(); return true; }
        return false;
    """)

    if abriu:
        time.sleep(1)
        print("    Menu ⋮ aberto com sucesso")
    return abriu


def aguardar_painel_atualizar(driver, num_processo, data_disp=None, orgao=None, timeout=10):
    """
    Aguarda o painel de detalhes exibir o conteúdo do card clicado.
    O painel tem botão COPIAR; verifica se o container do Copiar contém orgao/data.
    """
    if not orgao and not data_disp:
        time.sleep(2)  # Fallback: espera fixa
        return
    for _ in range(timeout):
        try:
            ok = driver.execute_script(r"""
                var numProc = arguments[0], orgao = (arguments[1]||'').trim(), data = (arguments[2]||'').trim();
                var btns = document.querySelectorAll('button, [role="button"]');
                for (var i = 0; i < btns.length; i++) {
                    if ((btns[i].innerText||'').toUpperCase().indexOf('COPIAR') === -1) continue;
                    var p = btns[i].parentElement;
                    for (var j = 0; j < 15; j++) {
                        if (!p) break;
                        var t = (p.innerText||'');
                        if (t.indexOf(numProc) !== -1 && t.length > 200) {
                            if (orgao && t.indexOf(orgao) !== -1) return true;
                            if (data && t.indexOf(data) !== -1) return true;
                        }
                        p = p.parentElement;
                    }
                }
                return false;
            """, num_processo, orgao or "", data_disp or "")
            if ok:
                time.sleep(1)
                return
        except Exception:
            pass
        time.sleep(0.5)


def _limpar_teor(texto):
    """Remove linhas de UI (botões, ícones Material) e linhas que são nomes de tribunais."""
    ignorar_exatos = {
        "IMPRIMIR", "COPIAR", "COPIAR SEM FORMATAÇÃO", "COPIAR SEM FORMATACAO",
        "CLOSE", "PRINT", "CONTENT_COPY", "CONTENT_PASTE", "MORE_VERT", "IMPR", ""
    }
    import re as _re
    # Padrão de sigla de tribunal no início da linha (ex: "TJSP - Tribunal de Justiça de São Paulo")
    tribunal_re = _re.compile(
        r'^(TJ[A-Z]{2}|TRF\s*\d|TRT\s*\d{1,2}|STF|STJ|TST|TSE|STM|CNJ|TST)\b', _re.IGNORECASE
    )
    linhas = texto.split('\n')
    texto_limpo = []
    for linha in linhas:
        ls = linha.strip()
        if ls.upper() in ignorar_exatos:
            continue
        if ls.lower() in ("print", "content_copy", "content_paste", "more_vert", "close"):
            continue
        if tribunal_re.match(ls):
            continue
        texto_limpo.append(ls)
    return '\n'.join(texto_limpo).strip()


def _tem_muitas_siglas_tribunal(texto):
    """Retorna True se o texto parece ser uma lista de tribunais (nav sidebar)."""
    import re as _re
    tribunal_re = _re.compile(
        r'^(TJ[A-Z]{2}|TRF\s*\d|TRT\s*\d{1,2}|STF|STJ|TST|TSE|STM|CNJ)\b', _re.IGNORECASE
    )
    linhas = texto.split('\n')
    total_tribunal = sum(1 for l in linhas if tribunal_re.match(l.strip()))
    return total_tribunal > 5


def extrair_inteiro_teor_painel(driver, num_processo="", intimacao=None):
    """
    Extrai o inteiro teor do painel de detalhes (lado direito da página).
    Ancora a busca no número do processo atual para garantir que extrai
    o conteúdo CORRETO mesmo quando múltiplos painéis estão visíveis.
    Usa orgao/data da intimacao para identificar o painel correto.
    """
    orgao = (intimacao or {}).get("orgao") or ""
    data_disp = (intimacao or {}).get("data_disponibilizacao") or ""

    # Estratégia 0a: Painel que contém botão COPIAR + num_processo + orgao/data
    # O painel de detalhe tem o botão Copiar; os cards da lista não têm
    teor0a = driver.execute_script(r"""
        var numProc = arguments[0];
        var orgaoBusca = (arguments[1] || '').trim();
        var dataBusca = (arguments[2] || '').trim();
        if (!numProc) return null;

        var copiarBtns = document.querySelectorAll('button, [role="button"], a');
        for (var i = 0; i < copiarBtns.length; i++) {
            var btn = copiarBtns[i];
            if ((btn.innerText || '').toUpperCase().indexOf('COPIAR') === -1) continue;
            var parent = btn;
            for (var j = 0; j < 20; j++) {
                parent = parent.parentElement;
                if (!parent || parent.tagName === 'BODY') break;
                var text = (parent.innerText || '').trim();
                if (text.indexOf(numProc) !== -1 && text.length > 300) {
                    if (orgaoBusca && text.indexOf(orgaoBusca) !== -1) return text;
                    if (dataBusca && text.indexOf(dataBusca) !== -1) return text;
                    if (!orgaoBusca && !dataBusca) return text;
                }
            }
        }
        return null;
    """, num_processo, orgao, data_disp)

    if teor0a and len(teor0a) > 100:
        resultado = _limpar_teor(teor0a)
        if resultado and len(resultado) > 100:
            processos = re.findall(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', resultado)
            if num_processo and processos and (processos[0] == num_processo or num_processo in processos):
                print(f"    Inteiro teor extraído via painel Copiar ({len(resultado)} chars)")
                return resultado

    # Estratégia 0b: Painel expandido (mat-expansion-panel)
    teor0 = driver.execute_script(r"""
        var numProc = arguments[0];
        var orgaoBusca = (arguments[1] || '').trim();
        var dataBusca = (arguments[2] || '').trim();
        if (!numProc) return null;

        var expanded = document.querySelectorAll('.mat-expansion-panel-expanded, mat-expansion-panel[aria-expanded="true"]');
        for (var i = 0; i < expanded.length; i++) {
            var el = expanded[i];
            var text = (el.innerText || '').trim();
            if (text.indexOf(numProc) !== -1 && text.length > 200) {
                if (orgaoBusca && text.indexOf(orgaoBusca) !== -1) return text;
                if (dataBusca && text.indexOf(dataBusca) !== -1) return text;
                if (!orgaoBusca && !dataBusca) return text;
            }
        }
        return null;
    """, num_processo, orgao, data_disp)

    if teor0 and len(teor0) > 100:
        resultado = _limpar_teor(teor0)
        if resultado and len(resultado) > 100:
            processos = re.findall(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', resultado)
            if num_processo and processos and (processos[0] == num_processo or num_processo in processos):
                print(f"    Inteiro teor extraído via painel expandido ({len(resultado)} chars)")
                return resultado

    # Estratégia 1: Encontrar o ÚLTIMO <a> com o número do processo no DOM.
    # O card-list vem primeiro no DOM, o painel de detalhe vem depois.
    # O último link é o do painel de detalhe. Subir até achar o menor
    # container que tenha metadados (Órgão) e no máximo 2 processos únicos.
    teor = driver.execute_script(r"""
        var numProc = arguments[0];
        if (!numProc) return null;

        var tribunalRe = /^(TJ[A-Z]{2,4}|TRF\s*\d|TRT\s*\d{1,2}|TRE-[A-Z]{2}|STF|STJ|TST|TSE|STM|CNJ)\s/i;

        function contarSiglasTribunal(text) {
            var linhas = text.split('\n');
            var cnt = 0;
            for (var i = 0; i < linhas.length; i++) {
                if (tribunalRe.test(linhas[i].trim())) cnt++;
            }
            return cnt;
        }

        function contarProcessosUnicos(text) {
            var matches = text.match(/\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}/g) || [];
            var unique = {};
            for (var k = 0; k < matches.length; k++) unique[matches[k]] = true;
            return Object.keys(unique).length;
        }

        // Encontrar links no PAINEL de detalhe (não nos cards da lista)
        // O painel tem botão COPIAR; subir do link que está no mesmo container que COPIAR
        var orgaoBusca = (arguments[1] || '').trim();
        var dataBusca = (arguments[2] || '').trim();

        var allLinks = document.querySelectorAll('a');
        var detailLink = null;
        for (var i = 0; i < allLinks.length; i++) {
            if ((allLinks[i].innerText || '').indexOf(numProc) !== -1) {
                detailLink = allLinks[i];
            }
        }

        if (!detailLink) return null;

        var parent = detailLink.parentElement;
        var bestPanel = null;

        for (var j = 0; j < 15; j++) {
            if (!parent || parent.tagName === 'BODY') break;
            var text = (parent.innerText || '');

            if (text.length > 500 && text.indexOf('Órgão') !== -1 && text.indexOf(numProc) !== -1) {
                if (contarProcessosUnicos(text) <= 2 && contarSiglasTribunal(text) < 5) {
                    var matchOrgao = !orgaoBusca || text.indexOf(orgaoBusca) !== -1;
                    var matchData = !dataBusca || text.indexOf(dataBusca) !== -1;
                    if (matchOrgao && matchData) {
                        if (!bestPanel || text.length < (bestPanel.innerText || '').length) {
                            bestPanel = parent;
                        }
                    }
                }
            }
            parent = parent.parentElement;
        }

        if (bestPanel) return bestPanel.innerText;
        return null;
    """, num_processo, orgao, data_disp)

    if teor and len(teor) > 100:
        resultado = _limpar_teor(teor)
        if resultado and len(resultado) > 100:
            # Validar: o conteúdo deve pertencer ao processo correto
            processos_no_texto = re.findall(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', resultado)
            if num_processo and processos_no_texto:
                # Se o primeiro processo mencionado NÃO é o atual, é conteúdo errado
                if processos_no_texto[0] != num_processo and num_processo not in processos_no_texto:
                    print(f"    REJEITADO: conteúdo pertence a {processos_no_texto[0]}, não a {num_processo}")
                else:
                    print(f"    Inteiro teor extraído via painel detalhe ({len(resultado)} chars)")
                    return resultado
            else:
                print(f"    Inteiro teor extraído via painel detalhe ({len(resultado)} chars)")
                return resultado

    # Estratégia 2: buscar o maior bloco "folha" com keyword jurídica
    teor2 = driver.execute_script(r"""
        var keywords = ['ATO ORDINATÓRIO', 'DESPACHO', 'SENTENÇA', 'DECISÃO',
                        'EDITAL', 'CERTIDÃO', 'MANDADO', 'PROCEDIMENTO COMUM',
                        'PROCEDIMENTO DO JUIZADO', 'ADV:', 'REQUERENTE',
                        'REQUERIDO', 'FAZ SABER', 'INTIME-SE'];

        var tribunalRe = /^(TJ[A-Z]{2,4}|TRF\s*\d|TRT\s*\d{1,2}|TRE-[A-Z]{2}|STF|STJ|TST|TSE|STM|CNJ)\s/i;

        function temMuitasSiglas(text) {
            var linhas = text.split('\n');
            var cnt = 0;
            for (var i = 0; i < linhas.length; i++) {
                if (tribunalRe.test(linhas[i].trim())) cnt++;
            }
            return cnt > 5;
        }

        var allEls = document.querySelectorAll('div, section, article');
        var candidatos = [];

        for (var i = 0; i < allEls.length; i++) {
            var el = allEls[i];
            var text = (el.innerText || '').trim();
            if (text.length < 200 || text.length > 60000) continue;

            var upper = text.toUpperCase();
            var hasKeyword = keywords.some(function(kw) {
                return upper.indexOf(kw) !== -1;
            });
            if (!hasKeyword) continue;
            if (temMuitasSiglas(text)) continue;

            // Verificar se é "folha" — nenhum filho com 80%+ do texto
            var children = el.querySelectorAll('div, section, article');
            var isLeaf = true;
            for (var j = 0; j < children.length; j++) {
                var ct = (children[j].innerText || '').trim();
                if (ct.length > text.length * 0.8 && ct.length > 200) {
                    isLeaf = false; break;
                }
            }
            if (isLeaf) {
                candidatos.push({text: text, len: text.length});
            }
        }

        if (candidatos.length === 0) return null;

        // Pegar o MAIOR bloco folha (conteúdo mais completo)
        candidatos.sort(function(a, b) { return b.len - a.len; });
        return candidatos[0].text;
    """)

    if teor2 and len(teor2) > 100:
        resultado = _limpar_teor(teor2)
        if resultado and len(resultado) > 100:
            print(f"    Inteiro teor extraído via DOM folha ({len(resultado)} chars)")
            return resultado

    # Estratégia 3: fallback via body text split por processo
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        blocos = re.split(r'(?=Processo\s+\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})', body_text)
        for bloco in blocos:
            bloco = bloco.strip()
            if re.match(r'Processo\s+\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', bloco):
                if len(bloco) > 200 and not _tem_muitas_siglas_tribunal(bloco):
                    resultado = _limpar_teor(bloco)
                    if resultado and len(resultado) > 100:
                        print(f"    Inteiro teor extraído via body text ({len(resultado)} chars)")
                        return resultado
    except:
        pass

    return None


def extrair_intimacoes_fallback(driver, body_text):
    """
    Fallback: extrai intimações via parsing de texto quando não encontra links clicáveis.
    """
    intimacoes = []
    pattern = r'Processo\s+(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})'
    matches = list(re.finditer(pattern, body_text))

    processos_unicos = {}
    for m in matches:
        num = m.group(1)
        if num not in processos_unicos:
            processos_unicos[num] = []
        processos_unicos[num].append(m.start())

    todos_inicios = sorted([p for procs in processos_unicos.values() for p in procs])

    for idx, (num_processo, posicoes) in enumerate(processos_unicos.items()):
        inicio = posicoes[0]
        idx_atual = todos_inicios.index(inicio)
        fim = todos_inicios[idx_atual + 1] if idx_atual + 1 < len(todos_inicios) else len(body_text)
        bloco = body_text[inicio:fim].strip()

        intimacao = {"numero": idx + 1, "numero_processo": num_processo}
        extrair_campos_do_bloco(bloco, intimacao)

        if len(posicoes) > 1:
            inicio_teor = posicoes[1]
            idx_teor = todos_inicios.index(inicio_teor)
            fim_teor = todos_inicios[idx_teor + 1] if idx_teor + 1 < len(todos_inicios) else len(body_text)
            intimacao["inteiro_teor"] = body_text[inicio_teor:fim_teor].strip()

        intimacoes.append(intimacao)

    return intimacoes, body_text


def extrair_campos_do_bloco(bloco, intimacao):
    """
    Extrai campos estruturados de um bloco de texto de intimação.
    Campos: órgão, data_disponibilização, tipo_comunicação, meio, partes, advogados.
    """
    # Órgão
    match = re.search(r'Órgão:\s*(.+?)(?:\n|$)', bloco)
    if match:
        intimacao["orgao"] = match.group(1).strip()

    # Data de disponibilização
    match = re.search(r'Data de disponibilização:\s*(\d{2}/\d{2}/\d{4})', bloco)
    if match:
        intimacao["data_disponibilizacao"] = match.group(1)

    # Tipo de comunicação
    match = re.search(r'Tipo de comunicação:\s*(.+?)(?:\n|$)', bloco)
    if match:
        intimacao["tipo_comunicacao"] = match.group(1).strip()

    # Meio
    match = re.search(r'Meio:\s*(.+?)(?:\n|$)', bloco)
    if match:
        intimacao["meio"] = match.group(1).strip()

    # Partes - texto entre "Parte(s)" e "Advogado(s)"
    match_partes = re.search(r'Parte\(s\)\n(.+?)(?=Advogado\(s\)|$)', bloco, re.DOTALL)
    if match_partes:
        partes_texto = match_partes.group(1).strip()
        partes = [p.strip() for p in partes_texto.split('\n') if p.strip()]
        intimacao["partes"] = partes

    # Advogados - texto após "Advogado(s)" até próxima seção ou linhas longas (que são conteúdo)
    match_advs = re.search(r'Advogado\(s\)\n(.+?)(?=Processo|Inteiro teor|$)', bloco, re.DOTALL)
    if match_advs:
        advs_texto = match_advs.group(1).strip()
        advogados = []
        for linha in advs_texto.split('\n'):
            linha = linha.strip()
            if not linha:
                continue
            # Advogados são nomes curtos (< 200 chars) com formato "NOME - OAB XX-NNNNNN"
            # Linhas longas são conteúdo de inteiro teor que vazou para cá
            if len(linha) > 200:
                break
            advogados.append(linha)
        if advogados:
            intimacao["advogados"] = advogados


def obter_processos_existentes():
    """Retorna set de chaves únicas (numero_processo, tribunal, data) já salvas em todos os JSONs."""
    existentes = set()
    if not os.path.exists(OUTPUT_DIR):
        return existentes
    for f in os.listdir(OUTPUT_DIR):
        if f.endswith(".json") and f.startswith("intimacoes_"):
            try:
                with open(os.path.join(OUTPUT_DIR, f), "r", encoding="utf-8") as fp:
                    dados = json.load(fp)
                for intim in dados.get("intimacoes", []):
                    chave = (
                        intim.get("numero_processo", ""),
                        intim.get("tribunal", ""),
                        intim.get("data_disponibilizacao", "")
                    )
                    existentes.add(chave)
            except:
                pass
    return existentes


def salvar_resultados(intimacoes, oab, data_inicio, data_fim, body_text="", uf_oab=""):
    """Salva os resultados em JSON e CSV."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uf_parte = f"_UF{uf_oab.upper()}" if uf_oab else ""
    nome_base = f"intimacoes_OAB{oab}{uf_parte}_{data_inicio}_{data_fim}_{timestamp}"

    # Salvar JSON
    json_path = os.path.join(OUTPUT_DIR, f"{nome_base}.json")
    consulta_info = {
        "oab": oab,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "data_extracao": datetime.now().isoformat(),
        "total_intimacoes": len(intimacoes)
    }
    if uf_oab:
        consulta_info["uf_oab"] = uf_oab.upper()
    dados_export = {
        "consulta": consulta_info,
        "intimacoes": intimacoes
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dados_export, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON salvo em: {json_path}")

    # Salvar CSV
    if intimacoes:
        csv_path = os.path.join(OUTPUT_DIR, f"{nome_base}.csv")
        todas_chaves = set()
        for intimacao in intimacoes:
            todas_chaves.update(intimacao.keys())
        todas_chaves = sorted(todas_chaves)

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=todas_chaves)
            writer.writeheader()
            for intimacao in intimacoes:
                writer.writerow(intimacao)
        print(f"  CSV salvo em: {csv_path}")

    # Salvar texto bruto da página (para debug/referência)
    if body_text:
        txt_path = os.path.join(OUTPUT_DIR, f"{nome_base}_raw.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(body_text)
        print(f"  Texto bruto salvo em: {txt_path}")

    return json_path


def salvar_screenshot(driver, nome: str):
    """Salva screenshot para debug."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{nome}.png")
    driver.save_screenshot(path)
    print(f"  Screenshot salvo: {path}")
    return path


def obter_total_paginas(driver):
    """Detecta o número total de páginas na paginação."""
    try:
        # Procurar botões de paginação numéricos (1, 2, 3, 4, 5...)
        total = driver.execute_script(r"""
            // Procurar links/botões de paginação com números
            var pagBtns = document.querySelectorAll(
                'a[aria-label*="page"], button[aria-label*="page"], ' +
                'a[aria-label*="página"], button[aria-label*="página"], ' +
                '.pagination a, .pagination button, ' +
                'nav a, nav button, ' +
                'ul.pagination li a, ' +
                '[class*="pagina"] a, [class*="pagina"] button'
            );
            var maxPage = 1;
            // Fallback genérico: buscar qualquer botão/link com número puro
            var allClickables = document.querySelectorAll('a, button');
            for (var i = 0; i < allClickables.length; i++) {
                var txt = (allClickables[i].textContent || '').trim();
                // Pular textos que não são apenas números
                if (/^\d+$/.test(txt)) {
                    var n = parseInt(txt);
                    // Verificar se está próximo de outros números (contexto de paginação)
                    var parent = allClickables[i].parentElement;
                    if (parent) {
                        var siblings = parent.querySelectorAll('a, button');
                        var numCount = 0;
                        for (var j = 0; j < siblings.length; j++) {
                            if (/^\d+$/.test((siblings[j].textContent || '').trim())) numCount++;
                        }
                        // Se há pelo menos 2 números irmãos, é paginação
                        if (numCount >= 2 && n > maxPage) {
                            maxPage = n;
                        }
                    }
                }
            }
            return maxPage;
        """)
        return total if total else 1
    except:
        return 1


def ir_para_pagina(driver, pagina):
    """Navega para uma página específica da paginação."""
    try:
        clicou = driver.execute_script(r"""
            var targetPage = arguments[0].toString();
            // Procurar botão/link com o número da página
            var allClickables = document.querySelectorAll('a, button');
            for (var i = 0; i < allClickables.length; i++) {
                var txt = (allClickables[i].textContent || '').trim();
                if (txt === targetPage) {
                    // Verificar se está num contexto de paginação
                    var parent = allClickables[i].parentElement;
                    if (parent) {
                        var siblings = parent.querySelectorAll('a, button');
                        var numCount = 0;
                        for (var j = 0; j < siblings.length; j++) {
                            if (/^\d+$/.test((siblings[j].textContent || '').trim())) numCount++;
                        }
                        if (numCount >= 2) {
                            allClickables[i].click();
                            return true;
                        }
                    }
                }
            }
            return false;
        """, pagina)

        if clicou:
            time.sleep(3)
            # Aguardar spinner/loading
            try:
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, ".spinner, .loading, mat-spinner"))
                )
            except:
                pass
            time.sleep(2)
        return clicou
    except:
        return False


def clicar_proxima_pagina(driver):
    """Clica no botão de próxima página (>)."""
    try:
        clicou = driver.execute_script(r"""
            // Procurar botão ">" ou "next" ou "próxima"
            var btns = document.querySelectorAll('a, button');
            for (var i = 0; i < btns.length; i++) {
                var txt = (btns[i].textContent || '').trim();
                var label = (btns[i].getAttribute('aria-label') || '').toLowerCase();
                if (txt === '>' || txt === '›' || txt === '→' ||
                    label.includes('next') || label.includes('próxima') || label.includes('proxima')) {
                    // Verificar se não está desabilitado
                    if (!btns[i].disabled && !btns[i].classList.contains('disabled')) {
                        btns[i].click();
                        return true;
                    }
                }
            }
            // Fallback: procurar mat-icon com chevron_right ou navigate_next
            var icons = document.querySelectorAll('mat-icon');
            for (var j = 0; j < icons.length; j++) {
                var iconTxt = (icons[j].textContent || '').trim();
                if (iconTxt === 'chevron_right' || iconTxt === 'navigate_next') {
                    var btn = icons[j].closest('button') || icons[j].closest('a') || icons[j].parentElement;
                    if (btn && !btn.disabled && !btn.classList.contains('disabled')) {
                        btn.click();
                        return true;
                    }
                }
            }
            return false;
        """)

        if clicou:
            time.sleep(3)
            try:
                WebDriverWait(driver, 5).until(
                    EC.invisibility_of_element_located((By.CSS_SELECTOR, ".spinner, .loading, mat-spinner"))
                )
            except:
                pass
            time.sleep(2)
        return clicou
    except:
        return False


def obter_pagina_atual(driver):
    """Detecta o número da página ativa atualmente."""
    try:
        return driver.execute_script(r"""
            // Procurar elemento ativo/selecionado na paginação
            var actives = document.querySelectorAll(
                '[aria-current="page"], .active a, .active button, ' +
                'a.active, button.active, ' +
                '[class*="current"], [class*="selected"]'
            );
            for (var i = 0; i < actives.length; i++) {
                var txt = (actives[i].textContent || '').trim();
                if (/^\d+$/.test(txt)) return parseInt(txt);
            }
            // Fallback: procurar botão com estilo diferente (bold, background, etc.)
            var allBtns = document.querySelectorAll('a, button');
            for (var j = 0; j < allBtns.length; j++) {
                var t = (allBtns[j].textContent || '').trim();
                if (/^\d+$/.test(t)) {
                    var style = window.getComputedStyle(allBtns[j]);
                    if (style.fontWeight >= 700 || style.backgroundColor !== 'rgba(0, 0, 0, 0)') {
                        return parseInt(t);
                    }
                }
            }
            return 1;
        """)
    except:
        return 1


def detectar_ultima_pagina(driver):
    """
    Tenta detectar o número da última página clicando no botão >| (última página)
    e lendo o número, depois volta para a página 1.
    Se não encontrar, retorna o maior número visível na paginação.
    """
    try:
        # Tentar encontrar botão de última página (>|)
        tem_ultima = driver.execute_script(r"""
            var btns = document.querySelectorAll('a, button');
            for (var i = 0; i < btns.length; i++) {
                var txt = (btns[i].textContent || '').trim();
                var label = (btns[i].getAttribute('aria-label') || '').toLowerCase();
                if (txt === '>|' || txt === '»' || txt === '>>|' ||
                    label.includes('last') || label.includes('última') || label.includes('ultima')) {
                    if (!btns[i].disabled && !btns[i].classList.contains('disabled')) {
                        btns[i].click();
                        return true;
                    }
                }
            }
            // Fallback: mat-icon last_page
            var icons = document.querySelectorAll('mat-icon');
            for (var j = 0; j < icons.length; j++) {
                var iconTxt = (icons[j].textContent || '').trim();
                if (iconTxt === 'last_page') {
                    var btn = icons[j].closest('button') || icons[j].closest('a') || icons[j].parentElement;
                    if (btn && !btn.disabled) { btn.click(); return true; }
                }
            }
            return false;
        """)

        if tem_ultima:
            time.sleep(3)
            # Ler o maior número visível agora
            total = obter_total_paginas(driver)
            # Voltar para a primeira página
            ir_para_pagina(driver, 1)
            return total
    except:
        pass

    return obter_total_paginas(driver)


def extrair_todas_paginas(driver, inicio_num=1):
    """
    Extrai intimações de TODAS as páginas, navegando pela paginação.
    Usa estratégia de clicar "próxima página" até não haver mais próxima.
    Retorna lista completa de intimações e body_text da última página.
    inicio_num: número inicial para a numeração contínua das intimações.
    """
    todas_intimacoes = []
    body_text = ""

    # Detectar total de páginas
    total_paginas = detectar_ultima_pagina(driver)
    print(f"\n  Paginação detectada: {total_paginas} página(s)")

    pagina_atual = 1
    max_paginas = 100  # Segurança para evitar loop infinito

    while pagina_atual <= max_paginas:
        print(f"\n{'─'*40}")
        print(f"  PÁGINA {pagina_atual}" + (f" de {total_paginas}" if total_paginas > 1 else ""))
        print(f"{'─'*40}")

        if pagina_atual > 1:
            salvar_screenshot(driver, f"pagina_{pagina_atual}")

        # Extrair intimações desta página
        resultado = extrair_intimacoes(driver, inicio_num=inicio_num + len(todas_intimacoes))
        if isinstance(resultado, tuple):
            intimacoes_pagina, body_text = resultado
        else:
            intimacoes_pagina = resultado
            body_text = driver.find_element(By.TAG_NAME, "body").text.strip()

        print(f"  → {len(intimacoes_pagina)} intimação(ões) nesta página")
        todas_intimacoes.extend(intimacoes_pagina)

        # Se não há mais páginas ou é a última, parar
        if total_paginas <= 1 or pagina_atual >= total_paginas:
            # Tentar clicar próxima mesmo assim (total_paginas pode estar errado)
            if total_paginas > 1:
                break
            # Para total_paginas == 1, verificar se existe botão próxima
            if not clicar_proxima_pagina(driver):
                break
            # Se chegou aqui, havia mais páginas do que detectado
            pagina_atual += 1
            total_paginas = max(total_paginas, pagina_atual + 1)
            continue

        # Tentar ir para a próxima página
        proxima = pagina_atual + 1
        print(f"  Navegando para página {proxima}...")

        if not ir_para_pagina(driver, proxima):
            if not clicar_proxima_pagina(driver):
                print(f"  ⚠ Não conseguiu navegar para página {proxima}. Parando.")
                break

        pagina_atual += 1

    print(f"\n  Total geral: {len(todas_intimacoes)} intimação(ões) em {pagina_atual} página(s)")
    return todas_intimacoes, body_text


def detectar_abas_tribunais(driver):
    """
    Detecta todas as abas de tribunais na página de resultados do DJEN.
    Retorna lista de dicts: [{nome: 'TJSP', quantidade: 2, elemento: WebElement}, ...]
    """
    abas = []

    # Seletores possíveis para as tabs de tribunal
    seletores_tab = [
        "mat-tab-header .mat-tab-label",
        ".mat-tab-label",
        ".mat-mdc-tab",
        "mat-tab-header button[role='tab']",
        "[role='tab']",
        ".mat-tab-labels .mat-tab-label",
        ".mat-tab-labels div[role='tab']",
        "div[role='tablist'] div[role='tab']",
        "div[role='tablist'] button[role='tab']",
        ".mdc-tab",
    ]

    elementos_tab = []
    for seletor in seletores_tab:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, seletor)
            if els and len(els) > 0:
                elementos_tab = els
                print(f"  Abas de tribunal encontradas via: {seletor} ({len(els)} aba(s))")
                break
        except:
            continue

    if not elementos_tab:
        print("  Nenhuma aba de tribunal detectada (apenas 1 tribunal)")
        return []

    for el in elementos_tab:
        try:
            texto = el.text.strip()
            if not texto:
                continue
            # Extrair nome do tribunal e quantidade (ex: "TJSP 2" ou "TRF2 1")
            partes = texto.split()
            nome = partes[0] if partes else texto
            qtd = 0
            if len(partes) > 1:
                try:
                    qtd = int(partes[-1])
                except:
                    pass
            abas.append({"nome": nome, "quantidade": qtd, "elemento": el, "texto": texto})
        except:
            continue

    return abas


def clicar_aba_tribunal(driver, aba):
    """Clica em uma aba de tribunal e aguarda carregamento."""
    nome = aba.get("nome", "?")
    print(f"\n  Clicando na aba do tribunal: {nome}...")

    try:
        el = aba["elemento"]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
        time.sleep(0.5)

        # Tentar click normal, depois JS
        try:
            el.click()
        except:
            driver.execute_script("arguments[0].click();", el)

        # Aguardar carregamento após trocar de aba
        time.sleep(2)

        # Aguardar spinner desaparecer
        try:
            WebDriverWait(driver, 10).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".spinner, .loading, mat-spinner, .mat-progress-spinner"))
            )
        except:
            pass

        time.sleep(1)
        print(f"  ✓ Aba {nome} ativa")
        return True
    except Exception as e:
        print(f"  ⚠ Erro ao clicar aba {nome}: {e}")
        return False


def consultar_intimacoes(oab: str, data_inicio: str, data_fim: str, headless: bool = False, uf_oab: str = ""):
    """
    Função principal: consulta intimações no DJEN por OAB e período.
    Detecta e navega por TODAS as abas de tribunais (TJSP, TRF2, etc.).

    Args:
        oab: Número da OAB (ex: "165230")
        data_inicio: Data início formato YYYY-MM-DD (ex: "2026-01-20")
        data_fim: Data fim formato YYYY-MM-DD (ex: "2026-01-20")
        headless: Se True, roda sem abrir janela do navegador
        uf_oab: UF da OAB (ex: "SP", "RJ", "PI"). Vazio = todas.
    """
    url = montar_url(oab, data_inicio, data_fim, uf_oab)
    print(f"\n{'='*60}")
    print(f"  JurisRapido - Consulta de Intimações")
    print(f"{'='*60}")
    print(f"  OAB: {oab}")
    if uf_oab:
        print(f"  UF da OAB: {uf_oab.upper()}")
    print(f"  Período: {data_inicio} a {data_fim}")
    print(f"  URL: {url}")
    print(f"  Headless: {headless}")
    print(f"{'='*60}\n")

    driver = None
    try:
        print("[1/5] Criando driver do Chrome...")
        driver = criar_driver(headless=headless)

        print("[2/5] Acessando página de consulta...")
        driver.get(url)

        wait = WebDriverWait(driver, TIMEOUT)

        print("[3/5] Aguardando carregamento dos resultados...")
        aguardar_carregamento(driver, wait)

        salvar_screenshot(driver, f"pagina_carregada_OAB{oab}")

        # Verificar se há resultados
        body_text = driver.find_element(By.TAG_NAME, "body").text.strip()
        print(f"\n  Texto da página ({len(body_text)} caracteres):")
        print(f"  {body_text[:500]}...")

        if "Nenhum resultado" in body_text or "Nenhuma comunicação" in body_text:
            print("\n  ⚠ Nenhuma intimação encontrada para os parâmetros informados.")
            return []

        # Detectar abas de tribunais
        print("\n[4/5] Detectando tribunais disponíveis...")
        abas_tribunais = detectar_abas_tribunais(driver)

        todas_intimacoes = []
        body_text_final = body_text

        if not abas_tribunais or len(abas_tribunais) <= 1:
            # Apenas 1 tribunal (ou sem abas) - extrair normalmente
            print("  Apenas 1 tribunal detectado. Extraindo...")
            intimacoes, body_text_final = extrair_todas_paginas(driver)
            todas_intimacoes.extend(intimacoes)
        else:
            # Múltiplos tribunais - iterar por cada aba
            print(f"  {len(abas_tribunais)} tribunal(is) detectado(s): {', '.join(a['nome'] + ' (' + str(a['quantidade']) + ')' for a in abas_tribunais)}")

            for i, aba in enumerate(abas_tribunais):
                nome_tribunal = aba["nome"]
                qtd = aba["quantidade"]

                print(f"\n{'═'*50}")
                print(f"  TRIBUNAL {i+1}/{len(abas_tribunais)}: {nome_tribunal} ({qtd} intimação(ões))")
                print(f"{'═'*50}")

                # Clicar na aba do tribunal
                if i > 0:  # Primeira aba já está ativa
                    if not clicar_aba_tribunal(driver, aba):
                        print(f"  ⚠ Pulando tribunal {nome_tribunal} - não foi possível acessar")
                        continue

                salvar_screenshot(driver, f"tribunal_{nome_tribunal}_OAB{oab}")

                # Extrair intimações deste tribunal (todas as páginas)
                inicio = len(todas_intimacoes) + 1
                intimacoes_tribunal, bt = extrair_todas_paginas(driver, inicio_num=inicio)

                # Adicionar nome do tribunal a cada intimação
                for intim in intimacoes_tribunal:
                    intim["tribunal"] = nome_tribunal

                print(f"  → {len(intimacoes_tribunal)} intimação(ões) extraída(s) do {nome_tribunal}")
                todas_intimacoes.extend(intimacoes_tribunal)
                body_text_final = bt

        if todas_intimacoes:
            print(f"\n  Total de intimações encontradas: {len(todas_intimacoes)}")
            for i, intimacao in enumerate(todas_intimacoes):
                print(f"\n  --- Intimação {i + 1} ---")
                for chave, valor in intimacao.items():
                    if chave in ("conteudo", "inteiro_teor"):
                        preview = str(valor)[:200]
                        print(f"    {chave}: {preview}...")
                    else:
                        print(f"    {chave}: {valor}")
        else:
            print("\n  Nenhuma intimação pôde ser extraída dos resultados.")
            return []

        # Deduplicar contra resultados já salvos
        existentes = obter_processos_existentes()
        novas = []
        duplicadas = 0
        for intim in todas_intimacoes:
            chave = (
                intim.get("numero_processo", ""),
                intim.get("tribunal", ""),
                intim.get("data_disponibilizacao", "")
            )
            if chave in existentes:
                duplicadas += 1
            else:
                novas.append(intim)

        if duplicadas > 0:
            print(f"\n  ⚠ {duplicadas} intimação(ões) duplicada(s) ignorada(s)")

        if not novas:
            print("\n  Todas as intimações já foram salvas anteriormente.")
            return []

        todas_intimacoes = novas

        print(f"\n[5/5] Salvando {len(todas_intimacoes)} nova(s) intimação(ões)...")
        json_path = salvar_resultados(todas_intimacoes, oab, data_inicio, data_fim, body_text_final, uf_oab=uf_oab)

        salvar_screenshot(driver, f"resultado_final_OAB{oab}")

        print(f"\n{'='*60}")
        print(f"  CONSULTA FINALIZADA")
        print(f"  Intimações encontradas: {len(todas_intimacoes)}")
        print(f"  Resultados em: {OUTPUT_DIR}")
        print(f"{'='*60}\n")

        return todas_intimacoes

    except Exception as e:
        print(f"\n  ERRO: {e}")
        if driver:
            salvar_screenshot(driver, f"erro_OAB{oab}")
        raise
    finally:
        if driver:
            driver.quit()
            print("  Driver fechado.")


# ──────────────────────────────────────────────
# Execução direta
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # Valores padrão (podem ser alterados via argumentos)
    oab = "165230"
    data_inicio = "2026-01-20"
    data_fim = "2026-01-20"
    headless = False
    uf_oab = ""

    # Suporte a argumentos de linha de comando:
    # python main.py <OAB> <DATA_INICIO> <DATA_FIM> [headless] [UF_OAB]
    if len(sys.argv) >= 4:
        oab = sys.argv[1]
        data_inicio = sys.argv[2]
        data_fim = sys.argv[3]
    if len(sys.argv) >= 5:
        arg4 = sys.argv[4]
        if arg4.lower() in ("true", "1", "sim", "yes", "false", "0", "nao", "no"):
            headless = arg4.lower() in ("true", "1", "sim", "yes")
        elif len(arg4) == 2 and arg4.isalpha():
            uf_oab = arg4.upper()
    if len(sys.argv) >= 6:
        arg5 = sys.argv[5]
        if len(arg5) == 2 and arg5.isalpha():
            uf_oab = arg5.upper()
        elif arg5.lower() in ("true", "1", "sim", "yes"):
            headless = True

    # Se nenhum argumento, perguntar interativamente
    if len(sys.argv) < 2:
        print("\n  AUTOMAÇÃO DJEN CNJ - Consulta de Intimações")
        print("  " + "-" * 45)
        entrada_oab = input("  Número OAB (enter para 165230): ").strip()
        if entrada_oab:
            oab = entrada_oab

        entrada_uf = input("  UF da OAB (ex: SP, RJ, PI - enter para todas): ").strip()
        if entrada_uf:
            uf_oab = entrada_uf.upper()

        entrada_inicio = input("  Data início YYYY-MM-DD (enter para 2026-01-20): ").strip()
        if entrada_inicio:
            data_inicio = entrada_inicio

        entrada_fim = input("  Data fim YYYY-MM-DD (enter para 2026-01-20): ").strip()
        if entrada_fim:
            data_fim = entrada_fim

        entrada_headless = input("  Rodar headless? (s/N): ").strip().lower()
        headless = entrada_headless in ("s", "sim", "y", "yes")

    resultados = consultar_intimacoes(oab, data_inicio, data_fim, headless, uf_oab=uf_oab)
    print(f"\n  Total retornado: {len(resultados)} intimação(ões)")

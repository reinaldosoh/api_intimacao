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
python main.py <OAB> <DATA_INICIO> <DATA_FIM> [headless]
```

**Exemplo:**
```bash
python main.py 165230 2026-01-20 2026-01-20
python main.py 165230 2026-01-20 2026-01-20 true
```

## Saída

Os resultados são salvos na pasta `resultados/`:
- `intimacoes_OAB{numero}_{datas}_{timestamp}.json` - Dados estruturados
- `intimacoes_OAB{numero}_{datas}_{timestamp}.csv` - Planilha
- `intimacoes_OAB{numero}_{datas}_{timestamp}_raw.txt` - Texto bruto da página
- Screenshots `.png` da página carregada

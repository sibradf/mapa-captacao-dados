"""Sonda as fontes de Transferências Especiais (emendas Pix) e fundo a fundo: endereço, status, campos e exemplo."""
import json, sys, urllib.request
B = 'https://api.transferegov.gestao.gov.br/transferenciasespeciais/'
URLS = [
    B + 'plano_trabalho_especial?limit=3&order=id_plano_acao.desc',
    B + 'plano_acao_especial?limit=3&ano_plano_acao=eq.2026&order=id_plano_acao.desc',
    B + 'plano_acao_especial?limit=3&ano_plano_acao=eq.2025&situacao_plano_acao=neq.CIENTE',
    B + 'finalidade_especial?limit=2',
    B + 'historico_pagamento_especial?limit=2',
    B + 'documento_habil_especial?limit=2',
    B + 'programa_especial?limit=3&order=id_programa.desc',
    B + 'plano_trabalho_analise_especial?limit=2',
    B + 'orgao_analise_pendente_especial?limit=2',
    B + 'relatorio_gestao_especial?limit=2',
]
for sit in ['CIENTE','IMPEDIDO','APROVADO','EM_ANALISE','PENDENTE','CANCELADO','EM_ELABORACAO','ENVIADO']:
    URLS.append(B + 'plano_acao_especial?select=id_plano_acao&limit=1&situacao_plano_acao=eq.' + sit)
for ano in [2024, 2025, 2026]:
    URLS.append(B + 'plano_acao_especial?select=id_plano_acao&limit=1&ano_plano_acao=eq.%d' % ano)
for u in URLS:
    print('###', u)
    try:
        req = urllib.request.Request(u, headers={'User-Agent': 'robo-mapadegoverno', 'Accept': 'application/json', 'Prefer': 'count=exact'})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read(400000)
            print('  status', r.status, r.headers.get('Content-Type'), 'Content-Range', r.headers.get('Content-Range'))
            try:
                j = json.loads(b)
                if isinstance(j, list):
                    print('  lista', len(j)); [print('  ex:', json.dumps(x, ensure_ascii=False)[:1500]) for x in j[:2]]
                elif isinstance(j, dict):
                    ks = list(j.keys()); print('  chaves', ks[:60])
                    if 'paths' in j: print('  paths:', list(j['paths'].keys())[:80])
            except Exception:
                print('  texto:', b[:1500].decode('utf-8', 'replace'))
    except Exception as e:
        print('  FALHOU', e)

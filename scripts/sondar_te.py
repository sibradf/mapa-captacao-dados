"""Sonda as fontes de Transferências Especiais (emendas Pix) e fundo a fundo: endereço, status, campos e exemplo."""
import json, sys, urllib.request
URLS = [
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/',
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/plano_acao_especial?limit=2',
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/relatorio_gestao_novo_especial?limit=2',
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/empenho_especial?limit=2',
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/ordem_pagamento_ordem_bancaria_especial?limit=2',
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/executor_especial?limit=2',
    'https://api.transferegov.gestao.gov.br/transferenciasespeciais/meta_especial?limit=2',
    'https://api.transferegov.gestao.gov.br/fundoafundo/',
    'https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/',
    'https://api-publica.transferegov.gestao.gov.br/downloads/',
]
for u in URLS:
    print('###', u)
    try:
        req = urllib.request.Request(u, headers={'User-Agent': 'robo-mapadegoverno', 'Accept': 'application/json'})
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

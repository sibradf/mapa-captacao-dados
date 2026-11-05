"""
Mapa de Governo · metadados do IBGE para o painel de Produção.
O servidor do Mapa não alcança servicodados.ibge.gov.br; o robô busca aqui os metadados (produtos e variáveis)
e os anos publicados de cada tabela usada pelo painel e publica producao_meta.json.
Os valores continuam vindo do SIDRA (apisidra), que o servidor alcança.
"""
import json, os, sys, time, datetime, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (robo-mapadegoverno producao)'}
TABELAS = ['5457', '289', '291', '3939', '74', '3940']
BASE = 'https://servicodados.ibge.gov.br/api/v3/agregados/'


def get(url):
    for t in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:
            print('falha', url, e, flush=True); time.sleep(15 * (t + 1))
    return None


def main(saida):
    os.makedirs(saida, exist_ok=True)
    out = {'gerado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'fonte': BASE, 'tabelas': {}}
    for t in TABELAS:
        meta = get(BASE + t + '/metadados')
        per = get(BASE + t + '/periodos')
        if not meta or not per:
            print(f'tabela {t}: sem resposta do IBGE; nada será publicado hoje', flush=True)
            sys.exit(1)
        # só o que o painel usa: variáveis e as classificações com categorias
        out['tabelas'][t] = {
            'nome': meta.get('nome'),
            'variaveis': [{'id': v.get('id'), 'nome': v.get('nome'), 'unidade': v.get('unidade')} for v in meta.get('variaveis', [])],
            'classificacoes': [{'id': c.get('id'), 'nome': c.get('nome'),
                                'categorias': [{'id': k.get('id'), 'nome': k.get('nome'), 'nivel': k.get('nivel')} for k in c.get('categorias', [])]}
                               for c in meta.get('classificacoes', [])],
            'periodos': sorted({int(p['id']) for p in per if str(p.get('id', '')).isdigit()}),
        }
        print(t, len(out['tabelas'][t]['periodos']), 'anos', flush=True)
    with open(os.path.join(saida, 'producao_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/val')

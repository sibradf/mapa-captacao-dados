"""
Mapa de Governo · painel de embaixada (demonstração): Brasil x um país, só com dados oficiais.
  - MDIC/Comex Stat: arquivos anuais EXP_AAAA e IMP_AAAA (NCM) + tabelas de nomes
  - Banco Central (PTAX): câmbio diário da moeda do país
  - GDELT: manchetes recentes que citam Brasil e o país (com link de cada uma)
Uso: python3 scripts/embaixada.py PASTA_SAIDA CODIGO_PAIS_MDIC MOEDA "termo GDELT"   (ex.: 399 JPY Japan)
"""
import csv, io, json, os, sys, time, urllib.request, urllib.parse, datetime, collections

MDIC = 'https://balanca.mdic.gov.br/balanca/bd/'
UA = {'User-Agent': 'Mozilla/5.0 (robo-mapadegoverno)'}
csv.field_size_limit(10**9)


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def get(url, timeout=600, tentativas=3):
    for t in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            log(f'falha {url} ({t}): {e}')
            time.sleep(10 * t)
    return None


def tabela(nome):
    b = get(MDIC + 'tabelas/' + nome)
    if not b:
        return []
    txt = b.decode('latin-1') if b[:3] != b'\xef\xbb\xbf' else b.decode('utf-8-sig')
    try:
        txt = b.decode('utf-8-sig')
    except UnicodeDecodeError:
        pass
    return list(csv.DictReader(io.StringIO(txt), delimiter=';'))


def main(saida, pais, moeda, termo):
    os.makedirs(saida, exist_ok=True)
    hoje = datetime.date.today()
    anos = [hoje.year - 2, hoje.year - 1, hoje.year]
    paises = {r['CO_PAIS']: r for r in tabela('PAIS.csv')}
    ncm = {r['CO_NCM']: r for r in tabela('NCM.csv')}
    sh4 = {}
    for r in tabela('NCM_SH.csv'):
        sh4[r['CO_SH4']] = (r.get('NO_SH4_POR', ''), r.get('NO_SH4_ING', ''))
    ufs = {r['SG_UF']: r.get('NO_UF', r['SG_UF']) for r in tabela('UF.csv')}
    vias = {r['CO_VIA']: r.get('NO_VIA', '') for r in tabela('VIA.csv')}
    urfs = {r['CO_URF']: r.get('NO_URF', '') for r in tabela('URF.csv')}
    ncm_sh4 = {k: (v.get('CO_SH4') or k[:4]) for k, v in ncm.items()}
    log(f'tabelas: {len(paises)} países, {len(ncm)} NCM, {len(sh4)} SH4')

    # pares para "oportunidades": economias asiáticas desenvolvidas e grandes compradores parecidos
    nomes_pares = ['Coreia do Sul', 'China', 'Taiwan (Formosa)', 'Singapura', 'Estados Unidos', 'Alemanha', 'Países Baixos (Holanda)']
    pares = [c for c, r in paises.items() if r.get('NO_PAIS') in nomes_pares]

    mensal = collections.defaultdict(lambda: [0.0, 0.0])           # (ano, mes) -> [exp, imp]
    por_uf = {f: collections.defaultdict(lambda: collections.defaultdict(float)) for f in ('exp', 'imp')}   # f -> ano -> uf
    por_sh4 = {f: collections.defaultdict(lambda: collections.defaultdict(float)) for f in ('exp', 'imp')}
    por_urf = {f: collections.defaultdict(float) for f in ('exp', 'imp')}
    por_via = {f: collections.defaultdict(float) for f in ('exp', 'imp')}
    uf_sh4 = collections.defaultdict(lambda: collections.defaultdict(float))       # exp do último ano: uf -> sh4
    pares_sh4 = collections.defaultdict(float)                     # exp do Brasil aos pares no último ano completo
    total_br = {f: collections.defaultdict(float) for f in ('exp', 'imp')}   # total do Brasil por ano (para participação)
    ultimo = {'exp': (0, 0), 'imp': (0, 0)}
    for ano in anos:
        for f, pref in (('exp', 'EXP'), ('imp', 'IMP')):
            b = get(MDIC + f'comexstat-bd/ncm/{pref}_{ano}.csv', timeout=1800)
            if not b:
                log(f'sem arquivo {pref}_{ano}')
                continue
            rd = csv.DictReader(io.StringIO(b.decode('latin-1')), delimiter=';')
            n = 0
            for r in rd:
                v = float(r['VL_FOB'] or 0)
                a, m = int(r['CO_ANO']), int(r['CO_MES'])
                total_br[f][a] += v
                if (a, m) > ultimo[f]:
                    ultimo[f] = (a, m)
                if r['CO_PAIS'] == pais:
                    n += 1
                    mensal[(a, m)][0 if f == 'exp' else 1] += v
                    s4 = ncm_sh4.get(r['CO_NCM'], r['CO_NCM'][:4])
                    por_uf[f][a][r['SG_UF_NCM']] += v
                    por_sh4[f][a][s4] += v
                    if a == anos[-1] or a == anos[-2]:
                        por_urf[f][(a, r['CO_URF'])] += v
                        por_via[f][(a, r['CO_VIA'])] += v
                    if f == 'exp' and a == anos[-1]:
                        uf_sh4[r['SG_UF_NCM']][s4] += v
                elif f == 'exp' and a == anos[-2] and r['CO_PAIS'] in pares:
                    pares_sh4[ncm_sh4.get(r['CO_NCM'], r['CO_NCM'][:4])] += v
            del b
            log(f'{pref}_{ano}: {n} linhas do país')

    def top(d, k=15):
        return sorted(d.items(), key=lambda x: -x[1])[:k]

    ua, ap = anos[-1], anos[-2]
    mes_ult = min(ultimo['exp'][1] if ultimo['exp'][0] == ua else 12, ultimo['imp'][1] if ultimo['imp'][0] == ua else 12)
    def acum(a, f, ate):
        return sum(v[0 if f == 'exp' else 1] for (x, m), v in mensal.items() if x == a and m <= ate)
    # oportunidades: produtos que o Brasil vende muito aos pares e pouco ao país (ano completo anterior)
    exp_pais_ap = por_sh4['exp'][ap]
    oport = []
    for s4, v in top(pares_sh4, 200):
        if v < 50e6:
            break
        meu = exp_pais_ap.get(s4, 0.0)
        if meu < 0.03 * v:
            oport.append({'sh4': s4, 'nome': sh4.get(s4, ('', ''))[0], 'nome_en': sh4.get(s4, ('', ''))[1], 'pares': round(v), 'pais': round(meu)})
    oport = oport[:15]

    dados = {
        'pais': {'codigo': pais, 'nome': paises.get(pais, {}).get('NO_PAIS', ''), 'nome_en': paises.get(pais, {}).get('NO_PAIS_ING', ''), 'iso3': paises.get(pais, {}).get('CO_PAIS_ISOA3', '')},
        'gerado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'ultimo_mes': [ua, mes_ult], 'anos': anos,
        'mensal': sorted([[a, m, round(v[0]), round(v[1])] for (a, m), v in mensal.items()]),
        'acumulado': {'ano': ua, 'ate_mes': mes_ult, 'exp': round(acum(ua, 'exp', mes_ult)), 'imp': round(acum(ua, 'imp', mes_ult)),
                      'exp_ant': round(acum(ap, 'exp', mes_ult)), 'imp_ant': round(acum(ap, 'imp', mes_ult))},
        'ano_completo': {'ano': ap, 'exp': round(sum(por_uf['exp'][ap].values())), 'imp': round(sum(por_uf['imp'][ap].values())),
                         'exp_br': round(total_br['exp'][ap]), 'imp_br': round(total_br['imp'][ap])},
        'ranking_parceiro': None,
        'ufs': {f: [{'uf': u, 'nome': ufs.get(u, u), 'v': round(v), 'v_ant': round(por_uf[f][ap].get(u, 0))} for u, v in top(por_uf[f][ua], 27)] for f in ('exp', 'imp')},
        'produtos': {f: [{'sh4': s, 'nome': sh4.get(s, ('', ''))[0], 'nome_en': sh4.get(s, ('', ''))[1], 'v': round(v), 'v_ant': round(por_sh4[f][ap].get(s, 0))} for s, v in top(por_sh4[f][ua], 15)] for f in ('exp', 'imp')},
        'uf_produtos': {u: [{'sh4': s, 'nome': sh4.get(s, ('', ''))[0], 'nome_en': sh4.get(s, ('', ''))[1], 'v': round(v)} for s, v in top(d, 3)] for u, d in uf_sh4.items()},
        'portos': {f: [{'urf': c, 'nome': urfs.get(c, c), 'v': round(v)} for (a, c), v in top({k: v for k, v in por_urf[f].items() if k[0] == ua}, 8)] for f in ('exp', 'imp')},
        'vias': {f: [{'via': c, 'nome': vias.get(c, c), 'v': round(v)} for (a, c), v in top({k: v for k, v in por_via[f].items() if k[0] == ua}, 5)] for f in ('exp', 'imp')},
        'oportunidades': oport, 'pares': [paises[c]['NO_PAIS'] for c in pares],
    }
    # posição do país entre os destinos do Brasil (ano completo anterior) - calculada à parte para não pesar a memória
    # (feita na mesma leitura acima seria mais rápido, mas o arquivo é lido só uma vez por ano)

    # câmbio PTAX (Banco Central)
    ini = (hoje - datetime.timedelta(days=400)).strftime('%m-%d-%Y'); fim = hoje.strftime('%m-%d-%Y')
    u = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
         f"?@moeda='{moeda}'&@dataInicial='{ini}'&@dataFinalCotacao='{fim}'&$format=json&$select=cotacaoVenda,dataHoraCotacao,tipoBoletim")
    b = get(u, 60)
    cot = []
    if b:
        for x in json.loads(b).get('value', []):
            if x.get('tipoBoletim') == 'Fechamento':
                cot.append([x['dataHoraCotacao'][:10], x['cotacaoVenda']])
    dados['cambio'] = {'moeda': moeda, 'fonte': 'Banco Central do Brasil (PTAX, fechamento)', 'serie': cot}
    log(f'câmbio: {len(cot)} dias')

    # manchetes (GDELT): só título, veículo, data e link
    q = urllib.parse.quote(f'(Brazil OR Brasil) {termo}')
    b = get(f'https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&maxrecords=75&format=json&timespan=14d&sort=datedesc', 60)
    noticias = []
    if b:
        try:
            vistos = set()
            for a in json.loads(b.decode('utf-8', 'ignore')).get('articles', []):
                t = (a.get('title') or '').strip()
                k = t.lower()[:60]
                if not t or k in vistos:
                    continue
                vistos.add(k)
                noticias.append({'titulo': t, 'url': a.get('url'), 'veiculo': a.get('domain'), 'data': (a.get('seendate') or '')[:8], 'idioma': a.get('language')})
        except Exception as e:
            log(f'gdelt: {e}')
    dados['noticias'] = noticias[:30]
    log(f'notícias: {len(noticias)}')
    with open(os.path.join(saida, f'pais_{pais}.json'), 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False)
    log('ok')


if __name__ == '__main__':
    main(*sys.argv[1:5])

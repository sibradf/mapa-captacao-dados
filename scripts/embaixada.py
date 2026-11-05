"""
Mapa de Governo · painel de embaixada: Brasil x cada país, só com dados oficiais.
  - MDIC/Comex Stat: arquivos anuais EXP_AAAA e IMP_AAAA (NCM) + tabelas de nomes (lidos uma vez para todos os países)
  - Banco Central (PTAX): câmbio diário da moeda do país, quando o BC publica essa moeda
  - Google Notícias (RSS público): manchetes recentes que citam o Brasil e o país (com link de cada uma)
Uso: python3 scripts/embaixada.py PASTA_SAIDA [CODIGOS]   (CODIGOS vazio ou "todos" = todos os países com comércio)
Saída: pais_CODIGO.json por país + paises.json (lista para a página de escolha).
"""
import csv, io, json, os, re, sys, time, urllib.request, urllib.parse, datetime, collections, tempfile
import xml.etree.ElementTree as ET, email.utils

MDIC = 'https://balanca.mdic.gov.br/balanca/bd/'
UA = {'User-Agent': 'Mozilla/5.0 (robo-mapadegoverno)'}
csv.field_size_limit(10**9)

# moeda de cada país (ISO3 -> código), usada só se o Banco Central publicar PTAX dessa moeda
EURO = 'AUT BEL HRV CYP EST FIN FRA DEU GRC IRL ITA LVA LTU LUX MLT NLD PRT SVK SVN ESP'.split()
MOEDA = {**{p: 'EUR' for p in EURO}, 'JPN': 'JPY', 'USA': 'USD', 'GBR': 'GBP', 'CHE': 'CHF', 'CAN': 'CAD', 'AUS': 'AUD',
         'DNK': 'DKK', 'NOR': 'NOK', 'SWE': 'SEK', 'CHN': 'CNY', 'ARG': 'ARS', 'CHL': 'CLP', 'COL': 'COP', 'MEX': 'MXN',
         'PRY': 'PYG', 'URY': 'UYU', 'PER': 'PEN', 'BOL': 'BOB', 'KOR': 'KRW', 'IND': 'INR', 'ZAF': 'ZAR', 'RUS': 'RUB',
         'TUR': 'TRY', 'SAU': 'SAR', 'ARE': 'AED', 'ISR': 'ILS', 'SGP': 'SGD', 'HKG': 'HKD', 'TWN': 'TWD', 'THA': 'THB',
         'IDN': 'IDR', 'MYS': 'MYR', 'PHL': 'PHP', 'VNM': 'VND', 'NZL': 'NZD', 'POL': 'PLN', 'CZE': 'CZK', 'HUN': 'HUF',
         'ROU': 'RON', 'EGY': 'EGP', 'NGA': 'NGN', 'MAR': 'MAD', 'KWT': 'KWD', 'QAT': 'QAR', 'PAK': 'PKR', 'VEN': 'VES'}
# termos extras para reconhecer o país nas manchetes
EXTRAS = {'399': ['japanese', 'japonês', 'japonesa', 'tóquio', 'tokyo', 'nikkei', 'iene', 'yen', 'jica', 'jbic', 'takaichi', 'ishiba'],
          '160': ['china', 'chinese', 'chinês', 'chinesa', 'pequim', 'beijing', 'xi jinping'],
          '249': ['eua', 'u.s.', 'us ', 'american', 'americano', 'washington', 'trump'],
          '023': ['german', 'alemão', 'alemã', 'berlim', 'berlin'], '063': ['argentin', 'buenos aires', 'milei'],
          '275': ['france', 'french', 'francês', 'francesa', 'paris', 'macron']}
# pares do Japão (mantidos como na demonstração já apresentada)
PARES_JAPAO = ['Coreia do Sul', 'China', 'Taiwan (Formosa)', 'Singapura', 'Estados Unidos', 'Alemanha', 'Países Baixos (Holanda)']


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def get(url, timeout=600, tentativas=3):
    for t in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            log(f'falha {url[:120]} ({t}): {e}')
            time.sleep(10 * t)
    return None


def baixar(url, destino):
    """Grava em disco (os anuais têm centenas de MB) e devolve o caminho, ou None."""
    for t in range(1, 4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=1800) as r, open(destino, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            return destino
        except Exception as e:
            log(f'falha {url} ({t}): {e}')
            time.sleep(15 * t)
    return None


def tabela(nome):
    b = get(MDIC + 'tabelas/' + nome)
    if not b:
        return []
    try:
        txt = b.decode('utf-8-sig')
    except UnicodeDecodeError:
        txt = b.decode('latin-1')
    return list(csv.DictReader(io.StringIO(txt), delimiter=';'))


def dd(f):
    return collections.defaultdict(f)


def curto_nome(n):
    n = re.sub(r'\s*\(.*?\)\s*', ' ', n or '')
    return re.sub(r'\s+', ' ', n.split(',')[0]).strip()


def manchetes(cod, nome, nome_en):
    noticias, vistos = [], set()
    termo_pt, termo = curto_nome(nome), curto_nome(nome_en)
    for consulta, hl, gl, ceid in ((f'Brasil "{termo_pt}"', 'pt-BR', 'BR', 'BR:pt-419'), (f'Brazil "{termo}"', 'en-US', 'US', 'US:en')):
        b = get('https://news.google.com/rss/search?q=' + urllib.parse.quote(consulta + ' when:14d') + f'&hl={hl}&gl={gl}&ceid={ceid}', 60, 2)
        time.sleep(1.5)
        if not b:
            continue
        try:
            for it in ET.fromstring(b).iter('item'):
                t = (it.findtext('title') or '').strip()
                fonte = (it.findtext('source') or '').strip()
                if fonte and t.endswith(' - ' + fonte):
                    t = t[: -len(fonte) - 3]
                k = t.lower()[:60]
                if not t or k in vistos:
                    continue
                vistos.add(k)
                try:
                    dt = email.utils.parsedate_to_datetime(it.findtext('pubDate')).strftime('%Y%m%d')
                except Exception:
                    dt = ''
                noticias.append({'titulo': t, 'url': it.findtext('link'), 'veiculo': fonte, 'data': dt, 'idioma': 'Portuguese' if hl == 'pt-BR' else 'English'})
        except Exception as e:
            log(f'rss {cod}: {e}')
    # só manchetes que citam OS DOIS países no título, sem esporte
    br = re.compile(r'\b(brasil|brazil|brasileir|brazilian|lula|bras[ií]lia|s[ãa]o paulo)', re.I)
    alvo = re.compile(r'(' + '|'.join(re.escape(x) for x in {termo, termo_pt} | set(EXTRAS.get(cod, [])) if x) + r')', re.I)
    esporte = re.compile(r'(sele[çc][ãa]o|amistos|friendl|world cup|copa do mundo|squad|convoca|futebol|football|soccer|v[ôo]lei|volley|u-1\d|sub-1\d|ancelotti|p[êe]nalti|gol\b|goal|match|partida|jogo|olymp|ol[íi]mp|grand prix|f[óo]rmula|mma|ufc|jud[ôo]|surf|skate|tennis|t[êe]nis|basket)', re.I)
    noticias = [n for n in noticias if br.search(n['titulo']) and alvo.search(n['titulo']) and not esporte.search(n['titulo'])]
    noticias.sort(key=lambda n: n['data'], reverse=True)
    return noticias[:40]


def ptax(moeda, hoje, cache={}):
    if moeda in cache:
        return cache[moeda]
    ini = (hoje - datetime.timedelta(days=400)).strftime('%m-%d-%Y'); fim = hoje.strftime('%m-%d-%Y')
    u = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
         f"?@moeda='{moeda}'&@dataInicial='{ini}'&@dataFinalCotacao='{fim}'&$format=json&$select=cotacaoVenda,dataHoraCotacao,tipoBoletim")
    b = get(u, 60, 2)
    cot = []
    if b:
        try:
            for x in json.loads(b).get('value', []):
                if x.get('tipoBoletim') == 'Fechamento':
                    cot.append([x['dataHoraCotacao'][:10], x['cotacaoVenda']])
        except Exception as e:
            log(f'ptax {moeda}: {e}')
    cache[moeda] = cot
    return cot


def main(saida, filtro=''):
    os.makedirs(saida, exist_ok=True)
    tmp = tempfile.mkdtemp()
    hoje = datetime.date.today()
    anos = [hoje.year - 2, hoje.year - 1, hoje.year]
    paises = {r['CO_PAIS']: r for r in tabela('PAIS.csv')}
    ncm = {r['CO_NCM']: r for r in tabela('NCM.csv')}
    sh4 = {r['CO_SH4']: (r.get('NO_SH4_POR', ''), r.get('NO_SH4_ING', '')) for r in tabela('NCM_SH.csv')}
    ufs = {r['SG_UF']: r.get('NO_UF', r['SG_UF']) for r in tabela('UF.csv')}
    vias = {r['CO_VIA']: r.get('NO_VIA', '') for r in tabela('VIA.csv')}
    urfs = {r['CO_URF']: r.get('NO_URF', '') for r in tabela('URF.csv')}
    ncm_sh4 = {k: (v.get('CO_SH4') or k[:4]) for k, v in ncm.items()}
    log(f'tabelas: {len(paises)} países, {len(ncm)} NCM, {len(sh4)} SH4')
    pares_jp = {c for c, r in paises.items() if r.get('NO_PAIS') in PARES_JAPAO}
    ua, ap = anos[-1], anos[-2]

    # tudo por país numa só leitura de cada arquivo
    mensal = dd(lambda: dd(lambda: [0.0, 0.0]))                    # pais -> (ano, mes) -> [exp, imp]
    por_uf = {f: dd(lambda: dd(lambda: dd(float))) for f in ('exp', 'imp')}    # f -> pais -> ano -> uf
    por_sh4 = {f: dd(lambda: dd(lambda: dd(float))) for f in ('exp', 'imp')}   # f -> pais -> ano -> sh4
    por_urf = {f: dd(lambda: dd(float)) for f in ('exp', 'imp')}   # f -> pais -> urf (ano atual)
    por_via = {f: dd(lambda: dd(float)) for f in ('exp', 'imp')}
    uf_sh4 = dd(lambda: dd(lambda: dd(float)))                     # pais -> uf -> sh4 (exp do ano atual)
    total_br = {f: dd(float) for f in ('exp', 'imp')}
    # gabarito do validador: soma dos 27 estados por mês e por UF/ano (o Mapa não guarda UF não declarada, "ND")
    UF27 = set('AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO'.split())
    total_mes = {f: dd(float) for f in ('exp', 'imp')}
    total_nd = {f: dd(float) for f in ('exp', 'imp')}
    uf_ano = {f: dd(float) for f in ('exp', 'imp')}
    mundo_sh4 = dd(float)                                          # exp do Brasil ao mundo por sh4 (ano completo)
    ultimo = {'exp': (0, 0), 'imp': (0, 0)}
    for ano in anos:
        for f, pref in (('exp', 'EXP'), ('imp', 'IMP')):
            arq = baixar(MDIC + f'comexstat-bd/ncm/{pref}_{ano}.csv', os.path.join(tmp, f'{pref}_{ano}.csv'))
            if not arq:
                log(f'sem arquivo {pref}_{ano}')
                continue
            n = 0
            with open(arq, encoding='latin-1', newline='') as fh:
                for r in csv.DictReader(fh, delimiter=';'):
                    v = float(r['VL_FOB'] or 0)
                    a, m = int(r['CO_ANO']), int(r['CO_MES'])
                    p = r['CO_PAIS']
                    n += 1
                    total_br[f][a] += v
                    if r['SG_UF_NCM'] in UF27:
                        total_mes[f][(a, m)] += v
                        uf_ano[f][(a, r['SG_UF_NCM'])] += v
                    else:
                        total_nd[f][a] += v
                    if (a, m) > ultimo[f]:
                        ultimo[f] = (a, m)
                    s4 = ncm_sh4.get(r['CO_NCM'], r['CO_NCM'][:4])
                    mensal[p][(a, m)][0 if f == 'exp' else 1] += v
                    por_uf[f][p][a][r['SG_UF_NCM']] += v
                    por_sh4[f][p][a][s4] += v
                    if a == ua:
                        por_urf[f][p][r['CO_URF']] += v
                        por_via[f][p][r['CO_VIA']] += v
                        if f == 'exp':
                            uf_sh4[p][r['SG_UF_NCM']][s4] += v
                    if f == 'exp' and a == ap:
                        mundo_sh4[s4] += v
            os.remove(arq)
            log(f'{pref}_{ano}: {n} linhas')

    def top(d, k=15):
        return sorted(d.items(), key=lambda x: -x[1])[:k]

    def soma(f, p, a):
        return sum(por_uf[f][p][a].values())

    mes_ult = min(ultimo['exp'][1] if ultimo['exp'][0] == ua else 12, ultimo['imp'][1] if ultimo['imp'][0] == ua else 12)

    # países: só os que existem como país (ISO3) e tiveram comércio com o Brasil nos últimos dois anos
    lista = []
    for c, r in paises.items():
        iso = (r.get('CO_PAIS_ISOA3') or '').strip()
        tot = soma('exp', c, ap) + soma('imp', c, ap) + soma('exp', c, ua) + soma('imp', c, ua)
        if iso and tot > 0:
            lista.append(c)
    if filtro and filtro != 'todos':
        quer = set(filtro.replace(' ', '').split(','))
        lista = [c for c in lista if c in quer]
    lista.sort(key=lambda c: -(soma('exp', c, ap) + soma('imp', c, ap)))
    # posição de cada país entre os destinos e as origens (ano completo)
    rank = {f: {c: i + 1 for i, c in enumerate(sorted(por_uf[f], key=lambda c: -soma(f, c, ap)))} for f in ('exp', 'imp')}
    log(f'{len(lista)} países com comércio')

    indice = []
    for pais in lista:
        P = paises[pais]
        mens = mensal[pais]
        def acum(a, f, ate):
            return sum(v[0 if f == 'exp' else 1] for (x, m), v in mens.items() if x == a and m <= ate)
        exp_ap = soma('exp', pais, ap)
        # espaço para crescer
        oport = []
        if pais == '399':
            pares_sh4 = dd(float)
            for c in pares_jp:
                for s4, v in por_sh4['exp'][c][ap].items():
                    pares_sh4[s4] += v
            for s4, v in top(pares_sh4, 200):
                if v < 50e6:
                    break
                meu = por_sh4['exp'][pais][ap].get(s4, 0.0)
                if meu < 0.03 * v:
                    oport.append({'sh4': s4, 'nome': sh4.get(s4, ('', ''))[0], 'nome_en': sh4.get(s4, ('', ''))[1], 'pares': round(v), 'pais': round(meu)})
            metodo = {'tipo': 'pares', 'pares': [paises[c]['NO_PAIS'] for c in pares_jp]}
        else:
            # produto que o Brasil vende muito ao mundo (> US$ 50 mi) e em que a fatia do país fica abaixo de 1/4
            # da fatia que o país tem no total das exportações brasileiras
            fatia = exp_ap / total_br['exp'][ap] if total_br['exp'][ap] else 0
            for s4, v in top(mundo_sh4, 400):
                if v < 50e6 or fatia <= 0:
                    break
                meu = por_sh4['exp'][pais][ap].get(s4, 0.0)
                resto = v - meu
                if resto > 0 and meu < 0.25 * fatia * v and fatia * v >= 2e6:
                    oport.append({'sh4': s4, 'nome': sh4.get(s4, ('', ''))[0], 'nome_en': sh4.get(s4, ('', ''))[1], 'pares': round(resto), 'pais': round(meu), 'esperado': round(fatia * v)})
            metodo = {'tipo': 'mundo', 'fatia': round(fatia * 100, 3)}
        oport = oport[:15]
        moeda = MOEDA.get(P.get('CO_PAIS_ISOA3', ''), '')
        cot = ptax(moeda, hoje) if moeda and moeda != 'USD' else []
        if moeda == 'USD':
            cot = ptax('USD', hoje)
        dados = {
            'pais': {'codigo': pais, 'nome': P.get('NO_PAIS', ''), 'nome_en': P.get('NO_PAIS_ING', ''), 'iso3': P.get('CO_PAIS_ISOA3', '')},
            'gerado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'ultimo_mes': [ua, mes_ult], 'anos': anos,
            'mensal': sorted([[a, m, round(v[0]), round(v[1])] for (a, m), v in mens.items() if (a, m) <= (ua, mes_ult)]),
            'acumulado': {'ano': ua, 'ate_mes': mes_ult, 'exp': round(acum(ua, 'exp', mes_ult)), 'imp': round(acum(ua, 'imp', mes_ult)),
                          'exp_ant': round(acum(ap, 'exp', mes_ult)), 'imp_ant': round(acum(ap, 'imp', mes_ult))},
            'ano_completo': {'ano': ap, 'exp': round(exp_ap), 'imp': round(soma('imp', pais, ap)),
                             'exp_br': round(total_br['exp'][ap]), 'imp_br': round(total_br['imp'][ap])},
            'ranking_parceiro': {'exp': rank['exp'].get(pais), 'imp': rank['imp'].get(pais)},
            'ufs': {f: [{'uf': u, 'nome': ufs.get(u, u), 'v': round(v), 'v_ant': round(por_uf[f][pais][ap].get(u, 0))} for u, v in top(por_uf[f][pais][ua], 27) if v > 0] for f in ('exp', 'imp')},
            'produtos': {f: [{'sh4': s, 'nome': sh4.get(s, ('', ''))[0], 'nome_en': sh4.get(s, ('', ''))[1], 'v': round(v), 'v_ant': round(por_sh4[f][pais][ap].get(s, 0))} for s, v in top(por_sh4[f][pais][ua], 15) if v > 0] for f in ('exp', 'imp')},
            'uf_produtos': {u: [{'sh4': s, 'nome': sh4.get(s, ('', ''))[0], 'nome_en': sh4.get(s, ('', ''))[1], 'v': round(v)} for s, v in top(d, 3)] for u, d in uf_sh4[pais].items()},
            'portos': {f: [{'urf': c, 'nome': urfs.get(c, c), 'v': round(v)} for c, v in top(por_urf[f][pais], 8) if v > 0] for f in ('exp', 'imp')},
            'vias': {f: [{'via': c, 'nome': vias.get(c, c), 'v': round(v)} for c, v in top(por_via[f][pais], 5) if v > 0] for f in ('exp', 'imp')},
            'oportunidades': oport, 'metodo_oport': metodo, 'pares': metodo.get('pares', []),
            'cambio': {'moeda': moeda if cot else '', 'fonte': 'Banco Central do Brasil (PTAX, fechamento)', 'serie': cot},
            'noticias': manchetes(pais, P.get('NO_PAIS', ''), P.get('NO_PAIS_ING', '')),
        }
        with open(os.path.join(saida, f'pais_{pais}.json'), 'w', encoding='utf-8') as fo:
            json.dump(dados, fo, ensure_ascii=False)
        indice.append({'codigo': pais, 'nome': dados['pais']['nome'], 'nome_en': dados['pais']['nome_en'], 'iso3': dados['pais']['iso3'],
                       'exp': dados['ano_completo']['exp'], 'imp': dados['ano_completo']['imp'], 'noticias': len(dados['noticias'])})
        log(f"{pais} {dados['pais']['nome']}: exp {exp_ap/1e6:.0f} mi · {len(oport)} oport · câmbio {moeda or '-'} {len(cot)} · {len(dados['noticias'])} notícias")
    if not filtro or filtro == 'todos':
        with open(os.path.join(saida, 'paises.json'), 'w', encoding='utf-8') as fo:
            json.dump({'gerado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'ano': ap, 'ultimo_mes': [ua, mes_ult], 'paises': indice}, fo, ensure_ascii=False)
    # anos mais antigos: só os totais, para o validador conferir o histórico guardado no Mapa
    for ano in (anos[0] - 2, anos[0] - 1):
        for f, pref in (('exp', 'EXP'), ('imp', 'IMP')):
            arq = baixar(MDIC + f'comexstat-bd/ncm/{pref}_{ano}.csv', os.path.join(tmp, f'{pref}_{ano}.csv'))
            if not arq:
                continue
            with open(arq, encoding='latin-1', newline='') as fh:
                for r in csv.DictReader(fh, delimiter=';'):
                    v = float(r['VL_FOB'] or 0); a, m = int(r['CO_ANO']), int(r['CO_MES'])
                    if r['SG_UF_NCM'] in UF27:
                        total_mes[f][(a, m)] += v; uf_ano[f][(a, r['SG_UF_NCM'])] += v
                    else:
                        total_nd[f][a] += v
            os.remove(arq)
            log(f'{pref}_{ano}: totais para o validador')
    # gabarito para o validador do Mapa de Governo (MDIC, arquivos anuais; só os 27 estados)
    with open(os.path.join(saida, 'gabarito_comex.json'), 'w', encoding='utf-8') as fo:
        json.dump({'gerado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'fonte': MDIC + 'comexstat-bd/ncm/',
                   'criterio': 'soma dos 27 estados (SG_UF_NCM); exclui UF não declarada (ND), que o Mapa não guarda',
                   'ultimo_mes': {f: list(ultimo[f]) for f in ('exp', 'imp')},
                   'mensal': {f: {f'{a}-{m:02d}': round(v, 2) for (a, m), v in sorted(total_mes[f].items())} for f in ('exp', 'imp')},
                   'uf_ano': {f: {f'{a}-{u}': round(v, 2) for (a, u), v in sorted(uf_ano[f].items())} for f in ('exp', 'imp')},
                   'nd_ano': {f: {str(a): round(v, 2) for a, v in sorted(total_nd[f].items())} for f in ('exp', 'imp')}}, fo, ensure_ascii=False)
    log('ok')


if __name__ == '__main__':
    main(*sys.argv[1:3])

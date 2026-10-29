"""
Robô do Mapa de Governo · Captação de Recursos
Baixa os dados abertos do Transferegov.br (Discricionárias e Legais) e gera arquivos pequenos para o portal:
  programas.csv.gz        um programa por linha (prazos para propostas, ministério, ação orçamentária, natureza, UFs)
  propostas.csv.gz        propostas de MUNICÍPIOS desde ANO_MIN (objeto por extenso, situação, valores, programa,
                          convênio celebrado e emendas parlamentares que a financiaram)
  habilitados.csv.gz      programas com lista fechada de proponentes: id_programa;codigo IBGE do município
  meta.json               data da carga do governo, data do processamento e contagens
Só dados públicos. Uso: python3 scripts/processar.py PASTA_DE_SAIDA
"""
import csv, gzip, io, json, os, sys, time, urllib.request, zipfile, datetime

BASE = 'https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/'
ARQUIVOS = ['data_carga_siconv', 'siconv_programa', 'siconv_programa_proponentes', 'siconv_proponentes',
            'siconv_programa_proposta', 'siconv_proposta', 'siconv_convenio', 'siconv_emenda',
            'siconv_meta_crono_fisico', 'siconv_plano_aplicacao_detalhado', 'siconv_licitacao', 'siconv_contrato',
            'siconv_desembolso', 'siconv_historico_situacao']
N_FATIAS = 500   # detalhes de cada proposta em detalhes/NNN.json.gz (NNN = id % 500): o portal baixa só a fatia que precisa
ANO_MIN = int(os.environ.get('ANO_MIN', '2019'))
TMP = os.environ.get('FONTE_LOCAL') or '/tmp/tg'
csv.field_size_limit(10**9)
HOJE = datetime.date.today()


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def baixar(nome):
    destino = os.path.join(TMP, nome + '.zip')
    if os.environ.get('FONTE_LOCAL'):
        return os.path.exists(destino)
    os.makedirs(TMP, exist_ok=True)
    for t in range(1, 4):
        try:
            req = urllib.request.Request(BASE + nome + '.zip', headers={'User-Agent': 'robo-mapadegoverno'})
            with urllib.request.urlopen(req, timeout=900) as r, open(destino, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            zipfile.ZipFile(destino).testzip()
            log(f'baixou {nome} ({os.path.getsize(destino) / 1048576:.1f} MB)')
            return True
        except Exception as e:
            log(f'falha {nome} tentativa {t}: {e}')
            time.sleep(15 * t)
    return False


def linhas(nome):
    caminho = os.path.join(TMP, nome + '.zip')
    if not os.path.exists(caminho):
        return
    z = zipfile.ZipFile(caminho)
    membro = next((n for n in z.namelist() if n.lower().endswith('.csv')), z.namelist()[0])
    rd = csv.reader(io.TextIOWrapper(z.open(membro), encoding='utf-8-sig', newline=''), delimiter=';')
    cab = [c.strip().upper() for c in next(rd)]
    for r in rd:
        if len(r) < len(cab):
            r += [''] * (len(cab) - len(r))
        yield dict(zip(cab, r))


def data(s):
    s = (s or '').strip()
    try:
        d, m, a = s[:10].split('/')
        return f'{int(a):04d}-{int(m):02d}-{int(d):02d}'
    except Exception:
        return ''


def num(s):
    s = (s or '').strip()
    if not s:
        return ''
    try:
        return f"{float(s.replace('.', '').replace(',', '.') if ',' in s else s):.2f}"
    except Exception:
        return ''


def limpa(s, n):
    return ' '.join((s or '').split())[:n]


def gravar(caminho, cab, rows):
    with gzip.open(caminho, 'wt', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(cab)
        n = 0
        for r in rows:
            w.writerow(r)
            n += 1
    log(f'gravou {os.path.basename(caminho)}: {n} linhas, {os.path.getsize(caminho) / 1048576:.1f} MB')
    return n


def main(saida):
    os.makedirs(saida, exist_ok=True)
    falhas = [a for a in ARQUIVOS if not baixar(a)]
    obrig = {'siconv_programa', 'siconv_proposta', 'siconv_programa_proposta'}
    if obrig & set(falhas):
        log('arquivos essenciais faltando: ' + ', '.join(falhas))
        sys.exit(1)
    carga = next((r.get('DATA_CARGA', '') for r in linhas('data_carga_siconv')), '')

    # ---------- programas (o arquivo tem uma linha por programa x UF x natureza): junta por ID_PROGRAMA
    prog = {}
    for r in linhas('siconv_programa'):
        i = r['ID_PROGRAMA']
        p = prog.get(i)
        if not p:
            p = prog[i] = {
                'id': i, 'cod': r['COD_PROGRAMA'], 'orgao_cod': r['COD_ORGAO_SUP_PROGRAMA'], 'orgao': limpa(r['DESC_ORGAO_SUP_PROGRAMA'], 160),
                'nome': limpa(r['NOME_PROGRAMA'], 400), 'sit': r['SIT_PROGRAMA'], 'ano': r['ANO_DISPONIBILIZACAO'],
                'disp': data(r['DATA_DISPONIBILIZACAO']),
                'ini_prop': data(r['DT_PROG_INI_RECEB_PROP']), 'fim_prop': data(r['DT_PROG_FIM_RECEB_PROP']),
                'ini_emenda': data(r['DT_PROG_INI_EMENDA_PAR']), 'fim_emenda': data(r['DT_PROG_FIM_EMENDA_PAR']),
                'ini_benef': data(r['DT_PROG_INI_BENEF_ESP']), 'fim_benef': data(r['DT_PROG_FIM_BENEF_ESP']),
                'modalidade': set(), 'natureza': set(), 'ufs': set(), 'acao': set(),
                'subtipo': limpa(r.get('NOME_SUBTIPO_PROGRAMA', ''), 120), 'subtipo_desc': limpa(r.get('DESCRICAO_SUBTIPO_PROGRAMA', ''), 400),
            }
        for k, c in (('modalidade', 'MODALIDADE_PROGRAMA'), ('natureza', 'NATUREZA_JURIDICA_PROGRAMA'), ('ufs', 'UF_PROGRAMA'), ('acao', 'ACAO_ORCAMENTARIA')):
            v = (r.get(c) or '').strip()
            if v:
                p[k].add(v)
        for k, c in (('fim_prop', 'DT_PROG_FIM_RECEB_PROP'), ('fim_emenda', 'DT_PROG_FIM_EMENDA_PAR'), ('fim_benef', 'DT_PROG_FIM_BENEF_ESP')):
            d = data(r[c])
            if d > p[k]:
                p[k] = d
    log(f'programas no arquivo: {len(prog)}')

    # ---------- propostas de municípios
    pp = {}
    for r in linhas('siconv_programa_proposta'):
        pp.setdefault(r['ID_PROPOSTA'], r['ID_PROGRAMA'])
    props = {}
    cnpj_ibge = {}   # CNPJ da prefeitura -> código IBGE (para saber quem está na lista fechada de um programa)
    for r in linhas('siconv_proposta'):
        if 'Municipal' not in (r.get('NATUREZA_JURIDICA') or ''):
            continue
        if r.get('IDENTIF_PROPONENTE') and r.get('COD_MUNIC_IBGE'):
            cnpj_ibge[r['IDENTIF_PROPONENTE']] = r['COD_MUNIC_IBGE']
        try:
            ano = int(r.get('ANO_PROP') or 0)
        except ValueError:
            continue
        if ano < ANO_MIN:
            continue
        props[r['ID_PROPOSTA']] = [r['ID_PROPOSTA'], ano, data(r.get('DIA_PROPOSTA')), r.get('UF_PROPONENTE', ''), r.get('COD_MUNIC_IBGE', ''),
                                   limpa(r.get('MUNIC_PROPONENTE'), 80), limpa(r.get('DESC_ORGAO_SUP'), 160), limpa(r.get('DESC_ORGAO'), 160),
                                   limpa(r.get('MODALIDADE'), 60), limpa(r.get('OBJETO_PROPOSTA'), 500), limpa(r.get('ITEM_INVESTIMENTO'), 120),
                                   limpa(r.get('SIT_PROPOSTA'), 80), num(r.get('VL_GLOBAL_PROP')), num(r.get('VL_REPASSE_PROP')),
                                   pp.get(r['ID_PROPOSTA'], ''), '', '', '', '', '', '', '']
    log(f'propostas de municípios desde {ANO_MIN}: {len(props)}')
    for r in linhas('siconv_convenio'):
        p = props.get(r['ID_PROPOSTA'])
        if p:
            p[15:21] = [r['NR_CONVENIO'], limpa(r['SIT_CONVENIO'], 60), data(r['DIA_ASSIN_CONV']), num(r['VL_REPASSE_CONV']), num(r['VL_DESEMBOLSADO_CONV']), data(r['DIA_FIM_VIGENC_CONV'])]
    emendas = {}
    for r in linhas('siconv_emenda'):
        if r['ID_PROPOSTA'] in props and r.get('NOME_PARLAMENTAR'):
            emendas.setdefault(r['ID_PROPOSTA'], []).append('|'.join([limpa(r['NOME_PARLAMENTAR'], 80), limpa(r.get('TIPO_PARLAMENTAR'), 30), num(r.get('VALOR_REPASSE_PROPOSTA_EMENDA') or r.get('VALOR_REPASSE_EMENDA')), r.get('NR_EMENDA', '')]))
    for i, l in emendas.items():
        props[i][21] = ' ## '.join(l)[:900]
    usados = {p[14] for p in props.values() if p[14]}

    # ---------- programas que interessam: abertos agora, recentes ou usados por municípios
    hoje = HOJE.isoformat()
    def interessa(p):
        aberto = max(p['fim_prop'], p['fim_emenda'], p['fim_benef']) >= hoje
        muni = any('Municipal' in n or 'Consórcio' in n or 'Consorcio' in n for n in p['natureza'])
        return aberto or p['id'] in usados or (muni and p['ano'] >= str(ANO_MIN))
    n_prog = gravar(os.path.join(saida, 'programas.csv.gz'),
                    ['id', 'cod', 'orgao_cod', 'orgao', 'nome', 'sit', 'ano', 'disp', 'ini_prop', 'fim_prop', 'ini_emenda', 'fim_emenda', 'ini_benef', 'fim_benef',
                     'modalidade', 'natureza', 'ufs', 'acao', 'subtipo', 'subtipo_desc'],
                    ([p['id'], p['cod'], p['orgao_cod'], p['orgao'], p['nome'], p['sit'], p['ano'], p['disp'], p['ini_prop'], p['fim_prop'], p['ini_emenda'], p['fim_emenda'],
                      p['ini_benef'], p['fim_benef'], ','.join(sorted(p['modalidade'])), ' | '.join(sorted(p['natureza'])), ','.join(sorted(p['ufs'])),
                      ','.join(sorted(p['acao'])), p['subtipo'], p['subtipo_desc']] for p in prog.values() if interessa(p)))
    n_prop = gravar(os.path.join(saida, 'propostas.csv.gz'),
                    ['id', 'ano', 'data', 'uf', 'ibge', 'municipio', 'orgao_sup', 'orgao', 'modalidade', 'objeto', 'item', 'sit', 'vl_global', 'vl_repasse',
                     'id_programa', 'nr_convenio', 'sit_convenio', 'assinatura', 'vl_conv_repasse', 'vl_desembolsado', 'fim_vigencia', 'emendas'],
                    sorted(props.values(), key=lambda p: -int(p[0] or 0)))

    # ---------- programas com lista fechada de proponentes (só os municípios)
    muni_por_id = {}
    for r in linhas('siconv_proponentes'):
        ibge = cnpj_ibge.get(r.get('IDENTIF_PROPONENTE') or '')
        if ibge:
            muni_por_id[r['ID_PROPONENTE']] = ibge
    abertos = {p['id'] for p in prog.values() if max(p['fim_prop'], p['fim_emenda'], p['fim_benef']) >= hoje}
    hab = set()
    for r in linhas('siconv_programa_proponentes'):
        if r['ID_PROGRAMA'] in abertos and r['ID_PROPONENTE'] in muni_por_id:
            hab.add((r['ID_PROGRAMA'], muni_por_id[r['ID_PROPONENTE']]))
    n_hab = gravar(os.path.join(saida, 'habilitados.csv.gz'), ['id_programa', 'ibge'], sorted(hab))

    n_det = detalhes(saida, props)

    meta = {'data_carga_governo': carga, 'detalhes': n_det, 'processado_em': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'ano_min': ANO_MIN, 'programas': n_prog, 'programas_abertos': len(abertos), 'propostas': n_prop, 'habilitados': n_hab,
            'programas_com_lista_fechada': len({h[0] for h in hab}), 'falhas_download': falhas, 'fonte': BASE}
    with open(os.path.join(saida, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log(json.dumps(meta, ensure_ascii=False))


def detalhes(saida, props):
    """Para cada proposta que virou convênio: metas, itens comprados, licitações e contratos, repasses e histórico.
    Nada de dados pessoais: pagamentos a pessoas (bolsas, folha) ficam de fora; fornecedores só em contratos (empresas)."""
    alvo = {i: p for i, p in props.items() if p[15]}           # tem número de convênio
    conv = {p[15]: i for i, p in alvo.items()}
    d = {i: {} for i in alvo}
    def add(i, k, v, lim):
        l = d[i].setdefault(k, [])
        if len(l) < lim:
            l.append(v)
    for r in linhas('siconv_meta_crono_fisico'):
        i = r['ID_PROPOSTA']
        if i in d:
            add(i, 'metas', [r['NR_META'], limpa(r['DESC_META'], 400), r['QTD_META'], limpa(r['UND_FORNECIMENTO_META'], 30), num(r['VL_META']), data(r['DATA_INICIO_META']), data(r['DATA_FIM_META'])], 20)
    for r in linhas('siconv_plano_aplicacao_detalhado'):
        i = r['ID_PROPOSTA']
        if i in d:
            add(i, 'itens', [limpa(r['DESCRICAO_ITEM'], 300), limpa(r['TIPO_DESPESA_ITEM'], 20), limpa(r['NATUREZA_DESPESA'], 60), r['QTD_ITEM'], num(r['VALOR_UNITARIO_ITEM']), num(r['VALOR_TOTAL_ITEM']), limpa(r['SIT_ITEM'], 20)], 60)
    lic = {}
    for r in linhas('siconv_licitacao'):
        i = conv.get(r['NR_CONVENIO'])
        if i:
            lic[r['ID_LICITACAO']] = i
            add(i, 'licitacoes', [r['ID_LICITACAO'], limpa(r['TP_PROCESSO_COMPRA'], 40), limpa(r['MODALIDADE_LICITACAO'], 40), limpa(r['NR_LICITACAO'], 30), limpa(r['STATUS_LICITACAO'], 30), num(r['VALOR_LICITACAO']), data(r['DATA_HOMOLOGACAO_LICITACAO']) or data(r['DATA_PUBLICACAO_LICITACAO'])], 15)
    for r in linhas('siconv_contrato'):
        i = lic.get(r['ID_LICITACAO'])
        if i:
            forn = r['ID_FORNECEDOR_CONTRATO'] or ''
            empresa = len(''.join(c for c in forn if c.isdigit())) == 14   # CNPJ: empresa (CPF de pessoa fica de fora)
            add(i, 'contratos', [limpa(r['OBJETO_CONTRATO'], 300), limpa(r['NOME_FORNECEDOR_CONTRATO'], 120) if empresa else '', num(r['VALOR_GLOBAL_CONTRATO']), data(r['DATA_ASSINATURA_CONTRATO']), limpa(r['TIPO_AQUISICAO_CONTRATO'], 30)], 15)
    for r in linhas('siconv_desembolso'):
        i = conv.get(r['NR_CONVENIO'])
        if i:
            add(i, 'repasses', [data(r['DATA_DESEMBOLSO']), num(r['VL_DESEMBOLSADO'])], 40)
    hist = {}
    for r in linhas('siconv_historico_situacao'):
        i = r['ID_PROPOSTA']
        if i in d:
            hist.setdefault(i, {})[r['HISTORICO_SIT']] = min(hist.get(i, {}).get(r['HISTORICO_SIT'], 'z'), r['DIA_HISTORICO_SIT'][:10])
    for i, h in hist.items():
        d[i]['historico'] = sorted([[data(v), k] for k, v in h.items()], key=lambda x: x[0])[-25:]
    for i in d:
        if 'itens' in d[i]:
            d[i]['itens'].sort(key=lambda x: -float(x[5] or 0))
    pasta = os.path.join(saida, 'detalhes')
    os.makedirs(pasta, exist_ok=True)
    fatias = {}
    for i, v in d.items():
        if v:
            fatias.setdefault(int(i) % N_FATIAS, {})[i] = v
    for f, dados in fatias.items():
        with gzip.open(os.path.join(pasta, f'{f:03d}.json.gz'), 'wt', encoding='utf-8') as fh:
            json.dump(dados, fh, ensure_ascii=False, separators=(',', ':'))
    tam = sum(os.path.getsize(os.path.join(pasta, x)) for x in os.listdir(pasta))
    log(f'detalhes: {sum(len(x) for x in fatias.values())} convênios em {len(fatias)} fatias, {tam / 1048576:.1f} MB')
    return sum(len(x) for x in fatias.values())


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'saida')

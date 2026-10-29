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
            'siconv_programa_proposta', 'siconv_proposta', 'siconv_convenio', 'siconv_emenda']
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

    meta = {'data_carga_governo': carga, 'processado_em': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'ano_min': ANO_MIN, 'programas': n_prog, 'programas_abertos': len(abertos), 'propostas': n_prop, 'habilitados': n_hab,
            'programas_com_lista_fechada': len({h[0] for h in hab}), 'falhas_download': falhas, 'fonte': BASE}
    with open(os.path.join(saida, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'saida')

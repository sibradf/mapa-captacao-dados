"""
Robô do Mapa de Governo · CAUC dos municípios
Baixa do Tesouro Transparente (dados abertos) a planilha diária "CAUC - Municípios" e gera:
  cauc_municipios.csv.gz   ibge;uf;nome;<um campo por item do CAUC>
                           valor de cada item: AAAA-MM-DD (comprovado, válido até a data) | ! (não comprovado) | D (desabilitado) | vazio
  cauc_meta.json           data da extração do Tesouro, itens (código e descrição), contagens e o recurso usado
Só dados públicos. Não publica nada se a planilha vier vazia ou estranha.
Uso: python3 scripts/cauc.py PASTA_DE_SAIDA
"""
import csv, gzip, io, json, os, re, sys, time, unicodedata, urllib.request, zipfile, datetime

CKAN = 'https://www.tesourotransparente.gov.br/ckan/api/3/action/'
PACOTE = os.environ.get('CAUC_PACOTE', '72b5f371-0c35-4613-8076-c99c821a6410')
UA = {'User-Agent': 'robo-mapadegoverno (+https://mapadegoverno.com.br)'}

# Descrições oficiais dos itens (metadados do Tesouro: "Metadados TT CAUC - Municípios")
ITENS = {
    '1.1': 'Regularidade quanto a tributos, contribuições previdenciárias federais e Dívida Ativa da União',
    '1.2': 'Regularidade no pagamento de precatórios judiciais',
    '1.3': 'Regularidade quanto às contribuições para o FGTS',
    '1.4': 'Adimplência em empréstimos e financiamentos concedidos pela União',
    '1.5': 'Regularidade perante o Poder Público Federal',
    '2.1.1': 'Prestação de contas de recursos federais recebidos anteriormente (SIAFI/Subsistema Transferências)',
    '2.1.2': 'Prestação de contas de recursos federais recebidos anteriormente (Transferegov)',
    '3.1.1': 'Publicação do Relatório de Gestão Fiscal (RGF)',
    '3.1.2': 'Encaminhamento do RGF ao Siconfi',
    '3.2.1': 'Publicação do Relatório Resumido de Execução Orçamentária (RREO)',
    '3.2.2': 'Encaminhamento do RREO ao Siconfi',
    '3.2.3': 'Encaminhamento do Anexo 8 do RREO ao SIOPE',
    '3.2.4': 'Encaminhamento do Anexo 12 do RREO ao SIOPS',
    '3.3': 'Encaminhamento das contas anuais',
    '3.4.1': 'Encaminhamento da Matriz de Saldos Contábeis mensal',
    '3.4.2': 'Encaminhamento da Matriz de Saldos Contábeis de encerramento',
    '3.5': 'Encaminhamento de informações para o Cadastro da Dívida Pública (CDP)',
    '3.6': 'Transparência da execução orçamentária e financeira em meio eletrônico de acesso público',
    '3.7': 'Adoção do Siafic',
    '4.1': 'Exercício da plena competência tributária',
    '4.2': 'Regularidade previdenciária',
    '5.1': 'Aplicação mínima de recursos em educação',
    '5.2': 'Aplicação mínima de recursos em saúde',
    '5.3': 'Limite de despesas com Parcerias Público-Privadas (PPP)',
    '5.4': 'Limite de operações de crédito, inclusive por antecipação de receita',
    '5.5': 'Aplicação mínima do Fundeb na remuneração dos profissionais da educação básica',
    '5.6': 'Aplicação mínima da complementação da União ao Fundeb em despesas de capital',
    '5.7': 'Aplicação de 50% da complementação VAAT do Fundeb na educação infantil',
}


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def sem_acento(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').lower()


def http(url, tempo=300):
    for t in range(1, 4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=tempo) as r:
                return r.read()
        except Exception as e:
            log(f'falha {url} tentativa {t}: {e}')
            time.sleep(10 * t)
    raise RuntimeError('não baixou ' + url)


def escolher_recurso():
    try:
        pac = json.loads(http(CKAN + 'package_show?id=' + PACOTE, 60))['result']
    except Exception as e:
        log(f'pacote {PACOTE} não abriu ({e}); procurando por "CAUC"')
        res = json.loads(http(CKAN + 'package_search?q=CAUC&rows=20', 60))['result']['results']
        pac = next(p for p in res if 'cauc' in sem_acento(p.get('title', '')))
    log(f'conjunto: {pac.get("title")} ({len(pac.get("resources", []))} recursos)')
    cands = []
    for r in pac.get('resources', []):
        nome = sem_acento((r.get('name') or '') + ' ' + (r.get('url') or ''))
        fmt = (r.get('format') or os.path.splitext(r.get('url') or '')[1].lstrip('.')).lower()
        log(f'  recurso: {r.get("name")!r} formato={fmt} atualizado={r.get("last_modified") or r.get("created")} url={r.get("url")}')
        if 'munic' in nome and 'metadad' not in nome and fmt in ('csv', 'xlsx', 'xls', 'zip', 'ods'):
            cands.append((r.get('last_modified') or r.get('created') or '', {'csv': 3, 'xlsx': 2, 'zip': 1}.get(fmt, 0), r, fmt))
    if not cands:
        raise RuntimeError('nenhum recurso de municípios em CSV/XLSX no conjunto do CAUC')
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cands[0][2], cands[0][3]


def tabela(bruto, fmt):
    """Devolve a lista de linhas (listas de texto) da planilha"""
    if fmt == 'zip' or bruto[:2] == b'PK' and fmt != 'xlsx':
        z = zipfile.ZipFile(io.BytesIO(bruto))
        nomes = [n for n in z.namelist() if n.lower().endswith(('.csv', '.xlsx'))]
        if not nomes:
            raise RuntimeError('zip sem CSV/XLSX: ' + ', '.join(z.namelist()[:5]))
        n = nomes[0]
        return tabela(z.read(n), 'xlsx' if n.lower().endswith('.xlsx') else 'csv')
    if fmt in ('xlsx', 'xls', 'ods'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(bruto), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        out = []
        for row in ws.iter_rows(values_only=True):
            out.append(['' if v is None else (v.strftime('%d/%m/%Y') if isinstance(v, (datetime.date, datetime.datetime)) else str(v)) for v in row])
        return out
    for enc in ('utf-8-sig', 'latin-1'):
        try:
            txt = bruto.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ';' if txt[:5000].count(';') >= txt[:5000].count(',') else ','
    return list(csv.reader(io.StringIO(txt), delimiter=sep))


def valor(v):
    v = str(v or '').strip()
    if not v:
        return ''
    if v.startswith('!'):
        return '!'
    if sem_acento(v).startswith('desab'):
        return 'D'
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})', v)
    if m:
        return f'{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', v)
    if m:
        return m.group(0)
    return '?' + v[:20]  # valor desconhecido: guarda para o validador ver


def main(saida):
    os.makedirs(saida, exist_ok=True)
    if os.environ.get('CAUC_ARQUIVO'):  # teste local
        rec = {'name': 'local', 'url': os.environ['CAUC_ARQUIVO']}; fmt = os.path.splitext(rec['url'])[1].lstrip('.').lower()
        bruto = open(rec['url'], 'rb').read()
    else:
        rec, fmt = escolher_recurso()
        log(f'baixando {rec.get("url")} ({fmt})')
        bruto = http(rec['url'], 600)
    log(f'{len(bruto) / 1048576:.1f} MB')
    linhas = tabela(bruto, fmt)
    log(f'{len(linhas)} linhas; primeiras: {linhas[:3]}')

    # data de extração: costuma estar na primeira célula (A1)
    extracao = ''
    for r in linhas[:5]:
        for c in r[:3]:
            m = re.search(r'(\d{2})/(\d{2})/(\d{4})', str(c))
            if m and not extracao:
                extracao = f'{m.group(3)}-{m.group(2)}-{m.group(1)}'

    # linha de cabeçalho: a que tem "IBGE"
    h = next((i for i, r in enumerate(linhas[:30]) if any('ibge' in sem_acento(c) for c in r)), None)
    if h is None:
        raise RuntimeError('cabeçalho com "IBGE" não encontrado')
    cab = [str(c).strip() for c in linhas[h]]
    log(f'cabeçalho (linha {h + 1}): {cab}')
    col = {}
    for i, c in enumerate(cab):
        s = sem_acento(c)
        cod = re.match(r'^(\d+(?:\.\d+)+)', c.strip())
        if cod and cod.group(1) in ITENS:
            col[cod.group(1)] = i
        elif 'ibge' in s:
            col['ibge'] = i
        elif s in ('uf', 'sigla uf') or s.startswith('uf'):
            col.setdefault('uf', i)
        elif 'nome' in s or 'ente' in s:
            col.setdefault('nome', i)
    itens = [k for k in ITENS if k in col]
    faltam = [k for k in ITENS if k not in col]
    log(f'itens encontrados: {len(itens)}; ausentes: {faltam}')
    if 'ibge' not in col or len(itens) < 15:
        raise RuntimeError('colunas inesperadas; nada publicado')

    rows, desconhecidos = [], {}
    for r in linhas[h + 1:]:
        if len(r) <= col['ibge']:
            continue
        ib = re.sub(r'\D', '', str(r[col['ibge']]))[:7]
        if len(ib) == 6:
            ib = ib  # alguns arquivos trazem 6 dígitos (sem verificador); o portal aceita os dois
        if len(ib) not in (6, 7):
            continue
        vals = []
        for k in itens:
            v = valor(r[col[k]] if col[k] < len(r) else '')
            if v.startswith('?'):
                desconhecidos[v] = desconhecidos.get(v, 0) + 1
            vals.append(v)
        rows.append([ib, str(r[col['uf']]).strip() if 'uf' in col else '', ' '.join(str(r[col['nome']]).split()) if 'nome' in col else ''] + vals)
    log(f'{len(rows)} municípios; valores desconhecidos: {dict(list(desconhecidos.items())[:10])}')
    if len(rows) < 5000:
        raise RuntimeError(f'só {len(rows)} municípios; nada publicado')

    with gzip.open(os.path.join(saida, 'cauc_municipios.csv.gz'), 'wt', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['ibge', 'uf', 'nome'] + itens)
        w.writerows(rows)
    pend = {k: sum(1 for r in rows if r[3 + i] == '!') for i, k in enumerate(itens)}
    meta = {'extracao_tesouro': extracao, 'processado_em': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'municipios': len(rows), 'itens': [{'codigo': k, 'descricao': ITENS[k]} for k in itens], 'itens_ausentes': faltam,
            'pendencias_por_item': pend, 'municipios_com_pendencia': sum(1 for r in rows if '!' in r[3:]),
            'valores_desconhecidos': desconhecidos, 'recurso': {'nome': rec.get('name'), 'url': rec.get('url'), 'atualizado': rec.get('last_modified')},
            'fonte': 'Tesouro Transparente · CAUC - Municípios (dados abertos)'}
    with open(os.path.join(saida, 'cauc_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log(f'ok: extração {extracao}, {meta["municipios_com_pendencia"]} municípios com alguma pendência')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/cauc')

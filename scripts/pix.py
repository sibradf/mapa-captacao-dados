"""
Robô do Mapa de Governo · Emendas Pix (transferências especiais) dos municípios
Fonte: API pública do Transferegov (módulo Transferências Especiais), só leitura.
Gera pix.csv.gz: uma linha por plano de ação de município (ano >= ANO_MIN) com a situação do plano de trabalho,
a última análise, o relatório de gestão e quanto foi empenhado e transferido.
Uso: python3 scripts/pix.py PASTA_DE_SAIDA
"""
import csv, gzip, io, json, os, sys, time, unicodedata, urllib.request, datetime

B = 'https://api.transferegov.gestao.gov.br/transferenciasespeciais/'
ANO_MIN = int(os.environ.get('ANO_MIN_PIX', '2020'))
UA = {'User-Agent': 'robo-mapadegoverno (+https://mapadegoverno.com.br)', 'Accept': 'application/json'}
CNPJ_IBGE = 'https://raw.githubusercontent.com/sibradf/mapa-captacao-dados/dados/cnpj_ibge.csv.gz'


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def get(url, tempo=180):
    for t in range(1, 6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=tempo) as r:
                return json.loads(r.read())
        except Exception as e:
            log(f'falha ({t}) {url[:140]}: {e}')
            time.sleep(8 * t)
    raise RuntimeError('não baixou ' + url)


def tudo(tabela, campos, filtro='', chave='', lote=1000):  # a API devolve no máximo 1000 por página
    """Lê a tabela inteira em páginas (ordenada pela chave para não perder linhas)"""
    out, off = [], 0
    while True:
        url = f'{B}{tabela}?select={campos}&order={chave}.asc&limit={lote}&offset={off}' + (('&' + filtro) if filtro else '')
        l = get(url)
        out.extend(l)
        if len(l) < lote:
            break
        off += lote
    log(f'{tabela}: {len(out)} linhas')
    return out


def norm(s):
    s = ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').lower()
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in s).split())


def main(saida):
    os.makedirs(saida, exist_ok=True)
    # CNPJ da prefeitura -> código IBGE (do robô principal)
    cnpj_ibge = {}
    try:
        with urllib.request.urlopen(urllib.request.Request(CNPJ_IBGE, headers=UA), timeout=120) as r:
            for row in csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(r.read())), encoding='utf-8'), delimiter=';'):
                cnpj_ibge[row['cnpj']] = row['ibge']
    except Exception as e:
        log(f'sem cnpj_ibge ({e}): o servidor casa pelo nome')
    log(f'cnpj_ibge: {len(cnpj_ibge)}')

    pa = tudo('plano_acao_especial', 'id_plano_acao,ano_plano_acao,situacao_plano_acao,cnpj_beneficiario_plano_acao,nome_beneficiario_plano_acao,uf_beneficiario_plano_acao,'
              'nome_parlamentar_emenda_plano_acao,numero_emenda_parlamentar_plano_acao,codigo_descricao_areas_politicas_publicas_plano_acao,motivo_impedimento_plano_acao,'
              'valor_custeio_plano_acao,valor_investimento_plano_acao,id_programa', f'ano_plano_acao=gte.{ANO_MIN}', 'id_plano_acao')
    pa = [r for r in pa if norm(r.get('nome_beneficiario_plano_acao')).startswith('municipio')]
    ids = {r['id_plano_acao'] for r in pa}
    log(f'planos de ação de municípios desde {ANO_MIN}: {len(pa)}')

    pt = {r['id_plano_acao']: r for r in tudo('plano_trabalho_especial', 'id_plano_trabalho,id_plano_acao,situacao_plano_trabalho,data_inicio_execucao_plano_trabalho,'
                                                'data_fim_execucao_plano_trabalho,prazo_execucao_meses_plano_trabalho', '', 'id_plano_trabalho') if r['id_plano_acao'] in ids}
    pt_por_id = {r['id_plano_trabalho']: r['id_plano_acao'] for r in pt.values()}
    pend = {}
    for r in tudo('orgao_analise_pendente_especial', 'id_plano_trabalho,nome_orgao_analise_pendente_pt', '', 'id_analise_pendente'):
        if r['id_plano_trabalho'] in pt_por_id:
            pend.setdefault(pt_por_id[r['id_plano_trabalho']], []).append(r['nome_orgao_analise_pendente_pt'])
    ult = {}
    for r in tudo('plano_trabalho_analise_especial', 'id_plano_trabalho_analise,id_plano_trabalho,situacao_parecer_analise_pt,situacao_analise_pt,data_analise_pt,nome_orgao_analise_pt',
                  '', 'id_plano_trabalho_analise'):
        a = pt_por_id.get(r.get('id_plano_trabalho'))
        if a is not None and (a not in ult or (r.get('data_analise_pt') or '') >= (ult[a].get('data_analise_pt') or '')):
            ult[a] = r
    rg = {}
    for r in tudo('relatorio_gestao_novo_especial', 'id_relatorio_gestao_novo,id_plano_acao,data_e_hora_relatorio_gestao_novo,tipo_relatorio_gestao_novo,situacao_relatorio_gestao_novo,'
                  'valor_executado_relatorio_gestao_novo,valor_pendente_relatorio_gestao_novo', '', 'id_relatorio_gestao_novo'):
        a = r['id_plano_acao']
        if a in ids and (a not in rg or (r.get('data_e_hora_relatorio_gestao_novo') or '') >= (rg[a].get('data_e_hora_relatorio_gestao_novo') or '')):
            rg[a] = r
    obj = {}
    for r in tudo('executor_especial', 'id_executor,id_plano_acao,objeto_executor', '', 'id_executor'):
        if r['id_plano_acao'] in ids and r.get('objeto_executor'):
            obj.setdefault(r['id_plano_acao'], []).append(' '.join(str(r['objeto_executor']).split())[:200])
    emp, emp_pa = {}, {}
    for r in tudo('empenho_especial', 'id_empenho,id_plano_acao,valor_empenho', '', 'id_empenho'):
        if r['id_plano_acao'] in ids:
            emp[r['id_plano_acao']] = emp.get(r['id_plano_acao'], 0.0) + float(r.get('valor_empenho') or 0)
            emp_pa[r['id_empenho']] = r['id_plano_acao']
    transf, ult_t = {}, {}
    for r in tudo('documento_habil_especial', 'id_dh,id_empenho,valor_dh,situacao_dh,data_emissao_dh', '', 'id_dh'):
        a = emp_pa.get(r.get('id_empenho'))
        if a is not None and int(r.get('situacao_dh') or 0) == 3:  # "Enviado com Sucesso"
            transf[a] = transf.get(a, 0.0) + float(r.get('valor_dh') or 0)
            ult_t[a] = max(ult_t.get(a, ''), r.get('data_emissao_dh') or '')

    rows, sem_ibge = [], 0
    for r in pa:
        a = r['id_plano_acao']
        ib = cnpj_ibge.get(r.get('cnpj_beneficiario_plano_acao') or '', '')
        if not ib:
            sem_ibge += 1
        p, an, g = pt.get(a, {}), ult.get(a, {}), rg.get(a, {})
        f2 = lambda v: f'{float(v):.2f}' if v not in (None, '') else ''
        rows.append([a, r['ano_plano_acao'], ib, r.get('cnpj_beneficiario_plano_acao') or '', r.get('uf_beneficiario_plano_acao') or '', r.get('nome_beneficiario_plano_acao') or '',
                     r.get('situacao_plano_acao') or '', ' '.join(str(r.get('motivo_impedimento_plano_acao') or '').split())[:200],
                     r.get('nome_parlamentar_emenda_plano_acao') or '', r.get('numero_emenda_parlamentar_plano_acao') or '',
                     ' '.join(str(r.get('codigo_descricao_areas_politicas_publicas_plano_acao') or '').split())[:200],
                     f2(r.get('valor_custeio_plano_acao')), f2(r.get('valor_investimento_plano_acao')), ' | '.join(obj.get(a, [])[:3])[:400],
                     p.get('situacao_plano_trabalho') or '', (p.get('data_inicio_execucao_plano_trabalho') or '')[:10], (p.get('data_fim_execucao_plano_trabalho') or '')[:10],
                     p.get('prazo_execucao_meses_plano_trabalho') or '', ', '.join(pend.get(a, []))[:200],
                     an.get('situacao_parecer_analise_pt') or '', (an.get('data_analise_pt') or '')[:10], an.get('nome_orgao_analise_pt') or '',
                     g.get('tipo_relatorio_gestao_novo') or '', g.get('situacao_relatorio_gestao_novo') or '', (g.get('data_e_hora_relatorio_gestao_novo') or '')[:10],
                     f2(g.get('valor_pendente_relatorio_gestao_novo')), f2(emp.get(a)), f2(transf.get(a)), ult_t.get(a, '')])
    log(f'{len(rows)} planos; {sem_ibge} sem código IBGE pelo CNPJ (o servidor casa pelo nome)')
    if len(rows) < 1000:
        raise RuntimeError('poucos planos; nada publicado')
    cab = ['id', 'ano', 'ibge', 'cnpj', 'uf', 'nome', 'sit_pa', 'motivo_impedimento', 'parlamentar', 'emenda', 'areas', 'vl_custeio', 'vl_investimento', 'objeto',
           'sit_pt', 'pt_inicio', 'pt_fim', 'pt_meses', 'analise_pendente', 'ult_parecer', 'ult_parecer_data', 'ult_parecer_orgao',
           'rg_tipo', 'rg_situacao', 'rg_data', 'rg_valor_pendente', 'vl_empenhado', 'vl_transferido', 'ult_transferencia']
    with gzip.open(os.path.join(saida, 'pix.csv.gz'), 'wt', encoding='utf-8', newline='') as f:
        w = csv.writer(f, delimiter=';'); w.writerow(cab); w.writerows(rows)
    sits = {}
    for r in rows:
        sits[r[14]] = sits.get(r[14], 0) + 1
    meta = {'processado_em': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'ano_min': ANO_MIN, 'planos': len(rows), 'sem_ibge': sem_ibge,
            'situacoes_plano_trabalho': sits, 'fonte': B}
    with open(os.path.join(saida, 'pix_meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log(json.dumps(meta, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/pix')

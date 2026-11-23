#!/usr/bin/env python3
"""
Robô do Mapa de Governo · Saúde: bases do DATASUS (TabNet) por município
O TabNet não atende o servidor do Mapa (fica fora do Brasil); o GitHub consegue. Este robô faz as mesmas
consultas que o sistema Saúde fazia (saude.mapadegoverno.com.br/app/importar.php) e publica no ramo "saude":
  tabnet_<fonte>.csv.gz   ano;codigo6;ind;valor   (codigo6 = município com 6 dígitos, como o TabNet devolve)
  tabnet_meta.json        por fonte: anos, gerado, erro
Fontes: sinasc (nascimentos), sim (óbitos por capítulo), infantil (óbitos infantis), leitos (CNES).
Uma fonte que falhar não apaga a publicação anterior dela.
"""
import csv, datetime, gzip, html, io, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request

TABNET = os.environ.get('TABNET_URL', 'http://tabnet.datasus.gov.br/cgi/')
DEFS = {'sinasc': 'sinasc/cnv/nvbr.def', 'sim': 'sim/cnv/obt10br.def', 'infantil': 'sim/cnv/inf10br.def', 'leitos': 'cnes/cnv/leiintbr.def'}
ANOS = int(os.environ.get('TABNET_ANOS', '3'))
UA = {'User-Agent': 'Mozilla/5.0 (MapaDeGoverno-robo; +https://mapadegoverno.com.br)'}

# mesmas peças do sistema Saúde: [coluna, categorias somadas]
PECAS = {
    'sinasc': {'q_pre7': [[r'consult', r'pre.?natal'], [r'7 ou mais', r'7 e mais', r'mais de 6']],
               'q_ces': [[r'tipo de parto', r'parto'], [r'cesar']],
               'q_adol': [[r'idade da mae', r'idade mae'], [r'10 a 14', r'15 a 19', r'menor de 10', r'menos de 15']],
               'q_baixo': [[r'peso'], [r'menos de 500', r'500 a 999', r'1000 a 1499', r'1500 a 2499', r'menos de 2500']],
               'q_prem': [[r'duracao', r'gestacao'], [r'menos de 22', r'22 a 27', r'28 a 31', r'32 a 36', r'menos de 37']]},
    'sim': {'caps': None},
    'infantil': {'total': None},
    'leitos': {'existente': None, 'sus': None},
}
CAPS = {'q_cap_circ': [r'circulat'], 'q_cap_neo': [r'neoplas', r'tumor'], 'q_cap_resp': [r'respirat'], 'q_cap_ext': [r'causas externas'], 'q_cap_inf': [r'infecc']}


def log(m):
    print(time.strftime('%H:%M:%S'), m, flush=True)


def norm(s):
    s = unicodedata.normalize('NFKD', str(s).strip().lower()).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9 ]+', ' ', s).strip()


def http(url, dados=None, tempo=300):
    for t in range(1, 4):
        try:
            cab = dict(UA)
            if dados is not None:
                cab['Content-Type'] = 'application/x-www-form-urlencoded'
                cab['Referer'] = url.replace('tabcgi.exe', 'deftohtm.exe')
            with urllib.request.urlopen(urllib.request.Request(url, data=dados, headers=cab), timeout=tempo) as r:
                b = r.read()
            return b.decode('utf-8') if b[:3] == b'\xef\xbb\xbf' else b.decode('windows-1252', 'replace')
        except Exception as e:
            log(f'falha {url} tentativa {t}: {e}')
            time.sleep(20 * t)
    raise RuntimeError('TabNet não respondeu: ' + url)


def formulario(defi):
    b = http(TABNET + 'deftohtm.exe?' + defi, tempo=180)
    out = {}
    for m in re.finditer(r'<select\b([^>]*)>(.*?)</select>', b, re.S | re.I):
        at = m.group(1)
        nome = re.search(r'name\s*=\s*"?([^"\s>]+)', at, re.I)
        ide = re.search(r'id\s*=\s*"?([^"\s>]+)', at, re.I)
        ide = (ide or nome).group(1) if (ide or nome) else ''
        ops = []
        for o in re.finditer(r'<option\b([^>]*)>(.*?)(?=<option\b|$)', m.group(2), re.S | re.I):
            v = re.search(r'value\s*=\s*"([^"]*)"', o.group(1), re.I) or re.search(r"value\s*=\s*'([^']*)'", o.group(1), re.I) or re.search(r'value\s*=\s*([^\s>]+)', o.group(1), re.I)
            txt = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', o.group(2)))).strip()
            ops.append((html.unescape(v.group(1)) if v else txt, txt))
        out[ide] = {'name': nome.group(1) if nome else ide, 'opcoes': ops}
    for k in ('L', 'C', 'I', 'A'):
        if not out.get(k, {}).get('opcoes'):
            raise RuntimeError(f'formulário do TabNet ({defi}) sem o campo {k}')
    extras = {}
    for m in re.finditer(r'<input\b([^>]*)>', b, re.I):
        at = m.group(1)
        n = re.search(r'name\s*=\s*"?([^"\s>]+)', at, re.I)
        if not n or n.group(1) in ('formato', 'mostre'):
            continue
        mt = re.search(r'type\s*=\s*"?([^"\s>]+)', at, re.I)
        tipo = mt.group(1).lower() if mt else ''
        v = re.search(r'value\s*=\s*"([^"]*)"', at, re.I)
        if tipo == 'hidden' or (tipo in ('checkbox', 'radio') and re.search(r'\bchecked\b', at, re.I)):
            extras[n.group(1)] = html.unescape(v.group(1)) if v and v.group(1) != '' else 'on'
    out['__extras'] = {'name': '', 'opcoes': [], 'campos': extras}
    return out


def opcao(campo, res, oque):
    for re_ in res:
        for v, t in campo['opcoes']:
            if re.search(re_, norm(t)):
                return v
    raise RuntimeError(f"opção '{oque}' não encontrada (há: {' | '.join(t for _, t in campo['opcoes'][:12])})")


def anos_form(form):
    o = {}
    for v, t in form['A']['opcoes']:
        m = re.search(r'(19|20)\d\d', t)
        if m and int(m.group(0)) not in o:
            o[int(m.group(0))] = v
    return dict(sorted(o.items(), reverse=True))


def consulta(defi, form, coluna, incremento, arquivo):
    campos = {form['L']['name']: opcao(form['L'], [r'^municipio', r'munic'], 'Município'),
              form['C']['name']: opcao(form['C'], coluna, ','.join(coluna)) if coluna else opcao(form['C'], [r'nao ativa', r'ativa'], 'Não ativa'),
              form['I']['name']: opcao(form['I'], incremento, ','.join(incremento)),
              form['A']['name']: arquivo}
    for k, c in form.items():
        if k not in ('L', 'C', 'I', 'A', '__extras') and c['opcoes']:
            campos[c['name']] = c['opcoes'][0][0]  # filtros: todas as categorias
    for k, v in form['__extras']['campos'].items():
        campos.setdefault(k, v)
    campos['formato'] = 'prn'
    campos['mostre'] = 'Mostra'
    corpo = '&'.join(urllib.parse.quote(str(k).encode('windows-1252', 'replace')) + '=' + urllib.parse.quote(str(v).encode('windows-1252', 'replace')) for k, v in campos.items())
    return ler(http(TABNET + 'tabcgi.exe?' + defi, corpo.encode('ascii'), 300), defi)


def ler(b, defi):
    linhas = []
    m = re.search(r'<pre[^>]*>(.*?)</pre>', b, re.S | re.I)
    if m:
        for l in html.unescape(re.sub(r'<[^>]+>', '', m.group(1))).splitlines():
            if l.strip() and ';' in l:
                linhas.append([c.strip() for c in next(csv.reader([l], delimiter=';'))])
    else:
        for tr in re.findall(r'<tr\b.*?</tr>', b, re.S | re.I):
            l = [html.unescape(re.sub(r'<[^>]+>', '', c)).strip() for c in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', tr, re.S | re.I)]
            if len(l) > 1:
                linhas.append(l)
    if len(linhas) < 2:
        txt = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', b)))
        raise RuntimeError(f'TabNet {defi} sem tabela: {txt[-300:]}')
    cab = [norm(h) for h in linhas.pop(0)]
    dados = {}
    for l in linhas:
        m = re.match(r'^\s*"?(\d{6})\b', l[0])
        if not m:
            continue
        vals = {}
        for i, h in enumerate(cab):
            if i == 0:
                continue
            v = (l[i] if i < len(l) else '').replace('.', '').replace(' ', '')
            vals[h] = 0.0 if v in ('', '-') else float(v.replace(',', '.'))
        dados[m.group(1)] = vals
    if not dados:
        raise RuntimeError(f'TabNet {defi}: nenhuma linha de município')
    return dados


def somar(vals, res):
    return sum(v for h, v in vals.items() if h != 'total' and any(re.search(r, h) for r in res))


def total(vals):
    return vals['total'] if 'total' in vals else sum(vals.values())


def peca(f, p, form, arq):
    defi = DEFS[f]
    q = {}
    if f == 'sinasc':
        col, cats = PECAS['sinasc'][p]
        for c, v in consulta(defi, form, col, [r'resid', r'nascim'], arq).items():
            q[c] = {'q_nasc': total(v), p: somar(v, cats)}
    elif f == 'sim':
        for c, v in consulta(defi, form, [r'capitulo', r'cid.?10'], [r'resid', r'obitos'], arq).items():
            q[c] = {'q_obitos': total(v), **{k: somar(v, r) for k, r in CAPS.items()}}
    elif f == 'infantil':
        for c, v in consulta(defi, form, None, [r'resid', r'obitos'], arq).items():
            q[c] = {'q_obt_inf': total(v)}
    else:
        ind = 'q_leitos_sus' if p == 'sus' else 'q_leitos'
        inc = [r'^quantidade sus$', r'(?<!nao )sus$'] if p == 'sus' else [r'existente', r'quantidade']
        for c, v in consulta(defi, form, None, inc, arq).items():
            q[c] = {ind: total(v)}
    return q


def fonte(f):
    form = formulario(DEFS[f])
    todos = anos_form(form)
    if f == 'leitos':
        anos = dict(list(todos.items())[:1])  # leitos: o mês mais recente
        quantos = 1
    else:
        anos = {a: v for a, v in todos.items() if a < datetime.date.today().year}  # ano corrente: preliminar
        quantos = ANOS
    linhas, feitos, vazios = [], [], []
    for ano, arq in anos.items():
        if len(feitos) >= quantos:
            break
        q = {}
        try:
            for p in PECAS[f]:
                parte = peca(f, p, form, arq)
                if len(parte) < 1000:
                    raise RuntimeError(f'só {len(parte)} municípios')
                for c, v in parte.items():
                    q.setdefault(c, {}).update(v)
                log(f'{f} {ano}/{p}: {len(parte)} municípios')
        except RuntimeError as e:
            if not q and ('sem tabela' in str(e) or 'só ' in str(e)):
                log(f'{f} {ano} sem dados, pulado: {str(e)[:200]}')
                vazios.append(ano)
                continue
            raise
        for c, vals in q.items():
            for ind, v in vals.items():
                linhas.append([ano, c, ind, round(v, 2)])
        feitos.append(ano)
    if not feitos:
        raise RuntimeError('nenhum ano com dados')
    return linhas, feitos, vazios


def main(saida):
    os.makedirs(saida, exist_ok=True)
    mp = os.path.join(saida, 'tabnet_meta.json')
    meta = json.load(open(mp, encoding='utf-8')) if os.path.exists(mp) else {}
    so = [x for x in sys.argv[2:] if x in DEFS] or list(DEFS)
    ok = 0
    for f in so:
        t0 = time.time()
        try:
            linhas, feitos, vazios = fonte(f)
            with gzip.open(os.path.join(saida, f'tabnet_{f}.csv.gz'), 'wt', encoding='utf-8', newline='') as g:
                w = csv.writer(g, delimiter=';')
                w.writerow(['ano', 'codigo6', 'ind', 'valor'])
                w.writerows(linhas)
            meta[f] = {'anos': feitos, 'vazios': vazios, 'linhas': len(linhas), 'gerado': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
                       'segundos': int(time.time() - t0), 'erro': '', 'def': DEFS[f]}
            ok += 1
            log(f'{f}: ok, anos {feitos}, {len(linhas)} linhas')
        except Exception as e:
            log(f'{f}: ERRO {e}')
            meta.setdefault(f, {})['erro'] = str(e)[:500]
            meta[f]['erro_em'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    with open(mp, 'w', encoding='utf-8') as g:
        json.dump(meta, g, ensure_ascii=False, indent=1)
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/saude')

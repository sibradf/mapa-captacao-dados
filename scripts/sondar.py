"""Sonda os arquivos do Transferegov: tamanho, cabeçalho e 2 linhas de exemplo (para montar o robô)."""
import csv, io, os, sys, time, urllib.request, zipfile
BASE = 'https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/'
csv.field_size_limit(10**9)
os.makedirs('/tmp/tg', exist_ok=True)
for nome in sys.argv[1:]:
    t = time.time(); dest = f'/tmp/tg/{nome}.zip'
    try:
        req = urllib.request.Request(BASE + nome + '.zip', headers={'User-Agent': 'robo-mapadegoverno'})
        with urllib.request.urlopen(req, timeout=900) as r, open(dest, 'wb') as f:
            while True:
                b = r.read(1 << 20)
                if not b: break
                f.write(b)
    except Exception as e:
        print(f'### {nome}: FALHOU {e}'); continue
    print(f'### {nome}: {os.path.getsize(dest)/1048576:.1f} MB em {time.time()-t:.0f}s')
    z = zipfile.ZipFile(dest)
    for m in z.namelist():
        print('  membro:', m, f'{z.getinfo(m).file_size/1048576:.0f} MB')
        txt = io.TextIOWrapper(z.open(m), encoding='utf-8-sig', newline='')
        if not m.lower().endswith('.csv'):
            print('  conteudo:', txt.read(300)); continue
        rd = csv.reader(txt, delimiter=';')
        cab = next(rd); print('  colunas:', cab)
        for i, r in enumerate(rd):
            if i < 2: print('  ex:', dict(zip(cab, [x[:120] for x in r])))
            else: break

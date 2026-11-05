"""
Mapa de Governo · gabarito do validador diário (roda no GitHub, que alcança fontes bloqueadas para o servidor).
Publica no ramo "validacao":
  fontes.json        cada fonte oficial: código HTTP e tempo de resposta vistos daqui
  gabarito_ibge.json população oficial (IBGE/SIDRA, tabela 6579, último ano) por município e por UF
O servidor do Mapa compara estes números com o que está no banco dele.
"""
import ssl, json, os, sys, time, datetime, urllib.request, urllib.error


# O MDIC (SERPRO) passou a mandar só o próprio certificado, sem o intermediário (nov/2026).
# Acrescenta o intermediário oficial "AC SERPRO AR46 OV TLS CA 2025" (assinado pela GlobalSign Root R46) à cadeia de confiança.
CTX = ssl.create_default_context()
try:
    CTX.load_verify_locations(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'certs', 'serpro_ar46_ov_tls_ca_2025.pem'))
except Exception:
    pass

UA = {'User-Agent': 'Mozilla/5.0 (robo-mapadegoverno validador)'}
FONTES = [
    ('ibge_localidades', 'IBGE · localidades', 'https://servicodados.ibge.gov.br/api/v1/localidades/estados'),
    ('ibge_sidra', 'IBGE · SIDRA', 'https://apisidra.ibge.gov.br/values/t/6579/n1/all/v/9324/p/last%201'),
    ('transparencia_api', 'Portal da Transparência · API', 'https://api.portaldatransparencia.gov.br/api-de-dados/emendas?pagina=1'),
    ('transparencia_download', 'Portal da Transparência · downloads', 'https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares'),
    ('camara', 'Câmara dos Deputados · API', 'https://dadosabertos.camara.leg.br/api/v2/deputados?itens=1'),
    ('senado', 'Senado · API', 'https://legis.senado.leg.br/dadosabertos/senador/lista/atual.json'),
    ('mdic', 'MDIC · Comex Stat (arquivos)', 'https://balanca.mdic.gov.br/balanca/bd/tabelas/PAIS.csv'),
    ('transferegov', 'Transferegov · downloads', 'https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov/siconv_programa.zip'),
    ('bcb_ptax', 'Banco Central · PTAX', "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/Moedas?$format=json&$top=1"),
    ('inep', 'INEP · microdados', 'https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados'),
    ('datasus', 'DATASUS · TabNet', 'http://tabnet.datasus.gov.br/cgi/tabcgi.exe?ibge/cnv/poptbr.def'),
    ('inpe_queimadas', 'INPE · queimadas', 'https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/'),
    ('inpe_terrabrasilis', 'INPE · TerraBrasilis', 'https://terrabrasilis.dpi.inpe.br/geoserver/ows?service=WMS&request=GetCapabilities'),
    ('github', 'GitHub · dados do robô', 'https://raw.githubusercontent.com/sibradf/mapa-captacao-dados/dados/meta.json'),
]


def sonda(url, metodo='HEAD'):
    t = time.time()
    try:
        req = urllib.request.Request(url, headers=UA, method=metodo)
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            if metodo == 'GET':
                r.read(2048)
            return r.status, round((time.time() - t) * 1000)
    except urllib.error.HTTPError as e:
        if e.code in (403, 405, 501) and metodo == 'HEAD':
            return sonda(url, 'GET')
        return e.code, round((time.time() - t) * 1000)
    except Exception as e:
        if metodo == 'HEAD':
            return sonda(url, 'GET')
        return 0, round((time.time() - t) * 1000)


def sidra(caminho):
    for t in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request('https://apisidra.ibge.gov.br/values' + caminho, headers=UA), timeout=300, context=CTX) as r:
                return json.loads(r.read())
        except Exception as e:
            print('sidra', caminho, e, flush=True); time.sleep(20 * (t + 1))
    return None


def main(saida):
    os.makedirs(saida, exist_ok=True)
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    fontes = []
    for chave, nome, url in FONTES:
        st, ms = sonda(url)
        # 401/403 da API = está no ar, só pede chave
        fontes.append({'chave': chave, 'nome': nome, 'url': url, 'http': st, 'ms': ms, 'no_ar': st in (200, 204, 301, 302, 401, 403)})
        print(chave, st, ms, flush=True)
    json.dump({'gerado': agora, 'fontes': fontes}, open(os.path.join(saida, 'fontes.json'), 'w', encoding='utf-8'), ensure_ascii=False)

    pop = {}; ano = None
    for nivel, rotulo in (('n3', 'Unidade da Federação'), ('n6', 'Município')):
        d = sidra(f'/t/6579/{nivel}/all/v/9324/p/last%201')
        if not d or len(d) < 2:
            continue
        cab = d[0]
        k_lugar = next((k for k, v in cab.items() if k.endswith('C') and str(v).startswith(rotulo)), None)
        k_ano = next((k for k, v in cab.items() if k.endswith('C') and str(v).startswith('Ano')), None)
        for r in d[1:]:
            try:
                pop[str(r[k_lugar])] = int(r['V'])
                if k_ano:
                    ano = int(r[k_ano])
            except (ValueError, KeyError, TypeError):
                pass
    json.dump({'gerado': agora, 'fonte': 'IBGE · SIDRA tabela 6579 (estimativas da população), variável 9324', 'ano': ano, 'pop': pop},
              open(os.path.join(saida, 'gabarito_ibge.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('população:', len(pop), 'lugares, ano', ano, flush=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '/tmp/val')

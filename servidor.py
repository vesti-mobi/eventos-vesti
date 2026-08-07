#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor local do Painel de Eventos Vesti.

- Serve o painel (painel-sintonia-001.html) e os arquivos da pasta.
- Endpoint GET /api/dados: puxa o HubSpot (pipeline) + a planilha (CSV publicado),
  monta a estrutura de dados e devolve como JSON. É isso que o botão "Atualizar" chama.

Usa apenas a biblioteca padrão do Python (nada para instalar).

Como usar:
  1) Copie  config.example.json  para  config.json  e preencha o token do HubSpot
     e a URL do CSV publicado da aba de custos (veja o README).
  2) python servidor.py
  3) Abra  http://localhost:8000/painel-sintonia-001.html
"""

import json, csv, io, re, ssl, sys, datetime
import urllib.request, urllib.parse, urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Garante saída UTF-8 no console do Windows (evita erro 'charmap' com ->, acentos etc.)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
CUSTOS_PATH = BASE / "dados" / "custos.json"

# De-para de fallback (usado só se a leitura das fases do pipeline no HubSpot falhar)
FASES_FALLBACK = {
    "161599650": "Recusou",
    "161599651": "Compareceu",
    "161599653": "Confirmou mas não compareceu",
    "1412577689": "Aguardando confirmação",
}

DEAL_PROPS = ["dealname", "dealstage", "nome_da_marca", "recusou_motivo", "hubspot_owner_id", "nome_evento"]


def load_config():
    if not CONFIG_PATH.exists():
        return None
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_custos():
    """Custos locais (privados) por nome de evento. Ignora chaves que começam com '_'."""
    if not CUSTOS_PATH.exists():
        return {}
    with open(CUSTOS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _hs_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _http_json(url, method="GET", headers=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_stage_map(token, pipeline_id):
    """id da fase -> rótulo, direto do HubSpot (fallback para o de-para fixo)."""
    try:
        url = f"https://api.hubapi.com/crm/v3/pipelines/deals/{pipeline_id}"
        data = _http_json(url, headers=_hs_headers(token))
        m = {s["id"]: s["label"] for s in data.get("stages", [])}
        return m or dict(FASES_FALLBACK)
    except Exception as e:
        print("  aviso: não li as fases do pipeline, usando fallback:", e)
        return dict(FASES_FALLBACK)


def fetch_owners(token):
    """id do proprietário -> nome."""
    owners, after = {}, None
    while True:
        url = "https://api.hubapi.com/crm/v3/owners/?limit=100"
        if after:
            url += f"&after={after}"
        data = _http_json(url, headers=_hs_headers(token))
        for o in data.get("results", []):
            nome = (f"{o.get('firstName','')} {o.get('lastName','')}").strip() or o.get("email") or f"Owner {o.get('id')}"
            owners[str(o.get("id"))] = nome
        after = (data.get("paging", {}).get("next", {}) or {}).get("after")
        if not after:
            break
    return owners


def fetch_deals(token, pipeline_id):
    """Todos os negócios do pipeline (com paginação)."""
    url = "https://api.hubapi.com/crm/v3/objects/deals/search"
    results, after = [], None
    while True:
        body = {
            "filterGroups": [{"filters": [{"propertyName": "pipeline", "operator": "EQ", "value": str(pipeline_id)}]}],
            "properties": DEAL_PROPS,
            "limit": 100,
        }
        if after:
            body["after"] = after
        data = _http_json(url, method="POST", headers=_hs_headers(token), body=body)
        results.extend(data.get("results", []))
        after = (data.get("paging", {}).get("next", {}) or {}).get("after")
        if not after:
            break
    return results


def parse_money(s):
    s = str(s or "").strip().replace("R$", "").replace("\xa0", " ").strip()
    if not s or s in ("-", "—"):
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s) if s not in ("", ".", "-") else 0.0
    except ValueError:
        return 0.0


def parse_int(s):
    try:
        return int(re.sub(r"[^0-9\-]", "", str(s)) or 0)
    except ValueError:
        return 0


def parse_cost_rows(rows):
    """Recebe linhas (lista de listas) e devolve { nome_evento: {local, data, itens, total} }."""
    rows = [[str(c) for c in row] for row in rows]
    header_idx = next((i for i, row in enumerate(rows)
                       if any(c.strip().lower() == "categoria gasto" for c in row)), None)
    if header_idx is None:
        return {}

    header = [c.strip() for c in rows[header_idx]]

    def col(*names):
        for name in names:
            for j, h in enumerate(header):
                if h.lower() == name.lower():
                    return j
        return None

    idx = {
        "item": col("Item"),
        "obs": col("Observação / Fornecedor", "Observação", "Observações"),
        "qtd": col("Qtd"),
        "unit": col("Custo unit.", "Custo unit"),
        "total": col("Total"),
        "status": col("Status"),
        "nome": col("Nome evento"),
        "local": col("Local evento"),
        "data": col("Data evento"),
        "categoria": col("Categoria gasto"),
    }

    def val(row, key):
        j = idx.get(key)
        return row[j].strip() if (j is not None and j < len(row)) else ""

    eventos = {}
    for row in rows[header_idx + 1:]:
        if not any(cell.strip() for cell in row):
            continue
        item, nome_ev = val(row, "item"), val(row, "nome")
        if not item or not nome_ev:
            continue
        ev = eventos.setdefault(nome_ev, {"local": "", "data": "", "itens": []})
        ev["local"] = ev["local"] or val(row, "local")
        ev["data"] = ev["data"] or val(row, "data")
        ev["itens"].append({
            "item": item,
            "obs": val(row, "obs"),
            "qtd": parse_int(val(row, "qtd")),
            "unit": parse_money(val(row, "unit")),
            "total": parse_money(val(row, "total")),
            "status": val(row, "status"),
            "categoria": val(row, "categoria") or "Outros",
        })
    for ev in eventos.values():
        ev["total"] = round(sum(i["total"] for i in ev["itens"]), 2)
    return eventos


def fetch_sheet_csv(csv_url):
    """Lê um CSV publicado na web."""
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(csv_url, context=ctx, timeout=30) as r:
        raw = r.read().decode("utf-8", errors="replace")
    return parse_cost_rows(list(csv.reader(io.StringIO(raw))))


def fetch_sheet_google(sa_file, sheet_id):
    """Lê a planilha PRIVADA via API do Google Sheets (conta de serviço)."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_file(
        sa_file, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    sess = AuthorizedSession(creds)
    meta = sess.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}",
                    params={"fields": "sheets.properties.title"}, timeout=30).json()
    if "error" in meta:
        raise RuntimeError(meta["error"].get("message", "erro na API do Google Sheets"))
    for s in meta.get("sheets", []):
        title = s["properties"]["title"]
        rng = urllib.parse.quote(title)
        r = sess.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}",
                     timeout=30).json()
        eventos = parse_cost_rows(r.get("values", []))
        if eventos:
            return eventos
    return {}


def parse_satisfacao_rows(rows):
    """Recebe as linhas da aba 'Formulário de satisfação' e devolve uma lista de respostas."""
    rows = [[str(c) for c in row] for row in rows]
    if not rows:
        return []
    header = [c.strip() for c in rows[0]]
    idx = {h: header.index(h) for h in header}

    def g(row, key):
        j = idx.get(key)
        return row[j].strip() if (j is not None and j < len(row)) else ""

    def to_int(s):
        try:
            return int(float(s))
        except (ValueError, TypeError):
            return None

    ANON = ("", "anônimo", "anonimo")
    out = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue
        marca, nome = g(row, "brand_name"), g(row, "name_people")
        autor = marca if marca.lower() not in ANON else (nome if nome.lower() not in ANON else "Anônimo")
        out.append({
            "event_name": g(row, "event_name"),
            "score": to_int(g(row, "score")),
            "score_reason": g(row, "score_reason"),
            "talk_rating": to_int(g(row, "talk_rating")),
            "talk_relevance": g(row, "talk_relevance"),
            "restaurant_rating": to_int(g(row, "restaurant_rating")),
            "schedule_ok": g(row, "schedule_ok"),
            "favorite_part": g(row, "favorite_part"),
            "improvements": g(row, "improvements"),
            "next_event": g(row, "next_event"),
            "autor": autor,
            "created_at": g(row, "created_at"),
        })
    return out


def fetch_satisfacao_google(sa_file, sheet_id):
    """Lê a aba 'Formulário de satisfação' da planilha PRIVADA (conta de serviço)."""
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_file(
        sa_file, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    sess = AuthorizedSession(creds)
    meta = sess.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}",
                    params={"fields": "sheets.properties.title"}, timeout=30).json()
    if "error" in meta:
        raise RuntimeError(meta["error"].get("message", "erro na API do Google Sheets"))
    aba = next((s["properties"]["title"] for s in meta.get("sheets", [])
                if "satisfa" in s["properties"]["title"].lower()), None)
    if not aba:
        raise RuntimeError("aba 'Formulário de satisfação' não encontrada na planilha.")
    rng = urllib.parse.quote(aba)
    r = sess.get(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}", timeout=30).json()
    return parse_satisfacao_rows(r.get("values", []))


def build_dados(cfg):
    token = cfg["hubspot_token"]
    pipeline_id = str(cfg.get("pipeline_id", "86720772"))

    stage_map = fetch_stage_map(token, pipeline_id)
    owners = fetch_owners(token)
    deals = fetch_deals(token, pipeline_id)

    # Custos: arquivo local (privado) + planilha ao vivo (Google API ou CSV), se configurada.
    costs = load_custos()
    sa = cfg.get("google_service_account_file")
    sid = cfg.get("sheet_id")
    url = cfg.get("sheet_csv_url", "")
    try:
        if sa and sid:
            sa_path = sa if Path(sa).is_absolute() else str(BASE / sa)
            g = fetch_sheet_google(sa_path, sid)
            if g:
                costs.update(g)
                print(f"  custos: planilha via Google Sheets ({len(g)} evento(s)).")
        elif url and "COLE_A_URL" not in url:
            costs.update(fetch_sheet_csv(url))
            print("  custos: planilha via CSV publicado.")
        else:
            print("  custos: arquivo local (dados/custos.json).")
    except Exception as e:
        print("  aviso: falha ao ler a planilha, mantendo custos locais:", e)

    por_evento = {}
    for d in deals:
        p = d.get("properties", {})
        nome_ev = (p.get("nome_evento") or "").strip()
        if not nome_ev:
            continue
        item = {
            "n": p.get("dealname") or "(sem nome)",
            "m": p.get("nome_da_marca") or "",
            "f": stage_map.get(str(p.get("dealstage", "")), "Outros"),
            "r": owners.get(str(p.get("hubspot_owner_id", "")), "Sem responsável"),
        }
        mot = (p.get("recusou_motivo") or "").strip()
        if mot:
            item["mot"] = mot
        por_evento.setdefault(nome_ev, []).append(item)

    hoje = datetime.date.today().isoformat()
    eventos = []
    for nome in (set(por_evento) | set(costs)):
        c = costs.get(nome, {})
        itens = c.get("itens", [])
        total = c.get("total")
        if total is None:
            total = round(sum(i.get("total", 0) for i in itens), 2)
        eventos.append({
            "nome": nome,
            "local": c.get("local", ""),
            "data_evento": c.get("data", ""),
            "atualizado_em": hoje,
            "custos": {"total": total, "itens": itens},
            "deals": por_evento.get(nome, []),
        })
    eventos.sort(key=lambda e: len(e["deals"]), reverse=True)
    return {"eventos": eventos, "gerado_em": datetime.datetime.now().strftime("%d/%m/%Y %H:%M")}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(BASE), **k)

    def do_GET(self):
        rota = self.path.split("?")[0]
        if rota == "/api/dados":
            return self._api_dados()
        if rota == "/api/satisfacao":
            return self._api_satisfacao()
        return super().do_GET()

    def _api_dados(self):
        cfg = load_config()
        try:
            if not cfg or not cfg.get("hubspot_token") or "COLE_SEU" in str(cfg.get("hubspot_token", "")):
                raise RuntimeError("config.json ausente ou sem hubspot_token válido. "
                                   "Copie config.example.json para config.json e preencha (veja o README).")
            print("-> /api/dados : buscando HubSpot + planilha...")
            dados = build_dados(cfg)
            n = sum(len(e["deals"]) for e in dados["eventos"])
            print(f"  ok: {len(dados['eventos'])} evento(s), {n} convidado(s).")
            self._send_json(200, dados)
        except urllib.error.HTTPError as e:
            self._send_json(502, {"erro": f"HubSpot respondeu {e.code}: verifique o token e os escopos."})
        except Exception as e:
            print("  erro:", e)
            self._send_json(503, {"erro": str(e)})

    def _api_satisfacao(self):
        cfg = load_config()
        try:
            if not cfg:
                raise RuntimeError("config.json ausente.")
            sa, sid = cfg.get("google_service_account_file"), cfg.get("sheet_id")
            if not (sa and sid):
                raise RuntimeError("Configure google_service_account_file e sheet_id no config.json.")
            sa_path = sa if Path(sa).is_absolute() else str(BASE / sa)
            print("-> /api/satisfacao : buscando respostas na planilha...")
            respostas = fetch_satisfacao_google(sa_path, sid)
            evento = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("evento", [""])[0]
            if evento:
                respostas = [r for r in respostas if r.get("event_name") == evento]
            elif respostas:
                evento = respostas[0].get("event_name", "")
            print(f"  ok: {len(respostas)} resposta(s) de satisfação.")
            self._send_json(200, {"evento": evento, "respostas": respostas})
        except Exception as e:
            print("  erro:", e)
            self._send_json(503, {"erro": str(e)})

    def _send_json(self, status, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass  # silencioso (os prints acima já dão o essencial)


def main():
    port = 8000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    cfg = load_config()
    print("=" * 62)
    print("  Painel de Eventos Vesti — servidor local")
    print("=" * 62)
    if not cfg:
        print("  AVISO: config.json não encontrado.")
        print("  O painel abre normalmente com os dados salvos, mas o botão")
        print("  'Atualizar' só funciona depois que você criar o config.json.")
    else:
        print("  config.json carregado.")
    print(f"  Abra:  http://localhost:{port}/painel-sintonia-001.html")
    print("  (Ctrl+C para parar)")
    print("=" * 62)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()

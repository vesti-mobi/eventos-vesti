# -*- coding: utf-8 -*-
"""
Atualiza os dados do site e regenera os snapshots embutidos nas páginas.

Usa as chaves LOCAIS (config.json + google-service-account.json) — que ficam só
na sua máquina e NUNCA vão para o GitHub. Rode este script (ou o publicar.bat)
antes de publicar, sempre que quiser levar dados novos para o ar.

O que faz:
  1) Puxa presença (HubSpot) + custos (planilha)  -> dados/sintonia-001.json
  2) Puxa respostas de satisfação (planilha)       -> dados/satisfacao-001.json
  3) Reinjeta esses dados nas páginas HTML (snapshot embutido)

Depois é só  git add/commit/push  (o publicar.bat já faz isso).
"""
import json, re, datetime, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import servidor  # reaproveita as funções de busca (HubSpot + Google Sheets)


def _write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _inject(html_path, pattern, replacement):
    html = html_path.read_text(encoding="utf-8")
    new, n = re.subn(pattern, lambda m: replacement, html, count=1, flags=re.DOTALL)
    if n != 1:
        raise SystemExit(f"ERRO: não achei o trecho de dados em {html_path.name}.")
    html_path.write_text(new, encoding="utf-8")


def main():
    cfg = servidor.load_config()
    if not cfg or "COLE_SEU" in str(cfg.get("hubspot_token", "")):
        raise SystemExit("config.json ausente ou sem token válido. Veja o README.")

    print("[1/3] Presença (HubSpot) + custos (planilha)...")
    dados = servidor.build_dados(cfg)
    _write_json(BASE / "dados" / "sintonia-001.json", dados)

    print("[2/3] Respostas de satisfação (planilha)...")
    sa, sid = cfg.get("google_service_account_file"), cfg.get("sheet_id")
    respostas = []
    if sa and sid:
        sa_path = sa if Path(sa).is_absolute() else str(BASE / sa)
        respostas = servidor.fetch_satisfacao_google(sa_path, sid)
    satisf = {
        "gerado_em": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
        "eventos": {e["nome"]: {"data_evento": e.get("data_evento", "")} for e in dados["eventos"]},
        "respostas": respostas,
    }
    _write_json(BASE / "dados" / "satisfacao-001.json", satisf)

    print("[3/3] Atualizando os snapshots embutidos nas páginas...")
    _inject(BASE / "painel-sintonia-001.html",
            r"let DADOS = \{.*?\n\};",
            "let DADOS = " + json.dumps(dados, ensure_ascii=False, indent=2) + ";")
    _inject(BASE / "satisfacao-sintonia-001.html",
            r"/\*__SAT_DATA__\*/.*?/\*__END__\*/",
            "/*__SAT_DATA__*/ " + json.dumps(satisf, ensure_ascii=False, indent=2) + " /*__END__*/")

    n_deals = sum(len(e["deals"]) for e in dados["eventos"])
    print(f"\nOK: {len(dados['eventos'])} evento(s), {n_deals} convidado(s), "
          f"{len(respostas)} resposta(s) de satisfação.")


if __name__ == "__main__":
    main()

# Painel de Resultados — Eventos Presenciais Vesti

Painel web que cruza a **presença dos convidados** (HubSpot) com os **custos do evento**
(planilha no Google Sheets) para mostrar quantas pessoas compareceram, quantas recusaram e
**quanto custou por participante**.

Primeiro evento: **Sintonia: Criação e Vendas #001**.

---

## ▶ Como abrir

Dê **dois cliques** em `painel-sintonia-001.html`. Ele abre no navegador, funciona **offline**
e pode ser enviado por e-mail/WhatsApp como um arquivo só. Não precisa instalar nada.

---

## 🔎 Filtros (no topo)

- **Evento** — troca entre eventos (o pipeline é multi-evento; hoje só o #001, pronto para os próximos).
- **Responsável (quem convidou)** — o **proprietário do deal** no HubSpot, que é o responsável pela marca. Ao selecionar, a **presença** (compareceu/recusou/funil/motivos) passa a mostrar só os convidados daquela pessoa. Os **custos são sempre do evento inteiro** (não dá para ratear por responsável) e ficam rotulados como tal.

## 📊 O que o painel mostra

1. **Presença** — distribuição da base convidada e funil de confirmação (convidados → confirmaram → compareceram).
2. **Investimento & custo por pessoa** — total investido, blocos *Consumo* vs *Materiais & Ativos*, e custo por pessoa **planejado (÷45) vs real (÷ quem compareceu)**.
3. **Custos por categoria** — gráfico + tabela detalhada dos gastos.
4. **Motivos de recusa** — o que os convidados registraram ao recusar.

---

## 🔗 De onde vêm os dados

| Fonte | Detalhe |
|---|---|
| **HubSpot** | Pipeline **Eventos Presenciais** (`id 86720772`), filtrado pela propriedade **`nome_evento`** = nome do evento. Cada convidado é um negócio (deal). |
| **Google Sheets** | Planilha de custos (`id 1IEYd78VJUST3iusrD24dbFDjgBI0hN0-Wjar1N35IYM`), aba *Overview do Investimento*. |

> A **chave de ligação** entre as duas fontes é o **nome do evento**: `nome_evento` no HubSpot
> tem que ser idêntico ao nome do evento na planilha.

### De-para das fases do pipeline (importante)

O HubSpot guarda a fase como um código interno. O de-para confirmado é:

| Código interno | Fase |
|---|---|
| `161599650` | Recusou |
| `161599651` | Compareceu |
| `161599653` | Confirmou mas não compareceu |
| `1412577689` | Aguardando confirmação |

*(As fases "Convidado", "Convidado acompanhante" e "Confirmou" existem no pipeline mas estavam vazias neste evento.)*

---

## 🔄 Botão "Atualizar" (dados ao vivo)

O painel tem um botão **⟳ Atualizar** que puxa os dados do HubSpot + planilha na hora. Para isso
funcionar, rode o painel pelo **servidor local** (`servidor.py`) — o navegador sozinho não pode
falar com o HubSpot (segurança do token + CORS), então quem faz as buscas é esse servidorzinho.

> Sem o servidor (ou sem `config.json`), o painel abre normalmente com os **dados salvos** e o
> botão apenas avisa "usando dados salvos". Nada quebra.

### Configuração (uma vez só)

**1. Gerar um token do HubSpot (Private App):**
   - HubSpot → ⚙️ **Configurações** → **Integrações** → **Aplicativos privados** → *Criar aplicativo privado*.
   - Aba **Escopos** → marque (somente leitura): `crm.objects.deals.read`, `crm.objects.owners.read`, `crm.schemas.deals.read`.
   - Crie e **copie o token** (começa com `pat-...`).

**2. Custos ao vivo via Google (planilha continua privada):**
   - Precisa das libs: `python -m pip install google-auth requests`.
   - No **Google Cloud Console** → criar projeto → **ativar Google Sheets API** → criar uma
     **conta de serviço** → gerar uma **chave JSON**.
   - Salvar a chave na pasta do projeto como **`google-service-account.json`**.
   - **Compartilhar a planilha** com o e-mail da conta de serviço (`...iam.gserviceaccount.com`), como **Leitor**.

**3. Criar o `config.json`:**
   - Copie `config.example.json` para `config.json` e preencha:
     ```json
     {
       "hubspot_token": "pat-...",
       "pipeline_id": "86720772",
       "sheet_csv_url": "",
       "google_service_account_file": "google-service-account.json",
       "sheet_id": "1IEYd78VJUST3iusrD24dbFDjgBI0hN0-Wjar1N35IYM"
     }
     ```
   - ⚠️ `config.json` e `google-service-account.json` têm segredos — **já estão no `.gitignore`**, nunca versione.

> **Prioridade das fontes de custo:** Google Sheets → CSV publicado (`sheet_csv_url`) → arquivo local
> `dados/custos.json` (fallback). Se o Google falhar por qualquer motivo, o painel segue com os custos locais.

### Rodar

Dê **dois cliques** em **`iniciar-painel.bat`** (liga o servidor e abre o painel). Ou, no terminal:
```
python servidor.py
```
Depois abra **http://localhost:8000/painel-sintonia-001.html** e use o botão **⟳ Atualizar**.
(O painel também busca dados ao vivo sozinho toda vez que abre, se o servidor estiver no ar.)

### Atualização diária (opcional, próximo passo)

Com o servidor pronto, dá para agendar no **Agendador de Tarefas do Windows** um passo que
regenera/salva os dados 1x/dia — a combinar quando quiser.

---

## ➕ Como adicionar um novo evento (#002, #003…)

O pipeline é multi-evento. Para um novo evento:
1. Confirme que os negócios têm o `nome_evento` do novo evento e que a planilha usa o mesmo nome.
2. Peça ao Claude para gerar o painel daquele evento (ele filtra por `nome_evento`).
3. Um novo arquivo `painel-<evento>.html` + `dados/<evento>.json` é criado.

---

## 📁 Estrutura

```
painel-sintonia-001.html   → o painel (entregável principal)
dados/sintonia-001.json    → dados estruturados (fonte de verdade)
README.md                  → este arquivo
```

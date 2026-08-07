# Publicar na Cloudflare Pages (com botão "Atualizar" ao vivo)

O site é estático + duas **Functions** (`functions/api/dados` e `functions/api/satisfacao`)
que puxam HubSpot + Google Sheets **no servidor da Cloudflare** — as chaves ficam guardadas
lá (criptografadas), **nunca** no navegador nem no git.

> ⚠️ As chaves **não vão** no repositório. Você as cola **uma vez** nos "secrets" da Cloudflare
> (passo 5). O arquivo `.dev.vars` é só pra teste local e está no `.gitignore`.

---

## 0. Antes de começar
- O repositório `eventos-vesti` deve estar na **org do GitHub da Vesti** (transfira primeiro:
  GitHub → repo → **Settings → General → Transfer ownership**).
- Tenha em mãos os valores do seu `config.json` e o arquivo `google-service-account.json`.

## 1. Criar conta Cloudflare (grátis)
- Acesse **dash.cloudflare.com** e crie a conta (pode ser a conta da Vesti).

## 2. Criar o projeto Pages
- Menu **Workers & Pages** → **Create application** → aba **Pages** → **Connect to Git**.
- Autorize o GitHub e **instale o app da Cloudflare na org da Vesti**, liberando o repo `eventos-vesti`.
- Selecione o repositório **`eventos-vesti`**.

## 3. Configurar o build
- **Project name:** `eventos-vesti` (vira o endereço `eventos-vesti.pages.dev`).
- **Production branch:** `main`
- **Framework preset:** `None`
- **Build command:** *(deixe vazio)*
- **Build output directory:** `/` *(a raiz)*
- As Functions em `functions/` são detectadas automaticamente.

## 4. (pode fazer aqui ou depois) Não clique em Deploy ainda sem os secrets
Se a tela deixar adicionar variáveis agora ("Environment variables (advanced)"), faça o passo 5
antes do primeiro deploy. Se já tiver publicado sem os secrets, adicione no passo 5 e clique em
**Retry deployment**.

## 5. Secrets (variáveis de ambiente)
Em **Settings → Environment variables → Production**, adicione (marque **Encrypt**):

| Nome | Valor |
|---|---|
| `HUBSPOT_TOKEN` | o token `pat-...` (do `config.json`) |
| `SHEET_ID` | `1IEYd78VJUST3iusrD24dbFDjgBI0hN0-Wjar1N35IYM` |
| `PIPELINE_ID` | `86720772` |
| `GOOGLE_SERVICE_ACCOUNT` | **todo o conteúdo** do arquivo `google-service-account.json` |

> Se o campo do `GOOGLE_SERVICE_ACCOUNT` não aceitar quebras de linha, cole a versão em **base64**
> (o código aceita as duas). Pra gerar o base64 no Windows (PowerShell, na pasta do projeto):
> ```powershell
> [Convert]::ToBase64String([IO.File]::ReadAllBytes("google-service-account.json"))
> ```
> Copie a linha gerada e cole no valor do secret.

## 6. Deploy
- **Save and Deploy**. Em ~1 min o site sobe em **https://eventos-vesti.pages.dev**.

## 7. Testar
- Abra a URL, clique em **Atualizar** — deve puxar os dados ao vivo. Cada clique repetido nos
  primeiros 3 min vem do **cache** (protege o HubSpot).

## 8. Atualizações futuras
- Qualquer `git push` no repo → a Cloudflare **reconstrói sozinha**. Nada manual.
- O `publicar.bat` continua útil só pra atualizar a "foto" offline embutida; pro site ao vivo
  **não é mais necessário**.

## 9. (opcional) Domínio próprio da Vesti
- Pages → **Custom domains** → **Set up a custom domain** → ex.: `relatorios.vesti.mobi`.
- Adicione o registro (CNAME) que a Cloudflare indicar no DNS da `vesti.mobi`. O link fica
  estável pra sempre, mesmo que algo mude depois.

## 10. (opcional) Desligar o GitHub Pages
- Depois que a Cloudflare estiver no ar, no GitHub: **Settings → Pages → desabilitar**, pra ficar
  só a Cloudflare como fonte.

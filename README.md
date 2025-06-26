# processing-service

![CI Cleaner](https://github.com/<YOUR_ORG>/processing-service/actions/workflows/cleaner.yml/badge.svg)
![CI Feature](https://github.com/<YOUR_ORG>/processing-service/actions/workflows/feature.yml/badge.svg)
![CI Macro Filter](https://github.com/<YOUR_ORG>/processing-service/actions/workflows/macro_filter.yml/badge.svg)
![CI Sentiment](https://github.com/<YOUR_ORG>/processing-service/actions/workflows/sentiment.yml/badge.svg)
![CI Purge](https://github.com/<YOUR_ORG>/processing-service/actions/workflows/purge.yml/badge.svg)

> **processing-service** é o *batch layer* do **Financial‑News Pipeline**, responsável por limpar,
> enriquecer e classificar as notícias captadas pelo repositório
> [`data-harvester`](https://github.com/<YOUR_ORG>/data-harvester).
> Ele roda 100 % em **GitHub Actions** + **Supabase Free Tier**, sem custos fixos.

---

## Funções principais

| Etapa        | Descrição resumida                                | Cron (UTC)   | Script                                 |
| ------------ | ------------------------------------------------- | ------------ | -------------------------------------- |
| Cleaner      | Remove HTML, normaliza campos e de‑dupa registros | `*/10 11-23` | `src/preprocessors/cleaner_*.py`       |
| Feature Eng. | Extrai entidades, n‑gramas, embeddings            | `*/15 11-23` | `src/feature_engineering/features.py`  |
| Macro Filter | Classifica notícias macroeconômicas               | `*/15 11-23` | `src/filters/macro_filter.py`          |
| Sentiment    | Gera sentimento (OpenAI, finetuned)               | `*/20 11-23` | `src/sentiment/sentiment_generator.py` |
| Purge        | Deleta dados antigos / archiva para S3            | `0 3 * * *`  | `src/purge/purge_old.py`               |

---

## Estrutura do repositório

```txt
processing-service/
├─ .github/workflows/           # 🗓️ cronjobs GitHub Actions
│  ├─ cleaner.yml
│  ├─ feature.yml
│  ├─ macro_filter.yml
│  ├─ sentiment.yml
│  └─ purge.yml
├─ src/
│  ├─ config.py                 # utilitários Supabase + env
│  ├─ preprocessors/
│  ├─ feature_engineering/
│  ├─ filters/
│  ├─ sentiment/
│  ├─ purge/
│  └─ pipeline.py               # orquestra tudo localmente
├─ tests/                       # pytest + mocks
├─ Dockerfile                   # ambiente reproduzível
├─ requirements.txt
└─ README.md 👈
```

---

## Começando rápido

### 1. Clone + ambiente virtual

```bash
git clone https://github.com/<YOUR_ORG>/processing-service.git
cd processing-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Variáveis de ambiente

| Nome             | Exemplo                    | Observação                                |
| ---------------- | -------------------------- | ----------------------------------------- |
| `SUPABASE_URL`   | `https://abcd.supabase.co` | End‑point do projeto Supabase             |
| `SUPABASE_ANON`  | `eyJhbGc...`               | Chave **anon** (*NÃO* use `service_role`) |
| `OPENAI_API_KEY` | `sk‑...`                   | Necessário para `sentiment_generator.py`  |
| `S3_BUCKET`      | `fin-news-archive`         | Opcional: arquivamento de purges          |

> No GitHub, configure estes valores em **Settings › Secrets › Actions**.

### 3. Executar um job localmente

```bash
python -m preprocessors.cleaner_corporate --once
# ou rode todos sequencialmente
python src/pipeline.py --all --once
```

---

## GitHub Actions

Todos os cronjobs vivem em **`.github/workflows/`** e aproveitam minutos ilimitados
de repositórios públicos.
Principais ajustes de segurança já aplicados:

* `permissions: { contents: read }`
* `concurrency` para evitar overlap
* Segredos mascarados com `::add-mask::`
* Dependabot + CodeQL habilitados (*Security › Code security and analysis*)

---

## Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

Os testes usam um **Supabase mock** local (`docker-compose up supabase_mock`).

---

## Contribuindo

1. Fork & branch `feat/mi‑minha‑feature`
2. `pre-commit install` (lint + format)
3. Abra um *Pull Request* 🎉

Leia `CONTRIBUTING.md` para detalhes.

---

## Licença

Distribuído sob a [MIT License](LICENSE).

---

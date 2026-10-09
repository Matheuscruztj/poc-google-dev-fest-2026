# Como Treinar Seu Agente de IA (Sem Incendiar a Cloud)

**DevFest 2026 · EventOps AI · Docker Compose local, Google Cloud ao final.**

Aplicação demonstrativa que sugere palestras, responde dúvidas com fontes e simula reservas. Todos os dados são fictícios. O MVP atual funciona em modo offline determinístico e não chama Gemini nem qualquer serviço externo.

## Executar localmente

Requisitos: Docker Compose v2. O SQLite persistente é criado no volume `eventops-data`; `app/data/sessions.json` é somente o seed versionado, carregado na inicialização configurada. As consultas da agenda vêm do SQLite.

```bash
cp .env.example .env
docker compose up --build -d
```

Abra <http://127.0.0.1:8000>. Para parar, rode `docker compose down`; o volume persiste. Para iniciar Ollama local com GPU NVIDIA/CUDA, instale NVIDIA Container Toolkit, defina `EVENTOPS_AGENT_MODE=local` em `.env` e rode `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu up --build -d`; baixe o modelo uma vez com `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu run --rm model-init`. Os pesos ficam em volume próprio. Sem GPU, use `docker compose --profile local-model up -d` e o Ollama executará em CPU. O modo padrão `offline` não inicia nem baixa modelo algum.

Para trocar para Gemini via API, defina `EVENTOPS_AGENT_MODE=live` e `GOOGLE_API_KEY` em `.env` antes de iniciar. Esse caminho usa um serviço externo e pode consumir quota. A aplicação, contrato do agente e ferramentas de domínio permanecem os mesmos.

Veja [operação local](docs/operacao-local.md) para reset, diagnóstico e instalação de dependências. O setup Python direto permanece disponível para desenvolvimento sem Docker (`make setup`, `make run`). Dependências Python são fixadas nos locks SHA-256 em `requirements/`.

### Reset local seguro

Pare o servidor e execute `python scripts/reset_demo.py`. O script só remove o SQLite local indicado por `EVENTOPS_DATABASE` (ou `var/eventops.sqlite3` por padrão), diretamente dentro de `var/`; também apaga seus arquivos WAL/SHM. Ele recusa modo diferente de `offline`, links simbólicos e caminhos fora desse diretório. Não use `rm` para apontar o reset a outros dados.

### Erros e identidade da API

Rotas JSON retornam erros no formato `{"error":{"code":"...","message":"...","request_id":"..."}}`; o mesmo identificador vem no cabeçalho `X-Request-ID`. Payloads inválidos recebem 422 (`invalid_request`), origem mutável ausente/não permitida recebe 403, recurso inexistente recebe 404, conflito de reserva recebe 409 e falha inesperada retorna mensagem genérica 500. Campos `user_id` enviados pelo cliente são rejeitados pelo schema. O navegador recebe identidade fictícia em cookie opaco HttpOnly, SameSite=Lax, validade de 24 horas e Secure configurável com `EVENTOPS_COOKIE_SECURE`; o valor persistido é somente o hash do cookie. Preview e confirmação pertencem ao mesmo navegador.

Para uma origem servida em outro host/porta, defina `EVENTOPS_ALLOWED_ORIGINS` com origens HTTP/S separadas por vírgula, sem caminhos (por exemplo `https://demo.example`). Por padrão, operações mutáveis aceitam a origem da própria aplicação.

## O que funciona

- **Agenda:** 20 sessões fictícias; filtros por trilha, nível e horário; até três escolhas sem conflito.
- **FAQ:** busca lexical em oito documentos Markdown, com citações de arquivo e seção e abstenção quando não há evidência.
- **Reserva simulada:** identidade de demonstração por cookie HttpOnly, prévia separada da confirmação, validade de cinco minutos, checagem de capacidade e idempotência no SQLite.
- **Agente único:** conversa via `/api/chat`, com tools de leitura para agenda e FAQ, fontes validadas e proposta de reserva que sempre exige preview e confirmação pela interface.
- **API:** `GET /health`, `GET /api/sessions`, `POST /api/schedule`, `POST /api/faq`, `POST /api/chat`, `POST /api/reservations/preview` e `POST /api/reservations`.

Não há login real, reserva real, pagamentos nem calendário de terceiros. Agenda e FAQ são determinísticos; o chat identifica os modos offline, Ollama local e Gemini live.

## Verificações

```bash
make lint
make typecheck
make test
make eval-offline
make build
make check
```

`make pre-push` executa todos os quality gates, build do pacote e smoke Docker Compose; instale Docker Desktop/Engine para esse último. O comando completo também exige Node 24.18.0 (via `.node-version`) e Chromium do Playwright. `npm ci` instala Husky e configura o hook versionado em `.husky/pre-push`, que bloqueia o push se `make pre-push` falhar. Instale também as dependências do Chromium com `python -m playwright install --with-deps chromium`. GitHub Actions executa o mesmo alvo em push e pull request e armazena relatórios. `make e2e` usa banco temporário. `make build` gera sdist/wheel e valida os recursos; `make eval-offline` avalia os 40 casos determinísticos, incluindo replay multi-turno de memória/contexto OWASP LLM/Agentic.

### Diagnóstico local

- **Porta ocupada:** use `EVENTOPS_PORT=8001 make run` e abra a URL com essa porta.
- **Banco sem permissão de escrita:** configure `EVENTOPS_DATABASE` para um diretório existente e gravável; a inicialização cria apenas o diretório do banco escolhido.
- **Chromium não abre ou falta biblioteca:** execute `python -m playwright install --with-deps chromium` em Linux ou `python -m playwright install chromium` nos demais ambientes. A aplicação em runtime não precisa de Node nem do navegador.
- **Catálogo inválido/incompatível:** a inicialização falha com mensagem explícita se os oito documentos FAQ previstos estiverem ausentes/alterados, ou se o banco existente divergir do catálogo enquanto houver reservas.

Para conversar com o agente, a seção **Converse com o guia** usa o provider offline por padrão. O provider `local` usa Ollama no serviço Compose; `live` usa ADK e Gemini por API. Instale a integração travada com `python -m pip install --require-hashes -r requirements/py311-agent.txt` e `python -m pip install --no-deps -e .`; configure `GOOGLE_API_KEY` e `EVENTOPS_AGENT_MODE=live` antes de iniciar `make run`. A página identifica o chat live. Uma chamada live usa serviço externo e pode consumir quota. Para executar o protocolo live de três rodadas (120 execuções): `make eval-live LIVE_CONFIRM=1`.

## Plano completo

O escopo e a arquitetura das próximas waves estão descritos em [visão completa](docs/visao-completa.md), com tasks e critérios de aceite no [plano de implementação](docs/plano-de-implementacao.md). Os gates estão em [quality-gates](docs/quality-gates.md).

**Implementado neste estágio:** base, MVP offline com catálogo SQLite, Docker Compose local, agente único, arquitetura multi offline com MCP stdio e políticas locais de deadline/retry/circuit breaker (W0–W5.6 offline). O adapter PostgreSQL passou em smoke local descartável para migração, API, idempotência e disputa da última vaga; ainda não há Cloud SQL provisionado nem G6 aprovado. Single segue como padrão. W3.7 e a comparação live aguardam chave/quota Google e revisão humana; multi live ainda não foi configurado e retorna erro explícito. Release e Cloud Run permanecem pendentes. Veja o [plano de implementação](docs/plano-de-implementacao.md).

Para repetir a validação do adapter, execute `make postgres-check` (requer Docker; usa um container PostgreSQL descartável, sem Google Cloud ou API key). Para apontar a aplicação a um PostgreSQL já existente, configure `EVENTOPS_DATABASE_URL` fora do repositório. O startup aplica migrations empacotadas; para produção, separar essa etapa em job com credencial DDL é pendência. Veja o [runbook cloud candidato](docs/operacao-cloud.md).

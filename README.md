# Como Treinar Seu Agente de IA (Sem Incendiar a Cloud)

**DevFest 2026 · EventOps AI · Docker Compose local, Google Cloud ao final.**

Aplicação demonstrativa que sugere palestras, responde dúvidas com fontes e simula reservas. Todos os dados são fictícios. O MVP atual funciona em modo offline determinístico e não chama Gemini nem qualquer serviço externo.

## Requisitos

Para o caminho mais simples, instale Docker Engine ou Docker Desktop com Docker Compose v2. Para desenvolver sem containers, use Python 3.11 e `make`. Node 24.18.0 e Playwright Chromium são necessários somente para os checks completos; a aplicação em si não precisa deles.

## Início rápido com Docker

Na raiz do projeto:

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Abra <http://127.0.0.1:8000>. O modo padrão é offline: não requer chave Google, Ollama ou acesso a serviços externos. SQLite e dados de demonstração ficam no volume `eventops-data` e sobrevivem a reinicializações.

Comandos úteis:

```bash
docker compose logs -f app  # acompanhar logs; Ctrl+C sai dos logs
docker compose down         # parar, preservando os dados
docker compose down -v      # parar e apagar banco e pesos locais
```

### Executar com Python (desenvolvimento)

Crie o ambiente e instale as dependências travadas para desenvolvimento e agente:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make setup
```

Copie a configuração de exemplo e carregue-a no shell. O `make run` não lê o arquivo `.env` automaticamente:

```bash
cp .env.example .env
set -a
source .env
set +a
make run
```

Abra <http://127.0.0.1:8000> e use `Ctrl+C` para parar. `make setup` valida Python 3.11 e instala os arquivos com hashes SHA-256 em `requirements/`. No PowerShell, use Docker Compose ou carregue as variáveis de ambiente pelo mecanismo do seu shell.

Para executar a suíte completa de verificações, instale Node 24.18.0, as dependências JavaScript e Chromium do Playwright:

```bash
npm ci
python -m playwright install --with-deps chromium  # Linux
make check
```

Em macOS/Windows, instale o navegador com `python -m playwright install chromium`. `make check` roda lint, typecheck, testes, E2E e evals offline. `make pre-push` também constrói o pacote e executa o smoke com Docker Compose.

### Modos do agente

`EVENTOPS_MODE` controla o modo da aplicação e permanece `offline`. `EVENTOPS_AGENT_MODE` escolhe o provider do chat:

- `offline` (padrão): respostas determinísticas, sem baixar modelo nem chamar APIs.
- `local`: usa Ollama. Defina `EVENTOPS_AGENT_MODE=local` no `.env`. Para CPU, inicie a aplicação e Ollama e baixe o modelo:

  ```bash
  docker compose --profile local-model up --build -d app ollama
  docker compose --profile local-model run --rm model-init
  ```

  Para NVIDIA/CUDA, instale NVIDIA Container Toolkit e use o arquivo base junto com o override:

  ```bash
  docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu up --build -d app ollama
  docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu run --rm model-init
  ```
- `live`: usa Gemini via Google ADK. A imagem Docker Compose atual não inclui esse extra opcional; use o ambiente Python instalado por `make setup`, carregue `EVENTOPS_AGENT_MODE=live` e `GOOGLE_API_KEY` no shell e rode `make run`. Chamadas live usam serviço externo e podem consumir quota; não coloque a chave no Git.

O seletor da interface permite escolher Agente único ou Coordenador + especialistas. Em modo `live`, Gemini responde no single e faz o roteamento do coordenador multi; em `local`, Ollama faz os dois papéis. Os especialistas usam ferramentas locais verificadas nos dois modos. Para instruções de reset, banco, diagnóstico e avaliação, consulte [operação local](docs/operacao-local.md). Dependências Python são fixadas nos locks SHA-256 em `requirements/`.

### Reset local seguro

Pare o servidor e execute `python scripts/local/reset_demo.py`. O script só remove o SQLite local indicado por `EVENTOPS_DATABASE` (ou `var/eventops.sqlite3` por padrão), diretamente dentro de `var/`; também apaga seus arquivos WAL/SHM. Ele recusa modo diferente de `offline`, links simbólicos e caminhos fora desse diretório. Não use `rm` para apontar o reset a outros dados.

### Erros e identidade da API

Rotas JSON retornam erros no formato `{"error":{"code":"...","message":"...","request_id":"..."}}`; o mesmo identificador vem no cabeçalho `X-Request-ID`. Payloads inválidos recebem 422 (`invalid_request`), origem mutável ausente/não permitida recebe 403, recurso inexistente recebe 404, conflito de reserva recebe 409 e falha inesperada retorna mensagem genérica 500. Campos `user_id` enviados pelo cliente são rejeitados pelo schema. O navegador recebe identidade fictícia em cookie opaco HttpOnly, SameSite=Lax, validade de 24 horas e Secure configurável com `EVENTOPS_COOKIE_SECURE`; o valor persistido é somente o hash do cookie. Preview e confirmação pertencem ao mesmo navegador.

Para uma origem servida em outro host/porta, defina `EVENTOPS_ALLOWED_ORIGINS` com origens HTTP/S separadas por vírgula, sem caminhos (por exemplo `https://demo.example`). Por padrão, operações mutáveis aceitam a origem da própria aplicação.

## O que funciona

- **Agenda:** 20 sessões fictícias; filtros por trilha, nível e horário; até três escolhas sem conflito.
- **FAQ:** busca lexical em oito documentos Markdown, com citações de arquivo e seção e abstenção quando não há evidência.
- **RAG semântico opcional:** retrieval híbrido local com Ollama embeddings e PostgreSQL/pgvector; a busca lexical segue disponível como baseline e fallback. Veja [operação local](docs/operacao-local.md#rag-semântico-local-opcional).
- **Case de benchmark do RAG local:** resultados comparativos, metodologia reproduzível, explicação de Recall@3/MRR e oportunidades de otimização em LLM, qualidade e FinOps em [case-benchmark-rag-local](docs/case-benchmark-rag-local.md).
- **Reserva simulada:** identidade de demonstração por cookie HttpOnly, prévia separada da confirmação, validade de cinco minutos, checagem de capacidade e idempotência no SQLite.
- **Agente único:** conversa via `/api/chat`, com tools de leitura para agenda e FAQ, fontes validadas e proposta de reserva que sempre exige preview e confirmação pela interface.
- **Sessões e histórico:** identidade e últimos quatro turnos persistidos no banco; recuperação após reinício, expiração em 24 h e bloqueio de chamadas simultâneas por conversa. API e MCP consultam o mesmo catálogo persistido.
- **API:** `GET /health`, `GET /api/sessions`, `POST /api/schedule`, `POST /api/faq`, `POST /api/chat`, `POST /api/reservations/preview` e `POST /api/reservations`.

Não há login real, reserva real, pagamentos nem calendário de terceiros. Agenda e FAQ são determinísticos; o chat identifica os modos offline, Ollama local e Gemini live.

Para publicar, validar e encerrar a API temporária no Cloud Run, use o [runbook Cloud](docs/operacao-cloud.md), que reúne deploy, smoke, arquitetura validada, custos e teardown. A infraestrutura foi recriada e validada em 10/10/2026 e está ativa; Cloud SQL gera custo enquanto permanecer ligado.

## Verificações

```bash
make lint
make typecheck
make test
make e2e
make eval-offline
make eval-compare
make build
make check
```

`make check` reúne os gates offline. `make pre-push` também constrói o pacote e executa o smoke com Docker Compose, então requer Docker Engine/Desktop. Para lint e E2E, siga a instalação de Node 24.18.0 e Playwright Chromium descrita acima. `npm ci` instala as dependências JavaScript e prepara Husky; o hook `.husky/pre-push` chama `make pre-push`. GitHub Actions executa o mesmo alvo em push e pull request. `make e2e` usa banco temporário; `make eval-offline` avalia 40 casos, incluindo replay multi-turno de contexto.

### Diagnóstico local

- **Porta ocupada:** use `EVENTOPS_PORT=8001 make run` e abra a URL com essa porta.
- **Banco sem permissão de escrita:** configure `EVENTOPS_DATABASE` para um diretório existente e gravável; a inicialização cria apenas o diretório do banco escolhido.
- **Chromium não abre ou falta biblioteca:** execute `python -m playwright install --with-deps chromium` em Linux ou `python -m playwright install chromium` nos demais ambientes. A aplicação em runtime não precisa de Node nem do navegador.
- **Catálogo inválido/incompatível:** a inicialização falha com mensagem explícita se os oito documentos FAQ previstos estiverem ausentes/alterados, ou se o banco existente divergir do catálogo enquanto houver reservas.

Para executar evals live, ative o ambiente Python instalado por `make setup` e exporte `GOOGLE_API_KEY` e `EVENTOPS_AGENT_MODE=live`. O protocolo requer confirmação explícita e roda três rodadas, com até 123 chamadas por arquitetura:

```bash
make eval-live LIVE_CONFIRM=1
```

Essa execução usa Gemini e pode consumir quota. A avaliação da arquitetura multi live ainda não está habilitada.

## Documentação

- [Operação local](docs/operacao-local.md): configuração, reset seguro, RAG local e PostgreSQL.
- [Quality gates](docs/quality-gates.md): comandos e critérios de validação.
- [Pendências funcionais](docs/pendencias.md): limitações conhecidas e itens sem comprovação.
- [Benchmark de RAG](docs/case-benchmark-rag-local.md): método e resultados do experimento local.
- [Runbook Cloud](docs/operacao-cloud.md): estado atual, recriação, validação, custos e encerramento da infraestrutura temporária.

Para repetir a validação do adapter PostgreSQL, execute `make postgres-check` (requer Docker; usa um container descartável, sem Google Cloud ou API key). Para apontar a aplicação a um PostgreSQL existente, configure `EVENTOPS_DATABASE_URL` fora do repositório. O startup aplica migrations empacotadas; para produção, separar essa etapa em job com credencial DDL segue pendente.

# Guia para abrir um novo repositório

Este guia registra como migrar o projeto validado localmente e na cloud para um
repositório novo. O objetivo é preservar o código e as evidências reproduzíveis
em grupos de commits pequenos, com mensagens semânticas em inglês.

## Antes de publicar

1. Crie o repositório vazio e confirme o proprietário, a visibilidade e a branch
   padrão. Não envie credenciais para criar ou configurar o repositório.
2. Faça uma cópia de trabalho limpa do projeto e revise `git status` e
   `git diff`. Não remova nem reescreva mudanças locais sem revisá-las.
3. Confira os documentos de operação e substitua URLs, IDs de projeto, nomes de
   recursos, datas e custos que já não representem o estado atual. A validação
   remota anterior foi concluída e os recursos EventOps foram removidos; não
   descreva a infraestrutura antiga como ativa.
4. Revise os exemplos de configuração e scripts para garantir que não contenham
   chaves, tokens, senhas, dados pessoais ou valores de state.
5. Adicione cada grupo abaixo separadamente, confira o staged diff e só então
   crie o commit. Envie a branch apenas depois de conferir a sequência final.

## Arquivos para versionar

Em geral, versionar os arquivos de origem, configuração, documentação e testes
que já fazem parte do projeto:

- Aplicação: `app/`, `mcp_server/` e os dados fictícios necessários ao produto em
  `app/data/`.
- Testes e avaliações: `tests/`, `evals/` e suas fixtures sintéticas. Eles
  registram contratos e permitem repetir a validação offline.
- Automação: `scripts/`, `Makefile`, `.github/workflows/`, `.husky/`,
  `Dockerfile`, `compose.yaml` e `compose.gpu.yaml`.
- Infraestrutura como código: `infra/terraform/*.tf`,
  `infra/terraform/.terraform.lock.hcl` e o `.gitignore` do diretório.
  Versione a configuração, nunca o state ou credenciais.
- Documentação: `README.md`, `docs/` e `requirements/README.md`. Antes da
  migração, atualize fatos remotos que mudaram após o teardown.
- Metadados e locks de dependências: `pyproject.toml`, `uv.lock`, arquivos
  `requirements/py311-*.txt` com hashes, `package.json`, `package-lock.json`,
  `eslint.config.js`, `.node-version` e `.python-version`.
- Arquivos de repositório: `.gitignore`, `.dockerignore` e hooks versionados.
  Confirme que os hooks não imprimem segredos nem dependem de estado pessoal.

Os arquivos de lock devem acompanhar a configuração de dependências. Isso deixa
instalações, CI e builds do novo repositório reproduzíveis.

## Arquivos para manter fora do Git

O `.gitignore` atual já exclui a maior parte destes caminhos. Confira a regra no
novo repositório e não force sua inclusão com `git add -f`:

- `.env` e variantes locais; somente `.env.example`, sem valores secretos, deve
  ser versionado.
- `infra/terraform/terraform.tfstate*`, planos Terraform, credenciais e arquivos
  locais de URL como `infra/terraform/service-url.txt`. State pode conter
  senhas e URLs sensíveis.
- `.terraform/` e caches de providers. Mantenha o lock file
  `infra/terraform/.terraform.lock.hcl`.
- `.venv/`, `venv/`, `node_modules/`, caches Python, `build/`, `dist/`,
  `*.egg-info/` e arquivos compilados.
- `reports/`, `coverage.*`, `.coverage`, `test-results/`, relatórios Playwright
  e logs locais. Se uma evidência for necessária, gere uma versão sanitizada e
  deliberadamente revisada.
- Bancos SQLite, WAL/SHM, dados em `var/`, dumps, backups e dados reais de
  usuários. Mantenha apenas seeds fictícios intencionais e pequenos.
- Chaves de API, tokens, service account keys, certificados privados, arquivos
  de credenciais Google, cookies e saídas de comandos que revelem segredos.

Antes do primeiro push, examine tanto arquivos rastreados como não rastreados:

```bash
git status --short
git diff --check
git diff --cached
git ls-files
```

Se algum segredo já tiver entrado em um commit, removê-lo de um commit posterior
não o invalida: revogue ou rotacione a credencial e limpe o histórico antes de
publicar.

## Sequência de commits por grupos

Use a sequência como roteiro. Um grupo pode ser dividido em commits menores
quando reunir mudanças independentes; cada commit deve representar uma única
mudança revisável. Prefira adicionar arquivos explicitamente ao stage, em vez de
usar `git add .` durante a migração.

| Ordem | Grupo | Exemplos de arquivos | Mensagem semântica em inglês |
|---|---|---|---|
| 1 | Base do repositório e ferramentas | `.gitignore`, `.dockerignore`, `pyproject.toml`, `Makefile`, metadados de Python/Node, locks e ESLint | `chore(repo): bootstrap project tooling` |
| 2 | Catálogo e regras de domínio | `app/data/`, `app/schedule.py`, `app/faq.py`, `app/reservations.py`, `app/data_validation.py` | `feat(domain): add event catalog and booking rules` |
| 3 | Persistência e sessões | `app/storage.py`, `app/chat_sessions.py`, `app/migrations/`, `app/postgres_compat.py` | `feat(storage): persist bookings and chat sessions` |
| 4 | API e contratos | `app/main.py`, `app/schemas.py`, `app/tools.py`, testes de integração/contrato pertinentes | `feat(api): expose schedule faq and booking endpoints` |
| 5 | Interface web | `app/static/` e alterações de API estritamente necessárias | `feat(web): add event assistant interface` |
| 6 | Agentes e MCP | `app/agent.py`, `app/agents/`, `app/mcp_client.py`, `mcp_server/`, testes correspondentes | `feat(agent): add single and coordinated chat modes` |
| 7 | RAG e recuperação | `app/rag.py`, metadados e avaliações de RAG, scripts de benchmark relacionados | `feat(rag): add optional hybrid retrieval` |
| 8 | Resiliência e métricas | `app/resilience.py`, `app/metrics.py`, testes específicos | `feat(runtime): add provider resilience and metrics` |
| 9 | Testes e avaliações | `tests/`, `evals/`, `scripts/evals/`; agrupe por domínio se o conjunto ficar grande | `test(eval): add offline quality and security scenarios` |
| 10 | Container e execução local | `Dockerfile`, `compose.yaml`, `compose.gpu.yaml`, scripts locais e checks de Compose/PostgreSQL | `build(container): add reproducible local deployment` |
| 11 | CI e quality gates | `.github/workflows/`, `.husky/`, checks e documentação dos gates | `ci: run offline quality gates on pull requests` |
| 12 | Operação e infraestrutura cloud | `infra/terraform/*.tf`, scripts cloud e runbooks revisados, sem state ou URL temporária | `feat(infra): define disposable cloud deployment` |
| 13 | Documentação de uso e decisões | README, operação local, limitações e benchmarks sanitizados | `docs: document setup operations and validation` |

### Mensagens prontas por grupo

Use estes títulos como ponto de partida. Se um grupo for dividido em vários
commits, adapte o escopo e descreva a mudança menor no título.

1. `chore(repo): bootstrap project tooling`
2. `feat(domain): add event catalog and booking rules`
3. `feat(storage): persist bookings and chat sessions`
4. `feat(api): expose schedule faq and booking endpoints`
5. `feat(web): add event assistant interface`
6. `feat(agent): add single and coordinated chat modes`
7. `feat(rag): add optional hybrid retrieval`
8. `feat(runtime): add provider resilience and metrics`
9. `test(eval): add offline quality and security scenarios`
10. `build(container): add reproducible local deployment`
11. `ci: run offline quality gates on pull requests`
12. `feat(infra): define disposable cloud deployment`
13. `docs: document setup operations and validation`

Os grupos 2–8 devem seguir as dependências do código: por exemplo, persistência
antes dos endpoints que a usam, e o servidor MCP antes dos testes que iniciam o
processo. Não é necessário forçar todos os grupos a um único commit. Mova um
arquivo para outro grupo se isso mantiver cada commit compilável e fácil de
revisar.

### Formato das mensagens

Use Conventional Commits, em inglês, com tipo e escopo curtos:

```text
<type>(<scope>): <imperative summary>
```

Tipos usuais: `feat` para funcionalidade, `fix` para correção, `test` para
cenários de validação, `build` para empacotamento/container, `ci` para automação,
`docs` para documentação e `chore` para manutenção. Use corpo quando explicar
motivo, impacto ou uma decisão que não fique clara pelo título. Evite mensagens
como `update`, `changes` ou `fix stuff`.

Exemplos:

```text
fix(rag): allow Vertex AI credentials through ADC
test(config): cover Vertex AI without an API key
docs(cloud): record teardown and current resource state
```

## Validação e push

O histórico de validação deste projeto inclui os gates locais e o smoke remoto
da infraestrutura então implantada. Depois do teardown, o smoke remoto antigo é
evidência histórica; não é uma validação de recursos atualmente ativos. Para o
novo repositório:

1. Rode `make check`, `make build`, `make compose-check` e
   `make postgres-check` na versão final que será publicada.
2. Revise os resultados e os diffs staged; mantenha relatórios gerados fora do
   Git, salvo quando uma evidência sanitizada tiver valor duradouro.
3. Revise novamente referências a projeto, região, URL, segredo e estado cloud.
   Um futuro deploy precisa usar projeto e credenciais escolhidos para o novo
   repositório.
4. Faça push e confirme que CI executou sobre o mesmo commit validado.

O teardown anterior removeu os recursos EventOps e manteve o projeto Google, as
APIs habilitadas e o alerta geral de orçamento. Recriar infraestrutura exige
uma nova revisão do Terraform e um novo inventário; não reutilize state antigo.

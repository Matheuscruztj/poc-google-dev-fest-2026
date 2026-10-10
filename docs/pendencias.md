# Pendências funcionais e controle de sessões

Revisão funcional: 2026-10-09; cloud: 2026-10-10. Escopo: funcionalidades e critérios de validação confrontados com o código. Infraestrutura remota, configuração de `GOOGLE_API_KEY` e execução de
gates dependentes dessas condições ficam fora da lista funcional abaixo. Em
10/10/2026, a infraestrutura temporária foi validada com agentes single/multi
e RAG híbrido remoto e removida após o smoke; o alerta de orçamento permanece.
Passar nos testes atuais não comprova requisitos que o avaliador ainda não verifica.

## Controle de sessões implementado

| ID | Estado | Entrega | Evidência |
|---|---|---|---|
| S01 | Concluído | API e MCP consultam o mesmo banco configurado; JSON é somente seed de banco vazio. MCP lê alterações a cada chamada, inclusive após iniciar o processo. | `mcp_server/server.py`, `app/mcp_client.py`, `tests/contracts/test_mcp.py`, `tests/integration/test_api.py` |
| S02 | Concluído | Histórico por sessão de navegador persistido, limitado a quatro turnos/oito mensagens, recuperado após recriar a aplicação. Identidade resolvida pelo hash do cookie opaco. | `app/chat_sessions.py`, `tests/unit/test_chat_sessions.py`, `tests/integration/test_api.py` |
| S03 | Concluído | Lease no banco impede chamadas simultâneas por conversa. Outra chamada recebe HTTP 409 `chat_busy`; falha/cancelamento libera o lease; após crash, expira em 120 s. Proprietário antigo não salva nem libera lease substituído. | `app/chat_sessions.py`, `tests/unit/test_chat_sessions.py`, `tests/integration/test_api.py` |
| S04 | Concluído | Sessões expiram em 24 h; cookie existente não recebe prazo novo sem renovar a validade no banco. Criar uma sessão limpa identidades expiradas e histórico/leases por cascade, preservando reservas e recibos. | `app/storage.py`, `app/main.py`, `tests/unit/test_chat_sessions.py` |
| S05 | Concluído | Schema SQLite v3 e migration PostgreSQL `0002_chat_sessions.sql`; atualização aditiva preserva catálogo/reservas. Cookies legados sem expiração são tratados como expirados. | `app/storage.py`, `app/migrations/0002_chat_sessions.sql`, `tests/unit/test_storage.py`, `scripts/checks/check_postgres.py` |

O banco contém texto das conversas fictícias. Histórico compartilhado exige o
mesmo banco e cookie. Os providers offline continuam determinísticos e não
interpretam histórico. O lease de 120 s supera o deadline máximo atual (65 s);
aumentar o deadline exige rever o lease. A limpeza é oportunista, ao criar uma
sessão, sem job periódico. Persistência local não aprova G6 cloud.

## Funcionalidades pendentes

| ID | Prioridade | Estado | Pendência | Critério de conclusão |
|---|---|---|---|---|
| F01 | Alta | Parcial | O roteador do coordenador usa Gemini live no perfil Cloud validado; os especialistas continuam determinísticos e usam ferramentas locais/MCP, não modelos independentes. O provider local Ollama para o coordenador não foi validado nesta sessão. | Se especialistas baseados em LLM forem necessários, implementar providers, permissões, orçamento e histórico por especialista. Manter as ferramentas determinísticas como validação final. W4.3. |
| F02 | Alta | Pendente | Runner pareado suporta somente offline. | Selecionar provider/modelo, controlar consumo e preservar tentativas das duas arquiteturas. Executar Gemini exige chave/quota. W4.6. |
| F03 | Alta | Concluído local | Single offline extrai e aplica nível solicitado, inclusive formas acentuadas e plurais; trilha é reconhecida por palavra inteira. | `app/agent.py: OfflineProvider.respond`; casos fixos em `tests/unit/test_agent.py`. |
| F04 | Alta | Concluído local | Casos de agenda declaram trilha, nível, horário e quantidade; avaliador confere filtros, mínimo/exato e conflitos contra o catálogo. O pedido de três opções após 14h exige três resultados. | `app/evaluators.py`, `evals/cases.jsonl`. |
| F05 | Alta | Concluído local | Cada caso usa SQLite isolado e executa passos por HTTP com cookie/origem; cobre prévia abandonada sem confirmação, token inválido, capacidade esgotada, confirmação e replay idempotente. Estado persistido é lido ao final. | `app/evaluators.py: execute_case_state`, `scripts/evals/run_evals.py`, `scripts/evals/run_comparison.py`, casos `adv-duplicate` e `adv-last-seat`. O browser real continua coberto pelo gate E2E, fora do replay de eval. |
| F06 | Alta | Parcial local | Breaker compartilhado por processo protege providers single (incluindo Ollama) e o breaker MCP existente protege o multi. Harness de eval sobe subprocessos MCP reais para timeout e saída abrupta e registra o lifecycle. | `app/agent.py`, `app/main.py`, `app/mcp_client.py`, `evals/harness.py`, `evals/mcp_failure_server.py`. Controle de retries internos do SDK Gemini depende da integração Gemini por API, ainda adiada. |
| F07 | Média | Concluído local | Tokens medidos pelo Ollama/ADK são agregados por chamada/retry; métricas mostram cobertura parcial, sucesso, duração, chamadas e custo por tarefa. Tabela datada identifica custo zero offline e mantém custo de compute local/desconhecido como indisponível. Dashboard HTML local é gerado junto ao JSON. | `app/agent.py`, `app/data/model_prices.json`, `app/metrics.py`, `scripts/evals/report_metrics.py`. Preço Gemini será preenchido quando a integração por API for adaptada. |
| F08 | Média | Concluído local | Metadados estruturados de versão, atualização, validade, status, conflito e confiança são validados e chegam às citações. Retrieval exclui regras futuras, expiradas, conflitantes e não confiáveis; fixture contaminada isolada exige abstenção. | `app/data/faq_metadata.json`, `app/data_validation.py`, `app/faq.py`, `evals/harness.py`, `tests/fixtures/adversarial/faq_poisoned_chunk.json`. A fixture não entra no catálogo publicado. |
| F09 | Média | Concluído local | `make release-check` executa gates offline, build e Compose; compara hash do candidato em eval/build/imagem, dataset/catálogo, wheel/sdist e digest Docker, falhando com evidência ausente ou divergente. | `scripts/checks/candidate.py`, `scripts/checks/release_check.py`, `scripts/checks/check_build.py`, `scripts/checks/check_compose.py`, `Makefile`. Gate live continua separado e exige execução autorizada. |

## RAG semântico com pgvector — status local e remoto

O armazenamento vetorial está implementado no Compose local e foi exercitado
em uma implantação temporária Cloud Run/Cloud SQL. No remoto foi usado
`gemini-embedding-001` com saída de 768 dimensões, PostgreSQL 17/pgvector e
busca híbrida com RRF. Os recursos remotos foram apagados após a validação;
o perfil continua opcional e lexical segue como padrão.

| ID | Prioridade | Estado | Pendência | Critério de conclusão |
|---|---|---|---|---|
| R01 | Alta | Implementado local | Contrato Ollama `nomic-embed-text:latest`, 768 dimensões, versão de índice, timeout, limite por texto e cache local; modelo configurável. | `app/rag.py`, `EVENTOPS_RAG_MODE`, `OLLAMA_EMBEDDING_MODEL`. Dimensão/provider/modelo divergentes são recusados. |
| R02 | Alta | Implementado local | Serviço PostgreSQL 17/pgvector, volume persistente, healthcheck e criação idempotente da extensão/schema. | Perfil `rag` em `compose.yaml`; smoke vetorial em `scripts/checks/check_postgres.py`. |
| R03 | Alta | Implementado local | Sincronização transacional de chunks e metadados, hash de conteúdo, atualização e remoção idempotentes. | `PgVectorFAQ.sync`; embedding é calculado só para chunk alterado. |
| R04 | Alta | Implementado local | Busca semântica com filtros de segurança e fusão por reciprocal rank fusion (RRF) com a busca lexical; fallback lexical em erro vetorial durante consulta. | `PgVectorFAQ.search`, `search_hybrid`; limite padrão de três e threshold inicial configurado. |
| R05 | Alta | Concluído local | Dataset versionado medido em lexical e híbrido: recall@3 0,600 → 0,667, MRR 0,567 → 0,622 e abstenção 0/1 → 1/1. A amostra tem 15 perguntas com fonte e uma pergunta fora do catálogo; manter calibração em novas perguntas antes de trocar o padrão. | `evals/rag_cases.jsonl`, `scripts/evals/eval_rag.py`; limiares iniciais: vetor 0,65 e lexical 0,34. |
| R06 | Alta | Concluído local | Seis casos híbridos cobrem injeção, metadados futuros/expirados/conflitantes/não confiáveis, duplicatas e dado fora de escopo: 0 fontes bloqueadas citadas, recall 1,0 nas fontes esperadas e 0 falhas de abstenção. | `evals/rag_security_cases.jsonl`, resultado local `reports/rag-local-20261009/rag-hybrid.json`. |
| R07 | Média | Concluído para POC Cloud | Cloud Run conectou ao Cloud SQL por socket gerenciado; extensão, schema, embeddings, sincronização e busca semântica foram exercitados. A busca multilíngue retornou `acessibilidade.md#Recursos`, score final 1.0. Não é aprovação de produção: sem backups, HA, pool dedicado ou persistência operacional. | Evidência: revisão `eventops-api-00038-4kh`, smoke em 10/10/2026 e [runbook](operacao-cloud.md). |
| R08 | Média | Parcial local | `eval-rag` e o benchmark de chat publicam chamadas/tokens/duração de embedding, cache, consulta vetorial e fallback; compute/energia local ainda não tem estimativa financeira. | `scripts/evals/eval_rag.py`, `scripts/evals/benchmark_rag_chat.py`; custo de API local é zero. |

## Validações e materiais restantes

- Smoke remoto single e multi/live foi aprovado em 10/10/2026; comparação
  quantitativa pareada continua pendente porque o runner de comparação ainda
  é offline e requer orçamento/quota específicos para Gemini.
- Ollama real CPU/GPU precisa ser executado e medido na máquina de apresentação;
  contratos não substituem essa execução. CUDA é opcional.
- `make pre-push` completo deve ser repetido para cada candidato relevante;
  relatórios antigos não aprovam mudanças novas.
- A2A é bônus. Comparar single/multi ambos via MCP é opcional para isolar a
  orquestração. Gravação de contingência ainda não foi produzida.
- Dataset atual: 40 casos, 20 normais e 20 adversariais. O bloqueio histórico de
  Playwright não representa a validação aprovada em 2026-10-09.

## Validação das mudanças de sessões e F05–F09

**Resultado local em 2026-10-09:** `make release-check` aprovado no candidato
`d41a164b016395eb5a998809e21812c1da0a874a4bc557de35526155f9739aa1`: Ruff,
formatação, ESLint, mypy, 137 testes sem navegador, cobertura de branches (FAQ
87,5%), três testes E2E, 40/40 evals offline, wheel/sdist e smoke Compose com
catálogo/MCP, histórico/identidade e reinício. `make postgres-check` aprovou
migrations, histórico/leases, idempotência e disputa da última vaga.
`make eval-compare` aprovou 40/40 casos por arquitetura em cada uma das três
rodadas; a fixture adversarial RAG, abstenção, citação e metadados passaram.

Relatórios locais, ignorados pelo Git: `reports/build.json`,
`reports/20261009T045651Z-a9e6ea93/evals.json`,
`reports/20261009T045738Z-ad08922e/comparison.json` e
`reports/compose.json`. O release-check confirmou hashes do candidato e dos
artefatos. Esses resultados locais não aprovam qualidade live G4 nem operação
cloud G6.

```bash
make release-check PYTHON=.venv/bin/python
make postgres-check PYTHON=.venv/bin/python
make eval-compare PYTHON=.venv/bin/python
```

PostgreSQL/Compose usam recursos locais descartáveis. Contratos verificam
API/MCP compartilhando catálogo, mudanças após iniciar MCP, histórico após
reinício, isolamento de cookies, concorrência, lease expirado, rollback e
limpeza do histórico sem apagar reservas.

# Pendências funcionais e controle de sessões

Revisão: 2026-10-09. Escopo: objetivos de `visao-completa.md`, tasks de
`plano-de-implementacao.md` e critérios de `quality-gates.md`, confrontados com o
código. Infraestrutura remota, configuração de `GOOGLE_API_KEY` e execução de
gates dependentes dessas condições ficam fora da lista funcional abaixo.
Passar nos testes atuais não comprova requisitos que o avaliador ainda não verifica.

## Controle de sessões implementado

| ID | Estado | Entrega | Evidência |
|---|---|---|---|
| S01 | Concluído | API e MCP consultam o mesmo banco configurado; JSON é somente seed de banco vazio. MCP lê alterações a cada chamada, inclusive após iniciar o processo. | `mcp_server/server.py`, `app/mcp_client.py`, `tests/contracts/test_mcp.py`, `tests/integration/test_api.py` |
| S02 | Concluído | Histórico por sessão de navegador persistido, limitado a quatro turnos/oito mensagens, recuperado após recriar a aplicação. Identidade resolvida pelo hash do cookie opaco. | `app/chat_sessions.py`, `tests/unit/test_chat_sessions.py`, `tests/integration/test_api.py` |
| S03 | Concluído | Lease no banco impede chamadas simultâneas por conversa. Outra chamada recebe HTTP 409 `chat_busy`; falha/cancelamento libera o lease; após crash, expira em 120 s. Proprietário antigo não salva nem libera lease substituído. | `app/chat_sessions.py`, `tests/unit/test_chat_sessions.py`, `tests/integration/test_api.py` |
| S04 | Concluído | Sessões expiram em 24 h; cookie existente não recebe prazo novo sem renovar a validade no banco. Criar uma sessão limpa identidades expiradas e histórico/leases por cascade, preservando reservas e recibos. | `app/storage.py`, `app/main.py`, `tests/unit/test_chat_sessions.py` |
| S05 | Concluído | Schema SQLite v3 e migration PostgreSQL `0002_chat_sessions.sql`; atualização aditiva preserva catálogo/reservas. Cookies legados sem expiração são tratados como expirados. | `app/storage.py`, `app/migrations/0002_chat_sessions.sql`, `tests/unit/test_storage.py`, `scripts/check_postgres.py` |

O banco contém texto das conversas fictícias. Histórico compartilhado exige o
mesmo banco e cookie. Os providers offline continuam determinísticos e não
interpretam histórico. O lease de 120 s supera o deadline máximo atual (65 s);
aumentar o deadline exige rever o lease. A limpeza é oportunista, ao criar uma
sessão, sem job periódico. Persistência local não aprova G6 cloud.

## Funcionalidades pendentes

| ID | Prioridade | Estado | Pendência | Critério de conclusão |
|---|---|---|---|---|
| F01 | Alta | Pendente | Providers de modelo para coordenador/especialistas: Gemini e Ollama multi retornam indisponibilidade. | Implementar providers, permissões, orçamentos e histórico; validar contratos com modelos controlados. A chave sozinha não entrega a funcionalidade. W4.3. |
| F02 | Alta | Pendente | Runner pareado suporta somente offline. | Selecionar provider/modelo, controlar consumo e preservar tentativas das duas arquiteturas. Executar Gemini exige chave/quota. W4.6. |
| F03 | Alta | Pendente | Single offline ignora nível solicitado no chat. Desenvolvimento iniciante inclui `S05`, intermediário. | Extrair/aplicar nível e verificar resultados fixos para cada nível. `app/agent.py: OfflineProvider.respond`. |
| F04 | Alta | Pendente | Avaliador aceita trilha/nível/horário errados e não exige três opções disponíveis. O pedido de três IA após 14h aceita uma sessão de outra trilha. | Expectativas explícitas; verificar filtros, quantidade e conflitos independentemente do seletor; respostas erradas devem reprovar. G4, `app/evaluators.py`, `evals/cases.jsonl`. |
| F05 | Alta | Pendente | Runner executa somente chat; passos UI/API e estado inicial de reservas não são aplicados. Contador do agente não observa escritas no banco. | Executar interações em banco isolado por caso; observar preview, confirmação, capacidade, idempotência e efeitos reais. W3.6, `app/evaluators.py: run_case`. |
| F06 | Alta | Pendente | Breaker Gemini/Ollama, controle de retries internos do SDK e harness de atraso/encerramento abrupto de MCP ausentes. Comparativo multi usa resultado pronto para falhas. | Dependência de modelo controlada e falha de processo real; verificar deadline, tentativas, lifecycle e fallback. W5.1–W5.3, `evals/harness.py`. |
| F07 | Média | Pendente | FinOps: custos sempre `None`, mesmo com tokens; falta consumo de todas as chamadas/tentativas e dashboard local. | Somar consumo disponível, aplicar tabela datada de preços, distinguir desconhecido/zero e mostrar sucesso/duração/consumo/custo por tarefa. Preços/medições remotos ficam fora desta revisão. Visão §11, W5.6. |
| F08 | Média | Pendente | Chunks FAQ sem versão/data estruturadas; faltam regras desatualizadas/conflitantes e injection indireta por trecho recuperado. | Propagar metadados e recuperar fixtures contaminadas isoladas; verificar abstenção/citação e ausência de ações proibidas. Visão §7–8, G4. |
| F09 | Média | Pendente | `make release-check` previsto nos gates não existe; falta conferência de hashes/evidências do mesmo candidato. | Conferir código/dados/prompts/configuração/wheel/imagem; recusar evidência ausente/divergente. Aprovação live exige execução autorizada. W5.7. |

## Validações e materiais restantes

- Baseline single e comparação live exigem chave/quota e revisão. Resolver
  F01/F02 antes de considerar o multi live disponível.
- Ollama real CPU/GPU precisa ser executado e medido na máquina de apresentação;
  contratos não substituem essa execução. CUDA é opcional.
- `make pre-push` completo deve ser repetido para cada candidato relevante;
  relatórios antigos não aprovam mudanças novas.
- A2A é bônus. Comparar single/multi ambos via MCP é opcional para isolar a
  orquestração. Gravação de contingência ainda não foi produzida.
- Dataset atual: 40 casos, 20 normais e 20 adversariais. O bloqueio histórico de
  Playwright não representa a validação aprovada em 2026-10-09.

## Validação das mudanças de sessões

**Resultado local em 2026-10-09:** `make pre-push` completo aprovado: Ruff,
formatação, ESLint, mypy, 129 testes sem navegador, três testes E2E, cobertura de
branches exigida, 40/40 evals offline, wheel instalado fora do checkout e smoke
Compose com catálogo/MCP, histórico/identidade e recibo após reinício.
`make postgres-check` aprovou migrations repetidas, histórico/leases em conexões
independentes, idempotência e disputa da última vaga. `make eval-compare`
aprovou 40/40 casos por arquitetura em cada uma das três rodadas.

Relatórios locais, ignorados pelo Git: `reports/build.json`,
`reports/20261009T043229Z-8e0dba0f/evals.json` e
`reports/20261009T043003Z-994fdb42/comparison.json`. Logs do pre-push:
`/tmp/eventops-session-pre-push.log`. Esses resultados não aprovam F01–F09,
qualidade live G4 nem operação cloud G6.

```bash
make lint typecheck test e2e eval-offline PYTHON=.venv/bin/python
make postgres-check PYTHON=.venv/bin/python
make eval-compare PYTHON=.venv/bin/python
make build compose-check PYTHON=.venv/bin/python
```

PostgreSQL/Compose usam recursos locais descartáveis. Contratos verificam
API/MCP compartilhando catálogo, mudanças após iniciar MCP, histórico após
reinício, isolamento de cookies, concorrência, lease expirado, rollback e
limpeza do histórico sem apagar reservas.

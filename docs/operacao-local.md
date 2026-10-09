# Operação local

Execute o produto com Docker Compose, conforme o [README](../README.md). O Compose mantém SQLite no volume `eventops-data`; `app/data/sessions.json` é somente o seed inicial e as consultas usam as linhas SQLite. Os documentos FAQ Markdown continuam sendo fontes versionadas. O modo offline não precisa de CUDA, chave Gemini ou modelo local. `make check` precisa de Python 3.11, Node 24.18.0 e Playwright Chromium:

```bash
npm ci
python -m playwright install --with-deps chromium
make check
```

Compose publica `127.0.0.1:8000` e mantém SQLite no volume `eventops-data`. `EVENTOPS_PORT` altera a porta publicada. Para modelo local, use o perfil `local-model` em CPU. Com NVIDIA Container Toolkit/CUDA, use `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu up -d` e baixe pesos com `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu run --rm model-init`. Para Gemini via API, selecione `EVENTOPS_AGENT_MODE=live` e forneça `GOOGLE_API_KEY`; offline permanece o padrão.

Para apagar os dados do Compose, rode `docker compose down -v`; isso remove o banco e o cache de pesos Ollama. Para preservar pesos, remova somente o volume de dados SQLite. No modo Python direto, pare o servidor e rode `python scripts/reset_demo.py`, que só aceita SQLite dentro de `var/` e modo offline.

## Problemas comuns

- **Porta em uso:** escolha outra com `EVENTOPS_PORT=8001 make run`.
- **Sem permissão no caminho do banco:** escolha um diretório gravável em `EVENTOPS_DATABASE`; o erro de inicialização identifica a configuração.
- **Chromium não inicia:** instale as dependências Linux com `python -m playwright install --with-deps chromium`; em macOS/Windows, use `python -m playwright install chromium`.
- **GPU não aparece no Compose:** confira o driver NVIDIA, `nvidia-smi` e NVIDIA Container Toolkit; use o override `compose.gpu.yaml`. Valide primeiro o perfil CPU `local-model`.
- **Modelo local não responde:** confira `docker compose logs ollama`, aguarde o pull inicial e confirme `EVENTOPS_AGENT_MODE=local`.
- **Catálogo FAQ inválido:** inicialização interrompe se os oito nomes publicados divergirem. Não renomeie documentos sem atualizar o catálogo e os testes.
- **Banco diverge da agenda:** se ainda existem reservas, não é permitido substituir a agenda armazenada silenciosamente. Para a demo sintética local, pare o servidor e use o reset seguro.

O smoke de `make build` instala o wheel fora do checkout, inicializa o banco a partir do seed e valida consultas SQLite. `make e2e` usa SQLite temporário isolado por teste. `npm ci` prepara Husky; o hook versionado `.husky/pre-push` executa `make pre-push`, igual ao GitHub Actions.

## Agentes e MCP local

O servidor MCP recebe da API o caminho absoluto SQLite ou `EVENTOPS_DATABASE_URL`
e consulta o mesmo banco em cada chamada. Na execução manual, essas variáveis
selecionam o banco; `EVENTOPS_SEED_CATALOG=true` importa o seed apenas se vazio.
Na execução iniciada pela API, MCP não faz seed. `make eval-compare` usa banco
temporário próprio para não depender das alterações do catálogo da demo.

O histórico do chat fica no banco, limitado a quatro turnos por cookie, e
continua disponível após reiniciar a aplicação. Chamadas simultâneas com o mesmo
cookie recebem 409 `chat_busy`; aguarde a resposta antes de tentar novamente.
Em crash, o bloqueio expira em 120 s. Sessões de navegador expiram em 24 h;
criar uma nova sessão limpa identidades expiradas e seus históricos/leases,
preservando reservas. Bancos legados sem expiração exigem um cookie novo após
migração. Consulte o controle de [pendências](pendencias.md).

O chat usa **Agente único** por padrão. O seletor da página também permite **Coordenador + especialistas**, disponível no modo offline. O especialista de agenda usa um servidor MCP local via stdio; o processo é iniciado e encerrado por solicitação. Para inspecionar manualmente o servidor, execute `python -m mcp_server.server` em um terminal: stdout fica reservado ao protocolo MCP e os logs vão para stderr. Instale o extra travado do agente/MCP com `python -m pip install --require-hashes -r requirements/py311-agent.txt`.

`make eval-compare` executa três rodadas pareadas sobre os 40 casos, reproduzindo todas as mensagens de chat de cada caso e salva relatório em `reports/<run_id>/`. O experimento atual compara tools internas do single com MCP stdio no multi e rotula essa diferença no manifesto. Ele é offline e não aprova G4 live. A arquitetura multi live permanece desativada até receber seus providers ADK e passar pelo protocolo com Gemini.

# Operação local

Execute o produto com Docker Compose, conforme o [README](../README.md). O Compose mantém SQLite no volume `eventops-data`; `app/data/sessions.json` é somente o seed inicial e as consultas usam as linhas SQLite. Os documentos FAQ Markdown continuam sendo fontes versionadas. O modo offline não precisa de CUDA, chave Gemini ou modelo local. `make check` precisa de Python 3.11, Node 24.18.0 e Playwright Chromium:

```bash
npm ci
python -m playwright install --with-deps chromium
make check
```

Compose publica `127.0.0.1:8000` e mantém SQLite no volume `eventops-data`. `EVENTOPS_PORT` altera a porta publicada. Para modelo local, use o perfil `local-model` em CPU. Com NVIDIA Container Toolkit/CUDA, use `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu up -d` e baixe pesos com `docker compose -f compose.yaml -f compose.gpu.yaml --profile gpu run --rm model-init`. Para Gemini via API, selecione `EVENTOPS_AGENT_MODE=live` e forneça `GOOGLE_API_KEY`; offline permanece o padrão.

Para apagar os dados do Compose, rode `docker compose down -v`; isso remove o banco e o cache de pesos Ollama. Para preservar pesos, remova somente o volume de dados SQLite. No modo Python direto, pare o servidor e rode `python scripts/reset_demo.py`, que só aceita SQLite dentro de `var/` e modo offline.

## RAG semântico local (opcional)

O FAQ segue lexical por padrão. Para ativar retrieval híbrido local, o Compose usa
Ollama para embeddings (`nomic-embed-text:latest`, 768 dimensões) e PostgreSQL 17
com pgvector. Documentos e consultas usam o mesmo modelo. O schema grava provider,
modelo, versão e dimensão; uma incompatibilidade interrompe a inicialização para
evitar misturar vetores de modelos diferentes. O provider não envia dados a uma API
externa. A configuração do modelo/limite de tempo fica em `app/rag.py`.

No `.env`, defina `EVENTOPS_RAG_MODE=hybrid` e
`EVENTOPS_RAG_DATABASE_URL=postgresql://eventops:eventops-local-only@pgvector:5432/eventops`.
Em seguida, suba os serviços e baixe o modelo de embedding:

```bash
docker compose --profile rag up -d pgvector ollama
docker compose --profile rag run --rm rag-init
docker compose up --build -d app
```

No primeiro startup híbrido, a aplicação cria a extensão e o schema e indexa os
chunks do FAQ. Inicializações seguintes só reprocessam chunks alterados e removem
os que saíram do catálogo. A sincronização é transacional. Se Ollama ou pgvector
estiver indisponível, o modo híbrido falha no startup, para não servir índice
antigo silenciosamente. Durante consultas, falhas vetoriais usam a busca lexical
existente. `docker compose down` preserva o índice em `eventops-rag-data`; `down
-v` também o apaga. Para Python direto, ajuste `OLLAMA_BASE_URL`,
`OLLAMA_EMBEDDING_MODEL`, `EVENTOPS_RAG_MODE` e `EVENTOPS_RAG_DATABASE_URL` no
ambiente.
Se os embeddings e o modelo de chat estiverem em servidores Ollama distintos,
configure `OLLAMA_EMBEDDING_BASE_URL`; por padrão, ele acompanha `OLLAMA_BASE_URL`.

Os conjuntos de perguntas ficam em `evals/rag_cases.jsonl` e
`evals/rag_security_cases.jsonl`. O segundo testa prompt injection direto e
indireto (OWASP LLM01/LLM03 e ASI01/ASI02), fontes futuras, expiradas,
conflitantes e não confiáveis, duplicatas e abstenção fora do escopo. As fixtures
maliciosas são adicionadas somente ao índice do eval e removidas ao final.
Compare o baseline lexical com o híbrido após iniciar os serviços e configurar a
URL do banco:

```bash
make eval-rag
RAG_EVAL_MODE=hybrid make eval-rag
```

Para medir o consumo do mesmo Ollama no chat normal (FAQ inteiro no prompt) e no
chat híbrido (somente trechos recuperados), use três perguntas por rodada:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434 .venv/bin/python scripts/benchmark_rag_chat.py --mode plain --repeat 3
EVENTOPS_RAG_DATABASE_URL=postgresql://eventops:eventops-local-only@127.0.0.1:55432/eventops \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_EMBEDDING_BASE_URL=http://127.0.0.1:11435 \
.venv/bin/python scripts/benchmark_rag_chat.py --mode hybrid --repeat 3
```

O benchmark cria banco SQLite temporário separado por modo e informa tokens de
prompt/saída, latência e custo de API (zero para o provider local); custo de
energia/compute não é estimado.
Ambos os modos usam `OLLAMA_CONTEXT_LENGTH` (padrão 8192, faixa 1024–32768),
para evitar comparar baseline truncado com híbrido.

Medição desta máquina (2026-10-09): nove chats válidos em cada modo, mesmo
`qwen3:8b` Q4_K_M na RTX 4060 Ti, contexto 8192. O chat normal consumiu em média
4.956 tokens de entrada; o híbrido, 2.697 (−45,6%). Incluindo os 59 tokens de
consulta do embedder nesta amostra, a redução de tokens totais foi 44,2%. A
mediana de latência foi 3,20 s no normal e 3,13 s no híbrido. Os nove chats de
cada modo retornaram uma fonte válida; o híbrido usou `nomic-embed-text` local,
sem custo de API, com 3 chamadas de embedding para as três perguntas distintas
e 6 acertos do cache nas repetições. A indexação inicial dos 24 chunks levou
1,26 s e 656 tokens de embedding. A amostra é pequena e não mede energia; veja
os relatórios detalhados em `reports/rag-local-20261009/`.

O relatório em stdout inclui recall@3, MRR, acerto de abstenção, vazamento de
fontes bloqueadas e contadores e tempos do processo; o score retornado pela
fusão híbrida é RRF, não cosine similarity. Na amostra local de 16 perguntas, o
recall@3 passou de 0,600 para 0,667 e a abstenção de 0/1 para 1/1. O conjunto
OWASP de seis casos registrou zero fonte bloqueada citada e zero falha de
abstenção; amplie a amostra antes de generalizar esses resultados.

### Como interpretar as métricas de busca

- **Recall@3** responde: “a fonte esperada apareceu entre os três primeiros
  resultados?”. Um resultado de `0,667` significa que isso ocorreu em cerca de
  dois terços das perguntas avaliadas. Ele mede cobertura, não se a resposta do
  chat foi correta.
- **MRR** (Mean Reciprocal Rank) responde: “em que posição apareceu o primeiro
  resultado relevante?”. Para cada pergunta, a posição 1 vale `1`, a posição 2
  vale `0,5`, a posição 3 vale `0,333`; se não houver resultado relevante, vale
  `0`. A média dessas notas é o MRR. Portanto, quanto maior, mais cedo a busca
  coloca uma fonte útil.
- Em conjunto, Recall@3 mede se a fonte foi recuperada e MRR mede o quão alto ela
  ficou. Nenhuma das duas métricas avalia sozinha fidelidade, clareza ou
  segurança da resposta gerada: acompanhe também citações válidas, abstenção e
  vazamento de fontes bloqueadas.

### Próximas otimizações

Use estas ideias como hipóteses para novos experimentos; altere uma variável por
rodada e compare com o mesmo conjunto, hardware, modelo e contexto. Não promova
uma configuração que reduza tokens ou latência se ela piorar qualidade ou
segurança.

**LLM e latência**

- Aumente o número de perguntas e repetições e separe medição fria (modelo ainda
  não carregado) de aquecida. Registre p50/p95, tokens por segundo, duração de
  embedding e geração, uso de VRAM/RAM e erros. Nove chamadas são apenas um
  sinal inicial.
- Compare modelos e quantizações locais com o mesmo prompt e `OLLAMA_CONTEXT_LENGTH`.
  Avalie qualidade/citações e latência junto com tokens; um modelo menor pode
  ser mais rápido, mas precisa manter os critérios de resposta.
- Ajuste `num_predict`, temperatura e tamanho do contexto com limites explícitos.
  O benchmark atual fixa o contexto para tornar a comparação justa; reduzi-lo
  pode truncar fontes ou histórico.
- Para workloads concorrentes, meça throughput e latência sob concorrência antes
  de aumentar paralelismo. Observe a VRAM disponível para evitar troca de modelo
  para CPU e degradação abrupta.

**Qualidade do RAG e segurança**

- Amplie e mantenha um conjunto revisado de perguntas com fonte esperada,
  perguntas sem resposta, sinônimos, erros de digitação, perguntas ambíguas e
  casos multilíngues. Separe casos de desenvolvimento e validação para evitar
  ajustar thresholds ao mesmo conjunto usado para reportar resultado.
- Meça Recall@k e MRR em vários `k`; ajuste tamanho/sobreposição dos chunks,
  filtros de confiança e recência, peso lexical/vetorial e quantidade de
  trechos enviados ao modelo. Preserve exemplos de regressão para conflito,
  documento expirado e prompt injection direto/indireto.
- Avalie a resposta final por correção apoiada nas fontes, citações válidas,
  abstenção quando falta evidência e resistência a instruções contidas nos
  documentos. O score RRF ordena candidatos; não deve ser interpretado como
  probabilidade ou similaridade calibrada.
- Faça revisão humana de falhas e acompanhe resultados por categoria. Os seis
  casos OWASP atuais são smoke de segurança, não certificação nem cobertura
  abrangente.

**FinOps e custo operacional**

- Registre custo por conversa e por resposta útil, separando tokens do LLM,
  tokens/chamadas de embedding, armazenamento vetorial, CPU/GPU e energia. Para
  execução local, “custo de API zero” não significa custo total zero: hardware,
  energia e operação continuam existindo. O benchmark atual não mede esses itens.
- Reaproveite embeddings por hash de conteúdo/modelo, como já ocorre no cache de
  consulta, e reindexe somente chunks alterados. Acompanhe taxa de cache, tempo
  de indexação, falhas e crescimento do índice para detectar custo de ingestão.
- Compare o custo total do chat normal e do RAG incluindo ingestão e consultas de
  embedding, e calcule o ponto de equilíbrio pela frequência de perguntas. Em
  FAQ pequeno, a economia por chat pode não compensar manter serviços sempre
  ligados; meça o perfil de uso real.
- Defina limites de tokens, tempo, concorrência e orçamento para providers pagos
  antes de habilitar um modo remoto. Alertas devem observar custo por usuário ou
  sessão, não apenas custo agregado mensal.

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

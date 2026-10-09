# Case: redução de contexto com RAG local

## Resumo

Este experimento compara o chat local com FAQ inteiro no prompt a uma versão com
retrieval híbrido local: embeddings Ollama + PostgreSQL/pgvector e busca lexical.
O objetivo foi reduzir o contexto enviado ao LLM sem perder fontes úteis ou
segurança contra conteúdo malicioso nos documentos.

O resultado observado nesta máquina foi redução de **45,6% nos tokens de entrada
do LLM**. Incluindo tokens das consultas de embedding, a redução total observada
foi **44,2%**. A busca híbrida melhorou Recall@3 de `0,600` para `0,667` e MRR de
`0,567` para `0,622` no conjunto funcional usado. Esses valores são resultados
de uma amostra pequena, não uma garantia para outros dados ou hardware.

## Contexto e configuração

- Data: 2026-10-09.
- Chat: `qwen3:8b` quantizado Q4_K_M via Ollama.
- Embeddings: `nomic-embed-text:latest`, 768 dimensões, também local.
- Vetor store: PostgreSQL 17 com pgvector.
- GPU de chat: NVIDIA GeForce RTX 4060 Ti, 8 GB.
- Contexto: 8192 tokens nos dois modos.
- Corpus: 24 chunks extraídos do FAQ versionado.
- Tráfego medido: três perguntas repetidas três vezes (nove respostas por modo).

No modo normal, o prompt recebe o FAQ inteiro. No modo híbrido, a busca lexical e
vetorial seleciona os trechos; o LLM recebe somente o contexto recuperado. Os
dois modos usam o mesmo endpoint de chat e o mesmo modelo, banco de sessão
temporário por execução e perguntas equivalentes.

## Resultado observado

| Indicador | Chat normal | RAG híbrido |
| --- | ---: | ---: |
| Chats válidos | 9/9 | 9/9 |
| Tokens de entrada do LLM | 44.601 total; 4.956 por chat | 24.276 total; 2.697 por chat |
| Tokens de saída | 1.062 total | 1.147 total |
| Latência mediana | 3,20 s | 3,13 s |
| Latência p95 | 4,69 s | 3,25 s |
| Respostas com fonte válida | 9/9 | 9/9 |
| Custo de API | 0 | 0 |

O RAG realizou três consultas de embedding (uma por pergunta distinta) e teve
seis hits de cache nas repetições, consumindo 59 tokens de embedding de consulta.
Somando esses tokens ao input do LLM, a queda total foi 44,2%. A indexação fria
dos 24 chunks levou 1,26 s, fez 17 chamadas reais de embedding após deduplicação
por cache e consumiu 656 tokens. Energia e custo de hardware local não foram
medidos; portanto, custo de API zero não representa custo operacional total
zero.

Os relatórios brutos estão em
[`reports/rag-local-20261009/`](../reports/rag-local-20261009/):
`summary.json`, `chat-plain.json`, `chat-hybrid.json`, `indexing-cold.json`,
`rag-lexical.json`, `rag-hybrid.json` e `runtime.json`.

## Qualidade e segurança

No conjunto funcional local, a busca híbrida teve Recall@3 `0,667` (baseline
lexical `0,600`) e MRR `0,622` (baseline `0,567`). Recall@3 responde se a fonte
esperada apareceu entre os três primeiros resultados: `0,667` significa que
isso ocorreu em aproximadamente dois terços das perguntas avaliadas. MRR mede a
posição do primeiro resultado relevante: posição 1 vale `1`, posição 2 vale
`0,5`, posição 3 vale `0,333`, e ausência vale `0`; a média maior indica que a
fonte tende a aparecer antes.

No conjunto OWASP/prompt injection de seis casos, houve zero citações de fontes
bloqueadas e zero falhas de abstenção. Esse conjunto é um smoke de regressão
pequeno. Ele não certifica segurança nem substitui revisão de casos novos. As
medidas de Recall@3 e MRR avaliam retrieval, não correção factual ou fidelidade da
resposta final; por isso devem ser lidas junto com validade de citações,
abstenção e vazamento de fontes bloqueadas.

## Como reproduzir

Pré-requisitos: Python 3.11 com dependências do projeto, Docker Compose, Ollama,
modelo de chat e embedding baixados, e os serviços do perfil RAG disponíveis.
Defina o modo local e os endpoints conforme seu ambiente:

```bash
docker compose --profile rag up -d pgvector ollama
docker compose --profile rag run --rm rag-init
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
  .venv/bin/python scripts/benchmark_rag_chat.py --mode plain --repeat 3
EVENTOPS_RAG_DATABASE_URL=postgresql://eventops:eventops-local-only@127.0.0.1:55432/eventops \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_EMBEDDING_BASE_URL=http://127.0.0.1:11435 \
  .venv/bin/python scripts/benchmark_rag_chat.py --mode hybrid --repeat 3
make eval-rag
RAG_EVAL_MODE=hybrid make eval-rag
```

Para comparar, mantenha o mesmo modelo de chat, contexto, conjunto de perguntas
e quantidade de repetições. Salve os JSONs em diretório de execução próprio,
registre GPU/CPU/RAM e não compare uma execução fria com outra aquecida sem
identificá-las. O benchmark informa latência e tokens; o processo não estima
consumo de energia.

## Decisões tomadas durante a implementação

1. Preservar o modo lexical como padrão e adicionar o modo híbrido opt-in, para
   que a aplicação continue executável sem serviços locais extras.
2. Indexar FAQ com metadados de confiança, validade e grupo de conflito, além de
   sincronização idempotente, para que conteúdo antigo ou conflitante possa ser
   filtrado.
3. Manter busca lexical como fallback operacional quando uma consulta vetorial
   falha e medir esse fallback explicitamente.
4. Avaliar perguntas normais e adversariais antes de interpretar economia de
   tokens como melhoria. Os primeiros evals apontaram vazamentos/abstenções
   inadequados; os ajustes de filtros e thresholds foram então verificados
   novamente pelo conjunto de segurança.
5. Medir o mesmo modelo local nos dois fluxos, com contexto equivalente, e
   contabilizar separadamente o embedding. Isso evita atribuir ao LLM economia
   que apenas foi transferida para outro componente.

## Próximas otimizações

As ideias abaixo são hipóteses para testar em rodadas isoladas. Consulte
[operação local](operacao-local.md#próximas-otimizações) para a lista completa e
os limites de cada métrica.

- **LLM:** testar modelos e quantizações menores com o mesmo conjunto, prompt e
  limite de contexto; registrar p50/p95, tokens por segundo e uso de VRAM/RAM.
  Ajustar limite de saída e concorrência sem sacrificar citações ou respostas
  completas.
- **Qualidade:** aumentar e manter conjunto revisado com perguntas sem resposta,
  paráfrases, ambiguidades, conflitos e ataques indiretos; separar dados de
  ajuste e validação. Experimentar chunking, top-k, thresholds e pesos lexical/
  vetorial, reportando Recall@k, MRR, citações, abstenção e segurança em conjunto.
- **FinOps:** medir custo por resposta útil, não só tokens. Contabilizar
  ingestão, cache, armazenamento, execução de CPU/GPU, energia e operação; medir
  a taxa de cache e o ponto de equilíbrio entre custo de indexação e volume de
  perguntas. Para APIs pagas, adicionar limites de tokens/orçamento e alertas por
  usuário ou sessão.

## Limitações

São nove requisições por modo, três perguntas e um único equipamento; o p95 tem
baixa estabilidade estatística. O conjunto funcional tem 16 perguntas e o
conjunto de segurança seis casos. Resultados não são generalizáveis sem
repetição maior, dados representativos, revisão humana e teste em hardware e
carga concorrente de produção.

# Runbook de operação Cloud Run e Cloud SQL

## Estado do projeto

Revisado em 10/10/2026. A infraestrutura temporária foi recriada com Terraform
e está ativa em `us-central1`: Cloud Run `eventops-api` e Cloud SQL
`eventops-rag-test` (`db-f1-micro`). A URL atual é
`https://eventops-api-w4fiqopm2a-uc.a.run.app`. Health, agenda, FAQ, Gemini
single/multi, MCP stdio, reserva e RAG semântico foram validados. O Cloud SQL
gera custo enquanto permanecer ativo; execute o teardown ao terminar a demo.
Este runbook registra a configuração, os comandos de operação e as orientações
de custo e teardown.

## Recursos e configuração usados

- Cloud Run `eventops-api`, região `us-central1`, 1 vCPU, 512 MiB, concorrência
  8, timeout 60 s, escala 0–1 e invocação pública. Chat e mutações verificavam
  origem e cookie de demonstração; não havia login de usuário.
- Single, roteamento multi e embeddings usam Gemini 2.5 Flash e
  `gemini-embedding-001` via Vertex AI, autenticados pela service account
  runtime. O multi delega agenda pelo servidor MCP stdio no mesmo container.
- Perfil híbrido opcional usava `gemini-embedding-001`, saída 768 dimensões,
  Cloud SQL PostgreSQL 17 e pgvector. A aplicação cria o schema vetorial no
  startup e sincroniza FAQ Markdown por hash.
- O deploy de 10/10 usa PostgreSQL gerenciado também para catálogo, sessões,
  histórico, confirmações, reservas e idempotência. A service account runtime
  tem `roles/cloudsql.client`, `roles/aiplatform.user` e acesso apenas aos
  secrets de conexão.
- A configuração de código do perfil híbrido usa PostgreSQL no Cloud SQL para
  catálogo, sessões, histórico, confirmações, reservas e idempotência, além do
  banco pgvector do FAQ.
- `EVENTOPS_DATABASE_URL` e `EVENTOPS_RAG_DATABASE_URL` são entregues pelo
  Secret Manager; chamadas Vertex AI usam a identidade Google do runtime.
  Não registrar valores em state outputs, logs, `.env` versionado ou imagem.

As variáveis Terraform são identificadores/configuração (`project_id`, região,
nomes, tag, origem e flag de RAG); **nenhuma variável declara segredo**. A
senha PostgreSQL é gerada com `random_password`, mas seu valor e a URL resultante
existem no state local do Terraform. O state e seus backups são segredos e não
devem ir para Git ou ser enviados sem criptografia. O teardown desta sessão
removeu esses arquivos locais depois de destruir os recursos.

## Recriação

Pré-requisitos: `gcloud`, Docker Engine e Terraform, com o projeto correto e
billing habilitado. Os scripts não leem nem enviam `.env`; forneça credenciais
por Secret Manager ou identidade Google. Para publicar a aplicação, execute
`./scripts/cloud/cloud-up.sh`. O perfil
econômico começa com RAG lexical. Para criar Cloud SQL e mudar o runtime para
hybrid, ativar explicitamente `enable_managed_rag=true`. A instância deve ser
tratada como temporária, sem backups, zonal e sem SLA. Não usar para dados reais.

O deploy escreve a URL em `infra/terraform/service-url.txt`. Para consultas
diretas, use `BASE_URL="$(cat infra/terraform/service-url.txt)"` e, por
exemplo, `curl -fsS "$BASE_URL/health"` ou
`curl -fsS "$BASE_URL/api/sessions?track=IA"`. Chat e mutações exigem cookie e
header `Origin` compatíveis com a URL; o smoke automatizado cobre o fluxo de
chat e reserva sintética.

Depois do deploy, execute `./scripts/cloud/cloud-smoke.sh`. Com RAG híbrido
ativo, use `./scripts/cloud/cloud-rag-smoke.sh "$(cat infra/terraform/service-url.txt)"`.
Cloud SQL `db-f1-micro` foi estimado em cerca de US$ 0,0117/h com disco de 10 GiB,
antes de rede e embeddings. Confira as [tarifas atuais](https://cloud.google.com/sql/pricing);
budget de R$ 5 é um alerta, não um teto universal.

Antes de expor a aplicação novamente:

1. Confirmar IAM mínimo para runtime e deploy em identidades separadas.
2. Criar/usar secrets com acesso restrito; rotacionar credenciais que tenham
   sido expostas e evitar impressões de state/variáveis.
3. Manter Cloud Run público somente para a demo; definir origem permitida,
   cookie seguro, escala e limites de requisição.
4. Validar health, agenda, FAQ, single, multi/MCP e, se híbrido, smoke de RAG.
5. Conferir custo e logs no projeto após o smoke.

## Alertas e rollback

O budget de projeto de R$ 5 notifica em 50%, 80% e 100%. O spend cap de R$ 5
atinge Cloud Run dentro do filtro configurado. Alertas e cap não são um teto
universal e não interrompem automaticamente Vertex AI, armazenamento ou todos
os serviços.

Em uma futura revisão, retornar para uma revisão Cloud Run anterior só é seguro
se o schema continuar compatível. O armazenamento relacional pode preservar os
dados entre revisões quando configurado por `EVENTOPS_DATABASE_URL`; não aplicar
rollback de schema automaticamente.

## Encerramento e verificação

Execute `./scripts/cloud/cloud-down.sh`. O script remove a instância Cloud SQL antes
do destroy Terraform para suportar operações longas, apaga os recursos
EventOps (Cloud Run, registry, secrets e identidades), confirma que o alerta
permanece e remove state local contendo credenciais. O projeto e as APIs
habilitadas são mantidos. Para uma API key criada separadamente, informe seu
resource name em `EVENTOPS_API_KEY_RESOURCE`; essa opção pula a checagem de uso
recente ao revogar a chave. Depois, confira também os recursos fora do inventário
Terraform no Console se o projeto tiver sido usado por outras aplicações.

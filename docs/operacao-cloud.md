# Runbook candidato: Cloud Run e Cloud SQL

Este runbook descreve a preparação para publicação; nenhum projeto ou recurso Google foi criado. Cloud SQL PostgreSQL e a região `southamerica-east1` são candidatos, não decisões de provisionamento. Antes de publicar, confirmar projeto, região disponível, acesso da demo, estimativa de custo/quota, retenção, responsáveis e política de dados. A [integração Cloud Run/Cloud SQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run) e os [preços do Cloud SQL](https://cloud.google.com/sql/pricing) devem ser consultados novamente na data da decisão.

## Configuração e identidade

- Usar uma identidade de execução dedicada ao Cloud Run, com apenas os papéis exigidos pelo método de conexão escolhido e acesso ao segredo de conexão. A identidade de deploy fica separada.
- Guardar `EVENTOPS_DATABASE_URL` no Secret Manager e referenciá-lo no serviço; não o inserir em imagem, arquivo de ambiente versionado, saída de shell, logs ou manifesto.
- `GOOGLE_API_KEY` só será necessária quando a arquitetura Gemini live for implementada e autorizada para avaliação. O serviço ainda opera no modo offline/local configurado e não deve receber essa chave como parte desta etapa.
- Definir `EVENTOPS_SEED_CATALOG=false` após o seed inicial explícito, `EVENTOPS_COOKIE_SECURE=true` sob HTTPS e origens permitidas específicas. O catálogo não deve ser sincronizado durante o startup concorrente de várias instâncias.
- As sessões de demonstração e o histórico de chat atuais não são autenticação nem armazenamento distribuído. Definir política de acesso da demo antes de torná-la pública.

## Migration e publicação

As migrations PostgreSQL estão em `app/migrations/NNNN_*.sql`, são aplicadas em transação e a versão está em `schema_meta`. Fazer backup/point-in-time recovery compatível com a política do projeto antes de qualquer alteração destrutiva. Publicar mudanças aditivas e compatíveis primeiro; remoção/renomeação de colunas exige estratégia expand/contract e uma nova imagem antes de remover schema antigo.

Antes do deploy:

1. Rodar `make lint typecheck test build postgres-check compose-check eval-offline` e completar E2E Playwright; guardar relatório e digest da imagem.
2. Revisar migration SQL e snapshot/backup restaurável em ambiente de teste. Reproduzir falha em transação e confirmar rollback; nunca depender do rollback do schema após commit.
3. Criar/validar conexão por Cloud SQL connector ou socket suportado pela configuração final, com TLS/identidade apropriados; a URL atual do adapter usa conexão TCP padrão e precisa ser adaptada/testada para o método escolhido.
4. Publicar uma revisão inicialmente privada, com escala máxima baixa, health check e limites de timeout/conexão coerentes com o banco.
5. Rodar smoke de agenda, FAQ, preview, confirmação, replay idempotente e disputa de capacidade antes de liberar acesso.

O startup do app aplica migrations pendentes. Por isso, usar credencial de banco com DDL apenas se a política aceitar esse privilégio no runtime. Para separar privilégio de migration do usuário de aplicação, mover a migration para um job de deploy e conectar o runtime com grants mínimos antes de produção.

## Verificação e rollback

Após publicação, registrar região, revisão, digest, versão de schema, configuração não secreta e resultado G6. Confirmar persistência de uma reserva após nova instância/revisão e teste concorrente com conexões distintas. Conferir logs e métricas sem capturar tokens, cookies ou credenciais.

Em falha da aplicação, rotear tráfego para a revisão anterior se o schema continuar compatível. Não reverter schema automaticamente: restaurar backup apenas mediante procedimento aprovado e avaliação de perda de dados. Se houver incompatibilidade de migration, interromper rollout, preservar evidências e seguir plano de recuperação do banco.

## Custo e remoção

Configurar orçamento e alertas antes da criação. Escala zero reduz uso do Cloud Run, mas não implica custo zero de banco, armazenamento, logs, registry, backups ou rede; confirmar a tarifa da região e dimensionamento no cálculo aprovado. Revisar orçamento e quotas após smoke e antes de abrir tráfego.

Para encerrar, exportar evidências não sensíveis, inventariar serviço, instância, backups, secrets, imagens e logs, e decidir retenção dos dados de demonstração. Os comandos de remoção devem apontar somente aos IDs do inventário e exigir revisão humana antes de apagar banco ou backups. Este runbook não executa criação, deploy, exclusão ou cobrança.

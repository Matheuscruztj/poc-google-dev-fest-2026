# Roteiro local da demonstração

Este roteiro usa dados fictícios e modo offline. A comparação atual mede single com tools internas e multi com MCP stdio; transporte e arquitetura variam juntos. Não é uma comparação live de custo/qualidade.

## Preparação

```bash
docker compose up --build -d app
curl http://127.0.0.1:8000/health
```

Use a página em `http://127.0.0.1:8000`. O seletor começa em **Agente único**. Para reiniciar a demo sintética e apagar reservas locais, `docker compose down -v` remove o volume `eventops-data`.

## Demonstrações

1. **Agenda sem conflitos:** pergunte “Quero três palestras de IA após 14h”. Mostre IDs e horários retornados pelo catálogo SQLite.
2. **FAQ com fonte:** pergunte “Que recursos de acessibilidade existem?”. Confira documento e seção exibidos.
3. **Separar resposta e ação:** pergunte “Quero reservar uma palestra de IA após 14h”. Abra a prévia e cancele; o chat não cria reserva.
4. **Comparar arquiteturas:** repita a pergunta de agenda com **Coordenador + especialistas**. O trace mostra delegação e chamada MCP local.
5. **Resiliência e segurança:** consulte o relatório offline de comparação e os testes adversariais. Hooks de falha existem apenas no harness e não são acionados por texto público.

Para comparar as 40 entradas, execute `make eval-compare`. O relatório de cada arquitetura mantém todas as tentativas. Para agregar duração, falhas, chamadas, retries e tokens conhecidos:

```bash
make report-metrics REPORT=reports/<run_id>/comparison.json
```

O agregador deixa custo como desconhecido sem consumo completo e tabela de preços datada. Ele omite p95 abaixo de 100 amostras. Uma gravação de demonstração ainda não foi produzida; se for usada como contingência, identifique-a como gravação.

Depois da etapa local, use `docker compose down` para parar os serviços. Use `docker compose down -v` apenas quando quiser apagar também os dados sintéticos persistidos.

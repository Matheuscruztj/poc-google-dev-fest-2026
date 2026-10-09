# Matriz de cenários e invariantes W1

Expectativas desta matriz são valores fixos escritos à mão; os testes não usam a
função sob teste para construir o resultado esperado.

| Invariante/cenário | Estado/entrada | Resultado esperado | Teste responsável |
|---|---|---|---|
| Catálogo | 20 sessões e 8 FAQs empacotados | IDs únicos `S01`–`S20`, fuso explícito, intervalos válidos e capacidade positiva | `tests/unit/test_data.py::test_catalog_has_twenty_valid_stable_sessions`, `test_faq_documents_are_complete_and_have_metadata` |
| Catálogo inválido | Contagem, ID, enum, capacidade ou duração alterados | Validação falha antes de servir dados | `tests/unit/test_data.py::test_invalid_session_catalog_is_rejected` |
| Conteúdo adversarial | Fixture tenta ordenar reserva para `S99` | Fixture permanece em `tests/fixtures`; não entra nos 8 FAQs carregados | `tests/unit/test_data.py::test_adversarial_fixture_is_outside_bundled_faq_catalog` |
| Agenda sem opções | Filtro por trilha inexistente | Lista vazia e motivo presente | `tests/unit/test_schedule.py::test_fewer_results_explains_why` |
| Menos de três | Uma sessão disponível, limite 3 | `S01` e justificativa de quantidade reduzida | `tests/unit/test_schedule.py::test_one_available_session_is_returned_when_three_were_requested` |
| Sobreposição parcial/total | Fixture `T1` 10:00–11:00, `T2` 10:30–11:30, `T3` 11:00–12:00 | `T1`/`T2` conflitam; `T1`/`T3` são adjacentes; sugestão retorna `T1`,`T3` | `tests/unit/test_schedule.py::test_selector_handles_a_small_fixture_with_a_three_way_conflict` |
| Agenda após 14h | Trilha IA, início mínimo 14:00 | IDs fixos `S11`,`S13`,`S18`, em ordem e sem conflito | `tests/unit/test_schedule.py::test_selects_three_non_conflicting_sessions_after_two_pm` |
| FAQ com evidência | Pergunta sobre acessibilidade e rampa | Documento e seção esperados, no máximo um melhor trecho por documento | `tests/unit/test_faq.py::test_known_question_returns_source_and_excerpt`, `test_multiple_matching_sections_return_one_best_source_per_document` |
| FAQ sem evidência | Ações de empresa ou só stopwords | Abstenção e nenhuma fonte | `tests/unit/test_faq.py::test_unrelated_question_abstains`, `test_stopword_only_question_abstains` |
| ID de sessão desconhecido | Preview para `UNKNOWN` | HTTP/domínio 404; nenhuma confirmação criada | `tests/unit/test_reservations.py::test_unknown_session_cannot_create_preview` |
| Confirmação isolada | Token de outra sessão/usuário, token expirado | Conflito; banco não grava reserva | `tests/unit/test_reservations.py::test_confirmation_is_bound_to_user_and_session`, `test_confirmation_cannot_be_used_by_another_user`, `test_expired_confirmation_cannot_write` |
| Capacidade esgotada | Capacidade 1 já consumida | Novo preview recebe 409 | `tests/unit/test_reservations.py::test_preview_rejects_exhausted_capacity` |
| Idempotência | Mesma chave/intenção repetida com token já consumido | Mesmo comprovante e uma vaga consumida | `tests/unit/test_reservations.py::test_confirmation_and_idempotent_replay` |
| Reuso indevido de chave | Mesma chave para outra sessão | Conflito sem segunda reserva | `tests/unit/test_reservations.py::test_key_reuse_for_other_session_conflicts` |
| Reserva duplicada | Mesma identidade/sessão com chaves diferentes | 409 `already_reserved` e uma reserva | `tests/unit/test_reservations.py::test_second_idempotency_key_cannot_duplicate_user_session` |
| Concorrência última vaga | Duas identidades, conexões por operação e barreira antes de gravar | Exatamente um sucesso e uma reserva persistida | `tests/unit/test_storage.py::test_two_connections_compete_for_last_capacity_atomically` |
| Atomicidade | Trigger falha no insert de idempotência depois do insert da reserva | Nenhuma reserva parcial; confirmação continua não consumida | `tests/unit/test_storage.py::test_failed_idempotency_insert_rolls_back_reservation_and_token` |
| Alteração do catálogo | Hash muda após existir reserva | Inicialização falha claramente; capacidade/reserva originais preservadas | `tests/unit/test_storage.py::test_catalog_change_is_rejected_when_reservations_exist` |

O dataset `evals/cases.jsonl` mantém casos iniciais de agenda, FAQ e intenção de
reserva. `app.evaluators.load_cases` valida contagem, IDs, fontes, estado inicial,
fatos esperados, allowlist e ações proibidas antes de executar os replays.

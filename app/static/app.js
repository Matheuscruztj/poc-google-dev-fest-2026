const byId = (id) => document.getElementById(id);
const scheduleForm = byId('schedule-form');
const scheduleResults = byId('schedule-results');
const faqForm = byId('faq-form');
const faqResults = byId('faq-results');
const dialog = byId('reservation-dialog');
let selectedSession = null;
let confirmationToken = null;
let idempotencyKey = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function time(value) {
  return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', timeZone: 'America/Fortaleza' }).format(new Date(value));
}

async function request(path, body) {
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || 'Não foi possível concluir a solicitação.');
  return data;
}

function renderSessions(items, reason) {
  scheduleResults.replaceChildren();
  if (!items.length) {
    scheduleResults.append(element('p', 'empty-state', 'Nenhuma sessão encontrada para esses filtros.'));
    return;
  }
  for (const session of items) {
    const card = element('article', 'session-card');
    const meta = element('div', 'card-meta');
    meta.append(element('span', 'tag', session.track), element('span', 'session-id', session.id));
    card.append(meta, element('h3', '', session.title), element('p', '', `${session.level} · ${time(session.starts_at)}–${time(session.ends_at)}`));
    const footer = element('div', 'card-footer');
    footer.append(element('span', 'session-id', `${session.capacity} lugares`));
    const button = element('button', '', 'Reservar vaga →');
    button.type = 'button';
    button.addEventListener('click', () => openPreview(session));
    footer.append(button);
    card.append(footer);
    scheduleResults.append(card);
  }
  if (reason) scheduleResults.prepend(element('p', 'empty-state', reason));
}

async function suggest() {
  const body = { limit: 3 };
  if (byId('track').value) body.track = byId('track').value;
  if (byId('level').value) body.level = byId('level').value;
  if (byId('after').value) {
    body.after = new Date(`2026-11-07T${byId('after').value}:00-03:00`).toISOString();
  }
  const result = await request('/api/schedule', body);
  renderSessions(result.sessions, result.reason);
}

scheduleForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = scheduleForm.querySelector('button');
  button.disabled = true;
  try { await suggest(); } catch (error) { scheduleResults.replaceChildren(element('p', 'empty-state', error.message)); }
  finally { button.disabled = false; }
});

async function loadSessions() {
  const health = await request('/health');
  byId('mode-status').textContent = health.agent_mode === 'live' ? 'DADOS OFFLINE · CHAT GEMINI LIVE' : 'DEMO OFFLINE';
  const result = await request('/api/sessions');
  const tracks = [...new Set(result.sessions.map((session) => session.track))].sort();
  const select = byId('track');
  for (const track of tracks) {
    const option = element('option', '', track);
    option.value = track;
    select.append(option);
  }
  renderSessions(result.sessions.slice(0, 6), null);
}

faqForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = faqForm.querySelector('button');
  button.disabled = true;
  faqResults.replaceChildren(element('p', 'faq-answer', 'Buscando nos documentos do evento…'));
  try {
    const result = await request('/api/faq', { question: byId('question').value });
    faqResults.replaceChildren(element('p', 'faq-answer', result.answer));
    for (const source of result.sources) {
      const card = element('article', 'source-card');
      const title = element('div', 'source-title');
      title.append(document.createTextNode(`${source.section} `));
      title.append(element('span', '', `· ${source.document}`));
      card.append(title, element('p', 'source-excerpt', source.excerpt));
      faqResults.append(card);
    }
  } catch (error) { faqResults.replaceChildren(element('p', 'faq-answer', error.message)); }
  finally { button.disabled = false; }
});

byId('chat-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button');
  const output = byId('chat-results');
  button.disabled = true;
  output.replaceChildren(element('p', 'faq-answer', 'O guia está consultando as fontes…'));
  try {
    const result = await request('/api/chat', { message: byId('chat-message').value, architecture: byId('chat-architecture').value });
    output.replaceChildren();
    const answer = element('article', 'chat-answer');
    answer.append(element('p', '', result.answer), element('span', 'mode-pill', `${result.mode.toUpperCase()} · ${result.trace?.delegations ?? 0} delegações`));
    output.append(answer);
    for (const source of result.sources || []) {
      const card = element('article', 'source-card');
      card.append(element('div', 'source-title', `${source.section} · ${source.document}`), element('p', 'source-excerpt', source.excerpt));
      output.append(card);
    }
    if (result.session_ids?.length) {
      const list = element('div', 'chat-session-list');
      const catalog = await request('/api/sessions');
      for (const id of result.session_ids) {
        const session = catalog.sessions.find((item) => item.id === id);
        if (!session) continue;
        const card = element('article', 'session-card');
        card.append(element('div', 'card-meta'), element('h3', '', session.title), element('p', '', `${id} · ${time(session.starts_at)}–${time(session.ends_at)}`));
        if (result.reservation_proposal === id) {
          const reserveButton = element('button', 'button button-outline', 'Ver prévia da reserva →');
          reserveButton.addEventListener('click', () => openPreview(session));
          card.append(reserveButton);
        }
        list.append(card);
      }
      output.append(list);
    }
    if (result.error) output.append(element('p', 'error-note', `A resposta foi rejeitada ou o provider falhou: ${result.error}`));
  } catch (error) { output.replaceChildren(element('p', 'error-note', error.message)); }
  finally { button.disabled = false; }
});

async function openPreview(session) {
  selectedSession = session;
  confirmationToken = null;
  idempotencyKey = crypto.randomUUID();
  byId('confirm-reservation').disabled = true;
  byId('reservation-message').textContent = '';
  byId('reservation-message').className = 'reservation-message';
  const content = byId('preview-content');
  content.replaceChildren(element('p', '', 'Preparando uma prévia…'));
  dialog.showModal();
  try {
    const preview = await request('/api/reservations/preview', { session_id: session.id });
    confirmationToken = preview.confirmation_token;
    const card = element('div', 'preview-card');
    card.append(element('strong', '', preview.title), element('p', '', `${session.id} · ${time(preview.starts_at)}–${time(preview.ends_at)}`), element('p', '', `Confirme em até ${Math.floor(preview.expires_in_seconds / 60)} minutos. A prévia não bloqueia uma vaga.`));
    content.replaceChildren(card);
    byId('confirm-reservation').disabled = false;
  } catch (error) {
    content.replaceChildren(element('p', 'faq-answer', error.message));
    byId('confirm-reservation').disabled = true;
  }
}

byId('cancel-reservation').addEventListener('click', () => dialog.close());
byId('confirm-reservation').addEventListener('click', async (event) => {
  if (!confirmationToken || !selectedSession) return;
  const button = event.currentTarget;
  button.disabled = true;
  const message = byId('reservation-message');
  message.textContent = 'Registrando sua reserva fictícia…';
  message.className = 'reservation-message';
  try {
    const result = await request('/api/reservations', { session_id: selectedSession.id, confirmation_token: confirmationToken, idempotency_key: idempotencyKey });
    message.textContent = `Reserva confirmada · comprovante ${result.receipt_id}${result.replayed ? ' · solicitação repetida com segurança' : ''}`;
    message.className = 'reservation-message';
    confirmationToken = null;
  } catch (error) {
    message.textContent = error.message;
    message.className = 'reservation-message error';
    button.disabled = false;
  }
});

loadSessions().catch((error) => scheduleResults.replaceChildren(element('p', 'empty-state', error.message)));

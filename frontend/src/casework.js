const token = () => localStorage.getItem('cdt_token');
const endpoint = '/api/operational-cases';
const statusLabel = {submitted: '待主管复核', returned: '已退回', closed: '已关闭'};

function element(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

async function request(path = '', body) {
  const response = await fetch(endpoint + path, {
    method: body ? 'POST' : 'GET',
    headers: {'Authorization': `Bearer ${token() || ''}`, 'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `操作失败 (${response.status})`);
  return data;
}

const launcher = element('button', '港口异常交接');
launcher.type = 'button';
launcher.id = 'operational-cases-open';
launcher.hidden = true;
const dialog = element('dialog');
dialog.id = 'operational-cases';
dialog.setAttribute('aria-labelledby', 'operational-cases-title');
const header = element('header');
const title = element('h2', '港口异常交接');
title.id = 'operational-cases-title';
const close = element('button', '关闭');
close.addEventListener('click', () => dialog.close());
header.append(title, close);
const controls = element('section');
const selector = element('select');
selector.setAttribute('aria-label', '处置类型');
const sourceSelect = element('select');
sourceSelect.setAttribute('aria-label', '业务记录');
const sourceSummary = element('p');
const feedback = element('p');
feedback.setAttribute('role', 'status');
const current = element('section');
const gradePanel = element('section');
gradePanel.className = 'grade-panel';
controls.className = 'casework-controls';
controls.append(selector, sourceSelect);
dialog.append(header, controls, feedback, sourceSummary, current, gradePanel);
document.body.append(launcher, dialog);

let index;
let sequence = 0;
let active = false;
function use(path) { return `/${selector.value}/${path}?key=${encodeURIComponent(sourceSelect.value)}`; }
function sessionChanged() {
  let signedIn = false;
  try { signedIn = Boolean(token()); } catch { /* corrupted session will be handled by the login page */ }
  launcher.hidden = !signedIn;
  if (!signedIn && dialog.open) dialog.close();
}
sessionChanged();
window.addEventListener('storage', sessionChanged);
setInterval(sessionChanged, 600);

function collectField(form, label, control) {
  const field = element('label', label);
  field.append(control);
  form.append(field);
  return control;
}

function render(view) {
  const workflow = index.workflows[selector.value];
  const latest = view.history[0];
  sourceSummary.textContent = view.source?.source_summary || '源业务记录已不可用';
  const state = element('h3', latest ? statusLabel[latest.status] : '待登记');
  current.replaceChildren(state);  const form = element('form');
  const submitMode = index.role !== 'viewer' && view.source && (!latest || latest.status === 'returned');
  const reviewMode = index.role === 'supervisor' && latest?.status === 'submitted';
  let outcome, reference;
  if (submitMode) {
    outcome = collectField(form, '处置结果', element('select'));
    for (const [key, label] of Object.entries(workflow.outcomes)) outcome.add(new Option(label, key));
    reference = collectField(form, workflow.reference_label, element('input'));
    reference.required = true;
    reference.minLength = 3;
    reference.maxLength = 120;
  }
  if (submitMode || reviewMode) {
    const note = collectField(form, submitMode ? '处置依据' : '复核依据', element('textarea'));
    note.required = true;
    note.minLength = 4;
    note.maxLength = 500;
    for (const [value, text] of submitMode ? [['submit', '提交处置']] : [['approve', '验收关闭'], ['return', '退回补证']]) {
      const button = element('button', text);
      button.type = 'submit';
      button.value = value;
      form.append(button);
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (active || !event.submitter) return;
      const requestSequence = sequence;
      active = true;
      event.submitter.disabled = true;
      feedback.textContent = '正在保存…';
      try {
        const updated = await request(use('actions'), {action: event.submitter.value, revision: view.revision,
          outcome: outcome?.value || '', reference: reference?.value || '', note: note.value});
        if (requestSequence !== sequence) return;
        feedback.textContent = '已保存处置记录';
        render(updated);
      } catch (error) {
        if (requestSequence === sequence) feedback.textContent = error.message;
      } finally {
        active = false;
        event.submitter.disabled = false;
      }
    });
    current.append(form);
  }
  if (view.history.length) {
    const history = element('ol');
    for (const event of view.history) {
      const item = element('li');
      item.append(element('strong', `${statusLabel[event.status]} · ${event.actor}`),
        element('p', `${workflow.outcomes[event.outcome] || event.outcome} · ${event.reference} · ${event.note}`),
        element('small', `${event.event_at} · ${event.source_summary}`));
      history.append(item);
    }
    current.append(element('h4', '处置历史'), history);
  }
}

async function loadSource(seq) {
  if (!sourceSelect.value) return;
  try {
    const view = await request(use('history'));
    if (seq === sequence) render(view);
  } catch (error) {
    if (seq === sequence) feedback.textContent = error.message;
  }
  loadGradePanel(seq);
}

function gradePath() {
  return `/${encodeURIComponent(selector.value)}/grade-explanation?key=${encodeURIComponent(sourceSelect.value)}`;
}

function explanationCard(exp) {
  const doc = exp.document || {};
  const card = element('article');
  card.className = 'grade-doc';
  const head = element('h4', `分级说明原件 · ${exp.explained_level.toUpperCase()}（次高 ${exp.runner_up_level.toUpperCase()}）`);
  const meta = element('p', `签发人 ${exp.issued_by} · ${exp.created_at} · 依据推理任务 #${exp.analysis_job_id}${exp.dispatch_action_id ? ` · 处置动作 #${exp.dispatch_action_id}` : ''}`);
  card.append(head, meta);

  const summary = element('p');
  summary.className = 'grade-math';
  summary.textContent = `分差核对：基础分差 ${doc.base_margin} + 特征贡献合计 ${doc.contribution_sum} = ${doc.recomputed_margin}（原判断分差 ${doc.original_margin}）${doc.reconciles ? ' ✓ 核回原判断' : ' ✗ 核对异常'}`;
  card.append(summary);

  const table = element('table');
  table.append(element('caption', '各特征对领先等级相对次高等级的分差贡献'));
  const thead = element('thead');
  const headRow = element('tr');
  for (const text of ['特征', '原始值', '标准化值', `领先系数(${exp.explained_level})`, `次高系数(${exp.runner_up_level})`, '系数差', '分差贡献']) {
    headRow.append(element('th', text));
  }
  thead.append(headRow);
  table.append(thead);
  const tbody = element('tbody');
  for (const row of doc.contributions || []) {
    const tr = element('tr');
    for (const value of [row.feature_key, row.feature_value, row.standardized_value, row.leader_coef, row.runner_coef, row.coef_delta, row.margin_contribution]) {
      tr.append(element('td', String(value)));
    }
    tbody.append(tr);
  }
  table.append(tbody);
  card.append(table);

  const scores = element('details');
  scores.append(element('summary', '查看冻结的各类别决策得分与特征快照'));
  const pre = element('pre', JSON.stringify({decision_scores: doc.decision_scores, frozen_features: doc.frozen_features, formula: doc.formula}, null, 2));
  scores.append(pre);
  card.append(scores);
  return card;
}

async function loadGradePanel(seq) {
  gradePanel.replaceChildren();
  if (!sourceSelect.value) return;
  // 分级说明仅对延误案件类处置流程开放
  if (selector.value !== 'triage-followup') return;
  let payload;
  try {
    payload = await request(gradePath());
  } catch (error) {
    const warn = element('p', `分级说明暂不可用：${error.message}`);
    warn.className = 'grade-warn';
    gradePanel.append(warn);
    return;
  }
  if (seq !== sequence) return;
  const heading = element('h3', '船方申诉 · 分级说明');
  gradePanel.append(heading);

  const trace = element('p');
  trace.className = payload.traceability?.traceable ? 'grade-ok' : 'grade-warn';
  trace.textContent = payload.traceability?.traceable
    ? `证据可追溯（推理任务 #${payload.traceability.analysis_job_id}），说明将按派工当时采用的等级与那次推理签发。`
    : `无法追溯：${payload.traceability?.reason || '旧单缺少推理证据'}。旧单缺证据时不能补造说明。`;
  gradePanel.append(trace);

  if (payload.role === 'supervisor' && payload.traceability?.traceable) {
    const issueBtn = element('button', payload.explanations?.length ? '重新调阅/补签（幂等，不重复出单）' : '主管签发分级说明');
    issueBtn.type = 'button';
    issueBtn.addEventListener('click', async () => {
      issueBtn.disabled = true;
      try {
        const result = await request(gradePath(), {});
        feedback.textContent = result.message || '分级说明已处理';
        await loadGradePanel(seq);
      } catch (error) {
        feedback.textContent = error.message;
        issueBtn.disabled = false;
      }
    });
    gradePanel.append(issueBtn);
  }

  if (payload.explanations?.length) {
    const list = element('div');
    list.className = 'grade-doc-list';
    for (const exp of payload.explanations) list.append(explanationCard(exp));
    gradePanel.append(list);
    const note = element('small', '已签说明为冻结原件；案件后续重新分级不影响此处查阅内容。');
    gradePanel.append(note);
  } else {
    gradePanel.append(element('p', '尚未签发分级说明。'));
  }
}

async function loadWorkflow() {
  const seq = ++sequence;
  sourceSelect.replaceChildren();
  sourceSummary.textContent = '';
  feedback.textContent = '正在读取源业务记录…';
  current.replaceChildren();
  gradePanel.replaceChildren();
  try {
    const rows = await request(`/${selector.value}/sources`);
    if (seq !== sequence) return;
    for (const row of rows) sourceSelect.add(new Option(row.subject, row.source_key));
    feedback.textContent = rows.length ? `${rows.length} 条源业务记录` : '当前没有相关源业务记录';
    await loadSource(seq);
  } catch (error) {
    if (seq === sequence) feedback.textContent = error.message;
  }
}
selector.addEventListener('change', loadWorkflow);
sourceSelect.addEventListener('change', () => { current.replaceChildren(); feedback.textContent = ''; loadSource(++sequence); });
launcher.addEventListener('click', async () => {
  dialog.showModal();
  feedback.textContent = '正在加载处置台…';
  try {
    index = await request();
    selector.replaceChildren(...Object.entries(index.workflows).map(([key, value]) => new Option(value.title, key)));
    await loadWorkflow();
  } catch (error) {
    feedback.textContent = error.message;
  }
});

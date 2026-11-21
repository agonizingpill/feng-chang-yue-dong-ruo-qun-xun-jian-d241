import {book,openNotebook} from '../notebook.js';
import {api,account} from '../api.js';
import {headline} from '../components/notes.js';
import {BATCH_STATES,READING_STATES,BATCH_SCREEN_STATES} from '../constants.js';
import {text,num,toast,when} from '../utils.js';

const FIELD_ROWS = [
  ['weight_kg','抬箱体重 / kg','0.1','0.1'],
  ['temperature','箱内温度 / °C','0.1','-10'],
  ['activity','出入蜂 / 只每分钟','1','0'],
  ['feed_left','余饲 / kg','0.01','0'],
  ['colony_frames','蜂量 / 框','1','0'],
];

const rid = () => (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36));
const canEdit = () => account() && account().role !== 'viewer';
const batchState = state => BATCH_STATES[state] || state;
const readingState = state => READING_STATES[state] || state;
const batchScreenState = state => BATCH_SCREEN_STATES[state] || state;
const pct = p => `${num(p,1)}%`;

function claimForm() {
  const blocked = book.batches
    .filter(b => ['claimed', 'received'].includes(b.state))
    .flatMap(b => b.hive_ids || []);
  const draft = book.batchClaimDraft || {};
  const chosen = new Set(draft.hive_ids || []);
  const code = draft.code ?? `BAT-${new Date().toISOString().slice(2, 10).replaceAll('-', '')}-${String(book.batches.length + 1).padStart(2, '0')}`;
  const note = draft.note ?? '';
  return `<section class="sheet"><h2>领取巡检批次</h2><form id="claim-form"><label>批次编号<input name="code" value="${text(code)}" required></label><label>分工说明<input name="note" value="${text(note)}" placeholder="东坡 001–020，蜂师两人一组"></label><fieldset class="roster"><legend>勾选本批锁定的蜂箱（${chosen.size} 箱）</legend><div class="roster-grid">${book.hives.map(h => {const busy = blocked.includes(h.id); return `<label class="pick ${busy ? 'busy' : ''}" data-hive-pick="${h.id}"><input type="checkbox" name="hive_ids" value="${h.id}" ${chosen.has(h.id) ? 'checked' : ''} ${busy ? 'disabled' : ''}>${text(h.code)}<small>${text(h.site.slice(-2))}${busy ? ' · 在途' : ''}</small></label>`;}).join('')}</div></fieldset><button class="primary" ${canEdit() ? '' : 'disabled'}>领取并锁定箱清单</button><button type="button" id="pick-site">按场址全选东坡</button><button type="button" id="clear-pick">清空选择</button></form><div class="rule">领批即锁定箱清单。任一箱已在其他在途批次、存在未结束处置、待换王或在途转场，整批退回并列出原因；不会部分领用。重试同一批不会重复锁定。</div></section>`;
}

function batchList() {
  if (!book.batches.length) return '<div class="empty">尚无巡检批次。先在左侧领批，再逐箱补录。</div>';
  return book.batches.map(b => {
    const p = b.progress;
    return `<article class="batch-item ${b.id === book.selectedBatch ? 'selected' : ''}" data-batch="${b.id}" role="button" tabindex="0"><span class="code">${text(b.code)} · ${batchState(b.state)}</span><h3>${p.complete_count}/${p.hive_count} 箱完整 <span class="badge ${b.state === 'sealed' ? 'closed' : b.state === 'cancelled' ? 'flagged' : ''}">${batchState(b.state)}</span></h3><div class="meter"><i style="width:${Math.min(100, p.percent)}%"></i></div><p class="hint">领批 ${text(b.claimed_by)} · ${when(b.claimed_at)}<br>缺检 ${p.missing_count} 箱 · 缺项 ${p.incomplete_count} 条 · 冲突 ${p.conflict_count} 条${b.sealed_by ? '<br>封存 ' + text(b.sealed_by) + ' · ' + when(b.sealed_at) : ''}${b.seal_reason ? '<br>依据：' + text(b.seal_reason) : ''}</p></article>`;
  }).join('');
}

function readingRow(batch, item) {
  const b = book.batchDetail;
  const editable = b && b.state === 'claimed' && canEdit();
  const late = b && b.state === 'sealed' && canEdit();
  const complete = item.status === 'complete';
  const reading = item.reading;
  const state = reading ? readingState(reading.state) : '缺完整读数';
  const values = reading
    ? `${num(reading.weight_kg)} kg · ${num(reading.temperature, 1)}°C · 活动 ${num(reading.activity, 0)} · 余饲 ${num(reading.feed_left)} kg · ${reading.queen_seen == null ? '王况未填' : reading.queen_seen ? '见王' : '未见王'} · ${reading.colony_frames ?? '—'}框`
    : '尚未补录';
  const missing = reading && reading.missing_fields?.length ? `<p class="hint">缺项：${reading.missing_fields.map(text).join('、')}</p>` : '';
  const conflict = reading && reading.conflict_note ? `<p class="hint conflict">${text(reading.conflict_note)}</p>` : '';
  const score = reading && reading.anomaly_score != null ? `<p class="hint">封存读数分值 ${num(reading.anomaly_score, 4)} ${reading.anomaly_flag ? '· 偏离参考' : ''}</p>` : '';
  const form = editable
    ? `<form class="reading-form" data-hive="${item.hive_id}"><div class="reading-grid">${FIELD_ROWS.map(([name, label, step, min]) => `<label>${label}<input name="${name}" type="number" step="${step}" min="${min}" value="${reading?.[name] ?? ''}" placeholder="缺项可留空"></label>`).join('')}<label>巡检王况<select name="queen_seen"><option value="" ${reading?.queen_seen == null ? 'selected' : ''}>未填</option><option value="true" ${reading?.queen_seen === true ? 'selected' : ''}>见王</option><option value="false" ${reading?.queen_seen === false ? 'selected' : ''}>未见王</option></select></label></div><label>备注<input name="note" value="${text(reading?.note || '')}" placeholder="缺项原因或现场说明"></label><div class="actions"><button class="wax">补录本箱读数</button>${complete ? `<button type="button" class="correct" data-correct="${reading.id}">更正本箱完整读数</button>` : ''}</div><p class="hint">每箱只接收一条完整读数；已有完整读数时再次提交不同值会作为冲突证据留在原批，不覆盖原值。完全相同视为重复提交，不重复记账。</p></form>`
    : late
      ? `<details class="late-form"><summary>本批已封存，补录迟到读数（进入下一批）</summary><form class="reading-form" data-hive="${item.hive_id}"><div class="reading-grid">${FIELD_ROWS.map(([name, label, step, min]) => `<label>${label}<input name="${name}" type="number" step="${step}" min="${min}" value="${reading?.[name] ?? ''}" placeholder="缺项可留空"></label>`).join('')}<label>巡检王况<select name="queen_seen"><option value="" ${reading?.queen_seen == null ? 'selected' : ''}>未填</option><option value="true" ${reading?.queen_seen === true ? 'selected' : ''}>见王</option><option value="false" ${reading?.queen_seen === false ? 'selected' : ''}>未见王</option></select></label></div><label>备注<input name="note" placeholder="迟到补录原因"></label><div class="actions"><button class="wax">提交迟到补录</button></div><p class="hint">提交后自动进入该箱下一批，本批封存快照与筛查分值不变。</p></form></details>`
      : '';
  return `<article class="sheet hive-card ${complete ? 'complete' : item.status === 'partial' ? 'partial' : 'missing'}"><header><span class="code">${text(item.hive_code)} · ${text(item.site)}</span><span class="badge ${complete ? 'closed' : 'flagged'}">${state}</span></header><p class="hint">${values}</p>${missing}${conflict}${score}${form}</article>`;
}

function sealPanel(b) {
  const p = b.progress;
  return `<section class="sheet"><h2>交接接收与封存</h2><div class="progress-strip"><div><strong>${p.complete_count}</strong><span>完整读数</span></div><div><strong>${p.missing_count}</strong><span>缺检箱</span></div><div><strong>${p.incomplete_count}</strong><span>缺项记录</span></div><div><strong>${p.conflict_count}</strong><span>冲突证据</span></div><div><strong>${pct(p.percent)}</strong><span>进度</span></div></div><div class="actions"><button id="receive-batch" ${account()?.role === 'admin' && b.state === 'claimed' ? '' : 'disabled'}>主管交接接收整批</button></div><p class="hint">接收要求每箱恰好一条完整读数；缺项与冲突留在原批继续处理，不进入接收。接收人与时间会记录，封存只能由主管在接收后进行。</p><form id="seal-form"><label>封存依据（至少5字）<textarea name="reason" minlength="5" required placeholder="11月17日东坡一组读数齐全，核对无缺检，同意封存用于筛查"></textarea></label><button class="primary" ${account()?.role === 'admin' && b.state === 'received' ? '' : 'disabled'}>主管封存该批</button></form><div class="rule">封存后读数冻结：筛查只用封存时读数，之后迟到补录自动进入下一批，不改本批快照。重复封存或重试不会产生第二份封存记录。</div><div class="actions"><button id="screen-batch" ${canEdit() && b.state === 'sealed' && b.screen_state !== 'done' ? '' : 'disabled'}>按封存读数筛查</button><button id="cancel-batch" ${canEdit() && ['claimed', 'received'].includes(b.state) ? '' : 'disabled'}>取消未封存批次</button></div>${b.screen_state !== 'idle' ? `<p class="hint">筛查：${batchScreenState(b.screen_state)} · 已筛查 ${b.screened_count} 箱${b.screen_job_id ? ' · 任务 ' + text(b.screen_job_id.slice(0, 8)) : ''}</p>` : ''}</section>`;
}

function snapshotPanel(b) {
  const snap = b.seal_snapshot;
  if (!snap) return '';
  return `<section class="sheet"><h2>封存依据与快照</h2><p class="hint">封存人 ${text(snap.sealed_by)} · ${when(b.sealed_at)}<br>依据：${text(snap.reason)}<br>指纹 ${text(snap.fingerprint?.slice(0, 16))}… · ${snap.complete_count}/${snap.hive_count} 箱</p><div class="tablewrap"><table><thead><tr><th>蜂箱</th><th>封存读数</th><th>王况 / 框数</th><th>补录人</th><th>巡检编号</th></tr></thead><tbody>${snap.hives.map(h => `<tr><td>${text(h.hive_code)}</td><td>${num(h.weight_kg)} kg / ${num(h.temperature, 1)}°C / 活动 ${num(h.activity, 0)} / 余饲 ${num(h.feed_left)}</td><td>${h.queen_seen ? '见王' : '未见王'} / ${h.colony_frames}框</td><td>${text(h.recorded_by)}</td><td>${h.visit_id ? 'V-' + h.visit_id : '—'}${h.superseded_by_batch_id ? ' · 已有新批' : ''}</td></tr>`).join('')}</tbody></table></div></section>`;
}

function detailPanel() {
  const b = book.batchDetail;
  if (!b) return '<section class="sheet"><div class="empty">选择左侧批次查看进度、缺检箱与封存依据。</div></section>';
  const p = b.progress;
  return `<div class="batch-head"><div><span class="code">${text(b.code)} · 责任人 ${text(b.claimed_by)}</span><h2>${batchState(b.state)} · ${b.next_action}</h2><p class="hint">领批 ${when(b.claimed_at)}${b.received_by ? '<br>交接接收 ' + text(b.received_by) + ' · ' + when(b.received_at) : ''}${b.parent_batch_id ? '<br>迟到补录自批次 #' + b.parent_batch_id : ''}${b.cancelled_by ? '<br>取消 ' + text(b.cancelled_by) + ' · ' + text(b.cancel_reason) : ''}</p></div><div class="meter big"><i style="width:${Math.min(100, p.percent)}%"></i></div></div>${p.missing.length ? `<section class="sheet"><h2>缺检箱（${p.missing.length}）</h2><p class="hint">${p.missing.map(m => text(m.hive_code) + ' · ' + text(m.site)).join('　')}</p><p class="hint">以下箱在接收前必须有且仅有一条完整读数，否则交接退回原批。</p></section>` : ''}${p.incomplete.length ? `<section class="sheet"><h2>缺项记录（留在原批）</h2>${p.incomplete.map(r => `<p class="hint">${text(r.hive_code)} · R-${r.id} · 缺 ${r.missing_fields.map(text).join('、')} · ${text(r.recorded_by)}</p>`).join('')}</section>` : ''}${p.conflicts.length ? `<section class="sheet"><h2>冲突证据（未覆盖原值）</h2>${p.conflicts.map(r => `<p class="hint">${text(r.hive_code)} · ${text(r.conflict_note)} · 提交 ${text(r.recorded_by)}</p>`).join('')}</section>` : ''}${sealPanel(b)}${snapshotPanel(b)}<section class="batch-hives">${b.hives.map(item => readingRow(b, item)).join('')}</section>`;
}

export function render() {
  return headline('10 / BATCH HANDOVER','领到哪一批，就只对这一批负责','领批锁定箱清单，逐箱补录完整读数，交接接收后由主管封存。筛查只使用封存时读数；迟到补录进入下一批，不回头改旧快照。') + `<div class="toolbar"><p class="hint">页面显示批次进度、缺检箱、责任人与封存依据；冲突与缺项留在原批。</p></div><div class="resource-layout"><aside>${claimForm()}${batchList()}</aside><section>${detailPanel()}</section></div>`;
}

function readingPayload(form, extra = {}) {
  const hiveId = Number(form.dataset.hive);
  const payload = {hive_id: hiveId, client_reading_id: rid()};
  for (const [name] of FIELD_ROWS) {
    const raw = form.elements[name].value.trim();
    payload[name] = raw === '' ? null : Number(raw);
  }
  const queen = form.elements.queen_seen.value;
  payload.queen_seen = queen === '' ? null : queen === 'true';
  payload.note = form.elements.note.value;
  return {...payload, ...extra};
}

export function bind(rerender) {
  const b = book.batchDetail;
  document.querySelector('#claim-form').onsubmit = async e => {
    e.preventDefault();
    const form = e.target;
    const ids = [...form.querySelectorAll('input[name=hive_ids]:checked')].map(x => Number(x.value));
    if (!ids.length) return toast('请至少勾选一只蜂箱');
    try {
      const created = await api('/inspection-batches', 'POST', {code: form.elements.code.value, note: form.elements.note.value, hive_ids: ids, idempotency_key: rid()});
      book.selectedBatch = created.id;
      book.batchClaimDraft = null;
      await openNotebook();
      rerender();
      toast(`批次 ${created.code} 已领取，锁定 ${created.hives.length} 箱`);
    } catch (err) {
      toast(err.message);
    }
  };
  document.querySelector('#claim-form').addEventListener('change', e => {
    if (e.target.name === 'hive_ids') {
      book.batchClaimDraft = {
        hive_ids: [...document.querySelectorAll('#claim-form input[name=hive_ids]:checked')].map(x => Number(x.value)),
        code: document.querySelector('#claim-form').elements.code.value,
        note: document.querySelector('#claim-form').elements.note.value,
      };
    }
  });
  document.querySelector('#pick-site').onclick = () => {
    const form = document.querySelector('#claim-form');
    book.batchClaimDraft = {
      hive_ids: book.hives.filter(h => h.site.includes('东坡')).map(h => h.id),
      code: form.elements.code.value,
      note: form.elements.note.value,
    };
    rerender();
  };
  document.querySelector('#clear-pick').onclick = () => {
    const form = document.querySelector('#claim-form');
    book.batchClaimDraft = {hive_ids: [], code: form.elements.code.value, note: form.elements.note.value};
    rerender();
  };
  document.querySelectorAll('[data-batch]').forEach(btn => {
    btn.onclick = async () => {
      book.selectedBatch = Number(btn.dataset.batch);
      await openNotebook();
      rerender();
    };
    btn.onkeydown = e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        btn.click();
      }
    };
  });
  if (!b) return;
  document.querySelectorAll('.reading-form').forEach(form => form.onsubmit = async e => {
    e.preventDefault();
    try {
      const result = await api(`/inspection-batches/${b.id}/readings`, 'POST', readingPayload(form));
      await openNotebook();
      rerender();
      toast(result.message || (result.reading?.state === 'complete' ? '本箱完整读数已补录' : `缺项已留在原批：${result.reading?.missing_fields?.join('、') || ''}`));
    } catch (err) {
      toast(err.message);
    }
  });
  document.querySelectorAll('[data-correct]').forEach(btn => btn.onclick = async () => {
    const form = btn.closest('form');
    try {
      const result = await api(`/inspection-batches/${b.id}/readings`, 'POST', readingPayload(form, {correct_reading_id: Number(btn.dataset.correct)}));
      await openNotebook();
      rerender();
      toast(result.reading?.state === 'complete' ? '原完整读数已更正，旧值标记为已更正' : '更正未完成');
    } catch (err) {
      toast(err.message);
    }
  });
  document.querySelector('#receive-batch').onclick = async () => {
    try {
      await api(`/inspection-batches/${b.id}/receive`, 'POST', {idempotency_key: rid()});
      await openNotebook();
      rerender();
      toast('整批已交接接收，等待主管封存');
    } catch (err) {
      toast(err.message);
    }
  };
  document.querySelector('#seal-form').onsubmit = async e => {
    e.preventDefault();
    try {
      await api(`/inspection-batches/${b.id}/seal`, 'POST', {reason: e.target.elements.reason.value, idempotency_key: rid()});
      await openNotebook();
      rerender();
      toast('批次已封存，筛查将只使用封存时读数');
    } catch (err) {
      toast(err.message);
    }
  };
  document.querySelector('#screen-batch').onclick = async e => {
    e.target.disabled = true;
    e.target.textContent = '按封存读数筛查中…';
    try {
      const job = await api(`/inspection-batches/${b.id}/screen`, 'POST');
      for (let i = 0; i < 100; i++) {
        const result = await api(`/inspection-batches/${b.id}/screen/${job.job_id}`);
        if (result.status === 'done') {
          await openNotebook();
          rerender();
          toast(`已按封存读数筛查 ${result.count} 箱`);
          return;
        }
        if (result.status === 'failed') throw new Error(result.error || '批次筛查失败');
        await new Promise(r => setTimeout(r, 400));
      }
      throw new Error('筛查尚未结束，请稍后刷新');
    } catch (err) {
      toast(err.message);
      e.target.disabled = false;
      e.target.textContent = '按封存读数筛查';
    }
  };
  document.querySelector('#cancel-batch').onclick = async () => {
    const reason = prompt('取消依据（至少5字），取消后箱清单释放：', '分组调整，重新领批');
    if (reason == null) return;
    try {
      await api(`/inspection-batches/${b.id}/cancel`, 'POST', {reason});
      await openNotebook();
      rerender();
      toast('批次已取消，箱清单已释放');
    } catch (err) {
      toast(err.message);
    }
  };
}

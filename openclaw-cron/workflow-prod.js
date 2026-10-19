const py = '/root/project/ai-weekly-report/.venv/bin/python';
const dir = '/root/project/ai-weekly-report';
const chat = 'chat:oc_b254a7eaff866ce3495b70a4aa254a28';
const driveFolder = 'CManfJqKdlDnsUdXhXJcjG6inQh'; // 「AI资讯周报」文件夹
// 六步流水线（2026-10-19 升级，与测试版 workflow-test.js 同构）：
// ①fetch(HF readme全文落盘) ②filter → 【③review·llm_task LLM复核，HF喂readme前2000字符】
//   → 【④interpret·llm_task LLM解读，仅HF，产readme_interpretation】 → ⑤translate ⑥render
// 生产版差异：render 不带 test 参数（出刊 output/prod/、文件名无时间戳）；发刊后云盘归档
// review 降级：llm_task 整体失败 → reviewed 整体复制 filtered（LLM 缺席=全员通过）
// interpret 降级：失败条目不带字段，render 遇空不显示正文（只显更新内容）
const BATCH = 25;
const INTERPRET_PROMPT = '阅读README，用通俗易懂的中文介绍这个模型是什么，100字以内。\n\n严格输出 JSON，勿输出其它内容：\n{"interpretation":"中文介绍"}\n\n【材料】\n';
const PROMPT_HEAD = '判断以下条目是否属于大模型（LLM）与智能体（Agent）方向，是则保留，不是则剔除。不确定时倾向保留。\n\n严格输出 JSON，勿输出其它内容：\n{"results":[{"id":编号,"verdict":"keep|kill","reason":"一句话中文理由"}]}\n\n【待判条目】\n';
const pipeline1 = 'cd ' + dir + ' && echo ==STEP==fetch && ' + py + ' fetch.py'
  + ' && echo ==STEP==filter && ' + py + ' filter.py';
const pipeline2 = 'cd ' + dir + ' && echo ==STEP==translate && ' + py + ' translate.py'
  + ' && echo ==STEP==render && ' + py + ' render.py';

async function runStage(command) {
  // 沙箱 exec 默认 ~1s 后返回 running 并丢后台（07:00 空刊根因），
  // yieldMs 强制阻塞到结束；仍 running 则 process poll 兜底
  let p = await exec({ command, yieldMs: 780000 });
  if (p && p.status === 'running' && p.sessionId) {
    for (let i = 0; i < 30; i++) {
      const r = await process({ action: 'poll', sessionId: p.sessionId, timeout: 25000 });
      if (r && (r.status === 'completed' || r.status === 'exited' || r.exitCode !== undefined)) {
        p = r; break;
      }
    }
  }
  return p;
}

try {
  const d = await exec({ command: 'date +%F', yieldMs: 30000 });
  const today = String(d && d.aggregated ? d.aggregated : '').trim();
  if (!today) return { notify: 'FAIL: cannot resolve today' };

  // ===== Stage 1: fetch + filter（重试 3 次，fetch 断点续传）=====
  let p = null, log = '';
  for (let attempt = 1; attempt <= 3; attempt++) {
    p = await runStage(pipeline1);
    log = String(p && p.aggregated ? p.aggregated : '');
    if (p && p.status === 'completed' && p.exitCode === 0) break;
    if (attempt < 3) await exec({ command: 'sleep 30', yieldMs: 35000 });
  }
  if (!p || p.status !== 'completed' || p.exitCode !== 0) {
    return { notify: 'FAIL@stage1-fetch/filter(3次尝试均失败) status=' + (p && p.status) + ' exit=' + (p && p.exitCode) + ' log: ' + log.slice(-400) };
  }

  // 校验1：filter 产物必须非空
  const fl = await exec({ command: 'ls ' + dir + '/filtered/' + today + '/ 2>/dev/null | grep -c "\\.json"', yieldMs: 30000 });
  const fcount = Number(String(fl && fl.aggregated ? fl.aggregated : '').trim());
  if (!fcount || fcount < 1) {
    return { notify: 'FAIL: filtered empty. log: ' + log.slice(-300) };
  }

  // ===== Stage 2: review（LLM 复核，读 filtered 写 reviewed）=====
  let reviewStat = 'review: 未知';
  try {
    const fdir = dir + '/filtered/' + today;
    const rdir = dir + '/reviewed/' + today;
    await exec({ command: 'mkdir -p ' + rdir, yieldMs: 30000 });
    let total = 0, keptN = 0, degraded = false; const killed = [];
    for (const src of ['huggingface', 'github', 'aibase']) {
      // HF 大文件通道：tool.py 产 slim 版（含 readme 前2000字符，~15KB），
      // 避免 exec 聚合输出对 108KB 全量 json 截断导致 JSON.parse 失败静默跳过
      if (src === 'huggingface') {
        await exec({ command: 'cd ' + dir + ' && ' + py + ' tool.py slim ' + today, yieldMs: 30000 });
      }
      const cat = await exec({ command: 'cat ' + fdir + '/' + (src === 'huggingface' ? 'huggingface-slim.json' : src + '.json'), yieldMs: 30000 });
      let data;
      try { data = JSON.parse(String(cat && cat.aggregated ? cat.aggregated : '').trim()); }
      catch (e) { continue; }
      const items = data.items || [];
      total += items.length;
      const keptItems = [];
      for (let i = 0; i < items.length; i += BATCH) {
        const batch = items.slice(i, i + BATCH);
        const lines = batch.map((it, bi) => {
          const heat = it.stars != null ? it.stars + ' stars' : (it.likes != null ? it.likes + ' likes' : '无');
          // HF：slim 版已含 readme 前2000字符（readme_head）；GitHub：trending 短描述
          const desc = src === 'huggingface'
            ? String(it.readme_head || '')
            : String(it.summary || '').slice(0, 280);
          return '编号:' + (bi + 1) + '\n来源:' + src + '\n标题:' + (it.title || '') + '\n描述:' + desc + '\n热度:' + heat;
        }).join('\n---\n');
        let verdicts = null;
        // 批级重试：3 次尝试，间隔 10s（确保复核完整性，失败批不裸奔）
        for (let attempt = 1; attempt <= 3; attempt++) {
          try {
            const r = await llm_task({ prompt: PROMPT_HEAD + lines });
            verdicts = (r && r.json && r.json.results) || [];
            if (verdicts.length > 0) break;
          } catch (e) { verdicts = null; }
          if (attempt < 3) await exec({ command: 'sleep 10', yieldMs: 15000 });
        }
        if (!verdicts || verdicts.length < batch.length) degraded = true; // 全败或返回截断都算发生过失败
        for (let bi = 0; bi < batch.length; bi++) {
          const it = batch[bi];
          const v = verdicts.find(x => String(x.id) === String(bi + 1));
          if (v && v.verdict === 'kill') killed.push((it.title || '').slice(0, 30));
          else { if (v && v.reason) it.review_reason = v.reason; keptItems.push(it); }
        }
      }
      keptN += keptItems.length;
      // HF 走 slim 通道：items 已瘦身（无 readme 全文），heredoc 写盘安全
      const out = Object.assign({}, data, { items: keptItems });
      const json = JSON.stringify(out, null, 1);
      await exec({ command: 'cat > ' + rdir + '/' + src + '.json <<\'JSONEOF\'\n' + json + '\nJSONEOF', yieldMs: 30000 });
    }
    reviewStat = 'review: ' + total + '→' + keptN + '（剔' + (total - keptN) + '）'
      + (degraded ? ' ⚠有降级' : '')
      + (killed.length ? ' 剔除: ' + killed.slice(0, 5).join('、') : '');
  } catch (e) {
    // 整体降级：reviewed = filtered 原样复制，流水线继续
    await exec({ command: 'mkdir -p ' + dir + '/reviewed/' + today + ' && cp ' + dir + '/filtered/' + today + '/*.json ' + dir + '/reviewed/' + today + '/', yieldMs: 30000 });
    reviewStat = 'review: 降级通过（LLM失败 ' + String(e && e.message ? e.message : e).slice(0, 80) + '）';
  }

  // ===== Stage 2.5: interpret（LLM 解读，读 reviewed 写 interpreted，仅 HF）=====
  let interpStat = '';
  try {
    const rvdir = dir + '/reviewed/' + today;
    const ipdir = dir + '/interpreted/' + today;
    await exec({ command: 'mkdir -p ' + ipdir, yieldMs: 30000 });
    // github/aibase 原样过境（本轮只做 HF）
    await exec({ command: 'cp ' + rvdir + '/github.json ' + rvdir + '/aibase.json ' + ipdir + '/ 2>/dev/null', yieldMs: 30000 });
    // prep：按 keep 名单导出 readme-{i}.txt（title+前30000字符）与 list.json（python 侧大文件 IO）
    await exec({ command: 'cd ' + dir + ' && ' + py + ' tool.py prep ' + today, yieldMs: 30000 });
    const lc = await exec({ command: 'cat ' + rvdir + '/hf-prep/list.json', yieldMs: 30000 });
    let lst = [];
    try { lst = JSON.parse(String(lc && lc.aggregated ? lc.aggregated : '').trim()); } catch (e) {}
    let okN = 0;
    for (let k = 0; k < lst.length; k++) {
      const rc = await exec({ command: 'cat ' + rvdir + '/hf-prep/readme-' + lst[k].i + '.txt', yieldMs: 30000 });
      const material = String(rc && rc.aggregated ? rc.aggregated : '').trim();
      if (!material) continue; // 无 readme 不产出字段（字段没有就不显示）
      for (let attempt = 1; attempt <= 2; attempt++) {
        try {
          const r = await llm_task({ prompt: INTERPRET_PROMPT + material });
          const txt = r && r.json && r.json.interpretation;
          if (txt) {
            await exec({ command: 'cat > ' + rvdir + '/hf-prep/interpretation-' + lst[k].i + '.txt <<\'IEOF\'\n' + String(txt).trim() + '\nIEOF', yieldMs: 30000 });
            okN++; break;
          }
        } catch (e) {}
        if (attempt < 2) await exec({ command: 'sleep 5', yieldMs: 10000 });
      }
    }
    // assemble：filtered 全字段 + keep 名单 + 解读 → interpreted/huggingface.json（python 侧组装）
    const asm = await exec({ command: 'cd ' + dir + ' && ' + py + ' tool.py assemble ' + today, yieldMs: 30000 });
    const asmOut = String(asm && asm.aggregated ? asm.aggregated : '').trim();
    // ⚠判定以 assemble 输出为准（prep 失败时 lst=[]，旧条件 0<0 恒 false 会漏标）
    const am = asmOut.match(/(\d+)\/(\d+)/);
    const warn = am ? (Number(am[1]) < Number(am[2])) : (okN < lst.length);
    interpStat = 'interpret: ' + (asmOut || (okN + '/' + lst.length)) + (warn ? ' ⚠有降级' : '');
  } catch (e) {
    // 整体降级：优先 assemble 兜底（无解读但保全卡片字段——reviewed 的 HF 是 slim 版缺
    // downloads/params/license/last_commit，直接 cp 会让卡片丢 tags 和更新内容）；
    // assemble 也挂了才 cp 裸过境
    let salvaged = false;
    try {
      const r2 = await exec({ command: 'cd ' + dir + ' && ' + py + ' tool.py assemble ' + today, yieldMs: 30000 });
      if (r2 && r2.exitCode === 0) salvaged = true;
    } catch (e2) {}
    if (!salvaged) {
      await exec({ command: 'mkdir -p ' + dir + '/interpreted/' + today + ' && cp ' + dir + '/reviewed/' + today + '/*.json ' + dir + '/interpreted/' + today + '/', yieldMs: 30000 });
    }
    interpStat = 'interpret: 降级' + (salvaged ? '（无解读，卡片字段保全）' : '跳过（字段不保全）') + '（' + String(e && e.message ? e.message : e).slice(0, 50) + '）';
  }

  // ===== Stage 3: translate + render（重试 3 次）=====
  let p2 = null, log2 = '';
  for (let attempt = 1; attempt <= 3; attempt++) {
    p2 = await runStage(pipeline2);
    log2 = String(p2 && p2.aggregated ? p2.aggregated : '');
    if (p2 && p2.status === 'completed' && p2.exitCode === 0) break;
    if (attempt < 3) await exec({ command: 'sleep 30', yieldMs: 35000 });
  }
  if (!p2 || p2.status !== 'completed' || p2.exitCode !== 0) {
    return { notify: 'FAIL@stage3-translate/render(3次尝试均失败) status=' + (p2 && p2.status) + ' exit=' + (p2 && p2.exitCode) + ' ' + reviewStat + (interpStat ? '\n' + interpStat : '') + ' log: ' + log2.slice(-400) };
  }

  // 校验2：今日正式刊（output/prod/ + 文件名含今日日期 + ≥60KB，与测试版阈值统一）
  const l = await exec({ command: 'ls -t ' + dir + '/output/prod/AI周报-' + today + '*.pdf 2>/dev/null | head -1', yieldMs: 30000 });
  const pdf = String(l && l.aggregated ? l.aggregated : '').trim().split('\n')[0];
  if (!pdf || !pdf.includes(today)) {
    return { notify: 'FAIL: no pdf for today in output/prod. ' + reviewStat + (interpStat ? '\n' + interpStat : '') + ' log: ' + log2.slice(-300) };
  }
  const sz = await exec({ command: 'stat -c %s "' + pdf + '"', yieldMs: 30000 });
  const size = Number(String(sz && sz.aggregated ? sz.aggregated : '').trim());
  if (!size || size < 60000) {
    return { notify: 'FAIL: pdf only ' + size + 'B，疑似空刊，拒绝发送。' + reviewStat + (interpStat ? '\n' + interpStat : '') };
  }

  // 发群（正式刊）—— 校验发送结果，防假成功
  const fname = pdf.split('/').pop();
  const mr = await message({
    action: 'send', channel: 'feishu', target: chat,
    message: 'AI周报 ' + today,
    attachments: [{ type: 'file', media: pdf, name: 'AI周报-' + today + '.pdf' }],
  });
  if (mr && mr.ok === false) {
    return { notify: 'FAIL: 群发送被拒 ' + JSON.stringify(mr).slice(0, 200) };
  }

  // 云盘归档：失败不影响发刊，只在回执里备注
  // 沙箱实测（drill1-4）：upload 返回无 token，需 list 根目录按文件名找回；
  // move 必须用 folder_token 参数名（parent_node 会报 params error）
  let driveNote = '云盘归档失败';
  try {
    const fnameDrive = pdf.split('/').pop();
    const up = await feishu_drive_file({ action: 'upload', file_path: pdf, name: fnameDrive });
    let token = up && (up.file_token || up.token);
    if (!token) {
      const l = await feishu_drive_file({ action: 'list' });
      const files = (l && l.files) || [];
      let best = null;
      for (const f of files) {
        if (f && f.type === 'file' && f.name === fnameDrive) {
          if (!best || Number(f.created_time || 0) > Number(best.created_time || 0)) best = f;
        }
      }
      token = best && best.token;
    }
    if (token) {
      const mv = await feishu_drive_file({ action: 'move', file_token: token, type: 'file', folder_token: driveFolder });
      if (mv && (mv.success || (!mv.error && mv.status !== 'error'))) driveNote = '云盘已归档';
    }
  } catch (e) {
    driveNote = '云盘归档失败: ' + String(e && e.message ? e.message : e).slice(0, 80);
  }

  return { notify: 'SCRIPT模式执行成功，' + fname + '已发送。' + driveNote + '\n' + reviewStat + (interpStat ? '\n' + interpStat : '') };
} catch (e) {
  return { notify: 'FAIL ' + String(e && e.message ? e.message : e).slice(0, 300) };
}

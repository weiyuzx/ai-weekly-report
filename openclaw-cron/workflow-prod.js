const py = '/root/project/ai-weekly-report/.venv/bin/python';
const dir = '/root/project/ai-weekly-report';
const chat = 'chat:oc_b254a7eaff866ce3495b70a4aa254a28';
const driveFolder = 'CManfJqKdlDnsUdXhXJcjG6inQh'; // 「AI资讯周报」文件夹
// 生产版：render 不带 test 参数，出刊目录 output/prod/
// 同步语义与测试版一致：yieldMs 强制阻塞 + process 轮询兜底 + 三道校验门
const pipeline = 'cd ' + dir + ' && echo ==STEP==fetch && ' + py + ' fetch.py'
  + ' && echo ==STEP==filter && ' + py + ' filter.py'
  + ' && echo ==STEP==translate && ' + py + ' translate.py'
  + ' && echo ==STEP==render && ' + py + ' render.py';
try {
  const d = await exec({ command: 'date +%F', yieldMs: 30000 });
  const today = String(d && d.aggregated ? d.aggregated : '').trim();
  if (!today) return { notify: 'FAIL: cannot resolve today' };

  // 健壮性：流水线失败自动重试（fetch 断点续传，重试只补失败源），最多 3 次尝试，间隔 30s
  let p = null;
  let log = '';
  for (let attempt = 1; attempt <= 3; attempt++) {
    p = await exec({ command: pipeline, yieldMs: 780000 });
    log = String(p && p.aggregated ? p.aggregated : '');

    if (p && p.status === 'running' && p.sessionId) {
      for (let i = 0; i < 30; i++) {
        const r = await process({ action: 'poll', sessionId: p.sessionId, timeout: 25000 });
        if (r && (r.status === 'completed' || r.status === 'exited' || r.exitCode !== undefined)) {
          p = r;
          log = String(r.aggregated || log);
          break;
        }
      }
    }

    if (p && p.status === 'completed' && p.exitCode === 0) break;
    if (attempt < 3) await exec({ command: 'sleep 30', yieldMs: 35000 });
  }

  if (!p || p.status !== 'completed' || p.exitCode !== 0) {
    return { notify: 'FAIL@pipeline(3次尝试均失败) status=' + (p && p.status) + ' exit=' + (p && p.exitCode) + ' log: ' + log.slice(-400) };
  }

  // 校验1：filter 产物非空
  const fl = await exec({ command: 'ls ' + dir + '/filtered/' + today + '/ 2>/dev/null | grep -c "\\.json"', yieldMs: 30000 });
  const fcount = Number(String(fl && fl.aggregated ? fl.aggregated : '').trim());
  if (!fcount || fcount < 1) {
    return { notify: 'FAIL: filtered empty. log: ' + log.slice(-300) };
  }

  // 校验2：今日正式刊（output/prod/ + 文件名含今日日期 + ≥100KB）
  const l = await exec({ command: 'ls -t ' + dir + '/output/prod/AI周报-' + today + '*.pdf 2>/dev/null | head -1', yieldMs: 30000 });
  const pdf = String(l && l.aggregated ? l.aggregated : '').trim().split('\n')[0];
  if (!pdf || !pdf.includes(today)) {
    return { notify: 'FAIL: no pdf for today in output/prod. log: ' + log.slice(-300) };
  }
  const sz = await exec({ command: 'stat -c %s "' + pdf + '"', yieldMs: 30000 });
  const size = Number(String(sz && sz.aggregated ? sz.aggregated : '').trim());
  if (!size || size < 100000) {
    return { notify: 'FAIL: pdf only ' + size + 'B，疑似空刊，拒绝发送' };
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

  return { notify: 'SCRIPT模式执行成功，' + fname + '已发送。' + driveNote };
} catch (e) {
  return { notify: 'FAIL ' + String(e && e.message ? e.message : e).slice(0, 300) };
}

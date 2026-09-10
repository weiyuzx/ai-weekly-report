const py = '/root/project/ai-weekly-report/.venv/bin/python';
const dir = '/root/project/ai-weekly-report';
const chat = 'chat:oc_b254a7eaff866ce3495b70a4aa254a28';
// 核心修复：沙箱 exec 默认 ~1s 后就返回 status:"running" 并把进程丢后台
// （07:00 空刊根因）。传 yieldMs 强制阻塞到进程真正结束，返回 completed+exitCode。
// 兜底：万一仍返回 running，用 process poll 轮询等完。
const pipeline = 'cd ' + dir + ' && echo ==STEP==fetch && ' + py + ' fetch.py'
  + ' && echo ==STEP==filter && ' + py + ' filter.py'
  + ' && echo ==STEP==translate && ' + py + ' translate.py'
  + ' && echo ==STEP==render && ' + py + ' render.py test';
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

  // 校验1：filter 产物必须非空
  const fl = await exec({ command: 'ls ' + dir + '/filtered/' + today + '/ 2>/dev/null | grep -c "\\.json"', yieldMs: 30000 });
  const fcount = Number(String(fl && fl.aggregated ? fl.aggregated : '').trim());
  if (!fcount || fcount < 1) {
    return { notify: 'FAIL: filtered empty. log: ' + log.slice(-300) };
  }

  // 校验2：必须是「今天」的真刊——文件名含今日日期 + ≥100KB（空壳刊约24KB）
  const l = await exec({ command: 'ls -t ' + dir + '/output/test/AI周报-测试-' + today + '-*.pdf 2>/dev/null | head -1', yieldMs: 30000 });
  const pdf = String(l && l.aggregated ? l.aggregated : '').trim().split('\n')[0];
  if (!pdf || !pdf.includes(today)) {
    return { notify: 'FAIL: no pdf for today. log: ' + log.slice(-300) };
  }
  const sz = await exec({ command: 'stat -c %s "' + pdf + '"', yieldMs: 30000 });
  const size = Number(String(sz && sz.aggregated ? sz.aggregated : '').trim());
  if (!size || size < 100000) {
    return { notify: 'FAIL: pdf only ' + size + 'B，疑似空刊，拒绝发送' };
  }

  const fname = pdf.split('/').pop();
  await message({
    action: 'send', channel: 'feishu', target: chat,
    message: 'AI周报 测试版 ' + today + '（script 模式）',
    attachments: [{ type: 'file', media: pdf, name: 'AI周报-测试版-' + today + '.pdf' }],
  });
  return { notify: 'SCRIPT模式执行成功，' + fname + '已发送。' };
} catch (e) {
  return { notify: 'FAIL ' + String(e && e.message ? e.message : e).slice(0, 300) };
}

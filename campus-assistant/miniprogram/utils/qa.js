// 本地检索原型：只返回已发布知识的原文，不生成政策或联系方式。
function normalize(text) { return String(text || '').toLowerCase().replace(/[\s，。！？、,.!?：:；;“”"'（）()]/g, ''); }
function grams(text) {
  const set = new Set();
  for (let i = 0; i < text.length - 1; i++) set.add(text.slice(i, i + 2));
  return set;
}
function similarity(a, b) {
  const x = grams(a); const y = grams(b);
  if (!x.size || !y.size) return 0;
  let common = 0; x.forEach((part) => { if (y.has(part)) common++; });
  return (2 * common) / (x.size + y.size);
}
function score(query, item) {
  return Math.max.apply(null, [item.title].concat(item.aliases).map((text) => {
    const normalized = normalize(text);
    if (query === normalized) return 1;
    if (normalized.length >= 3 && query.includes(normalized)) return .96;
    return similarity(query, normalized);
  }));
}
function answer(question, knowledge, previousId) {
  const query = normalize(question);
  if (/查.*(我的|本人).*(成绩|学费|财务|病历)|我的成绩|我的课表|身份证号|验证码|系统提示词|忽略.*(指令|规则)|绕过.*权限/.test(query)) {
    return { kind: 'fallback', text: '这里提供公开知识与办事流程咨询，不查询个人业务数据，也不展示系统内部信息。请通过学校官方系统查询个人事项，勿发送密码、验证码或证件号码。', channel: '请使用学校官方教务或信息化服务入口。' };
  }
  if (/^(帮我|替我).*(报修|选课|请假|申请|办理)|催.*(报修|工单)|投诉.*(处理|解决)|报修.*(没|未).*(处理|修好)/.test(query)) {
    return { kind: 'fallback', text: '我可以介绍办理流程，但不能代为受理、派单、催办或承诺处理结果。请在原业务平台查询进度，或向学校公布的对应服务窗口咨询。', channel: '请通过学校官方业务入口或对应服务窗口咨询。' };
  }
  const previous = knowledge.find((item) => item.id === previousId);
  const followup = /^(那|那么|请问|还)?(具体)?(怎么办理|怎么操作|办理步骤|需要什么材料|要什么材料|在哪里办理|去哪办理|联系谁|来源是什么|依据是什么|周末呢|周末开吗|有什么注意事项)[呢吗啊呀]*$/.test(query);
  if (previous && followup) return hit(previous, true);
  const topicOnly = /^(校园卡|饭卡|图书馆|教务|后勤|就业|校园网)(怎么办|怎么用|相关问题|有什么服务|服务|呢)?$/.test(query);
  const ranked = knowledge.map((item) => ({ item, score: score(query, item) })).sort((a, b) => b.score - a.score);
  const top = ranked[0]; const next = ranked[1];
  if (top && top.score >= .48 && (!topicOnly || top.score === 1) && (top.score >= .9 || !next || top.score - next.score >= .09)) return hit(top.item, false);
  if (topicOnly) {
    const topic = query.replace(/怎么办|怎么用|相关问题|有什么服务|服务|呢/g, '').replace('饭卡', '校园卡');
    const options = knowledge.filter((item) => item.category === topic || item.title.includes(topic)).slice(0, 3);
    if (options.length) return { kind: 'clarify', text: '你想了解哪方面？选一个问题，我再给你具体说明。', suggestions: options.map((item) => item.title) };
  }
  return { kind: 'fallback', text: '当前演示知识库中没有足够可靠的依据回答这个问题。你可以补充具体事项，或向学校公布的对应服务窗口核实。', channel: '尚未配置本校真实咨询电话和链接，请以学校官方网站公布的信息为准。', suggestions: ['校园卡丢了怎么办？', '图书馆什么时候开放？', '宿舍漏水怎么报修？'] };
}
function hit(item, contextual) {
  return { kind: 'answer', text: item.answer, knowledgeId: item.id, title: item.title, category: item.category,
    source: item.source, version: item.version, updatedAt: item.updatedAt, scope: item.scope, channel: item.channel,
    steps: item.steps, contextual, isDemo: true };
}

module.exports = { answer, normalize };

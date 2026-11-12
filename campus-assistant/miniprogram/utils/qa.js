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
function tokenCounts(text) {
  const normalized = normalize(text);
  const counts = Object.create(null);
  if (normalized.length === 1) counts[normalized] = 1;
  for (let i = 0; i < normalized.length - 1; i++) {
    const token = normalized.slice(i, i + 2);
    counts[token] = (counts[token] || 0) + 1;
  }
  return counts;
}
function buildHandbookIndex(handbook) {
  const chunks = handbook.chunks || [];
  const docs = chunks.map((item) => {
    const counts = tokenCounts([item.doc, item.chapter, item.section, item.article, item.source, item.text].join(' '));
    let length = 0;
    Object.keys(counts).forEach((token) => { length += counts[token]; });
    return { item, counts, length: Math.max(1, length) };
  });
  const documentFrequency = Object.create(null);
  docs.forEach((doc) => {
    Object.keys(doc.counts).forEach((token) => {
      documentFrequency[token] = (documentFrequency[token] || 0) + 1;
    });
  });
  let totalLength = 0;
  docs.forEach((doc) => { totalLength += doc.length; });
  return { docs, documentFrequency, averageLength: Math.max(1, totalLength / Math.max(1, docs.length)) };
}
const handbookIndexes = new WeakMap();
function handbookIndex(handbook) {
  let index = handbookIndexes.get(handbook);
  if (!index) {
    index = buildHandbookIndex(handbook);
    handbookIndexes.set(handbook, index);
  }
  return index;
}
// 二元词 BM25：用于覆盖 586 条手册正文，避免每次提问都重新建立全文索引。
function searchHandbookChunks(query, handbook) {
  const index = handbookIndex(handbook);
  const queryCounts = tokenCounts(query);
  const tokens = Object.keys(queryCounts);
  if (!tokens.length || !index.docs.length) return null;
  const total = index.docs.length;
  const k1 = 1.2;
  const b = .72;
  let best = null;
  index.docs.forEach((doc) => {
    let scoreValue = 0;
    let matched = 0;
    tokens.forEach((token) => {
      const frequency = doc.counts[token] || 0;
      if (!frequency) return;
      matched++;
      const documentFrequency = index.documentFrequency[token] || 0;
      const idf = Math.log(1 + (total - documentFrequency + .5) / (documentFrequency + .5));
      scoreValue += idf * (frequency * (k1 + 1)) /
        (frequency + k1 * (1 - b + b * doc.length / index.averageLength));
    });
    const coverage = matched / tokens.length;
    const normalizedText = normalize([doc.item.doc, doc.item.chapter, doc.item.section, doc.item.article, doc.item.text].join(' '));
    const phraseBonus = normalizedText.includes(query) ? 4 : 0;
    const finalScore = scoreValue * (.65 + .35 * coverage) + phraseBonus;
    if (!best || finalScore > best.score) best = { item: doc.item, score: finalScore, coverage };
  });
  if (!best) return null;
  // 正文块只在校验到足够主题重合时回答；低相关命中交给统一兜底。
  if (best.score >= 1.15 && best.coverage >= .25) return best.item;
  return null;
}
function sourceBook(source) {
  const matched = String(source || '').match(/《([^》]+)》/);
  return matched ? matched[1] : '';
}
function handbookChunkForEntry(entry, handbook) {
  const book = sourceBook(entry.source);
  const candidates = (handbook.chunks || []).filter((chunk) => {
    if (entry.article && chunk.article !== entry.article) return false;
    if (entry.page && (entry.page < chunk.page_start || entry.page > chunk.page_end)) return false;
    if (!book) return true;
    const doc = String(chunk.doc || '');
    return doc === book || doc.includes(book) || book.includes(doc);
  });
  return candidates[0] || null;
}
function handbookEntryHit(entry, handbook) {
  const chunk = handbookChunkForEntry(entry, handbook);
  const meta = handbook.meta || {};
  return {
    kind: 'answer', text: entry.answer, knowledgeId: '', handbookChunkId: chunk ? chunk.id : '',
    title: entry.title, category: entry.category, source: entry.source,
    article: entry.article || (chunk && chunk.article) || '', page: entry.page || (chunk && chunk.page_start) || 0,
    kbId: meta.kbId || '', libraryName: meta.title || '', libraryVersion: meta.version || '',
    libraryUpdatedAt: meta.updatedAt || '', libraryIndexReady: true,
    version: entry.version || 1, updatedAt: entry.updatedAt || meta.updatedAt || '',
    scope: meta.scope || '', channel: entry.channel || '', steps: entry.steps || [],
    contextual: false, isDemo: false
  };
}
function handbookChunkHit(chunk, handbook) {
  const meta = handbook.meta || {};
  return {
    kind: 'answer', text: chunk.text, knowledgeId: '', handbookChunkId: chunk.id,
    title: chunk.article ? chunk.doc + ' ' + chunk.article : chunk.doc,
    category: '学生手册', source: chunk.source, article: chunk.article || '', page: chunk.page_start || 0,
    kbId: meta.kbId || '', libraryName: meta.title || '', libraryVersion: meta.version || '',
    libraryUpdatedAt: meta.updatedAt || '', libraryIndexReady: true,
    version: 1, updatedAt: meta.updatedAt || '', scope: meta.scope || '',
    channel: '', steps: [], contextual: false, isDemo: false
  };
}
function answerHandbook(query, handbook) {
  if (!handbook) return null;
  const entries = handbook.entries || [];
  const ranked = entries.map((item) => ({ item, score: score(query, item) })).sort((a, b) => b.score - a.score);
  const top = ranked[0];
  const next = ranked[1];
  if (top && top.score >= .48 && (top.score >= .9 || !next || top.score - next.score >= .09)) {
    return handbookEntryHit(top.item, handbook);
  }
  const chunk = searchHandbookChunks(query, handbook);
  return chunk ? handbookChunkHit(chunk, handbook) : null;
}
// restricted：当前身份看不到的已发布知识。传入后，如果“范围外”有比范围内明显更贴近的
// 条目，就直接兜底——既不越权作答，也不透露受限条目是否存在（需求文档 2.1 权限规则）。
function noAnswer() {
  return { kind: 'fallback', text: '当前演示知识库中没有足够可靠的依据回答这个问题。你可以补充具体事项，或向学校公布的对应服务窗口核实。', channel: '尚未配置本校真实咨询电话和链接，请以学校官方网站公布的信息为准。', suggestions: ['校园卡丢了怎么办？', '图书馆什么时候开放？', '宿舍漏水怎么报修？'] };
}
function answer(question, knowledge, previousId, restricted, handbook) {
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
  if (restricted && restricted.length) {
    const hidden = Math.max.apply(null, restricted.map((item) => score(query, item)));
    const best = top ? top.score : 0;
    // 范围外有达到阈值、且比范围内更贴近的条目 → 兜底。
    if (hidden >= .48 && hidden > best) return noAnswer();
  }
  if (top && top.score >= .48 && (!topicOnly || top.score === 1) && (top.score >= .9 || !next || top.score - next.score >= .09)) return hit(top.item, false);
  const handbookAnswer = answerHandbook(query, handbook);
  if (handbookAnswer) return handbookAnswer;
  if (topicOnly) {
    const topic = query.replace(/怎么办|怎么用|相关问题|有什么服务|服务|呢/g, '').replace('饭卡', '校园卡');
    const options = knowledge.filter((item) => item.category === topic || item.title.includes(topic)).slice(0, 3);
    if (options.length) return { kind: 'clarify', text: '你想了解哪方面？选一个问题，我再给你具体说明。', suggestions: options.map((item) => item.title) };
  }
  return noAnswer();
}
// hit() 把「知识来源」一起带出去：知识库（名称/版本）+ 文档 + 条号/页码。
// 字段来自 store.getKnowledge() 的 decorate()，检索层不自己查表。
function hit(item, contextual) {
  return { kind: 'answer', text: item.answer, knowledgeId: item.id, title: item.title, category: item.category,
    source: item.source, article: item.article || '', page: item.page || 0,
    kbId: item.kbId || '', libraryName: item.libraryName || '', libraryVersion: item.libraryVersion || '',
    libraryUpdatedAt: item.libraryUpdatedAt || '', libraryIndexReady: !!item.libraryIndexReady,
    version: item.version, updatedAt: item.updatedAt, scope: item.scope, channel: item.channel,
    steps: item.steps, contextual, isDemo: true };
}

module.exports = { answer, normalize };

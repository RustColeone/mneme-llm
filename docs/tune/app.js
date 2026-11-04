// The tuner's page: open her gut file (and her memory file), change her dials and locks, save the changed files. The
// files are opened with sql.js in this browser and never leave it; every change goes through tune.js, which changes
// them as mneme-llm's Python does. Changes are made to the open copy at once; Save downloads each changed file, and
// Discard opens it again as it was. One language at a time, English or Chinese.
(function () {
  'use strict'
  const T = window.Tune
  const S = window.StarMap
  const SQL_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/'
  const KEPT = 'mneme-llm-tune-language'

  // Words reused from the DSH plugin's panel (dsh-mneme-llm plugin/client.js) keep its keys: 66 of them.
  const EN = {
    'page.title': 'Tuner',
    'nav.architecture': 'Architecture',
    'lang.other': '中文',
    'lang.label': 'Show this page in Chinese',
    'intro.title': 'Tune her',
    'intro.text': 'Open her gut file, and her memory file if you like, change her dials and locks, and save the ' +
      'changed files. Everything happens in this browser: the files are not sent anywhere.',
    'intro.stop': 'Stop her before opening her files, so that everything she has written is in the one file. Put ' +
      'each saved file in place of the old one before she starts again. A file beside it whose name ends in -wal ' +
      'means she has not fully stopped.',
    'drop.title': 'Drop her files here',
    'drop.pick': 'Choose files',
    'drop.hint': 'Her gut file and her memory file (SQLite), and her starter (.json.gz) for her star map. Which is ' +
      'which is read from the file itself.',
    'settings.title': 'Her gut',
    'file.starter': 'Her starter',
    'file.memory': 'Her memory',
    'file.close': 'Close',
    'file.closeConfirm': '{name} has unsaved changes. Close it anyway?',
    'file.replaceConfirm': '{name} has unsaved changes. Open {other} in its place?',
    'file.space': 'Space',
    'error.notSqlite': '{name} is not an SQLite file.',
    'error.notHers': '{name} is neither a gut file nor a memory file.',
    'error.schema': '{name} has schema {found}; this page reads schema 2. Run python -m mneme_llm.migrate on it first.',
    'error.read': '{name} could not be read: {error}',
    'error.starter': '{name} could not be read as a starter: {error}',
    'error.sql': 'SQLite could not be loaded ({error}). The page fetches sql.js from cdnjs, so it needs the internet.',
    'error.change': 'Not changed: {error}',
    'error.sensitivity': 'sensitivity is from -1 to 1',
    'error.age': 'an age is a number of lessons, 0 or more',
    'error.noHeart': 'her heart is not in this file yet: wake her once first',
    'error.nature': 'nature is from -6 to 6',
    'error.now': 'now is from -1 to 1',
    'error.weight': 'a weight is from 0 to 1',
    'error.often': 'how often is from 0 to 1',
    'error.own': 'a weight is 0 or more',
    'error.name': '{name} is not a side she can have',
    'error.notSide': '{name} is not one of her sides yet: give it a sentence first',
    'error.what': 'a side needs a sentence: what she does',
    'error.band': 'closeness here is from {floor} to {ceiling}',
    'error.noRole': '{subject} has no role in her memory',
    'error.liking': 'liking is from 0 to 100',
    'error.fadeDays': 'fading is from 0 to 1,000,000 days',
    'settings.grown': 'Growing up',
    'settings.age': 'Age: {age} lessons, {grown}% grown up, learning at {learning}% of her young pace',
    'age.label': 'Age (lessons)',
    'age.hint': 'Lessons that have taught her heart. Lower makes her younger: she learns faster again and forgets ' +
      'nothing.',
    'settings.young': 'Young again',
    'settings.youngConfirm': 'Make her young again? Her age goes back to 0 and her heart learns fast again. She ' +
      'forgets nothing.',
    'settings.tau': 'tau (lessons)',
    'settings.tauHint': 'How fast her heart grows up: young, a lesson moves her heart a lot; grown up (at five ' +
      'times tau), a little. A number above 0.',
    'settings.badTau': 'tau is a number above 0',
    'settings.heartLock': 'Lock her heart',
    'settings.heartLockHint': 'Her heart learns nothing and does not grow up until it is unlocked; how she is with ' +
      'each person still learns, unless locked too.',
    'settings.sensitivity': 'Sensitivity',
    'settings.sensitivityHint': 'How hard every moment hits her: -1 thick-skinned (lightly) to 1 sensitive (hard); ' +
      '0 is as she is.',
    'settings.dull': 'thick-skinned',
    'settings.keen': 'sensitive',
    'settings.tunes': 'Each feeling, by hand',
    'settings.tunesHint': 'Nature (-6 to 6) is where she stands on a feeling, as if she had been born so: 3 is ' +
      'about even, 6 is fully. What she lives moves her on from there (slowly once she is grown; a locked heart keeps ' +
      'it), and 0 removes it. Now (-1 to 1) is how much more or less of it she feels lately than usual: it fades as ' +
      'she lives.',
    'settings.nature': 'nature',
    'settings.now': 'now',
    'bars.title': 'Lately against usual',
    'bars.hint': 'The bar is lately, the tick is usual; a two-sided bar leans from the middle toward one end.',
    lately: 'lately {value}',
    usual: 'usual {value}',
    san: 'SAN',
    'self-esteem': 'Self-esteem',
    'people.title': 'People she knows',
    'people.none': 'Nobody yet.',
    'people.hint': 'How she is with each person, by hand. Closeness lives in her memory file; the rest in her gut.',
    'people.liking': 'Liking (points a level)',
    'people.likingHint': 'How far closeness moves with each exchange a person starts: this many points for each ' +
      'level of how it moved her (-2 to 2), less near the edge of their band. 0 to 100.',
    'people.fadeDays': 'Fading (days a point)',
    'people.fadeDaysHint': 'Closeness fades by one point for every this many days without a person, down to the ' +
      'floor of their role. 0 turns fading off.',
    'people.summary': '{lessons} lessons · {weight}% theirs',
    lessons: '{lessons} lessons',
    'mark.changed': 'changed, not saved',
    'person.memory': 'In her memory',
    'person.gut': 'In her gut',
    'role.creator': 'creator',
    'role.family': 'family',
    'role.friend': 'friend',
    'role.acquaintance': 'acquaintance',
    'people.closeness': 'Closeness ({role}, {floor} to {ceiling})',
    'people.noRole': 'No role in her memory: closeness needs one.',
    'people.holdCloseness': 'Lock closeness: no exchange or time moves it',
    'person.fades': 'fades without contact',
    'person.stays': 'does not fade',
    'person.closeness': 'Closeness',
    'person.closenessHint': 'Closeness now, faded by the days without them. Set by hand, their last contact counts ' +
      'as now.',
    'person.notMet': 'Not in her gut yet: what is set here waits for them.',
    'people.byHand': 'Set how much what is different with them counts, by hand',
    'people.weight': 'theirs',
    'person.weightHint': 'How much of how she is with them is theirs alone, on top of her heart. Learned, it grows ' +
      'as she knows them (at most 70%) and fades on talking days without them.',
    'person.weightLearned': 'learned: {weight}%',
    'people.lock': 'Lock how she is with them: what they say teaches nothing, and they do not fade',
    'people.tunes': 'Each feeling, with them alone',
    'people.tunesHint': 'A nudge to each feeling with this person only, on top of all she is and has learned with ' +
      'them; it stays (-6 to 6; 0 removes it).',
    'person.nudged': 'Nudged with them:',
    'people.forget': 'Forget them',
    'people.forgetConfirm': 'Forget {who}? How she is with them goes, and so do the sides only they wanted. What ' +
      'they did to her heart stays.',
    'person.memoryKept': 'Her memory file is not changed.',
    'person.forgotten': '{who} is forgotten in her gut; {count} lessons lost their name.',
    'sides.title': 'Her sides',
    'sides.hint': 'A side is a name and one sentence of what she does. A locked side holds for everyone, whatever ' +
      'is drawn and however long; how often is how strongly it shows.',
    'sides.none': 'No sides yet.',
    'sides.lockedIn': 'Locked in her {side} side.',
    'sides.lockThis': 'Lock her in this side',
    'sides.often': 'how often',
    'sides.oftenHint': 'The share of her turns the sentence goes beside the message: 1 is every turn.',
    'side.unlockHint': 'Unlocked, she stays in this side for a month first; then her sides are drawn by weight again.',
    'grown.side': 'In her {side} side for {days} more days',
    'sides.next': 'Her sides are drawn again at her next turn.',
    'side.weightHint': 'The weight is how much of her a side is, against her other sides when one is drawn; what ' +
      'people asked for adds to it. A side that has just grown is about 6.',
    'side.current': 'she is in this one',
    'sides.needsWhat': 'Write what she does before saving.',
    'sides.locked': 'locked',
    'sides.what': 'What she does, said to her ("You…")',
    'sides.weight': 'weight when drawn',
    'sides.drop': 'Remove',
    'side.dropConfirm': 'Drop her {side} side? It goes with what taught it, so growing it again starts over.',
    'sides.pick': 'Choose a name',
    'sides.write': 'Add',
    needGut: 'Open her gut file to tune her growing up, her feelings and her sides.',
    'map.title': 'Star map: her heart and the people she knows',
    'map.caption': 'Each dot is one thing she notices, placed toward the feeling it pulls her to; the brighter, ' +
      'the more it leans. The lines are her arms: how much more or less of each feeling she has now than when ' +
      'she was born (the ring). The big stars are people.',
    'map.counts': '{stars} brightest of {rows} · arms from her last {probed} lessons',
    'map.born': '{stars} brightest of {rows} · arms as born until 20 lessons ({probed} so far)',
    'map.view': 'View',
    'map.turn': 'Drag to turn it; a few seconds later it turns slowly by itself. The two ends of each bar sit side ' +
      'by side.',
    'map.slept': 'Her heart as of her last sleep: the {waiting} lessons since are not in it yet; she learns them ' +
      'again when she wakes.',
    'map.unknown': 'She was born from a starter, which is not open here, so each arm is drawn as she was born. Drop ' +
      'her starter (the .json.gz file her host gives her) beside her files to see how far she has grown.',
    'map.blank': 'She was born with no starter: her arms are measured from a blank heart.',
    'map.none': 'Her heart is not in this file yet: wake her once first.',
    'settings.save': 'Save',
    'settings.discard': 'Discard',
    'settings.unsaved': '{count} unsaved',
    'settings.none': 'No changes',
    saved: 'Saved {files}. Put each in place of the old file before she starts again.',
    discardConfirm: 'Discard every unsaved change?'
  }

  const ZH = {
    'page.title': '调校',
    'nav.architecture': '架构',
    'lang.other': 'English',
    'lang.label': '用英文显示这个页面',
    'intro.title': '调校她',
    'intro.text': '打开她的直觉文件（也可以同时打开她的记忆文件），调整她的各项设置和锁住的东西，再把改过的文件保存下来。一切都在这个浏览器里完成，文件不会被发送到任何地方。',
    'intro.stop': '打开文件之前先让她停下来，这样她写下的一切都在这一个文件里。她再次启动之前，用保存下来的文件替换旧文件。如果旁边还有一个名字以 -wal 结尾的文件，说明她还没有完全停下。',
    'drop.title': '把她的文件拖到这里',
    'drop.pick': '选择文件',
    'drop.hint': '她的直觉文件和记忆文件（SQLite），以及画星图用的 starter 文件（.json.gz）。哪个是哪个，会从文件本身读出来。',
    'settings.title': '她的直觉',
    'file.starter': '她的 starter 文件',
    'file.memory': '她的记忆',
    'file.close': '关闭',
    'file.closeConfirm': '{name} 还有未保存的改动。仍然关闭吗？',
    'file.replaceConfirm': '{name} 还有未保存的改动。要打开 {other} 来替换它吗？',
    'file.space': '空间',
    'error.notSqlite': '{name} 不是 SQLite 文件。',
    'error.notHers': '{name} 既不是直觉文件，也不是记忆文件。',
    'error.schema': '{name} 的 schema 是 {found}，这个页面只读 schema 2。请先对它运行 python -m mneme_llm.migrate。',
    'error.read': '无法读取 {name}：{error}',
    'error.starter': '无法把 {name} 读取为 starter 文件：{error}',
    'error.sql': '无法加载 SQLite（{error}）。这个页面要从 cdnjs 获取 sql.js，所以需要联网。',
    'error.change': '没有改动：{error}',
    'error.sensitivity': '敏感度在 -1 到 1 之间',
    'error.age': '年龄是课的节数，0 或以上',
    'error.noHeart': '这个文件里还没有她的心：先让她醒来一次',
    'error.nature': '天性在 -6 到 6 之间',
    'error.now': '现在在 -1 到 1 之间',
    'error.weight': '比重在 0 到 1 之间',
    'error.often': '出现频率在 0 到 1 之间',
    'error.own': '权重是 0 或以上',
    'error.name': '{name} 不是她能有的属性',
    'error.notSide': '{name} 还不是她的属性：先给它写一句她的做法',
    'error.what': '属性需要一句话：她的做法',
    'error.band': '这里的亲近度在 {floor} 到 {ceiling} 之间',
    'error.noRole': '{subject} 在她的记忆里没有角色',
    'error.liking': '好感步幅在 0 到 100 之间',
    'error.fadeDays': '淡去天数在 0 到 1,000,000 之间',
    'settings.grown': '长大',
    'settings.age': '年龄：{age} 节课，长大了 {grown}%，学习速度是她小时候的 {learning}%',
    'age.label': '年龄（节课）',
    'age.hint': '教过她的心的课数。调低会让她变年轻：她重新学得更快，也不会忘记任何事。',
    'settings.young': '回到小时候',
    'settings.youngConfirm': '让她回到小时候？她的年龄会归零，她的心又会学得很快。她不会忘记任何事。',
    'settings.tau': 'tau（节课）',
    'settings.tauHint': '她的心长得多快：小时候，一节课就能让她的心变化很大；长大后（到五倍 tau 时），变化就很小。填大于 0 的数。',
    'settings.badTau': 'tau 要大于 0',
    'settings.heartLock': '锁住她的心',
    'settings.heartLockHint': '解锁之前，她的心不再学习，也不再长大；她和每个人相处的样子仍会学，除非也锁住。',
    'settings.sensitivity': '敏感度',
    'settings.sensitivityHint': '每个瞬间对她的冲击有多大：-1 钝感（轻轻带过）到 1 敏感（冲击很重）；0 就是她本来的样子。',
    'settings.dull': '钝感',
    'settings.keen': '敏感',
    'settings.tunes': '每种感觉，逐个调',
    'settings.tunesHint': '天性（-6 到 6）是她在这种感受上站的位置，就像她生来如此：3 大约持平，6 是完全如此。她经历的事会让她从那里慢慢移开（长大后更慢；锁住她的心，它就留在那里），填 0 就是去掉它。现在（-1 到 1）是她最近比平常多或少感受到这种感觉的程度：它会随着她的生活慢慢变淡。',
    'settings.nature': '天性',
    'settings.now': '现在',
    'bars.title': '最近对比平常',
    'bars.hint': '实心条是最近，刻度线是平常；两端都能延伸的条会从中间偏向其中一端。',
    lately: '最近 {value}',
    usual: '平常 {value}',
    san: 'SAN',
    'self-esteem': '自尊',
    'people.title': '她认识的人',
    'people.none': '还没有人。',
    'people.hint': '她和每个人相处的样子，由你亲手设定。亲近度存在她的记忆文件里，其余的存在她的直觉里。',
    'people.liking': '好感步幅（每级的点数）',
    'people.likingHint': '一个人每开启一次交流，亲近度移动多少：按这次交流让她的心情变化了几级（-2 到 2），每级移动这么多点，越接近范围边缘移动越少。0 到 100。',
    'people.fadeDays': '淡去（每点的天数）',
    'people.fadeDaysHint': '一个人多少天没来，亲近度就淡去一点，最低到其角色的下限。填 0 就不再淡去。',
    'people.summary': '{lessons} 节课 · {weight}% 专属于这个人',
    lessons: '{lessons} 节课',
    'mark.changed': '已改动，未保存',
    'person.memory': '在她的记忆里',
    'person.gut': '在她的直觉里',
    'role.creator': '创造者',
    'role.family': '家人',
    'role.friend': '朋友',
    'role.acquaintance': '认识的人',
    'people.closeness': '亲近度（{role}，{floor} 到 {ceiling}）',
    'people.noRole': '她的记忆里没有角色：亲近度需要一个角色。',
    'people.holdCloseness': '锁住亲近度：不再因交流或时间而变动',
    'person.fades': '不联系会淡去',
    'person.stays': '不会淡去',
    'person.closeness': '亲近度',
    'person.closenessHint': '这是现在的亲近度，已按没联系的天数淡去。手动设定后，最后一次联系就算作现在。',
    'person.notMet': '还不在她的直觉里：这里的设定会等着这个人。',
    'people.byHand': '亲手设定：她和这个人在一起时不一样的那份算多少',
    'people.weight': '专属于这个人',
    'person.weightHint': '她和这个人相处的样子里，有多少是专属于这个人的，叠加在她的心之上。按学到的算，会随着她越来越了解这个人而增加（最多 70%），没有和这个人说话的日子里会慢慢变淡。',
    'person.weightLearned': '学到的：{weight}%',
    'people.lock': '锁住她和这个人相处的样子：这个人说的话什么也不教，也不会淡去',
    'people.tunes': '每一种感受，只对这个人',
    'people.tunesHint': '只针对这个人，给每种感受加一点偏移，叠加在她本来的样子和她与这个人相处中学到的一切之上，并且一直保留（-6 到 6；0 表示移除）。',
    'person.nudged': '已微调：',
    'people.forget': '忘记这个人',
    'people.forgetConfirm': '忘记{who}？她和这个人相处的样子会消失，只有这个人想要的属性也会消失；这个人在她心里留下的影响还在。',
    'person.memoryKept': '她的记忆文件不会改变。',
    'person.forgotten': '已在她的直觉里忘记 {who}；{count} 节课不再带有这个名字。',
    'sides.title': '她的属性',
    'sides.hint': '属性由一个名字和一句她的做法组成。锁住的属性对所有人都生效，无论抽到什么、持续多久；而它出现的频率，决定它表现得有多强。',
    'sides.none': '还没有属性。',
    'sides.lockedIn': '锁住在她的{side}一面。',
    'sides.lockThis': '把她锁在这一面',
    'sides.often': '出现频率',
    'sides.oftenHint': '她的回合中，这句做法附在消息旁的比例：1 表示每个回合。',
    'side.unlockHint': '解锁后，她会先在这一面再待一个月，然后重新按权重抽。',
    'grown.side': '还会在她的{side}一面待 {days} 天',
    'sides.next': '她的下一个回合会重新按权重抽属性。',
    'side.weightHint': '权重是这个属性在她身上占多少，抽取时和她的其他属性相比；别人提出的要求会再加上去。刚长出来的属性大约是 6。',
    'side.current': '她正处在这一面',
    'sides.needsWhat': '保存前写下她的做法。',
    'sides.locked': '已锁住',
    'sides.what': '她的做法，用对她说的话来写（你……）',
    'sides.weight': '抽到时的权重',
    'sides.drop': '去掉',
    'side.dropConfirm': '要去掉她的{side}一面吗？教出它的那些记录也会一起去掉，要再长出来就得从头开始。',
    'sides.pick': '选择一个名字',
    'sides.write': '添加',
    needGut: '打开她的直觉文件，才能调整她的长大、感觉和属性。',
    'map.title': '星图：她的心和她认识的人',
    'map.caption': '每个点都是她注意到的一件事，朝着它把她引向的那种感觉摆放；点越亮，偏向得越多。这些线是她的臂：她现在每种感觉比出生时（那个环）多了或少了多少。大星星是人。',
    'map.counts': '{rows} 个中最亮的 {stars} 个 · 臂来自她最近的 {probed} 节课',
    'map.born': '{rows} 个中最亮的 {stars} 个 · 臂仍是出生时的样子，直到上满 20 节课（目前 {probed} 节）',
    'map.view': '视图',
    'map.turn': '拖动可以旋转它；几秒后它会自己慢慢转。每一条的两端并排挨在一起。',
    'map.slept': '这是她上次睡觉时的心：之后的 {waiting} 节课还不在里面，她醒来时会重新学一遍。',
    'map.unknown': '她生来带着一份 starter 文件，但它没有在这里打开，所以每条臂都画成她出生时的长度。把她的 starter 文件（宿主程序给她的那个 .json.gz）也拖进来，就能看到她长大了多少。',
    'map.blank': '她出生时没有 starter 文件：她的臂是拿一颗空白的心来比的。',
    'map.none': '她的心还不在这个文件里：先让她醒来一次。',
    'settings.save': '保存',
    'settings.discard': '放弃',
    'settings.unsaved': '{count} 项未保存',
    'settings.none': '没有改动',
    saved: '已保存 {files}。她再次启动之前，用它们替换旧文件。',
    discardConfirm: '放弃所有未保存的改动吗？'
  }
  const WORDS = { en: EN, zh: ZH }

  let language = (() => {
    try {
      const kept = localStorage.getItem(KEPT)
      if (kept === 'en' || kept === 'zh') return kept
    } catch {}
    return /^zh\b/i.test(navigator.language || '') ? 'zh' : 'en'
  })()
  const chinese = () => language === 'zh'
  const format = (text, values = {}) => String(text).replace(/\{(\w+)\}/g, (all, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : all)
  const t = (key, values) => format(WORDS[language][key] ?? EN[key] ?? key, values)
  const endName = end => chinese() ? T.CHINESE[end] : end
  const barName = bar => chinese() ? T.CHINESE[bar] : bar
  const roleName = key => WORDS[language][`role.${key}`] ?? key
  const signed = (value, digits = 2) => (value > 0 ? '+' : value < 0 ? '−' : '±') + Math.abs(value).toFixed(digits)
  const percent = value => Math.round((Number(value) || 0) * 100)
  const stepped = (value, step) => {
    const digits = (String(step).split('.')[1] || '').length
    return Number((Math.round(value / step) * step).toFixed(digits))
  }

  // ---- what is open ---------------------------------------------------------------------------------------------
  const KINDS = ['gut', 'memory']
  const state = {
    files: {}, // kind → {name, bytes: as opened or last saved, db, changes: Map of what changed}
    base: {}, // kind → the view as opened or last saved, for telling a change undone from one made
    gut: null, memory: null, space: null, status: null,
    starter: null, // her starter, for her star map: {name, born: her heart as she was born}
    map: null, // her star map, made again after every change to her gut file
    mapError: null, // or why it could not be made
    pick: { end: null, person: null, side: null, personEnd: {} }, // what is chosen in each list
    pending: new Map() // sides added here and not written yet (they need a sentence): name → weight
  }
  let updaters = [] // text on the page that follows the files, run after every change
  let chain = Promise.resolve() // one change at a time

  const sqlReady = (async () => {
    if (typeof window.initSqlJs !== 'function') throw new Error('sql.js did not load')
    return window.initSqlJs({ locateFile: file => SQL_BASE + file })
  })()
  sqlReady.catch(() => {})

  function errorText (error, values = {}) {
    if (error && error.name === 'TuneError') {
      const key = error.code === 'tau' ? 'settings.badTau' : `error.${error.code}`
      if (EN[key]) return t(key, { ...values, ...error.values })
    }
    return String(error && error.message ? error.message : error)
  }
  function say (text, error = false) {
    state.status = text ? { text, error } : null
  }

  /** A task after the ones before it; whatever happens, the next one still runs. */
  function queue (task) {
    chain = chain.then(task).catch(error => {
      console.error(error)
      say(errorText(error), true)
      try { render() } catch {}
    })
    return chain
  }

  async function refresh (kind) {
    const file = state.files[kind]
    if (kind === 'gut') {
      state.gut = file ? await T.gutView(file.db) : null
      await remap()
    } else state.memory = file && state.space !== null ? T.memoryView(file.db, state.space) : null
  }

  /** Her star map, from her gut file as it is now and her starter if one is open; a map that cannot be made is
   * none (the rest of the page goes on without it). */
  async function remap () {
    const file = state.files.gut
    state.mapError = null
    try {
      state.map = file ? await S.starmap(file.db, { born: state.starter?.born || null }) : null
    } catch (error) {
      console.error(error)
      state.map = null
      state.mapError = errorText(error)
    }
  }

  /** Her starter: read, and her birth lived again from it, for her star map's arms. Never changed or saved. */
  function openStarter (name, bytes) {
    return queue(async () => {
      try {
        const born = S.born(await S.readStarter(bytes))
        state.starter = { name, born }
        say(null)
      } catch (error) {
        say(t('error.starter', { name, error: errorText(error) }), true)
        return
      }
      await remap()
    }).then(render)
  }

  async function baseline (kind) {
    const file = state.files[kind]
    if (kind === 'gut') {
      state.base.gut = await T.gutView(file.db)
    } else {
      const spaces = T.spaces(file.db)
      state.base.memory = Object.fromEntries(spaces.map(space => [space, T.memoryView(file.db, space)]))
      if (!spaces.includes(state.space)) { // the space with the most people, to begin with
        state.space = spaces.reduce((best, space) => best === null ||
          state.base.memory[space].people.length > state.base.memory[best].people.length ? space : best, null)
      }
    }
    await refresh(kind)
  }

  async function openFile (name, bytes) {
    if (S.isGzip(bytes)) return openStarter(name, bytes)
    let SQL
    try {
      SQL = await sqlReady
    } catch (error) {
      say(t('error.sql', { error: errorText(error) }), true)
      render()
      return
    }
    return queue(async () => {
      let opened
      try {
        opened = T.open(SQL, bytes)
      } catch (error) {
        say(error && error.name === 'TuneError' ? errorText(error, { name }) : t('error.read', { name,
          error: errorText(error) }), true)
        return
      }
      const old = state.files[opened.kind]
      if (old && old.changes.size && !window.confirm(t('file.replaceConfirm', { name: old.name, other: name }))) {
        opened.db.close()
        return
      }
      if (old) old.db.close()
      state.files[opened.kind] = { name, bytes: new Uint8Array(bytes), db: opened.db, changes: new Map() }
      say(null)
      try {
        await baseline(opened.kind)
      } catch (error) {
        opened.db.close()
        delete state.files[opened.kind]
        state[opened.kind] = null
        say(t('error.read', { name, error: errorText(error) }), true)
      }
    }).then(render)
  }

  async function openFiles (list) {
    for (const file of list) await openFile(file.name, new Uint8Array(await file.arrayBuffer()))
  }

  function closeFile (kind) {
    if (kind === 'starter') {
      return queue(async () => {
        state.starter = null
        await remap()
        render()
      })
    }
    const file = state.files[kind]
    if (!file || (file.changes.size && !window.confirm(t('file.closeConfirm', { name: file.name })))) return
    queue(() => {
      file.db.close()
      delete state.files[kind]
      delete state.base[kind]
      state[kind] = null
      if (kind === 'memory') state.space = null
      else {
        state.pending.clear()
        state.map = null
      }
      render()
    })
  }

  /** One change: made to the open file, marked as unsaved (unless `same` says it is back as it was), and shown. */
  function edit (kind, key, change, { same, structural = false, after } = {}) {
    return queue(async () => {
      const file = state.files[kind]
      if (!file) return
      try {
        const result = await change(file.db)
        file.changes.set(key, true)
        await refresh(kind)
        if (same && same()) file.changes.delete(key)
        if (after) after(result)
      } catch (error) {
        say(t('error.change', { error: errorText(error) }), true)
        await refresh(kind)
        structural = true // (what is shown goes back to what the file holds)
      }
      if (structural) render()
      else update()
    })
  }

  function count () {
    return KINDS.reduce((sum, kind) => sum + (state.files[kind]?.changes.size || 0), 0) + state.pending.size
  }

  function save () {
    if (state.pending.size) return savebar()
    queue(async () => {
      const names = []
      for (const kind of KINDS) {
        const file = state.files[kind]
        if (!file || !file.changes.size) continue
        const bytes = file.db.export()
        download(file.name, bytes)
        file.bytes = bytes
        file.changes.clear()
        names.push(file.name)
        await baseline(kind)
      }
      if (names.length) say(t('saved', { files: names.join(', ') }))
      render()
    })
  }

  function download (name, bytes) {
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/vnd.sqlite3' }))
    const link = el('a', { href: url, download: name, hidden: true })
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }

  function discard () {
    if (!count() || !window.confirm(t('discardConfirm'))) return
    queue(async () => {
      const SQL = await sqlReady
      for (const kind of KINDS) {
        const file = state.files[kind]
        if (!file || !file.changes.size) continue
        file.db.close()
        file.db = T.open(SQL, file.bytes).db
        file.changes.clear()
        await baseline(kind)
      }
      state.pending.clear()
      say(null)
      render()
    })
  }

  // ---- building the page ----------------------------------------------------------------------------------------
  function el (tag, props, ...children) {
    const node = document.createElement(tag)
    for (const [key, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue
      if (key === 'class') node.className = value
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value)
      else if (['value', 'checked', 'disabled', 'open', 'hidden', 'selected'].includes(key)) node[key] = value
      else node.setAttribute(key, value === true ? '' : String(value))
    }
    for (const child of children.flat(Infinity)) {
      if (child !== null && child !== undefined && child !== false) node.append(child)
    }
    return node
  }
  const $ = selector => document.querySelector(selector)
  let ids = 0
  const uid = () => `f${++ids}`

  /** A node whose text (or more) follows the files: `fill(node)` again after every change. */
  function live (node, fill) {
    updaters.push(() => fill(node))
    fill(node)
    return node
  }
  const text = (tag, props, words) => live(el(tag, props), node => { node.textContent = words() })

  function update () {
    for (const fill of updaters) fill()
    savebar()
  }

  function card (title, ...children) {
    return el('section', { class: 'card' }, el('h2', null, title), ...children)
  }
  const hint = words => el('p', { class: 'hint' }, words)

  /** A slider with its value beside it; `onChange` when it is let go. */
  function slider ({ label, value, low, high, step, show, onChange, disabled = false, wide = false }) {
    const id = uid()
    const out = el('output', { class: 'value', for: id }, show(value))
    const input = el('input', { id, type: 'range', min: low, max: high, step, value, disabled,
      oninput: () => { out.textContent = show(stepped(Number(input.value), step)) },
      onchange: () => onChange(stepped(Number(input.value), step)) })
    if (low < 0 && high > 0) input.classList.add('two')
    return { node: el('div', { class: wide ? 'slider wide' : 'slider' },
      el('label', { class: 'slider-name', for: id }, label), input, out), input, out }
  }

  /** A number field; `onChange` with the number when it is changed, or `bad` for what is not one. */
  function number ({ label, value, min, max, step = 'any', onChange, disabled = false }) {
    const id = uid()
    const input = el('input', { id, type: 'number', inputmode: 'decimal', min, max, step, value: String(value),
      disabled, onchange: () => onChange(input.value.trim() === '' ? NaN : Number(input.value), input) })
    return el('div', { class: 'field' }, el('label', { for: id }, label), input)
  }

  function check ({ label, checked, onChange, disabled = false }) {
    const input = el('input', { type: 'checkbox', checked, disabled, onchange: () => onChange(input.checked) })
    return el('label', { class: 'check' }, input, el('span', null, label))
  }

  function button (label, onClick, { kind = '', disabled = false } = {}) {
    return el('button', { type: 'button', class: `button ${kind}`.trim(), disabled, onclick: onClick }, label)
  }

  // ---- the parts ------------------------------------------------------------------------------------------------
  function header () {
    $('#brand').textContent = t('page.title')
    $('#nav-architecture').textContent = t('nav.architecture')
    const switcher = $('#language')
    switcher.textContent = t('lang.other')
    switcher.setAttribute('aria-label', t('lang.label'))
    switcher.setAttribute('lang', chinese() ? 'en' : 'zh-CN')
  }

  function intro () {
    return el('section', { class: 'intro' },
      el('h1', null, t('intro.title')),
      el('p', null, t('intro.text')),
      el('p', { class: 'note' }, t('intro.stop')))
  }

  function files () {
    const input = el('input', { type: 'file', id: 'pick', class: 'visually-hidden', multiple: true,
      onchange: () => { openFiles([...input.files]).finally(() => { input.value = '' }) } })
    const zone = el('div', { class: 'drop', id: 'drop' },
      el('p', { class: 'drop-title' }, t('drop.title')),
      el('label', { class: 'button primary', for: 'pick' }, t('drop.pick')), input,
      el('p', { class: 'hint' }, t('drop.hint')))
    const opened = KINDS.filter(kind => state.files[kind]).map(kind => {
      const file = state.files[kind]
      let space = null
      if (kind === 'memory') {
        const spaces = T.spaces(file.db)
        const id = uid()
        space = spaces.length > 1
          ? el('span', { class: 'space' }, el('label', { for: id }, t('file.space')),
            el('select', { id, onchange: event => {
              state.space = event.target.value
              refresh('memory').then(render)
            } },
              spaces.map(name => el('option', { value: name, selected: name === state.space }, name))))
          : el('span', { class: 'space' }, `${t('file.space')}: ${state.space ?? '—'}`)
      }
      return el('div', { class: 'file' },
        el('span', { class: 'file-kind' }, kind === 'gut' ? t('settings.title') : t('file.memory')),
        el('span', { class: 'file-name' }, file.name),
        space,
        text('span', { class: 'file-changes' }, () => file.changes.size ? t('settings.unsaved',
          { count: file.changes.size }) : ''),
        button(t('file.close'), () => closeFile(kind), { kind: 'quiet' }))
    })
    if (state.starter) {
      opened.push(el('div', { class: 'file' },
        el('span', { class: 'file-kind' }, t('file.starter')),
        el('span', { class: 'file-name' }, state.starter.name),
        button(t('file.close'), () => closeFile('starter'), { kind: 'quiet' })))
    }
    const status = KINDS.some(kind => state.files[kind]) ? null : statusLine() // (else in the save bar)
    return el('section', { class: 'files' }, zone, opened.length ? el('div', { class: 'opened' }, opened) : null,
      status)
  }

  function growing () {
    const gut = state.gut
    const base = () => state.base.gut
    return card(t('settings.grown'),
      text('p', { class: 'lead' }, () => t('settings.age', { age: Math.round(state.gut.age),
        grown: percent(state.gut.grown), learning: percent(state.gut.learning) })),
      el('div', { class: 'row' },
        number({ label: t('age.label'), value: gut.age, min: 0, step: 1, disabled: !gut.hasHeart,
          onChange: (value, input) => {
            if (!(Number.isFinite(value) && value >= 0)) {
              say(t('error.change', { error: t('error.age') }), true)
              input.value = String(state.gut.age)
              return savebar()
            }
            edit('gut', 'age', db => T.setAge(db, value), { same: () => state.gut.age === base().age })
          } }),
        button(t('settings.young'), () => {
          if (window.confirm(t('settings.youngConfirm'))) {
            edit('gut', 'age', db => T.setAge(db, 0), { same: () => state.gut.age === base().age, structural: true })
          }
        }, { disabled: !gut.hasHeart })),
      hint(gut.hasHeart ? t('age.hint') : t('error.noHeart')),
      el('div', { class: 'row' },
        number({ label: t('settings.tau'), value: gut.tau, step: 'any',
          onChange: (value, input) => {
            if (!(Number.isFinite(value) && value > 0)) {
              say(t('error.change', { error: t('settings.badTau') }), true)
              input.value = String(state.gut.tau)
              return savebar()
            }
            edit('gut', 'tau', db => T.configure(db, { tau: value }), { same: () => state.gut.tau === base().tau })
          } })),
      hint(t('settings.tauHint')),
      check({ label: t('settings.heartLock'), checked: gut.locked, onChange: locked =>
        edit('gut', 'locked', db => T.configure(db, { locked }), { same: () => state.gut.locked === base().locked }) }),
      hint(t('settings.heartLockHint')))
  }

  function sensitivity () {
    const gut = state.gut
    const dial = slider({ label: t('settings.sensitivity'), value: gut.sensitivity, low: -1, high: 1, step: 0.05,
      show: value => signed(value), wide: true,
      onChange: value => edit('gut', 'sensitivity', db => T.configure(db, { sensitivity: value }),
        { same: () => state.gut.sensitivity === state.base.gut.sensitivity }) })
    dial.input.setAttribute('aria-describedby', 'sensitivity-ends')
    return card(t('settings.sensitivity'),
      dial.node,
      el('div', { class: 'ends', id: 'sensitivity-ends' }, el('span', null, `−1 ${t('settings.dull')}`),
        el('span', null, `${t('settings.keen')} +1`)),
      hint(t('settings.sensitivityHint')))
  }

  // One colour for each of her 14 bars, as the DSH plugin's panel has them: the first end of a bar a deeper shade,
  // the second (and a one-sided bar's only end) a lighter one, stepped for each theme.
  const COLOURS = {
    dark: {
      deep: ['#ca5551', '#12976b', '#9167ca', '#a57710', '#128eaa', '#c35481', '#54932d', '#6676d8', '#c36109',
        '#13938f', '#b05bab', '#888510', '#1485d4', '#0f919c'],
      light: ['#ffaba3', '#72ddae', '#d0b4fd', '#ecbb64', '#58d6f9', '#fea6c5', '#a1d687', '#b2c0ff', '#fdb080',
        '#4fddd7', '#f0a7ea', '#cbca69', '#91caff', '#4ddae9']
    },
    light: {
      deep: ['#972e2d', '#0c6849', '#674098', '#735100', '#0b6276', '#912d59', '#316802', '#424da5', '#884204',
        '#0f6562', '#81357d', '#5d5b0a', '#0a5c94', '#0d646c'],
      light: ['#ce766f', '#44a87f', '#9f81cb', '#b68a37', '#22a2c0', '#c97493', '#73a25b', '#7d8cd7', '#c87e4d',
        '#0ca8a3', '#b878b3', '#99973d', '#5498d3', '#05a5b3']
    }
  }
  const darkScheme = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
  const barOf = end => T.BARS.find(([, , left, right]) => (left && left[0] === end) || right[0] === end)
  function endColour (end) {
    const index = T.BARS.indexOf(barOf(end))
    const shades = COLOURS[darkScheme?.matches ? 'dark' : 'light']
    const left = T.BARS[index][2]
    return (left && left[0] === end ? shades.deep : shades.light)[index]
  }
  const swatch = end => el('span', { class: 'swatch', style: `background: ${endColour(end)}`, 'aria-hidden': 'true' })

  function lockIcon (title) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svg.setAttribute('viewBox', '0 0 16 16')
    svg.setAttribute('class', 'lock-icon')
    svg.setAttribute('role', 'img')
    svg.setAttribute('aria-label', title)
    svg.innerHTML = '<title></title><rect x="3" y="7" width="10" height="7.5" rx="1.6" fill="currentColor"/>' +
      '<path d="M5.2 7V5.2a2.8 2.8 0 0 1 5.6 0V7" fill="none" stroke="currentColor" stroke-width="1.7"/>'
    svg.querySelector('title').textContent = title
    return svg
  }

  /** A dot that follows whether something is changed and not saved. */
  const changedMark = changed => live(el('span', { class: 'mark' }), node => {
    const on = changed()
    node.textContent = on ? '•' : ''
    node.title = on ? t('mark.changed') : ''
    node.setAttribute('aria-label', on ? t('mark.changed') : '')
  })

  // ---- her star map ---------------------------------------------------------------------------------------------
  // As the DSH plugin's panel shows it: flat or in 3D (the browser keeps which); in 3D it turns by a drag, and slowly by
  // itself a few seconds later while it is in view (not for reduced motion).
  const SKY = 'mneme-llm-tune-map3d'
  const TURNING = 0.12 // radians a second it turns by itself
  const RESTS = 3000 // milliseconds after a drag before it does
  const sky = { three: false, turn: { yaw: 0.6, pitch: -0.32 }, drag: null, rested: 0, stop: null }
  try { sky.three = localStorage.getItem(SKY) === '3d' } catch {}

  function skyLook (canvas) {
    return { dark: Boolean(darkScheme?.matches), ink: getComputedStyle(canvas).color, names: T.ENDS.map(endName),
      colours: T.ENDS.map(endColour) }
  }

  function starMap () {
    const map = state.map
    if (!map) {
      return card(t('map.title'), state.mapError ? el('p', { class: 'status error' }, t('error.read',
        { name: state.files.gut?.name ?? '', error: state.mapError })) : hint(t('map.none')))
    }
    const canvas = el('canvas', { class: sky.three ? 'sky turning' : 'sky', role: 'img', 'aria-label': t('map.caption') })
    const paint = () => {
      if (!state.map || !canvas.isConnected) return
      if (sky.three) S.drawRound(canvas, state.map, skyLook(canvas), sky.turn)
      else S.drawFlat(canvas, state.map, skyLook(canvas))
    }
    live(canvas, paint)
    canvas.addEventListener('pointerdown', event => {
      if (!sky.three) return
      sky.drag = { x: event.clientX, y: event.clientY }
      try { canvas.setPointerCapture(event.pointerId) } catch {} // (a pointer the page no longer holds)
    })
    canvas.addEventListener('pointermove', event => {
      const held = sky.drag
      if (!sky.three || !held) return
      const dx = event.clientX - held.x, dy = event.clientY - held.y
      held.x = event.clientX
      held.y = event.clientY
      sky.turn.yaw += dx * 0.01
      sky.turn.pitch = Math.max(-1.4, Math.min(1.4, sky.turn.pitch + dy * 0.01))
      paint()
    })
    const up = () => {
      sky.drag = null
      sky.rested = Date.now()
    }
    canvas.addEventListener('pointerup', up)
    canvas.addEventListener('pointercancel', up)
    // drawn once it is on the page and has a size, again when the size changes, and turning by itself in 3D
    const resized = typeof ResizeObserver === 'function' ? new ResizeObserver(paint) : null
    resized?.observe(canvas)
    let frame = null, last = null, painted = 0, seen = true
    const watched = typeof IntersectionObserver === 'function'
      ? new IntersectionObserver(entries => { seen = entries.some(entry => entry.isIntersecting) }) : null
    watched?.observe(canvas)
    const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const tick = at => {
      if (last !== null && seen && !document.hidden && !sky.drag && Date.now() - sky.rested > RESTS) {
        sky.turn.yaw += TURNING * Math.min(0.1, (at - last) / 1000)
        if (at - painted >= 33) { // (about 30 a second: it turns slowly)
          paint()
          painted = at
        }
      }
      last = at
      frame = requestAnimationFrame(tick)
    }
    if (sky.three && !still && window.requestAnimationFrame) frame = requestAnimationFrame(tick)
    if (!resized) requestAnimationFrame(paint)
    sky.stop = () => {
      resized?.disconnect()
      watched?.disconnect()
      if (frame !== null) cancelAnimationFrame(frame)
    }
    const choose = three => {
      if (three === sky.three) return
      sky.three = three
      try { localStorage.setItem(SKY, three ? '3d' : '2d') } catch {}
      render()
    }
    const views = el('div', { class: 'sky-switch', role: 'group', 'aria-label': t('map.view') },
      [false, true].map(three => el('button', { type: 'button', class: sky.three === three ? 'on' : '',
        'aria-pressed': String(sky.three === three), onclick: () => choose(three) }, three ? '3D' : '2D')))
    const counts = t(map.probed >= S.LEAST ? 'map.counts' : 'map.born',
      { stars: map.stars.length, rows: map.rows, probed: map.probed })
    const birth = map.birth === 'unknown' ? t('map.unknown') : map.birth === 'blank' ? t('map.blank') : null
    return el('section', { class: 'card sky-card' },
      el('div', { class: 'sky-head' }, el('h2', null, t('map.title')), views),
      canvas,
      sky.three ? hint(t('map.turn')) : null,
      birth ? el('p', { class: map.birth === 'unknown' ? 'sky-note' : 'hint' }, birth) : null,
      hint(counts),
      map.waiting ? hint(t('map.slept', { waiting: map.waiting })) : null,
      hint(t('map.caption')))
  }

  // ---- a list and one editor ------------------------------------------------------------------------------------------
  /** A list to choose from (its own scroll) beside the editor of what is chosen; stacked on a phone. */
  function picker (name, list, editor) {
    return el('div', { class: 'picker' },
      el('div', { class: 'pick-list', 'data-scroll': name }, list),
      el('div', { class: 'pick-editor', 'aria-live': 'polite' }, editor))
  }

  /** Choose something: the page again, with the focus where it was. */
  function choose (kind, value) {
    state.pick[kind] = value
    render()
    refocus(`${kind}:${value}`)
  }
  function refocus (key) {
    const found = document.querySelector(`[data-pick="${CSS.escape(key)}"]`)
    if (found) found.focus()
  }

  function pickRow (kind, value, on, ...children) {
    return el('button', { type: 'button', class: on ? 'pick-row on' : 'pick-row', 'aria-pressed': String(on),
      'data-pick': `${kind}:${value}`, onclick: () => choose(kind, value) }, children)
  }

  /** A bar lately against usual: two-sided from the middle, one-sided from the left. */
  function barView (name) {
    const fill = el('span', { class: 'bar-fill' }), tick = el('span', { class: 'bar-tick' })
    const [, , left, right] = T.BARS.find(item => item[0] === name)
    const two = Boolean(left)
    const track = el('div', { class: two ? 'bar-track two' : 'bar-track' }, two ? el('span', { class: 'bar-middle' })
      : null, fill, tick)
    live(track, () => {
      const bar = state.gut.bars.find(item => item.bar === name)
      const at = value => two ? 50 + Math.max(-1, Math.min(1, value)) * 50 : Math.max(0, Math.min(1, value)) * 100
      const from = two ? Math.min(50, at(bar.lately)) : 0, to = two ? Math.max(50, at(bar.lately)) : at(bar.lately)
      fill.style.left = `${from}%`
      fill.style.width = `${Math.max(0.5, to - from)}%`
      fill.style.background = endColour(two && bar.lately < 0 ? left[0] : right[0])
      tick.style.left = `${at(bar.usual)}%`
      track.title = `${t('lately', { value: signed(bar.lately) })} · ${t('usual', { value: signed(bar.usual) })}`
    })
    return el('div', { class: 'bar' },
      el('span', { class: 'bar-end' }, left ? endName(left[0]) : ''), track,
      el('span', { class: 'bar-end right' }, endName(right[0])))
  }

  function barTitle (name) {
    const named = name === 'composure' ? t('san') : name === 'pride' ? t('self-esteem') : ''
    return named ? `${barName(name)} · ${named}` : barName(name)
  }

  // Each feeling: the 26 ends by bar, and the one chosen.
  function feelings () {
    const ends = () => Object.fromEntries(state.gut.ends.map(item => [item.end, item]))
    const baseEnds = () => Object.fromEntries(state.base.gut.ends.map(item => [item.end, item]))
    const chosen = T.ENDS.includes(state.pick.end) ? state.pick.end : T.ENDS[0]
    const changed = end => ends()[end].nature !== baseEnds()[end].nature || ends()[end].now !== baseEnds()[end].now
    const note = end => {
      const found = ends()[end]
      return [found.nature ? `${t('settings.nature')} ${signed(found.nature, 1)}` : '',
        found.now ? `${t('settings.now')} ${signed(found.now)}` : ''].filter(Boolean).join(' · ')
    }
    const list = T.BARS.map(([name, , left, right]) => el('div', { class: 'pick-group' },
      el('div', { class: 'pick-group-title' }, barTitle(name)),
      [left, right].filter(Boolean).map(([end]) => pickRow('end', end, end === chosen,
        swatch(end), el('span', { class: 'pick-name' }, endName(end)), changedMark(() => changed(end)),
        text('span', { class: 'pick-note' }, () => note(end))))))
    const bar = barOf(chosen)[0]
    const now = ends()[chosen]
    const editor = [
      el('h3', { class: 'editor-title' }, swatch(chosen), endName(chosen)),
      el('div', { class: 'group-head' }, el('span', { class: 'meta' }, barTitle(bar)),
        text('span', { class: 'meta' }, () => {
          const found = state.gut.bars.find(item => item.bar === bar)
          return `${t('lately', { value: signed(found.lately) })} · ${t('usual', { value: signed(found.usual) })}`
        })),
      barView(bar),
      slider({ label: t('settings.nature'), value: now.nature, low: -6, high: 6, step: 0.1, wide: true,
        show: value => signed(value, 1), onChange: nature => edit('gut', `nature:${chosen}`,
          db => T.tune(db, chosen, { nature }), { same: () => ends()[chosen].nature === baseEnds()[chosen].nature }) }).node,
      slider({ label: t('settings.now'), value: now.now, low: -1, high: 1, step: 0.05, wide: true,
        show: value => signed(value), onChange: value => edit('gut', `now:${chosen}`,
          db => T.tune(db, chosen, { now: value }), { same: () => ends()[chosen].now === baseEnds()[chosen].now }) }).node
    ]
    return card(t('settings.tunes'),
      hint(t('settings.tunesHint')),
      hint(`${t('bars.title')}: ${t('bars.hint')}`),
      picker('ends', list, editor))
  }

  // People: each once, with her memory's half and her gut's half; the one chosen in the editor.
  const memoryOf = subject => state.memory?.people.find(item => item.subject === subject) || null
  const gutOf = (view, subject) => view?.people.find(item => item.subject === subject) || null
  const personKey = (subject, what) => `person:${subject}:${what}`
  const closenessKey = subject => `${state.space}:person:${subject}`
  function personChanged (subject) {
    const gut = state.files.gut?.changes, memory = state.files.memory?.changes
    return Boolean((gut && [...gut.keys()].some(key => key.startsWith(`person:${subject}:`))) ||
      (memory && memory.has(closenessKey(subject))))
  }

  function people () {
    const subjects = [...new Set([...(state.memory?.people || []).map(item => item.subject),
      ...(state.gut?.people || []).map(item => item.subject)])]
    subjects.sort((a, b) => (memoryOf(b)?.closeness ?? -1) - (memoryOf(a)?.closeness ?? -1) ||
      (gutOf(state.gut, b)?.lessons ?? 0) - (gutOf(state.gut, a)?.lessons ?? 0) || (a < b ? -1 : 1))
    const chosen = subjects.includes(state.pick.person) ? state.pick.person : subjects[0]
    const about = [
      state.memory ? [t('person.closeness'), t('person.closenessHint')] : null,
      state.gut ? [t('people.weight'), t('person.weightHint')] : null
    ].filter(Boolean)
    const list = subjects.map(subject => pickRow('person', subject, subject === chosen,
      el('span', { class: 'pick-name' }, subject), changedMark(() => personChanged(subject)),
      live(el('span', { class: 'pick-note' }), node => {
        const memory = memoryOf(subject), gut = gutOf(state.gut, subject)
        node.replaceChildren(...[
          memory ? el('span', null, `${roleName(memory.role)} ${memory.closeness.toFixed(0)}`) : null,
          memory && memory.locked !== null ? lockIcon(t('people.holdCloseness')) : null,
          memory && gut?.known ? el('span', null, ' · ') : null,
          gut?.known ? el('span', null, t('lessons', { lessons: gut.lessons })) : null,
          gut?.locked ? lockIcon(t('people.lock')) : null].filter(Boolean))
      })))
    const editor = chosen ? [
      el('h3', { class: 'editor-title' }, chosen),
      text('p', { class: 'meta' }, () => {
        const memory = memoryOf(chosen), gut = gutOf(state.gut, chosen)
        const parts = []
        if (memory) parts.push(`${roleName(memory.role)} · ${memory.closeness.toFixed(1)}`)
        if (gut?.known) parts.push(t('people.summary', { lessons: gut.lessons, weight: percent(gut.weight) }))
        return parts.join(' · ')
      }),
      state.memory ? memoryHalf(chosen) : null,
      state.gut ? gutHalf(chosen) : null
    ] : el('p', { class: 'meta' }, t('people.none'))
    return card(t('people.title'),
      hint(t('people.hint')),
      state.memory ? memorySettings() : null,
      el('dl', { class: 'about' }, about.map(([term, words]) => [el('dt', null, term), el('dd', null, words)])),
      subjects.length ? picker('people', list, editor) : el('p', { class: 'meta' }, t('people.none')))
  }

  function memorySettings () {
    const space = state.space
    const base = () => state.base.memory[space]
    return el('div', { class: 'row settings' },
      el('div', null,
        number({ label: t('people.liking'), value: state.memory.liking, min: 0, max: 100, step: 'any',
          onChange: value => edit('memory', `${space}:liking`, db => T.setLiking(db, space, value),
            { same: () => state.memory.liking === base().liking }) }),
        hint(t('people.likingHint'))),
      el('div', null,
        number({ label: t('people.fadeDays'), value: state.memory.fadeDays, min: 0, max: 1000000, step: 'any',
          onChange: value => edit('memory', `${space}:fade_days`, db => T.setFadeDays(db, space, value),
            { same: () => state.memory.fadeDays === base().fadeDays }) }),
        hint(t('people.fadeDaysHint'))))
  }

  function memoryHalf (subject) {
    const space = state.space
    const found = memoryOf(subject)
    const head = el('h4', null, t('person.memory'))
    if (!found) return el('div', { class: 'half' }, head, el('p', { class: 'meta' }, t('people.noRole')))
    const key = closenessKey(subject)
    const shown = found.locked ?? found.closeness
    // (locked where it is shown: one decimal, within the band)
    let current = Math.min(found.ceiling, Math.max(found.floor, Math.round(shown * 10) / 10))
    const hold = check({ label: t('people.holdCloseness'), checked: found.locked !== null, onChange: on =>
      edit('memory', key, db => on ? T.lockCloseness(db, space, subject, current)
        : T.unlockCloseness(db, space, subject)) })
    const dial = slider({ label: t('people.closeness', { role: roleName(found.role), floor: found.floor,
      ceiling: found.ceiling }), value: shown, low: found.floor, high: found.ceiling, step: 1,
    show: value => Number(value).toFixed(1), wide: true, onChange: value => {
      current = value
      const locked = hold.querySelector('input').checked
      edit('memory', key, db => locked ? T.lockCloseness(db, space, subject, value)
        : T.setCloseness(db, space, subject, value))
    } })
    dial.input.addEventListener('input', () => { current = stepped(Number(dial.input.value), 1) })
    return el('div', { class: 'half' }, head, dial.node,
      found.locked === null ? el('p', { class: 'meta' }, t(found.fades ? 'person.fades' : 'person.stays')) : null, hold)
  }

  function gutHalf (subject) {
    const found = gutOf(state.gut, subject) || { subject, known: false, set: null, learned: 0, locked: false,
      nudge: {} }
    const base = () => gutOf(state.base.gut, subject) || { set: null, locked: false, nudge: {} }
    const now = () => gutOf(state.gut, subject) || { set: null, locked: false, nudge: {}, learned: 0 }
    const weight = slider({ label: t('people.weight'), value: found.set ?? found.learned, low: 0, high: 1, step: 0.01,
      show: value => `${percent(value)}%`, disabled: found.set === null, wide: true,
      onChange: value => edit('gut', personKey(subject, 'weight'), db => T.tunePerson(db, subject, { weight: value }),
        { same: () => now().set === base().set }) })
    const byHand = check({ label: t('people.byHand'), checked: found.set !== null, onChange: on => {
      weight.input.disabled = !on
      edit('gut', personKey(subject, 'weight'), db => T.tunePerson(db, subject,
        { weight: on ? stepped(Number(weight.input.value), 0.01) : 'learned' }),
      { same: () => now().set === base().set, after: () => {
        if (!on) {
          weight.input.value = String(now().learned)
          weight.out.textContent = `${percent(now().learned)}%`
        }
      } })
    } })
    // her feelings with them: one end at a time, chosen from a list; the ends already nudged as chips
    const nudged = () => T.ENDS.filter(end => now().nudge[end])
    const pickedEnd = T.ENDS.includes(state.pick.personEnd[subject]) ? state.pick.personEnd[subject]
      : nudged()[0] ?? T.ENDS[0]
    const chooseEnd = (end, focus) => {
      state.pick.personEnd[subject] = end
      render()
      refocus(focus)
    }
    const endId = uid()
    const ends = el('select', { id: endId, 'data-pick': `personEnd:${subject}:${pickedEnd}`,
      onchange: event => chooseEnd(event.target.value, `personEnd:${subject}:${event.target.value}`) },
    T.BARS.map(([name, , left, right]) => el('optgroup', { label: barName(name) },
      [left, right].filter(Boolean).map(([end]) => el('option', { value: end, selected: end === pickedEnd },
        endName(end))))))
    const nudge = slider({ label: t('settings.nature'), value: Number(found.nudge[pickedEnd] || 0), low: -6, high: 6,
      step: 0.1, wide: true, show: value => signed(value, 1),
      onChange: nature => edit('gut', personKey(subject, `nudge:${pickedEnd}`),
        db => T.tunePerson(db, subject, { end: pickedEnd, nature }),
        { same: () => Number(now().nudge[pickedEnd] || 0) === Number(base().nudge[pickedEnd] || 0) }) })
    const chips = live(el('div', { class: 'chips' }), node => node.replaceChildren(
      ...(nudged().length ? [el('span', { class: 'meta' }, t('person.nudged'))] : []),
      ...nudged().map(end => el('button', { type: 'button', class: end === pickedEnd ? 'chip on' : 'chip',
        'data-pick': `chip:${subject}:${end}`, onclick: () => chooseEnd(end, `chip:${subject}:${end}`) },
      swatch(end), `${endName(end)} ${signed(now().nudge[end], 1)}`))))
    const forgettable = Boolean(gutOf(state.gut, subject))
    return el('div', { class: 'half' },
      el('h4', null, t('person.gut')),
      found.known ? null : el('p', { class: 'meta' }, t('person.notMet')),
      byHand, weight.node,
      text('p', { class: 'meta' }, () => t('person.weightLearned', { weight: percent(now().learned) })),
      check({ label: t('people.lock'), checked: found.locked, onChange: locked => edit('gut',
        personKey(subject, 'lock'), db => T.tunePerson(db, subject, { locked }),
        { same: () => now().locked === base().locked }) }),
      el('div', { class: 'field tunes' }, el('label', { for: endId }, t('people.tunes')), ends),
      nudge.node,
      hint(t('people.tunesHint')),
      chips,
      forgettable ? el('div', { class: 'actions' }, button(t('people.forget'), () => {
        if (!window.confirm(`${t('people.forgetConfirm', { who: subject })} ${t('person.memoryKept')}`)) return
        edit('gut', personKey(subject, 'forget'), db => T.forget(db, subject), { structural: true,
          after: gone => say(t('person.forgotten', { who: subject, count: gone })) })
      }, { kind: 'danger' })) : null)
  }

  // Sides: her sides as tags, a name to add and the chosen one to remove, and the chosen one's editor below.
  function sides () {
    const gut = state.gut
    const names = [...gut.sides.map(item => item.name), ...[...state.pending.keys()]
      .filter(name => !gut.sides.some(item => item.name === name))]
    const chosen = names.includes(state.pick.side) ? state.pick.side : names[0] ?? null
    const tags = el('div', { class: 'tags' }, names.map(name => {
      const pending = !gut.sides.some(item => item.name === name)
      const classes = ['tag', name === chosen ? 'on' : '', pending ? 'pending' : ''].filter(Boolean).join(' ')
      return el('button', { type: 'button', class: classes, 'aria-pressed': String(name === chosen),
        'data-pick': `side:${name}`, title: pending ? t('sides.needsWhat') : null,
        onclick: () => choose('side', name) },
      name, gut.side?.name === name ? lockIcon(t('sides.locked')) : null,
      changedMark(() => sideChanged(name)))
    }))
    const have = new Set(names)
    const addId = uid()
    const adding = el('select', { id: addId }, el('option', { value: '' }, t('sides.pick')),
      T.NAMES.filter(name => !have.has(name)).map(name => el('option', { value: name }, name)))
    const add = () => {
      if (!adding.value) return refuse(t('sides.pick'))
      state.pending.set(adding.value, T.GROWS)
      choose('side', adding.value)
      const sentence = document.querySelector('.side-editor textarea')
      if (sentence) sentence.focus()
    }
    const status = text('p', { class: 'lead' }, () => {
      const view = state.gut
      if (view.side && view.sides.some(item => item.name === view.side.name)) {
        return t('sides.lockedIn', { side: view.side.name })
      }
      if (view.holding.length && view.days > 0) return t('grown.side', { side: view.holding[0], days: view.days })
      return view.sides.length ? t('sides.next') : ''
    })
    return card(t('sides.title'),
      hint(t('sides.hint')),
      status,
      el('div', { class: 'tag-row' },
        names.length ? tags : el('p', { class: 'meta' }, t('sides.none')),
        el('div', { class: 'tag-controls' },
          el('label', { class: 'visually-hidden', for: addId }, t('sides.pick')), adding,
          button(t('sides.write'), add),
          button(t('sides.drop'), () => remove(chosen), { kind: 'danger', disabled: !chosen }))),
      chosen ? el('div', { class: 'side-editor pick-editor' }, sideEditor(chosen)) : null)
  }

  function sideChanged (name) {
    if (state.pending.has(name)) return true
    const changes = state.files.gut?.changes
    return Boolean(changes && [...changes.keys()].some(key => key === `side:${name}` || key === `own:${name}`) ||
      (changes?.has('side.lock') && (state.gut.side?.name === name || state.base.gut.side?.name === name)))
  }

  function refuse (words) {
    say(t('error.change', { error: words }), true)
    savebar()
  }

  function sideEditor (name) {
    const real = state.gut.sides.find(item => item.name === name)
    const base = () => state.base.gut.sides.find(item => item.name === name)
    const now = () => state.gut.sides.find(item => item.name === name)
    const locked = state.gut.side?.name === name
    const sentenceId = uid()
    const sentence = el('textarea', { id: sentenceId, rows: 3, value: real ? real.what : '', onchange: () => {
      if (real) {
        edit('gut', `side:${name}`, db => T.writeSide(db, name, sentence.value),
          { same: () => now()?.what === base()?.what })
      } else if (sentence.value.trim()) {
        const own = state.pending.get(name)
        edit('gut', `side:${name}`, db => {
          T.writeSide(db, name, sentence.value)
          T.sideWeight(db, name, own)
        }, { structural: true, after: () => state.pending.delete(name) })
      }
    } })
    const weight = number({ label: t('sides.weight'), value: real ? real.own : state.pending.get(name), min: 0,
      step: 'any', onChange: (value, input) => {
        if (!(Number.isFinite(value) && value >= 0)) {
          input.value = String(real ? now().own : state.pending.get(name))
          return refuse(t('error.own'))
        }
        if (real) edit('gut', `own:${name}`, db => T.sideWeight(db, name, value), { same: () => now()?.own === base()?.own })
        else state.pending.set(name, value)
      } })
    const sameLock = () => JSON.stringify([state.gut.side, state.gut.held]) ===
      JSON.stringify([state.base.gut.side, state.base.gut.held])
    const lock = check({ label: t('sides.lockThis'), checked: locked, disabled: !real, onChange: on =>
      edit('gut', 'side.lock', db => on ? T.lockSide(db, name, 1) : T.unlockSide(db),
        { same: sameLock, structural: true }) })
    const often = locked
      ? slider({ label: t('sides.often'), value: state.gut.side.often, low: 0, high: 1, step: 0.05, wide: true,
        show: value => value.toFixed(2), onChange: value => edit('gut', 'side.lock', db => T.lockSide(db, name, value),
          { same: sameLock }) })
      : null
    const badge = state.gut.holding.includes(name) && !locked ? el('span', { class: 'badges' }, t('side.current')) : null
    return [
      el('div', { class: 'side-head' }, el('h3', null, name), badge),
      real ? null : el('p', { class: 'status error' }, t('sides.needsWhat')),
      el('label', { class: 'label', for: sentenceId }, t('sides.what')), sentence,
      el('div', { class: 'row' }, weight),
      hint(t('side.weightHint')),
      lock,
      often ? often.node : null,
      often ? hint(t('sides.oftenHint')) : null,
      locked ? hint(t('side.unlockHint')) : null
    ]
  }

  function remove (name) {
    if (!name) return
    if (state.pending.has(name) && !state.gut.sides.some(item => item.name === name)) {
      state.pending.delete(name)
      return render()
    }
    if (!window.confirm(t('side.dropConfirm', { side: name }))) return
    edit('gut', `drop:${name}`, db => T.dropSide(db, name), { structural: true })
  }

  function statusLine () {
    return el('span', { class: state.status?.error ? 'status error' : 'status', role: 'status' },
      state.status?.text || '')
  }

  function savebar () {
    const bar = $('#savebar')
    const open = KINDS.some(kind => state.files[kind])
    bar.hidden = !open
    if (!open) return
    const changes = count()
    const blocked = [...state.pending.keys()]
    bar.replaceChildren(
      el('span', { class: changes ? 'changed' : 'meta' }, changes ? t('settings.unsaved', { count: changes })
        : t('settings.none')),
      blocked.length ? el('span', { class: 'status error', role: 'status' },
        `${blocked.join(chinese() ? '、' : ', ')}${chinese() ? '：' : ': '}${t('sides.needsWhat')}`) : statusLine(),
      el('span', { class: 'spacer' }),
      button(t('settings.discard'), discard, { disabled: !changes }),
      button(t('settings.save'), save, { kind: 'primary', disabled: !changes || blocked.length > 0 }))
  }

  function render () {
    updaters = []
    document.documentElement.lang = chinese() ? 'zh-CN' : 'en'
    document.title = `${t('page.title')} · mneme-llm`
    header()
    sky.stop?.()
    sky.stop = null
    const parts = [intro(), files()]
    if (state.gut) parts.push(starMap(), growing(), sensitivity(), feelings())
    if (state.gut || state.memory) parts.push(people())
    if (state.gut) parts.push(sides())
    else if (state.memory) parts.push(el('p', { class: 'hint center' }, t('needGut')))
    const scrolled = Object.fromEntries([...document.querySelectorAll('[data-scroll]')]
      .map(node => [node.dataset.scroll, node.scrollTop]))
    $('#main').replaceChildren(...parts)
    for (const node of document.querySelectorAll('[data-scroll]')) node.scrollTop = scrolled[node.dataset.scroll] || 0
    savebar()
  }

  // ---- starting ---------------------------------------------------------------------------------------------------
  darkScheme?.addEventListener?.('change', () => render())
  $('#language').addEventListener('click', () => {
    language = chinese() ? 'en' : 'zh'
    try { localStorage.setItem(KEPT, language) } catch {}
    render()
  })
  window.addEventListener('dragover', event => {
    event.preventDefault()
    document.body.classList.add('dragging')
  })
  window.addEventListener('dragleave', event => {
    if (!event.relatedTarget) document.body.classList.remove('dragging')
  })
  window.addEventListener('drop', event => {
    event.preventDefault()
    document.body.classList.remove('dragging')
    if (event.dataTransfer?.files?.length) openFiles([...event.dataTransfer.files])
  })
  window.addEventListener('beforeunload', event => {
    if (count()) {
      event.preventDefault()
      event.returnValue = ''
    }
  })
  sqlReady.catch(error => { say(t('error.sql', { error: errorText(error) }), true); render() })
  window.tuner = { open: openFile, state, sky } // (for a script, or a look from the console)
  render()
})()

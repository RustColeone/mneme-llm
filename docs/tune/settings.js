// Her settings as one page in four tabs, Her · People · Memory · Gut, the same wherever she is kept: the DSH plugin's
// page under Plugins (plugin/client.js has this file word for word), a host's own web page, and mneme-llm's tuner. A
// host gives it her settings and takes a change, in one shape (plugin/panel.js: `settings` is what `load` gives, and
// `settle` takes what `save` is handed); a part the host does not have is null in what it gives, and the page leaves
// it out. Nothing is changed until Save, which sends every tab's changes at once; starting over, and making her young
// again, go at once, each after a question. No framework: it draws itself into the element it is given.
//
//     const page = MnemeSettings.mount(element, { load, save, language: 'en' | 'zh', starmap, dark, words, confirm })
//     page.reload()   page.destroy()
//
// `starmap(box, view)`, if given, draws her star map into a box on the Gut tab (and may return a function that stops
// it); `dark()` says whether the page is dark (for the colours of her feelings); `words` are a host's own over these.
// A host's own settings come in its view as `rows`, each { tab, key, kind: bool | choice | number | text | info, label,
// hint, group (each { en, zh }), value; options for a choice, min, max and step for a number }.
;(function (root, make) {
  if (typeof module === 'object' && module && module.exports) module.exports = make()
  else root.MnemeSettings = make()
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict'

  const TABS = ['her', 'people', 'memory', 'gut']
  const KEPT = 'mneme-settings.tab' // (the browser keeps which tab was open)
  const NATURE = 6 // a nature goes from -6 to 6 (`NATURE` in mneme-llm's gut)
  const GROWS = 6.0 // a new side's weight when drawn (`GROWS` there)
  const LANGUAGES = ['auto', 'english', 'chinese', 'cantonese', 'japanese']

  // One colour for each of her 14 bars, in their order; the first end of a bar a deeper shade and the second a lighter
  // one, for each theme (as her star map draws them).
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

  const EN = {
    'page.intro': 'Her settings, in four tabs. A save is used at once and kept.',
    'page.loading': 'Reading her settings…',
    'page.unreachable': 'Her settings cannot be reached ({error}).',
    'tab.her': 'Her',
    'tab.people': 'People',
    'tab.memory': 'Memory',
    'tab.gut': 'Gut',
    you: 'you',
    // Her
    'her.title': 'Who she is',
    'her.name': 'Her name',
    'her.nameHint': '',
    'her.language': 'The language she answers in',
    'her.languageHint': 'Whatever people write in. Each person\'s own: she answers each in theirs.',
    'language.auto': 'Each person\'s own',
    'language.english': 'English',
    'language.chinese': 'Chinese',
    'language.cantonese': 'Cantonese',
    'language.japanese': 'Japanese',
    'her.zone': 'Her time zone',
    'her.zoneHint': 'Such as UTC+8 or Asia/Shanghai; empty, the machine\'s. Her days of talking are counted in it.',
    'card.title': 'Character Card',
    'card.hint': 'Who she is, in your words. On, it is in her system prompt, which every call carries.',
    'card.placeholder': 'You are…',
    'card.on': 'In her system prompt',
    'card.drop': 'Take it away',
    'card.dropped': 'Taken away when you save',
    'card.none': 'No card yet.',
    'card.how.set': 'Set by you.',
    'card.how.settings': 'From her settings file.',
    'card.how.said': 'The first thing you said to her.',
    'card.needsText': 'Write the card before putting it in her system prompt.',
    // People
    'people.title': 'People she knows',
    'people.hint': 'Who each person is to her and how close; with her gut, how she is with them too.',
    'people.none': 'Nobody yet.',
    'people.role': 'Who they are to her',
    'people.roleYou': 'Who you are to her',
    'people.noRole': 'no role',
    'people.closeness': 'Closeness ({role}, {floor} to {ceiling})',
    'people.needsRole': 'Closeness needs a role.',
    'people.holdCloseness': 'Lock closeness: no exchange or time moves it',
    'people.summary': '{lessons} lessons · {weight}% theirs',
    'people.byHand': 'Set how much what is different with them counts, by hand',
    'people.weight': 'theirs',
    'people.lock': 'Lock how she is with them: what they say teaches nothing, and they do not fade',
    'people.tunes': 'Each feeling, with them alone',
    'people.tunesHint': 'A nudge to each feeling with this person only, on top of all she is and has learned with ' +
      'them; it stays (-6 to 6; 0 removes it).',
    'people.forget': 'Forget them in her gut',
    'people.forgetConfirm': 'Forget {who} in her gut? How she is with them goes, and so do the sides only they ' +
      'wanted. What they did to her heart stays.',
    'people.forgotten': 'Forgotten when you save',
    'people.undo': 'Keep',
    'me.name': 'What she calls you',
    'me.accounts': 'Your accounts on chat channels',
    'me.accountsHint': 'Messages from them are yours: one person to her memory and to her gut.',
    'me.placeholder': 'qq:10001',
    'me.add': 'Add',
    'me.remove': 'Remove',
    'me.removed': 'removed when you save',
    'me.added': 'added when you save',
    'me.noAccounts': 'None yet.',
    'me.fixed': 'in the settings file',
    'me.badAccount': 'A channel and an id, such as qq:10001.',
    'others.title': 'People she meets',
    'others.role': 'Who they are to her at first',
    'others.hint': 'Until you give them a role of their own.',
    'role.creator': 'creator',
    'role.family': 'family',
    'role.friend': 'friend',
    'role.acquaintance': 'acquaintance',
    // Memory
    'surface.title': 'What she keeps of lately',
    'surface.hint': 'With one person she reads the newest of what was said, word for word: as many days of talking ' +
      'as fit between the least and the most.',
    'surface.days': 'Days of talking',
    'surface.floor': 'At least (tokens)',
    'surface.cap': 'At most (tokens)',
    'surface.window': 'Her model\'s window (tokens)',
    'look.title': 'What was said before, with each message',
    'look.hint': 'What bears on the message, found by its words and its meaning, up to so many characters.',
    'look.budget': 'Characters',
    'look.bar': 'Bar for words alone',
    'look.barHint': 'With no meaning to go by, what was said comes only when the words it shares carry this share ' +
      'of the message; 0 brings every match.',
    'memory.bad': 'A number is missing, or too small.',
    'start.title': 'Start over',
    'start.fresh': 'Lately, from the start',
    'start.freshHint': 'What she keeps of lately with you starts over; every word stays in her deep memory.',
    'start.freshConfirm': 'Start what she keeps of lately over?',
    'start.deep': 'Forget everyone',
    'start.deepHint': 'What she remembers of everyone, gone for good: every exchange and every note. Who they are ' +
      'to her stays, and so does her card.',
    'start.deepConfirm': 'Forget what she remembers of everyone, for good? This cannot be undone.',
    'start.gut': 'As she was born',
    'start.gutHint': 'That, and what people taught her gut: she is as she was born.',
    'start.gutConfirm': 'Forget everyone and everything people taught her gut, for good? This cannot be undone.',
    'start.done': 'Done.',
    'start.unsaved': 'What you have not saved stays as it is.',
    // Gut
    'gut.none': 'She has no gut here.',
    'gut.map': 'Her star map',
    'settings.grown': 'Growing up',
    'settings.tau': 'tau (lessons)',
    'settings.tauHint': 'How fast her heart grows up: young, a lesson moves her heart a lot; grown up (at five times ' +
      'tau), a little. A number above 0.',
    'settings.badTau': 'tau is a number above 0',
    'settings.age': 'Age: {age} lessons, {grown}% grown up, learning at {learning}% of her young pace',
    'settings.young': 'Young again',
    'settings.youngConfirm': 'Make her young again? Her age goes back to 0 and her heart learns fast again. She ' +
      'forgets nothing.',
    'settings.heartLock': 'Lock her heart',
    'settings.heartLockHint': 'Her heart learns nothing and does not grow up until it is unlocked; how she is with ' +
      'each person still learns, unless locked too.',
    'settings.sensitivity': 'Sensitivity',
    'settings.sensitivityHint': 'How hard every moment hits her: -1 thick-skinned (lightly) to 1 sensitive (hard); 0 ' +
      'is as she is.',
    'settings.dull': 'thick-skinned',
    'settings.keen': 'sensitive',
    'settings.tunes': 'Each feeling, by hand',
    'settings.tunesHint': 'Nature (-6 to 6) is where she stands on a feeling, as if she had been born so: 3 is about ' +
      'even, 6 is fully. What she lives moves her on from there (slowly once she is grown; a locked heart keeps it), ' +
      'and 0 removes it. Now (-1 to 1) is how much more or less of it she feels lately than usual: it fades as she ' +
      'lives.',
    'settings.nature': 'nature',
    'settings.now': 'now',
    'sides.title': 'Her sides',
    'sides.hint': 'A side is a name and one sentence of what she does. A locked side holds for everyone, whatever is ' +
      'drawn and however long; how often is how strongly it shows.',
    'sides.none': 'No sides yet.',
    'sides.given': 'given in her settings',
    'sides.weight': 'weight when drawn',
    'sides.drop': 'Remove',
    'sides.dropped': 'Removed when you save',
    'sides.often': 'how often',
    'sides.oftenHint': 'The share of her turns the sentence goes beside the message: 1 is every turn.',
    'sides.pick': 'Choose a name',
    'sides.what': 'What she does, said to her ("You…")',
    'sides.write': 'Add',
    'sides.locked': 'locked',
    'sides.lockThis': 'Lock her in this side',
    'sides.needsWhat': 'Write what she does before saving.',
    // The save bar
    'save.save': 'Save',
    'save.discard': 'Discard',
    'save.unsaved': '{count} unsaved',
    'save.none': 'No changes',
    'save.saved': 'Saved.',
    'save.failed': 'Not saved: {error}'
  }

  const ZH = {
    'page.intro': '她的设置，分成四页。保存后立刻生效，并且会一直保留。',
    'page.loading': '正在读取她的设置……',
    'page.unreachable': '读取不到她的设置（{error}）。',
    'tab.her': '她自己',
    'tab.people': '认识的人',
    'tab.memory': '记忆',
    'tab.gut': '直觉',
    you: '你',
    'her.title': '她是谁',
    'her.name': '她的名字',
    'her.nameHint': '',
    'her.language': '她回答用的语言',
    'her.languageHint': '不管对方用什么语言写。选“跟着对方”，她就用每个人自己的语言回答。',
    'language.auto': '跟着对方',
    'language.english': '英语',
    'language.chinese': '中文',
    'language.cantonese': '粤语',
    'language.japanese': '日语',
    'her.zone': '她的时区',
    'her.zoneHint': '比如 UTC+8 或 Asia/Shanghai；空着就用这台机器的时区。她按这个时区来算聊天的日子。',
    'card.title': '角色卡',
    'card.hint': '用你自己的话写她是谁。打开后，它会放进她的系统提示，每次调用都会带上。',
    'card.placeholder': '你是……',
    'card.on': '放进她的系统提示',
    'card.drop': '拿掉',
    'card.dropped': '保存后拿掉',
    'card.none': '还没有角色卡。',
    'card.how.set': '这是你设的。',
    'card.how.settings': '来自她的设置文件。',
    'card.how.said': '这是你对她说的第一句话。',
    'card.needsText': '先写好角色卡，再放进她的系统提示。',
    'people.title': '她认识的人',
    'people.hint': '每个人对她来说是谁、有多亲近；有直觉的话，还有她和这个人相处的样子。',
    'people.none': '还没有人。',
    'people.role': '对她来说是',
    'people.roleYou': '你对她来说是',
    'people.noRole': '没有角色',
    'people.closeness': '亲近度（{role}，{floor} 到 {ceiling}）',
    'people.needsRole': '要先有角色，才有亲近度。',
    'people.holdCloseness': '锁住亲近度：不再因交流或时间而变动',
    'people.summary': '{lessons} 节课 · {weight}% 专属于这个人',
    'people.byHand': '亲手设定：她和这个人在一起时不一样的那份算多少',
    'people.weight': '专属于这个人',
    'people.lock': '锁住她和这个人相处的样子：这个人说的话什么也不教，也不会淡去',
    'people.tunes': '每一种感受，只对这个人',
    'people.tunesHint': '只针对这个人，给每种感受加一点偏移，叠加在她本来的样子和她与这个人相处中学到的一切之上，并且一直保留（-6 到 6；0 表示移除）。',
    'people.forget': '在她的直觉里忘记这个人',
    'people.forgetConfirm': '在她的直觉里忘记{who}？她和这个人相处的样子会消失，只有这个人想要的属性也会消失；这个人在她心里留下的影响还在。',
    'people.forgotten': '保存后就会忘记',
    'people.undo': '保留',
    'me.name': '她怎么称呼你',
    'me.accounts': '你在聊天平台上的账号',
    'me.accountsHint': '从这些账号发来的消息都算你的：在她的记忆和直觉里是同一个人。',
    'me.placeholder': 'qq:10001',
    'me.add': '添加',
    'me.remove': '去掉',
    'me.removed': '保存后去掉',
    'me.added': '保存后添加',
    'me.noAccounts': '还没有。',
    'me.fixed': '写在设置文件里',
    'me.badAccount': '写平台名和账号，比如 qq:10001。',
    'others.title': '她新认识的人',
    'others.role': '刚认识时对她来说是',
    'others.hint': '直到你给这个人设了自己的角色为止。',
    'role.creator': '创造者',
    'role.family': '家人',
    'role.friend': '朋友',
    'role.acquaintance': '认识的人',
    'surface.title': '她记得的最近的对话',
    'surface.hint': '和一个人聊天时，她会逐字读你们最近说过的话：在下限和上限之间，能放下几天的聊天就放几天。',
    'surface.days': '聊天的天数',
    'surface.floor': '至少（token）',
    'surface.cap': '至多（token）',
    'surface.window': '她的模型的上下文窗口（token）',
    'look.title': '每条消息带上的以前的对话',
    'look.hint': '和这条消息有关的以前的对话，按字词和意思找出来，总长不超过这么多字。',
    'look.budget': '字数',
    'look.bar': '只按字词匹配时的门槛',
    'look.barHint': '没有意思可以参考时，共有的字词要占到这条消息的这么多比重，那段对话才会带上；0 表示每个匹配都带上。',
    'memory.bad': '有个数字没填，或者太小。',
    'start.title': '重新开始',
    'start.fresh': '最近的对话从头开始',
    'start.freshHint': '她记得的你们最近的对话从头开始；说过的每句话都还在她的深层记忆里。',
    'start.freshConfirm': '让她记得的最近的对话从头开始？',
    'start.deep': '忘掉所有人',
    'start.deepHint': '她记得的关于所有人的一切永久删除：每段对话和每条笔记。每个人对她来说是谁还保留着，她的角色卡也还在。',
    'start.deepConfirm': '永久忘掉她记得的关于所有人的一切？这无法撤销。',
    'start.gut': '回到刚出生的样子',
    'start.gutHint': '再加上大家教给她直觉的一切：她回到刚出生的样子。',
    'start.gutConfirm': '永久忘掉所有人，以及大家教给她直觉的一切？这无法撤销。',
    'start.done': '完成了。',
    'start.unsaved': '还没保存的改动会原样留着。',
    'gut.none': '她在这里没有直觉。',
    'gut.map': '她的星图',
    'settings.grown': '长大',
    'settings.tau': 'tau（节课）',
    'settings.tauHint': '她的心长得多快：小时候，一节课就能让她的心变化很大；长大后（到五倍 tau 时），变化就很小。填大于 0 的数。',
    'settings.badTau': 'tau 要大于 0',
    'settings.age': '年龄：{age} 节课，长大了 {grown}%，学习速度是她小时候的 {learning}%',
    'settings.young': '回到小时候',
    'settings.youngConfirm': '让她回到小时候？她的年龄会归零，她的心又会学得很快。她不会忘记任何事。',
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
    'sides.title': '她的属性',
    'sides.hint': '属性由一个名字和一句她的做法组成。锁住的属性对所有人都生效，无论抽到什么、持续多久；而它出现的频率，决定它表现得有多强。',
    'sides.none': '还没有属性。',
    'sides.given': '由她的设置指定',
    'sides.weight': '抽到时的权重',
    'sides.drop': '去掉',
    'sides.dropped': '保存后去掉',
    'sides.often': '出现频率',
    'sides.oftenHint': '她的回合中，这句做法附在消息旁的比例：1 表示每个回合。',
    'sides.pick': '选择一个名字',
    'sides.what': '她的做法，用对她说的话来写（你……）',
    'sides.write': '添加',
    'sides.locked': '已锁住',
    'sides.lockThis': '把她锁在这一面',
    'sides.needsWhat': '保存前写下她的做法。',
    'save.save': '保存',
    'save.discard': '放弃',
    'save.unsaved': '{count} 项未保存',
    'save.none': '没有改动',
    'save.saved': '已保存。',
    'save.failed': '未保存：{error}'
  }
  const WORDS = { en: EN, zh: ZH }

  // ---- what a draft is, counts and asks for: plain functions, with no page in sight ---------------------------------

  /** A draft with nothing in it: what Save would send, as it is staged. */
  const empty = () => ({ her: {}, me: { link: [], unlink: [] }, people: {}, memory: {}, rows: {},
    gut: { tune: {}, sides: {} } })

  const keys = table => Object.keys(table || {}).length

  /** How many values a draft changes. */
  function counted (draft) {
    let count = keys(draft.her) - ('card' in draft.her ? 1 : 0)
    if ('card' in draft.her) count += draft.her.card === null ? 1 : keys(draft.her.card)
    count += ('name' in draft.me ? 1 : 0) + draft.me.link.length + draft.me.unlink.length
    count += draft.others !== undefined ? 1 : 0
    for (const item of Object.values(draft.people)) count += keys(item) - ('tune' in item ? 1 : 0) + keys(item.tune)
    count += keys(draft.memory) + keys(draft.rows)
    const gut = draft.gut
    for (const key of ['tau', 'sensitivity', 'locked', 'side']) if (gut[key] !== undefined) count += 1
    for (const item of Object.values(gut.tune)) count += keys(item)
    return count + keys(gut.sides)
  }

  /** A draft as the change it asks for (`settle`'s shape). */
  function body (draft) {
    const asked = {}
    if (keys(draft.her)) asked.her = { ...draft.her }
    const me = {}
    if ('name' in draft.me) me.name = draft.me.name
    if (draft.me.link.length) me.link = [...draft.me.link]
    if (draft.me.unlink.length) me.unlink = [...draft.me.unlink]
    if (keys(me)) asked.me = me
    if (draft.others !== undefined) asked.others = draft.others
    const people = Object.entries(draft.people).map(([subject, { tune, ...item }]) => ({ subject, ...item,
      ...(tune ? { tune: Object.entries(tune).map(([end, nature]) => ({ end, nature })) } : {}) }))
    if (people.length) asked.people = people
    if (keys(draft.memory)) asked.memory = { ...draft.memory }
    if (keys(draft.rows)) asked.rows = { ...draft.rows }
    const gut = {}, staged = draft.gut
    if (staged.tau !== undefined) gut.tau = Number(staged.tau)
    if (staged.sensitivity !== undefined) gut.sensitivity = staged.sensitivity
    if (staged.locked !== undefined) gut.locked = staged.locked
    const tune = Object.entries(staged.tune).map(([end, item]) => ({ end, ...item }))
    if (tune.length) gut.tune = tune
    const sides = Object.entries(staged.sides).map(([name, { fresh, ...item }]) => ({ name, ...item }))
    if (sides.length) gut.sides = sides
    if (staged.side !== undefined) gut.side = staged.side
    if (keys(gut)) asked.gut = gut
    return asked
  }

  /** What stops a draft from being saved, as the words that say so; null when nothing does. */
  function blocked (draft, view) {
    const tau = draft.gut.tau
    if (tau !== undefined && !(Number(tau) > 0 && Number.isFinite(Number(tau)))) return 'settings.badTau'
    if (Object.values(draft.gut.sides).some(item => item.fresh && !String(item.what || '').trim())) {
      return 'sides.needsWhat'
    }
    if ([...Object.values(draft.memory), ...Object.values(draft.rows)].some(value => value === null)) return 'memory.bad'
    const card = draft.her.card
    if (card && card.on === true && !String(card.text ?? view?.her?.card?.text ?? '').trim()) return 'card.needsText'
    return null
  }

  /** An end's colour: its bar's, the first end of a bar deeper and the second lighter. */
  function endColour (bars, end, dark) {
    const index = bars.findIndex(bar => bar.ends.includes(end))
    const shades = COLOURS[dark ? 'dark' : 'light']
    if (index < 0) return dark ? '#cccccc' : '#555555'
    return (bars[index].ends[0] === end ? shades.deep : shades.light)[index]
  }

  const format = (text, values = {}) => String(text).replace(/\{(\w+)\}/g, (all, name) =>
    Object.hasOwn(values, name) ? String(values[name]) : all)
  const fixed = (value, digits = 2) => (Number(value) || 0).toFixed(digits)
  const signed = (value, digits = 2) => (value > 0 ? '+' : value < 0 ? '−' : '±') + Math.abs(value).toFixed(digits)
  const percent = value => fixed((Number(value) || 0) * 100, 0)
  const ACCOUNT = /^[A-Za-z][\w.-]{0,31}:\S{1,200}$/

  const CSS = `
.ms-page { --ms-accent-: var(--ms-accent, #4d6bfe); --ms-line-: var(--ms-line, rgba(128,128,128,.3));
  --ms-soft-: var(--ms-soft, rgba(128,128,128,.22)); --ms-strong-: var(--ms-strong, rgba(128,128,128,.5));
  --ms-dim-: var(--ms-dim, #888); --ms-field-: var(--ms-field, transparent); --ms-card-: var(--ms-card, transparent);
  --ms-bar-: var(--ms-bar, var(--ms-bg, #fff)); --ms-hover-: var(--ms-hover, rgba(128,128,128,.1));
  --ms-chosen-: var(--ms-chosen, rgba(77,107,254,.14)); --ms-error-: var(--ms-error, #d93036);
  --ms-ok-: var(--ms-ok, #2f9e63); --ms-on-accent-: var(--ms-on-accent, #fff);
  color: var(--ms-fg, inherit); font-size: 13px; line-height: 1.55; display: flex; flex-direction: column; gap: 12px;
  box-sizing: border-box; min-width: 0; max-width: 960px }
.ms-page *, .ms-page *::before, .ms-page *::after { box-sizing: border-box }
.ms-page p { margin: 0 }
.ms-tabs { display: flex; gap: 4px; flex-wrap: wrap; border-bottom: .5px solid var(--ms-line-); padding-bottom: 6px }
.ms-tab { height: 32px; padding: 0 14px; border-radius: 8px; border: 0; font: inherit; color: inherit; cursor: pointer;
  background: transparent; display: inline-flex; align-items: center; gap: 6px }
.ms-tab:hover { background: var(--ms-hover-) }
.ms-tab[aria-selected=true] { background: var(--ms-chosen-); font-weight: 600 }
.ms-tab-count { font-size: 11px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; line-height: 18px;
  text-align: center; color: var(--ms-on-accent-); background: var(--ms-accent-); font-weight: 600 }
.ms-panel { display: flex; flex-direction: column; gap: 12px }
.ms-subtitle { font-size: 13.5px; font-weight: 600; margin-bottom: 2px }
.ms-dim { color: var(--ms-dim-); font-size: 12px; line-height: 1.5 }
.ms-error { color: var(--ms-error-); font-size: 12px }
.ms-ok { color: var(--ms-ok-); font-size: 12px }
.ms-card { border: .5px solid var(--ms-line-); border-radius: 12px; padding: 10px 12px; display: flex;
  flex-direction: column; gap: 8px; min-width: 0; background: var(--ms-card-) }
.ms-row { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center }
.ms-field { display: grid; grid-template-columns: minmax(9em, 14em) minmax(0, 1fr); gap: 4px 10px; align-items: center }
.ms-field > .ms-dim { grid-column: 2 }
.ms-field-label { font-weight: 400 }
.ms-input, .ms-select, .ms-text { font: inherit; color: inherit; border-radius: 8px; background: var(--ms-field-);
  border: .5px solid var(--ms-strong-); min-width: 0 }
.ms-input, .ms-select { height: 30px; padding: 0 8px; max-width: 100% }
.ms-input[type=number] { width: 140px }
.ms-input.ms-wide { width: 100% }
.ms-text { width: 100%; padding: 6px 8px; resize: vertical }
.ms-input[aria-invalid=true] { border-color: var(--ms-error-) }
.ms-changed { color: var(--ms-accent-); font-weight: 600 }
.ms-input.ms-changed, .ms-select.ms-changed, .ms-text.ms-changed { border-color: var(--ms-accent-); font-weight: 400 }
.ms-check { display: flex; gap: 8px; align-items: flex-start; font-weight: 400; cursor: pointer }
.ms-check input { margin-top: 3px; flex: none }
.ms-check.ms-changed > span { color: var(--ms-accent-); font-weight: 600 }
.ms-slider { display: grid; grid-template-columns: minmax(3.6em, auto) 1fr 3.4em; gap: 6px; align-items: center }
.ms-slider input { width: 100%; min-width: 0 }
.ms-number { font-variant-numeric: tabular-nums; text-align: right }
.ms-slider.ms-changed .ms-number { color: var(--ms-accent-); font-weight: 600 }
.ms-slider.ms-changed > .ms-dim:first-child { color: var(--ms-accent-) }
.ms-range { display: flex; gap: 8px; align-items: center }
.ms-page input[type=range], .ms-page input[type=checkbox] { accent-color: var(--ms-accent-) }
.ms-range input { flex: 1 1 160px; min-width: 120px }
.ms-button { height: 30px; padding: 0 14px; border-radius: 8px; font: inherit; cursor: pointer; color: inherit;
  background: transparent; border: .5px solid var(--ms-strong-) }
.ms-button:hover:not(:disabled) { background: var(--ms-hover-) }
.ms-button:disabled { opacity: .5; cursor: default }
.ms-primary { color: var(--ms-on-accent-); border-color: transparent; background: var(--ms-accent-) }
.ms-primary:hover:not(:disabled) { filter: brightness(1.08); background: var(--ms-accent-) }
.ms-danger { color: var(--ms-error-); border-color: var(--ms-error-) }
.ms-split { display: grid; grid-template-columns: minmax(150px, 220px) minmax(0, 1fr); gap: 10px; align-items: start }
.ms-list { display: flex; flex-direction: column; gap: 1px; max-height: 300px; overflow-y: auto; padding: 4px;
  border: .5px solid var(--ms-soft-); border-radius: 10px }
.ms-list-group { font-size: 11.5px; font-weight: 600; padding: 6px 8px 2px; color: var(--ms-dim-) }
.ms-option { display: flex; align-items: center; gap: 6px; min-height: 30px; padding: 4px 8px; border: 0;
  border-radius: 7px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer }
.ms-option:hover { background: var(--ms-hover-) }
.ms-option[aria-selected=true] { background: var(--ms-chosen-) }
.ms-option-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.ms-option-note { font-size: 11px; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--ms-dim-) }
.ms-option.ms-changed .ms-option-name::after { content: ' •' }
.ms-gone .ms-option-name, .ms-tag.ms-gone, .ms-account.ms-gone > span { text-decoration: line-through; opacity: .6 }
.ms-edit { display: flex; flex-direction: column; gap: 8px; min-width: 0; padding: 10px 12px; border-radius: 10px;
  border: .5px solid var(--ms-soft-) }
.ms-edit-title { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-weight: 600 }
.ms-edit-title .ms-dim { font-weight: 400 }
.ms-inner { border-top: .5px solid var(--ms-soft-); padding-top: 8px; display: flex; flex-direction: column; gap: 6px }
.ms-tags { display: flex; flex-wrap: wrap; gap: 6px }
.ms-tag { display: inline-flex; align-items: center; gap: 4px; height: 28px; padding: 0 12px; border-radius: 14px;
  font: inherit; color: inherit; background: transparent; cursor: pointer; border: .5px solid var(--ms-strong-) }
.ms-tag[aria-pressed=true] { border-color: var(--ms-accent-); background: var(--ms-chosen-) }
.ms-tag.ms-changed { color: var(--ms-accent-) }
.ms-small-tag { height: 24px; padding: 0 9px; font-size: 12px }
.ms-swatch { width: 9px; height: 9px; border-radius: 50%; flex: none; display: inline-block }
.ms-stack { display: flex; flex-direction: column; gap: 4px }
.ms-accounts { display: flex; flex-direction: column; gap: 4px }
.ms-account { display: flex; align-items: center; gap: 8px; min-height: 30px }
.ms-account > span:first-child { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px }
.ms-start { display: grid; grid-template-columns: minmax(10em, auto) 1fr; gap: 8px 12px; align-items: center }
.ms-map { min-height: 40px }
.ms-savebar { position: sticky; bottom: 0; display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center;
  padding: 10px 12px; border-radius: 12px; z-index: 2; border: .5px solid var(--ms-line-); background: var(--ms-bar-) }
.ms-spacer { flex: 1 }
@media (max-width: 560px) {
  .ms-field { grid-template-columns: 1fr }
  .ms-field > .ms-dim { grid-column: 1 }
  .ms-split { grid-template-columns: 1fr }
  .ms-list { max-height: 200px }
  .ms-start { grid-template-columns: 1fr }
  .ms-tab { padding: 0 10px }
}`

  // ---- the page ----------------------------------------------------------------------------------------------------

  /** An element: `props` are its class, text, attributes (`attrs`), listeners (`on`), style and dataset (`data`). */
  function el (tag, props = {}, ...children) {
    const node = document.createElement(tag)
    if (props.className) node.className = props.className
    if (props.text !== undefined && props.text !== null) node.textContent = String(props.text)
    for (const [name, value] of Object.entries(props.attrs || {})) {
      if (value === false || value === null || value === undefined) continue
      if (name in node && typeof value !== 'string') node[name] = value
      else node.setAttribute(name, value === true ? '' : String(value))
    }
    for (const [name, listener] of Object.entries(props.on || {})) node.addEventListener(name, listener)
    if (props.style) Object.assign(node.style, props.style)
    for (const [name, value] of Object.entries(props.data || {})) node.dataset[name] = value
    for (const child of children.flat()) if (child !== null && child !== undefined && child !== false) node.append(child)
    return node
  }
  const classes = (...names) => names.filter(Boolean).join(' ')

  function style () {
    if (document.getElementById('mneme-settings-style')) return
    document.head.appendChild(el('style', { attrs: { id: 'mneme-settings-style' }, text: CSS }))
  }

  const kept = {
    get () {
      try { return localStorage.getItem(KEPT) } catch { return null }
    },
    set (value) {
      try { localStorage.setItem(KEPT, value) } catch { /* a private window */ }
    }
  }

  /** Her settings drawn into `element`; see the top of this file. */
  function mount (element, options = {}) {
    style()
    const languageOf = () => (typeof options.language === 'function' ? options.language() : options.language) ===
      'zh' ? 'zh' : 'en'
    const t = (key, values) => {
      const lang = languageOf()
      const own = options.words?.[lang]?.[key] ?? options.words?.en?.[key]
      return format(own ?? WORDS[lang][key] ?? EN[key] ?? key, values)
    }
    const chinese = () => languageOf() === 'zh'
    const dark = () => Boolean(options.dark?.())
    const ask = text => (options.confirm ? options.confirm(text) : window.confirm(text))
    let view = null, draft = empty(), status = { busy: false, text: '', error: null }, gone = false
    let tab = TABS.includes(kept.get()) ? kept.get() : 'her'
    const chosen = { person: null, end: null, nudge: null, side: null, adding: '', account: '' }
    const map = el('div', { className: 'ms-map' }) // (kept from one drawing of the page to the next)
    let stopMap = null, mapFor = null
    const root = el('div', { className: 'ms-page' })
    element.replaceChildren(root)

    // ---- staging: what each control changes, and the save bar ----
    const stage = (change, quiet = false) => {
      change(draft)
      status = { ...status, text: '', error: null }
      if (quiet) bar()
      else render()
    }
    let barNode = null
    function bar () {
      const count = counted(draft), stop = blocked(draft, view)
      const next = el('div', { className: 'ms-savebar' },
        el('span', { className: count ? 'ms-changed' : 'ms-dim', text: count ? t('save.unsaved', { count })
          : t('save.none') }),
        status.text ? el('span', { className: 'ms-ok', text: status.text }) : null,
        status.error ? el('span', { className: 'ms-error', text: status.error }) : null,
        stop && count ? el('span', { className: 'ms-error', text: t(stop) }) : null,
        el('span', { className: 'ms-spacer' }),
        el('button', { className: 'ms-button', text: t('save.discard'), attrs: { type: 'button',
          disabled: status.busy || !count }, on: { click: () => {
          draft = empty()
          render()
        } } }),
        el('button', { className: 'ms-button ms-primary', text: t('save.save'), attrs: { type: 'button',
          disabled: status.busy || !count || Boolean(stop) }, on: { click: save } }))
      if (barNode) barNode.replaceWith(next)
      barNode = next
      for (const name of TABS) {
        const badge = root.querySelector(`[data-tab="${name}"] .ms-tab-count`), many = countIn(name)
        if (badge) {
          badge.textContent = String(many)
          badge.hidden = !many
        }
      }
      return next
    }
    /** How many staged values a tab holds. */
    function countIn (name) {
      const part = empty()
      if (name === 'her') {
        part.her = draft.her
        part.rows = Object.fromEntries(Object.entries(draft.rows).filter(([key]) => rowOf(key)?.tab === 'her'))
        part.gut.sides = draft.gut.sides
        if (draft.gut.side !== undefined) part.gut.side = draft.gut.side
      } else if (name === 'people') {
        part.me = draft.me
        part.people = draft.people
        part.others = draft.others
        part.rows = Object.fromEntries(Object.entries(draft.rows).filter(([key]) => rowOf(key)?.tab === 'people'))
      } else if (name === 'memory') {
        part.memory = draft.memory
        part.rows = Object.fromEntries(Object.entries(draft.rows).filter(([key]) => rowOf(key)?.tab === 'memory'))
      } else {
        part.gut = { ...draft.gut, sides: {}, side: undefined }
        part.rows = Object.fromEntries(Object.entries(draft.rows).filter(([key]) => rowOf(key)?.tab === 'gut'))
      }
      return counted(part)
    }
    const rowOf = key => view?.rows?.find(row => row.key === key)

    async function send (asked, done, said = t('save.saved')) {
      status = { busy: true, text: '', error: null }
      bar()
      try {
        const next = await options.save(asked)
        if (gone) return
        view = next
        done()
        status = { busy: false, text: said, error: null }
      } catch (error) {
        if (gone) return
        status = { busy: false, text: '', error: t('save.failed', { error: String(error?.message ?? error) }) }
      }
      render()
    }
    const save = () => send(body(draft), () => { draft = empty() })

    // ---- controls ----
    const label = row => row.label?.[languageOf()] ?? row.label?.en ?? row.key
    const hintOf = row => row.hint?.[languageOf()] ?? row.hint?.en ?? ''
    const roleName = key => {
      if (!key) return t('people.noRole')
      const role = (view.roles || []).find(item => item.key === key)
      const own = role?.names?.[chinese() ? 'zh' : 'en'] ?? role?.names?.en
      const name = t(`role.${key}`)
      return own || (name === `role.${key}` ? key : name)
    }
    const endName = end => chinese() ? view.gut?.ends?.find(item => item.end === end)?.zh ?? end : end
    const barName = item => chinese() ? item.zh : item.bar

    /** A labelled field: its label, its control and a hint under it. */
    const field = (text, control, hint, changed = false) => el('label', { className: 'ms-field' },
      el('span', { className: classes('ms-field-label', changed && 'ms-changed'), text }), control,
      hint ? el('span', { className: 'ms-dim', text: hint }) : null)

    /** A text box staging `put(value)`; `typed` marks it changed when the value differs from what is saved. */
    function textBox ({ value, saved, put, placeholder = '', wide = true, max = 80, key }) {
      const box = el('input', { className: classes('ms-input', wide && 'ms-wide', value !== saved && 'ms-changed'),
        attrs: { type: 'text', value: value ?? '', placeholder, maxLength: max }, data: { key } })
      box.addEventListener('input', () => {
        box.classList.toggle('ms-changed', box.value !== (saved ?? ''))
        stage(() => put(box.value), true)
      })
      return box
    }
    function numberBox ({ value, saved, put, min, max, step = 1, key }) {
      const box = el('input', { className: classes('ms-input', value !== saved && 'ms-changed'),
        attrs: { type: 'number', value: String(value), min, max, step }, data: { key } })
      box.addEventListener('input', () => {
        const number = Number(box.value), good = box.value !== '' && Number.isFinite(number) &&
          (min === undefined || number >= min) && (max === undefined || number <= max)
        box.setAttribute('aria-invalid', String(!good))
        box.classList.toggle('ms-changed', good && number !== saved)
        stage(() => put(good ? number : undefined), true)
      })
      return box
    }
    function slider ({ value, low, high, step, put, text, changed, plain = false, key }) {
      const number = el('span', { className: 'ms-number' })
      const show = item => {
        number.textContent = step >= 1 ? fixed(item, 0) : plain ? fixed(item, 2) : signed(item, step < 0.1 ? 2 : 1)
      }
      show(value)
      const range = el('input', { attrs: { type: 'range', min: low, max: high, step, value: String(value),
        'aria-label': text }, data: { key } })
      const box = el('label', { className: classes('ms-slider', changed && 'ms-changed') },
        el('span', { className: 'ms-dim', text }), range, number)
      range.addEventListener('input', () => {
        const item = Number(range.value)
        show(item)
        box.classList.add('ms-changed')
        stage(() => put(item), true)
      })
      return box
    }
    function check ({ checked, put, text, changed, key, disabled = false }) {
      return el('label', { className: classes('ms-check', changed && 'ms-changed') },
        el('input', { attrs: { type: 'checkbox', checked, disabled }, data: { key },
          on: { change: event => stage(() => put(event.target.checked)) } }),
        el('span', { text }))
    }
    function select ({ value, items, put, text, changed, key }) {
      const box = el('select', { className: classes('ms-select', changed && 'ms-changed'),
        attrs: { 'aria-label': text }, data: { key }, on: { change: event => stage(() => put(event.target.value)) } },
      items.map(item => item.group
        ? el('optgroup', { attrs: { label: item.group } }, item.items.map(one =>
          el('option', { text: one.name, attrs: { value: one.value, selected: one.value === value } })))
        : el('option', { text: item.name, attrs: { value: item.value, selected: item.value === value } })))
      return box
    }
    /** A list to choose one from: rows, and the names of groups between them. */
    function choices ({ items, current, choose, text }) {
      return el('div', { className: 'ms-list', attrs: { role: 'listbox', 'aria-label': text } },
        items.map(item => item.group !== undefined
          ? el('div', { className: 'ms-list-group', text: item.group, attrs: { role: 'presentation' } })
          : el('button', { className: classes('ms-option', item.changed && 'ms-changed', item.gone && 'ms-gone'),
            attrs: { type: 'button', role: 'option', 'aria-selected': String(item.key === current) },
            data: { key: `choose:${item.key}` }, on: { click: () => choose(item.key) } },
          item.swatch ? el('span', { className: 'ms-swatch', style: { background: item.swatch } }) : null,
          el('span', { className: 'ms-option-name', text: item.name }),
          item.note ? el('span', { className: 'ms-option-note', text: item.note }) : null)))
    }
    const card = (title, hint, ...children) => el('section', { className: 'ms-card' },
      title ? el('div', { className: 'ms-subtitle', text: title }) : null,
      hint ? el('div', { className: 'ms-dim', text: hint }) : null, ...children)

    /** The host's own settings on a tab, grouped as it groups them. */
    function hostRows (name) {
      const rows = (view.rows || []).filter(row => row.tab === name)
      if (!rows.length) return null
      const groups = new Map()
      for (const row of rows) {
        const title = row.group?.[languageOf()] ?? row.group?.en ?? ''
        if (!groups.has(title)) groups.set(title, [])
        groups.get(title).push(row)
      }
      return [...groups].map(([title, items]) => card(title, '', ...items.map(row => {
        const staged = Object.hasOwn(draft.rows, row.key), value = staged ? draft.rows[row.key] : row.value
        const put = item => {
          if (item === row.value) delete draft.rows[row.key]
          else draft.rows[row.key] = item
        }
        if (row.kind === 'bool') {
          return el('div', { className: 'ms-stack' }, check({ checked: Boolean(value), text: label(row), changed: staged,
            key: `row:${row.key}`, put }), hintOf(row) ? el('div', { className: 'ms-dim', text: hintOf(row) }) : null)
        }
        if (row.kind === 'choice') {
          return field(label(row), select({ value, changed: staged, key: `row:${row.key}`, text: label(row), put,
            items: row.options.map(option => ({ value: option.value, name: option.label?.[languageOf()] ??
              option.label?.en ?? String(option.value) })) }), hintOf(row), staged)
        }
        if (row.kind === 'number') {
          return field(label(row), numberBox({ value: value ?? row.value, saved: row.value, min: row.min, max: row.max,
            step: row.step ?? 1, key: `row:${row.key}`, put: item => {
              if (item === undefined) draft.rows[row.key] = null // (no number: nothing is saved until there is one)
              else put(item)
            } }), hintOf(row), staged)
        }
        if (row.kind === 'text') {
          return field(label(row), textBox({ value: value ?? '', saved: row.value ?? '', key: `row:${row.key}`,
            put: item => put(item) }), hintOf(row), staged)
        }
        return field(label(row), el('span', { text: Array.isArray(value) ? value.join(' · ') : String(value ?? '') }),
          hintOf(row))
      })))
    }

    // ---- Her ----
    function herTab () {
      const her = view.her, staged = draft.her
      const name = staged.name ?? her.name
      const fields = [her.name === null || her.name === undefined ? null
        : field(t('her.name'), textBox({ value: name, saved: her.name, key: 'her:name', put: item => {
          if (item === her.name) delete draft.her.name
          else draft.her.name = item
        } }), t('her.nameHint'), 'name' in staged),
        her.language === null || her.language === undefined ? null
          : field(t('her.language'), select({ value: staged.language ?? her.language, changed: 'language' in staged,
            key: 'her:language', text: t('her.language'),
            items: LANGUAGES.map(item => ({ value: item, name: t(`language.${item}`) })),
            put: item => {
              if (item === her.language) delete draft.her.language
              else draft.her.language = item
            } }), t('her.languageHint'), 'language' in staged),
        her.zone === null || her.zone === undefined ? null
          : field(t('her.zone'), textBox({ value: staged.zone ?? her.zone, saved: her.zone, key: 'her:zone',
            placeholder: 'UTC+8', wide: false, max: 64, put: item => {
              if (item === her.zone) delete draft.her.zone
              else draft.her.zone = item
            } }), t('her.zoneHint'), 'zone' in staged)]
      const who = fields.some(Boolean) ? card(t('her.title'), '', ...fields) : null
      const cardNode = her.card === undefined ? null : characterCard()
      const sides = view.gut ? sidesCard() : null
      return [who, cardNode, ...(hostRows('her') || []), sides]
    }

    function characterCard () {
      const saved = view.her.card, staged = draft.her.card
      const dropping = staged === null
      const text = staged && staged.text !== undefined ? staged.text : saved?.text ?? ''
      const on = staged && staged.on !== undefined ? staged.on : Boolean(saved?.on)
      const put = (key, value) => {
        const next = { ...(draft.her.card || {}) }
        const before = key === 'text' ? saved?.text ?? '' : Boolean(saved?.on)
        if (value === before) delete next[key]
        else next[key] = value
        if (Object.keys(next).length) draft.her.card = next
        else delete draft.her.card
      }
      const area = el('textarea', { className: classes('ms-text', staged?.text !== undefined && 'ms-changed'),
        attrs: { rows: 5, placeholder: t('card.placeholder'), disabled: dropping }, data: { key: 'her:card' } })
      area.value = text
      area.addEventListener('input', () => {
        area.classList.toggle('ms-changed', area.value !== (saved?.text ?? ''))
        stage(() => put('text', area.value), true)
      })
      return card(t('card.title'), t('card.hint'),
        saved ? el('div', { className: 'ms-dim', text: t(`card.how.${saved.how || 'set'}`) })
          : el('div', { className: 'ms-dim', text: t('card.none') }),
        area,
        el('div', { className: 'ms-row' },
          check({ checked: on, changed: staged?.on !== undefined, key: 'her:card:on', text: t('card.on'),
            disabled: dropping, put: value => put('on', value) }),
          el('span', { className: 'ms-spacer' }),
          dropping ? el('span', { className: 'ms-changed', text: t('card.dropped') }) : null,
          saved || dropping ? el('button', { className: 'ms-button', text: dropping ? t('people.undo') : t('card.drop'),
            attrs: { type: 'button' }, on: { click: () => stage(() => {
              if (dropping) delete draft.her.card
              else draft.her.card = null
            }) } }) : null))
    }

    function sidesCard () {
      const gut = view.gut, sides = draft.gut.sides
      const locked = draft.gut.side !== undefined ? draft.gut.side : gut.side
      const staged = name => sides[name] || {}
      const set = (name, key, item) => { sides[name] = { ...(sides[name] || {}), [key]: item } }
      const lock = next => {
        if (JSON.stringify(next) === JSON.stringify(gut.side)) delete draft.gut.side
        else draft.gut.side = next
      }
      const added = Object.entries(sides).filter(([name, item]) => item.fresh && !gut.sides.some(side =>
        side.name === name)).map(([name]) => ({ name, what: '', given: false, own: GROWS, fresh: true }))
      const all = [...gut.sides, ...added]
      if (!all.some(item => item.name === chosen.side)) chosen.side = locked?.name ?? all[0]?.name ?? null
      const side = all.find(item => item.name === chosen.side) || null
      const free = gut.names.filter(name => !all.some(item => item.name === name))
      const mine = side ? staged(side.name) : {}, dropping = mine.drop === true
      const isLocked = Boolean(side && locked?.name === side.name)
      const remove = () => stage(() => {
        if (!side || side.given) return
        if (side.fresh) {
          delete sides[side.name]
          if (locked?.name === side.name) lock(gut.side)
        } else if (staged(side.name).drop) delete sides[side.name]
        else set(side.name, 'drop', true)
      })
      const what = side && !side.given ? el('textarea', { className: classes('ms-text', mine.what !== undefined &&
        'ms-changed'), attrs: { rows: 2, maxLength: 200, disabled: dropping, placeholder: t('sides.what') },
      data: { key: `side:${side.name}` } }) : null
      if (what) {
        what.value = mine.what ?? side.what
        what.addEventListener('input', () => {
          what.classList.add('ms-changed')
          stage(() => set(side.name, 'what', what.value), true)
        })
      }
      return card(t('sides.title'), t('sides.hint'),
        el('div', { className: 'ms-tags' }, all.length ? all.map(item => el('button', {
          className: classes('ms-tag', staged(item.name).drop && 'ms-gone', sides[item.name] && 'ms-changed'),
          attrs: { type: 'button', 'aria-pressed': String(item.name === chosen.side) }, data: { key: `tag:${item.name}` },
          on: { click: () => {
            chosen.side = item.name
            render()
          } } }, item.name, locked?.name === item.name ? el('span', { className: 'ms-dim',
          text: `· ${t('sides.locked')}` }) : null)) : el('span', { className: 'ms-dim', text: t('sides.none') })),
        el('div', { className: 'ms-row' },
          select({ value: chosen.adding, text: t('sides.pick'), key: 'side:pick', changed: false,
            items: [{ value: '', name: t('sides.pick') }, ...free.map(name => ({ value: name, name }))],
            put: item => { chosen.adding = item } }),
          el('button', { className: 'ms-button', text: t('sides.write'), attrs: { type: 'button',
            disabled: !chosen.adding }, on: { click: () => stage(() => {
            set(chosen.adding, 'fresh', true)
            chosen.side = chosen.adding
            chosen.adding = ''
          }) } }),
          el('button', { className: 'ms-button', text: dropping ? t('people.undo') : t('sides.drop'),
            attrs: { type: 'button', disabled: !side || side.given }, on: { click: remove } })),
        side ? el('div', { className: 'ms-edit' },
          el('div', { className: 'ms-edit-title' }, side.name,
            side.given ? el('span', { className: 'ms-dim', text: t('sides.given') }) : null,
            dropping ? el('span', { className: 'ms-changed', text: t('sides.dropped') }) : null),
          side.given ? el('div', { text: side.what }) : what,
          side.given ? null : field(t('sides.weight'), numberBox({ value: mine.weight ?? side.own, saved: side.own,
            min: 0, step: 0.5, key: `side:${side.name}:weight`, put: item => {
              if (item === undefined || item === side.own) {
                const { weight, ...rest } = sides[side.name] || {}
                if (Object.keys(rest).length) sides[side.name] = rest
                else delete sides[side.name]
              } else set(side.name, 'weight', item)
            } }), '', mine.weight !== undefined),
          check({ checked: isLocked, disabled: dropping, changed: draft.gut.side !== undefined,
            key: `side:${side.name}:lock`, text: t('sides.lockThis'),
            put: value => lock(value ? { name: side.name, often: locked?.often ?? 1 } : null) }),
          isLocked ? slider({ text: t('sides.often'), value: locked.often, low: 0, high: 1, step: 0.05, plain: true,
            changed: draft.gut.side !== undefined, key: `side:${side.name}:often`,
            put: often => lock({ name: side.name, often }) }) : null,
          el('div', { className: 'ms-dim', text: t('sides.oftenHint') })) : null)
    }

    // ---- People ----
    function peopleTab () {
      const nodes = [peopleCard()]
      if (view.others !== null && view.others !== undefined) {
        const value = draft.others !== undefined ? draft.others : view.others
        nodes.push(card(t('others.title'), '', field(t('others.role'), select({ value, changed: draft.others !==
          undefined, key: 'others', text: t('others.role'),
        items: [{ value: '', name: t('people.noRole') }, ...view.roles.filter(role => !role.unique)
          .map(role => ({ value: role.key, name: roleName(role.key) }))],
        put: item => {
          if (item === view.others) delete draft.others
          else draft.others = item
        } }), t('others.hint'), draft.others !== undefined)))
      }
      return [...nodes, ...(hostRows('people') || [])]
    }

    function peopleCard () {
      const people = view.people || []
      if (!people.length) return card(t('people.title'), '', el('div', { className: 'ms-dim', text: t('people.none') }))
      if (!people.some(item => item.subject === chosen.person)) chosen.person = people[0].subject
      const person = people.find(item => item.subject === chosen.person)
      const whoOf = item => item.you ? t('you') : item.name || item.subject
      const items = people.map(item => {
        const staged = draft.people[item.subject] || {}
        const value = staged.closeness ?? item.closeness?.value
        return { key: item.subject, name: whoOf(item), changed: Boolean(draft.people[item.subject]) ||
          (item.you && (('name' in draft.me) || draft.me.link.length || draft.me.unlink.length)),
        gone: staged.forget, note: value !== undefined && value !== null ? fixed(value, 0) : '' }
      })
      return card(t('people.title'), t('people.hint'),
        el('div', { className: 'ms-split' },
          choices({ items, current: person.subject, text: t('people.title'), choose: key => {
            chosen.person = key
            render()
          } }),
          personEditor(person, whoOf(person))))
    }

    function personEditor (person, who) {
      const staged = draft.people[person.subject] || {}
      const set = (key, item) => {
        draft.people[person.subject] = { ...(draft.people[person.subject] || {}), [key]: item }
      }
      const unset = key => {
        const { [key]: dropped, ...rest } = draft.people[person.subject] || {}
        if (Object.keys(rest).length) draft.people[person.subject] = rest
        else delete draft.people[person.subject]
      }
      const role = staged.role !== undefined ? staged.role : person.role
      const kind = (view.roles || []).find(item => item.key === role)
      const close = person.closeness
      const roles = (view.roles || []).filter(item => !item.unique || item.key === person.role ||
        !view.people.some(other => other.subject !== person.subject && other.role === item.key))
      const parts = [el('div', { className: 'ms-edit-title' }, who,
        person.gut ? el('span', { className: 'ms-dim', text: t('people.summary', { lessons: person.gut.lessons,
          weight: percent(person.gut.weight) }) }) : null)]
      if (staged.forget) {
        parts.push(el('div', { className: 'ms-row' }, el('span', { className: 'ms-changed', text: t('people.forgotten') }),
          el('button', { className: 'ms-button', text: t('people.undo'), attrs: { type: 'button' },
            on: { click: () => stage(() => unset('forget')) } })))
      }
      if (person.you && view.me && view.me.name !== null && view.me.name !== undefined) {
        parts.push(field(t('me.name'), textBox({ value: draft.me.name ?? view.me.name, saved: view.me.name,
          key: 'me:name', put: item => {
            if (item === view.me.name) delete draft.me.name
            else draft.me.name = item
          } }), '', 'name' in draft.me))
      }
      const roleWords = person.you ? t('people.roleYou') : t('people.role')
      if (view.roles) parts.push(field(roleWords, select({ value: role, changed: staged.role !== undefined, key: 'person:role',
        text: roleWords, items: [{ value: '', name: t('people.noRole') }, ...roles.map(item => ({
          value: item.key, name: roleName(item.key) }))],
        put: item => {
          if (item === person.role) {
            unset('role')
            unset('closeness')
          } else {
            set('role', item)
            unset('closeness')
          }
        } }), '', staged.role !== undefined))
      if (kind) {
        const start = staged.closeness ?? (role === person.role && close ? close.value : kind.start ??
          Math.round((kind.floor + kind.ceiling) / 2))
        parts.push(slider({ text: t('people.closeness', { role: roleName(role), floor: kind.floor,
          ceiling: kind.ceiling }), value: Math.min(kind.ceiling, Math.max(kind.floor, start)), low: kind.floor,
        high: kind.ceiling, step: 1, changed: staged.closeness !== undefined, key: 'person:closeness',
        put: item => set('closeness', item) }),
        check({ checked: staged.hold ?? Boolean(close?.locked), changed: staged.hold !== undefined, key: 'person:hold',
          text: t('people.holdCloseness'), put: value => {
            if (value === Boolean(close?.locked)) unset('hold')
            else set('hold', value)
          } }))
      } else if (view.roles) parts.push(el('div', { className: 'ms-dim', text: t('people.needsRole') }))
      if (person.you && view.me?.accounts) parts.push(accounts())
      if (person.gut && view.gut) parts.push(...gutOfPerson(person, staged, set, unset, who))
      return el('div', { className: 'ms-edit' }, ...parts)
    }

    function accounts () {
      const mine = view.me.accounts, link = draft.me.link, unlink = draft.me.unlink
      const box = el('input', { className: 'ms-input', attrs: { type: 'text', placeholder: t('me.placeholder'),
        value: chosen.account, maxLength: 240 }, data: { key: 'me:account' } })
      const good = () => ACCOUNT.test(box.value.trim()) && !mine.includes(box.value.trim()) &&
        !link.includes(box.value.trim())
      const add = el('button', { className: 'ms-button', text: t('me.add'), attrs: { type: 'button',
        disabled: !good() }, on: { click: () => stage(() => {
        link.push(box.value.trim())
        chosen.account = ''
      }) } })
      box.addEventListener('input', () => {
        chosen.account = box.value
        add.disabled = !good()
        box.setAttribute('aria-invalid', String(Boolean(box.value.trim()) && !ACCOUNT.test(box.value.trim())))
      })
      box.addEventListener('keydown', event => {
        if (event.key === 'Enter' && good()) {
          event.preventDefault()
          add.click()
        }
      })
      const fromFile = view.me.fixed || []
      const rows = [...mine.map(account => {
        const leaving = unlink.includes(account)
        if (fromFile.includes(account)) {
          return el('div', { className: 'ms-account' }, el('span', { text: account }),
            el('span', { className: 'ms-dim', text: t('me.fixed') }))
        }
        return el('div', { className: classes('ms-account', leaving && 'ms-gone') }, el('span', { text: account }),
          leaving ? el('span', { className: 'ms-changed', text: t('me.removed') }) : null,
          el('button', { className: 'ms-button', text: leaving ? t('people.undo') : t('me.remove'),
            attrs: { type: 'button' }, on: { click: () => stage(() => {
              if (leaving) unlink.splice(unlink.indexOf(account), 1)
              else unlink.push(account)
            }) } }))
      }), ...link.map(account => el('div', { className: 'ms-account' }, el('span', { text: account }),
        el('span', { className: 'ms-changed', text: t('me.added') }),
        el('button', { className: 'ms-button', text: t('me.remove'), attrs: { type: 'button' },
          on: { click: () => stage(() => link.splice(link.indexOf(account), 1)) } })))]
      return el('div', { className: 'ms-inner' },
        el('div', { className: classes('ms-subtitle', (link.length || unlink.length) && 'ms-changed'),
          text: t('me.accounts') }),
        el('div', { className: 'ms-dim', text: t('me.accountsHint') }),
        el('div', { className: 'ms-accounts' }, rows.length ? rows : el('span', { className: 'ms-dim',
          text: t('me.noAccounts') })),
        el('div', { className: 'ms-row' }, box, add))
    }

    function gutOfPerson (person, staged, set, unset, who) {
      const gut = view.gut, mine = person.gut
      if (!gut.ends.some(item => item.end === chosen.nudge)) chosen.nudge = gut.ends[0]?.end
      const end = chosen.nudge
      const weight = staged.weight !== undefined ? staged.weight : mine.set ?? 'learned'
      const byHand = weight !== 'learned'
      const nudge = name => staged.tune?.[name] ?? mine.nudge[name] ?? 0
      const nudged = gut.ends.map(item => item.end).filter(name => nudge(name))
      return [
        el('div', { className: 'ms-inner' },
          check({ checked: byHand, changed: staged.weight !== undefined, key: 'person:byHand', text: t('people.byHand'),
            put: value => {
              const next = value ? Number(fixed(mine.weight)) : 'learned'
              if (next === (mine.set ?? 'learned')) unset('weight')
              else set('weight', next)
            } }),
          byHand ? slider({ text: t('people.weight'), value: weight, low: 0, high: 1, step: 0.05, plain: true,
            changed: staged.weight !== undefined, key: 'person:weight', put: item => set('weight', item) }) : null,
          check({ checked: staged.locked ?? mine.locked, changed: staged.locked !== undefined, key: 'person:lock',
            text: t('people.lock'), put: value => {
              if (value === mine.locked) unset('locked')
              else set('locked', value)
            } })),
        el('div', { className: 'ms-inner' },
          el('div', { className: 'ms-subtitle', text: t('people.tunes') }),
          el('div', { className: 'ms-dim', text: t('people.tunesHint') }),
          el('div', { className: 'ms-row' },
            el('span', { className: 'ms-swatch', style: { background: endColour(gut.bars, end, dark()) } }),
            select({ value: end, changed: false, key: 'person:end', text: t('people.tunes'),
              items: gut.bars.map(item => ({ group: barName(item), items: item.ends.filter(Boolean).map(name =>
                ({ value: name, name: endName(name) })) })),
              put: item => { chosen.nudge = item } })),
          slider({ text: t('settings.nature'), value: nudge(end), low: -NATURE, high: NATURE, step: 0.1,
            changed: staged.tune?.[end] !== undefined, key: `person:nudge:${end}`,
            put: item => set('tune', { ...(draft.people[person.subject]?.tune || {}), [end]: item }) }),
          nudged.length ? el('div', { className: 'ms-tags' }, nudged.map(name => el('button', {
            className: 'ms-tag ms-small-tag', attrs: { type: 'button', 'aria-pressed': String(name === end) },
            on: { click: () => {
              chosen.nudge = name
              render()
            } } }, `${endName(name)} ${signed(nudge(name), 1)}`))) : null),
        staged.forget ? null : el('div', { className: 'ms-row' }, el('button', { className: 'ms-button',
          text: t('people.forget'), attrs: { type: 'button' }, on: { click: () => {
            if (ask(t('people.forgetConfirm', { who }))) stage(() => set('forget', true))
          } } }))]
    }

    // ---- Memory ----
    function memoryTab () {
      const nodes = []
      const memory = view.memory
      if (memory) {
        const number = (key, min, step = 1) => {
          const staged = Object.hasOwn(draft.memory, key)
          return field(t(KEYS[key]), numberBox({ value: staged ? draft.memory[key] ?? '' : memory[key],
            saved: memory[key], min, step, key: `memory:${key}`, put: item => {
              if (item === memory[key]) delete draft.memory[key]
              else draft.memory[key] = item ?? null // (null: not a number yet, and nothing is saved until it is)
            } }), '', staged)
        }
        nodes.push(card(t('surface.title'), t('surface.hint'), number('surface_days', 1), number('surface_floor', 0, 1000),
          number('surface_cap', 1000, 1000), number('surface_window', 1000, 1000)))
        const staged = Object.hasOwn(draft.memory, 'said_words')
        nodes.push(card(t('look.title'), t('look.hint'), number('said_budget', 0, 100),
          slider({ text: t('look.bar'), value: staged ? draft.memory.said_words : memory.said_words, low: 0, high: 1,
            step: 0.05, plain: true, changed: staged, key: 'memory:said_words', put: item => {
              if (item === memory.said_words) delete draft.memory.said_words
              else draft.memory.said_words = item
            } }), el('div', { className: 'ms-dim', text: t('look.barHint') })))
      }
      nodes.push(...(hostRows('memory') || []))
      const starts = view.starts || []
      if (starts.length) {
        nodes.push(card(t('start.title'), counted(draft) ? t('start.unsaved') : '',
          el('div', { className: 'ms-start' }, starts.flatMap(tier => [
            el('button', { className: classes('ms-button', tier !== 'fresh' && 'ms-danger'), text: t(`start.${tier}`),
              attrs: { type: 'button', disabled: status.busy }, data: { key: `start:${tier}` }, on: { click: () => {
                if (ask(t(`start.${tier}Confirm`))) send({ start: tier }, () => {}, t('start.done'))
              } } }),
            el('span', { className: 'ms-dim', text: t(`start.${tier}Hint`) })]))))
      }
      return nodes
    }
    const KEYS = { surface_days: 'surface.days', surface_floor: 'surface.floor', surface_cap: 'surface.cap',
      surface_window: 'surface.window', said_budget: 'look.budget' }

    // ---- Gut ----
    function gutTab () {
      const gut = view.gut
      if (!gut) return [card('', '', el('div', { className: 'ms-dim', text: t('gut.none') }))]
      const report = gut.report, staged = draft.gut
      const nodes = []
      if (options.starmap) nodes.push(card(t('gut.map'), '', map))
      const tau = staged.tau ?? String(report.tau)
      const tauBox = el('input', { className: classes('ms-input', staged.tau !== undefined && 'ms-changed'),
        attrs: { type: 'number', min: 1, step: 1, value: tau }, data: { key: 'gut:tau' } })
      tauBox.addEventListener('input', () => {
        const good = Number(tauBox.value) > 0 && Number.isFinite(Number(tauBox.value))
        tauBox.setAttribute('aria-invalid', String(!good))
        tauBox.classList.toggle('ms-changed', Number(tauBox.value) !== report.tau)
        stage(() => {
          if (Number(tauBox.value) === report.tau) delete draft.gut.tau
          else draft.gut.tau = tauBox.value
        }, true)
      })
      nodes.push(card(t('settings.grown'), '',
        el('div', { className: 'ms-row' },
          el('span', { text: t('settings.age', { age: report.age, grown: percent(report.grown),
            learning: percent(report.learning) }) }),
          el('button', { className: 'ms-button', text: t('settings.young'), attrs: { type: 'button',
            disabled: status.busy || report.age === 0 }, on: { click: () => {
            if (ask(t('settings.youngConfirm'))) send({ gut: { age: 0 } }, () => {})
          } } })),
        field(t('settings.tau'), tauBox, t('settings.tauHint'), staged.tau !== undefined),
        check({ checked: staged.locked ?? gut.locked, changed: staged.locked !== undefined, key: 'gut:locked',
          text: t('settings.heartLock'), put: value => {
            if (value === gut.locked) delete draft.gut.locked
            else draft.gut.locked = value
          } }),
        el('div', { className: 'ms-dim', text: t('settings.heartLockHint') })))
      const sensitivity = staged.sensitivity ?? report.sensitivity
      const number = el('span', { className: classes('ms-number', staged.sensitivity !== undefined && 'ms-changed'),
        text: signed(sensitivity) })
      const range = el('input', { attrs: { type: 'range', min: -1, max: 1, step: 0.05, value: String(sensitivity),
        'aria-label': t('settings.sensitivity') }, data: { key: 'gut:sensitivity' } })
      range.addEventListener('input', () => {
        const value = Number(range.value)
        number.textContent = signed(value)
        number.classList.add('ms-changed')
        stage(() => {
          if (value === report.sensitivity) delete draft.gut.sensitivity
          else draft.gut.sensitivity = value
        }, true)
      })
      nodes.push(card(t('settings.sensitivity'), '',
        el('div', { className: 'ms-range' }, el('span', { text: t('settings.dull') }), range,
          el('span', { text: t('settings.keen') }), number),
        el('div', { className: 'ms-dim', text: t('settings.sensitivityHint') })))
      nodes.push(feelings())
      return [...nodes, ...(hostRows('gut') || [])]
    }

    function feelings () {
      const gut = view.gut
      if (!gut.ends.some(item => item.end === chosen.end)) chosen.end = gut.ends[0]?.end
      const tuneOf = end => ({ ...gut.ends.find(item => item.end === end), ...draft.gut.tune[end] })
      const retune = (what, value) => {
        const saved = gut.ends.find(item => item.end === chosen.end)
        const next = { ...(draft.gut.tune[chosen.end] || {}), [what]: value }
        if (value === saved[what]) delete next[what]
        if (Object.keys(next).length) draft.gut.tune[chosen.end] = next
        else delete draft.gut.tune[chosen.end]
      }
      const items = gut.bars.flatMap(item => [{ key: `bar:${item.bar}`, group: barName(item) },
        ...item.ends.filter(Boolean).map(end => {
          const tune = tuneOf(end)
          return { key: end, name: endName(end), swatch: endColour(gut.bars, end, dark()),
            changed: Boolean(draft.gut.tune[end]), note: [tune.nature ? signed(tune.nature, 1) : '',
              tune.now ? signed(tune.now) : ''].filter(Boolean).join(' · ') }
        })])
      const tune = tuneOf(chosen.end), changed = draft.gut.tune[chosen.end] || {}
      const owner = gut.bars.find(item => item.ends.includes(chosen.end))
      return card(t('settings.tunes'), t('settings.tunesHint'),
        el('div', { className: 'ms-split' },
          choices({ items, current: chosen.end, text: t('settings.tunes'), choose: key => {
            chosen.end = key
            render()
          } }),
          el('div', { className: 'ms-edit' },
            el('div', { className: 'ms-edit-title' },
              el('span', { className: 'ms-swatch', style: { background: endColour(gut.bars, chosen.end, dark()) } }),
              endName(chosen.end), owner ? el('span', { className: 'ms-dim', text: barName(owner) }) : null),
            slider({ text: t('settings.nature'), value: tune.nature, low: -NATURE, high: NATURE, step: 0.1,
              changed: changed.nature !== undefined, key: `end:${chosen.end}:nature`,
              put: value => retune('nature', value) }),
            slider({ text: t('settings.now'), value: tune.now, low: -1, high: 1, step: 0.05,
              changed: changed.now !== undefined, key: `end:${chosen.end}:now`, put: value => retune('now', value) }))))
    }

    // ---- drawing ----
    function render () {
      if (gone) return
      const focused = root.contains(document.activeElement) ? document.activeElement?.dataset?.key : null
      if (!view) {
        root.replaceChildren(el('div', { className: 'ms-dim', text: status.error
          ? t('page.unreachable', { error: status.error }) : t('page.loading') }))
        return
      }
      const tabs = el('div', { className: 'ms-tabs', attrs: { role: 'tablist' } }, TABS.map(name => el('button', {
        className: 'ms-tab', attrs: { type: 'button', role: 'tab', 'aria-selected': String(name === tab) },
        data: { tab: name, key: `tab:${name}` }, on: { click: () => {
          tab = name
          kept.set(name)
          render()
        } } }, el('span', { text: t(`tab.${name}`) }), el('span', { className: 'ms-tab-count', attrs: { hidden: true } }))))
      const panel = el('div', { className: 'ms-panel', attrs: { role: 'tabpanel' } },
        ...(tab === 'her' ? herTab() : tab === 'people' ? peopleTab() : tab === 'memory' ? memoryTab() : gutTab()))
      barNode = null
      root.replaceChildren(el('p', { className: 'ms-dim', text: t('page.intro') }), tabs, panel)
      root.append(bar())
      if (tab === 'gut' && options.starmap && view.gut && mapFor !== view.gut.stamp) {
        stopMap?.()
        mapFor = view.gut.stamp
        stopMap = options.starmap(map, view) || null
      }
      if (focused) root.querySelector(`[data-key="${CSS_ESCAPE(focused)}"]`)?.focus()
    }
    const CSS_ESCAPE = text => (window.CSS?.escape ? window.CSS.escape(text) : String(text).replace(/["\\]/g, '\\$&'))

    async function reload () {
      try {
        const next = await options.load()
        if (gone) return
        view = next
        status = { ...status, error: null }
      } catch (error) {
        if (gone) return
        if (!view) status = { busy: false, text: '', error: String(error?.message ?? error) }
      }
      render()
    }
    render()
    reload()
    return {
      reload,
      render,
      destroy () {
        gone = true
        stopMap?.()
        root.remove()
      },
      get view () { return view },
      get draft () { return draft }
    }
  }

  return { mount, WORDS, TABS, empty, counted, body, blocked, endColour }
})

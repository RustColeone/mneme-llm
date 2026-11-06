// The tuner's page: open her gut file (and her memory file), change her settings, save the changed files. The files are
// opened with sql.js in this browser and never leave it. Her settings are the page every program that keeps her draws
// (settings.js: dsh-mneme-llm's page/settings.js, word for word), in four tabs, Her · People · Memory · Gut, over the
// open files (tune.js `settingsView` and `settle`, which change them as mneme-llm's own Python does): its Save puts
// the changes in the open files at once, all of them or none; Save the files, below, downloads each changed file, and
// Discard opens it again as it was. Her star map is drawn above them. One language at a time, English or Chinese.
(function () {
  'use strict'
  const T = window.Tune
  const S = window.StarMap
  const SQL_BASE = 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/'
  const KEPT = 'mneme-llm-tune-language'

  const EN = {
    'page.title': 'Tuner',
    'nav.architecture': 'Architecture',
    'lang.other': '中文',
    'lang.label': 'Show this page in Chinese',
    'intro.title': 'Tune her',
    'intro.text': 'Open her gut file, and her memory file if you like, change her settings in four tabs (the same page as in the programs that keep her), and save the changed files. Everything happens in this browser: the files are not sent anywhere.',
    'intro.stop': 'Stop her before opening her files, so that everything she has written is in the one file. Put each saved file in place of the old one before she starts again. A file beside it whose name ends in -wal means she has not fully stopped.',
    'drop.title': 'Drop her files here',
    'drop.pick': 'Choose files',
    'drop.hint': 'Her gut file and her memory file (SQLite), and her starter (.json.gz) for her star map. Which is which is read from the file itself.',
    'settings.title': 'Her gut',
    'file.starter': 'Her starter',
    'file.memory': 'Her memory',
    'file.close': 'Close',
    'file.changed': 'changed, not saved',
    'file.closeConfirm': '{name} has unsaved changes. Close it anyway?',
    'file.replaceConfirm': '{name} has unsaved changes. Open {other} in its place?',
    'file.space': 'Space',
    'error.notSqlite': '{name} is not an SQLite file.',
    'error.notHers': '{name} is neither a gut file nor a memory file.',
    'error.schema': '{name} has schema {found}; this page reads schema 2. Run python -m mneme_llm.migrate on it first.',
    'error.read': '{name} could not be read: {error}',
    'error.starter': '{name} could not be read as a starter: {error}',
    'error.sql': 'SQLite could not be loaded ({error}). The page fetches sql.js from cdnjs, so it needs the internet.',
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
    'settings.badTau': 'tau is a number above 0',
    'map.title': 'Star map: her heart and the people she knows',
    'map.caption': 'Each dot is one thing she notices, placed toward the feeling it pulls her to; the brighter, the more it leans. The lines are her arms: how much more or less of each feeling she has now than when she was born (the ring). The big stars are people.',
    'map.counts': '{stars} brightest of {rows} · arms from her last {probed} lessons',
    'map.born': '{stars} brightest of {rows} · arms as born until 20 lessons ({probed} so far)',
    'map.view': 'View',
    'map.turn': 'Drag to turn it; a few seconds later it turns slowly by itself. The two ends of each bar sit side by side.',
    'map.slept': 'Her heart as of her last sleep: the {waiting} lessons since are not in it yet; she learns them again when she wakes.',
    'map.unknown': 'She was born from a starter, which is not open here, so each arm is drawn as she was born. Drop her starter (the .json.gz file her host gives her) beside her files to see how far she has grown.',
    'map.blank': 'She was born with no starter: her arms are measured from a blank heart.',
    'map.none': 'Her heart is not in this file yet: wake her once first.',
    saved: 'Saved {files}. Put each in place of the old file before she starts again.',
    discardConfirm: 'Discard every unsaved change?',
    'settings.page': 'Her settings',
    'settings.intro': 'Her settings, in four tabs, from the files you opened. Saving puts the changes in the open files; save the files themselves below.',
    'settings.needFile': 'Open her gut file or her memory file, and her settings are here.',
    'files.unsaved': 'Files changed and not saved: {count}',
    'files.none': 'No changed files',
    'files.save': 'Save the files',
    'files.discard': 'Discard',
    'error.zone': 'a time zone is UTC+8 and the like (at most 14 hours from UTC), an IANA name such as Asia/Shanghai, or nothing for the machine\'s',
    'error.memoryValue': '{key} is a number from {low} to {high}',
    'error.memoryKey': '{key} is not a memory setting here',
    'error.unique': '{subject} is her {role} already: there is one',
    'error.role': '{role} is not one of her roles',
    'error.part': 'not a part of her settings: {parts}',
    'error.save': 'that is not a save this page makes',
    'error.herName': 'her name is some words, at most {most} characters',
    'error.card': 'a Character Card is some words',
    'error.cardLong': 'a Character Card is at most {most} characters',
    'error.noCard': 'there is no Character Card yet: write it first',
    'error.noHolder': 'nobody\'s Character Card is in this file yet',
    'error.noMemory': 'open her memory file first',
    'error.noGut': 'open her gut file first',
    'error.subject': 'a person is their account, such as discord:42',
    'error.end': '{end} is not one of her feelings',
    'error.locked': 'a lock is on or off'
  }
  const ZH = {
    'page.title': '调校',
    'nav.architecture': '架构',
    'lang.other': 'English',
    'lang.label': '用英文显示这个页面',
    'intro.title': '调校她',
    'intro.text': '打开她的直觉文件（也可以同时打开她的记忆文件），在四个分页里改她的设置（和运行她的程序里是同一个页面），再把改过的文件保存下来。一切都在这个浏览器里完成，文件不会被发送到任何地方。',
    'intro.stop': '打开文件之前先让她停下来，这样她写下的一切都在这一个文件里。她再次启动之前，用保存下来的文件替换旧文件。如果旁边还有一个名字以 -wal 结尾的文件，说明她还没有完全停下。',
    'drop.title': '把她的文件拖到这里',
    'drop.pick': '选择文件',
    'drop.hint': '她的直觉文件和记忆文件（SQLite），以及画星图用的 starter 文件（.json.gz）。哪个是哪个，会从文件本身读出来。',
    'settings.title': '她的直觉',
    'file.starter': '她的 starter 文件',
    'file.memory': '她的记忆',
    'file.close': '关闭',
    'file.changed': '改过了，还没保存',
    'file.closeConfirm': '{name} 还有未保存的改动。仍然关闭吗？',
    'file.replaceConfirm': '{name} 还有未保存的改动。要打开 {other} 来替换它吗？',
    'file.space': '空间',
    'error.notSqlite': '{name} 不是 SQLite 文件。',
    'error.notHers': '{name} 既不是直觉文件，也不是记忆文件。',
    'error.schema': '{name} 的 schema 是 {found}，这个页面只读 schema 2。请先对它运行 python -m mneme_llm.migrate。',
    'error.read': '无法读取 {name}：{error}',
    'error.starter': '无法把 {name} 读取为 starter 文件：{error}',
    'error.sql': '无法加载 SQLite（{error}）。这个页面要从 cdnjs 获取 sql.js，所以需要联网。',
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
    'settings.badTau': 'tau 要大于 0',
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
    saved: '已保存 {files}。她再次启动之前，用它们替换旧文件。',
    discardConfirm: '放弃所有未保存的改动吗？',
    'settings.page': '她的设置',
    'settings.intro': '她的设置，分成四页，来自你打开的文件。保存会把改动写进打开的文件；文件本身在下面保存。',
    'settings.needFile': '打开她的直觉文件或记忆文件，她的设置就会出现在这里。',
    'files.unsaved': '{count} 个改过的文件还没保存',
    'files.none': '没有改过的文件',
    'files.save': '保存文件',
    'files.discard': '放弃',
    'error.zone': '时区写成 UTC+8 这样（离 UTC 不超过 14 小时），或者 Asia/Shanghai 这样的 IANA 名字；空着就用这台机器的时区',
    'error.memoryValue': '{key} 是 {low} 到 {high} 之间的数',
    'error.memoryKey': '{key} 不是这里能设的记忆设置',
    'error.unique': '{subject} 已经是她的{role}了：这个角色只能有一个人',
    'error.role': '{role} 不是她的角色',
    'error.part': '不是她设置里的一部分：{parts}',
    'error.save': '这不是这个页面会发出的保存',
    'error.herName': '她的名字要有字，最多 {most} 个字符',
    'error.card': '角色卡要有内容',
    'error.cardLong': '角色卡最多 {most} 个字符',
    'error.noCard': '还没有角色卡：先写好它',
    'error.noHolder': '这个文件里还没有任何人的角色卡',
    'error.noMemory': '先打开她的记忆文件',
    'error.noGut': '先打开她的直觉文件',
    'error.subject': '一个人就是他的账号，比如 discord:42',
    'error.end': '{end} 不是她的一种感觉',
    'error.locked': '锁只有开和关'
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

  // ---- what is open ---------------------------------------------------------------------------------------------
  const KINDS = ['gut', 'memory']
  const state = {
    files: {}, // kind → {name, bytes: as opened or last saved, db, changes: Map of what changed}
    base: {}, // kind → the view as opened or last saved, for telling a change undone from one made
    gut: null, memory: null, space: null, status: null,
    starter: null, // her starter, for her star map: {name, born: her heart as she was born}
    map: null, // her star map, made again after every change to her gut file
    mapError: null // or why it could not be made
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
      else state.map = null
      render()
    })
  }

  /** How many open files are changed and not saved. */
  function count () {
    return KINDS.filter(kind => state.files[kind]?.changes.size).length
  }

  function save () {
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
        text('span', { class: 'file-changes' }, () => file.changes.size ? t('file.changed') : ''),
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
      redrawMap()
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

  /** Her star map again, in its place (after a save, or a change of view), leaving the rest of the page as it is. */
  function redrawMap () {
    if (!mapHolder || !mapHolder.isConnected) return render()
    sky.stop?.()
    sky.stop = null
    mapHolder.replaceChildren(starMap())
  }
  let mapHolder = null

  // ---- her settings: the page every program that keeps her draws ------------------------------------------------------
  let page = null
  const opened = () => ({ gut: state.files.gut?.db || null, memory: state.files.memory?.db || null, space: state.space })
  const same = (one, other) => one.length === other.length && one.every((value, index) => value === other[index])
  // (sql.js writes a file its own way: one is compared with its copy from just before a save, not with what was opened)

  /** A save from the page: checked and made by tune.js, to the open files, all of it or none (a copy of each is kept
   * until it is done, and opened again if anything goes wrong). The settings as they are then. */
  function change (asked) {
    return new Promise((resolve, reject) => {
      queue(async () => {
        const kinds = KINDS.filter(kind => state.files[kind])
        const before = Object.fromEntries(kinds.map(kind => [kind, state.files[kind].db.export()]))
        try {
          await T.settle(opened(), asked)
        } catch (error) {
          const SQL = await sqlReady
          for (const kind of kinds) {
            state.files[kind].db.close()
            state.files[kind].db = T.open(SQL, before[kind]).db
          }
          reject(new Error(errorText(error)))
          return
        }
        for (const kind of kinds) {
          if (!same(state.files[kind].db.export(), before[kind])) state.files[kind].changes.set('settings', true)
        }
        await refresh('gut')
        await refresh('memory')
        resolve(await T.settingsView(opened()))
        redrawMap()
        update()
      })
    })
  }

  function settingsCard () {
    page?.destroy()
    page = null
    const box = el('div', { class: 'settings-box' })
    if (!window.MnemeSettings) return null
    page = window.MnemeSettings.mount(box, {
      language: chinese() ? 'zh' : 'en',
      dark: () => Boolean(darkScheme?.matches),
      words: { en: { 'page.intro': EN['settings.intro'] }, zh: { 'page.intro': ZH['settings.intro'] } },
      load: async () => {
        await chain
        return T.settingsView(opened())
      },
      save: change
    })
    return el('section', { class: 'card settings-card' }, el('h2', null, t('settings.page')), box)
  }

  function statusLine () {
    return el('span', { class: state.status?.error ? 'status error' : 'status', role: 'status' },
      state.status?.text || '')
  }

  function savebar () {
    const bar = $('#savebar')
    const open = KINDS.some(kind => state.files[kind])
    bar.hidden = !open
    if (!open) {
      document.documentElement.style.setProperty('--savebar', '0px')
      return
    }
    const changes = count()
    bar.replaceChildren(
      el('span', { class: changes ? 'changed' : 'meta' }, changes ? t('files.unsaved', { count: changes })
        : t('files.none')),
      statusLine(),
      el('span', { class: 'spacer' }),
      button(t('files.discard'), discard, { disabled: !changes }),
      button(t('files.save'), save, { kind: 'primary', disabled: !changes }))
    document.documentElement.style.setProperty('--savebar', `${bar.offsetHeight}px`) // (the page's own bar sits above it)
  }

  function render () {
    updaters = []
    document.documentElement.lang = chinese() ? 'zh-CN' : 'en'
    document.title = `${t('page.title')} · mneme-llm`
    header()
    sky.stop?.()
    sky.stop = null
    const parts = [intro(), files()]
    mapHolder = state.gut ? el('div', { class: 'sky-holder' }, starMap()) : null
    if (mapHolder) parts.push(mapHolder)
    parts.push(state.gut || state.memory ? settingsCard() : el('p', { class: 'hint center' }, t('settings.needFile')))
    $('#main').replaceChildren(...parts.filter(Boolean))
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

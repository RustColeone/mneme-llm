// The tuner's file logic: plain functions over a sql.js `Database`, with no page in sight, so they run in node as
// well as in the browser. Each change is made to the file exactly as mneme-llm's own Python makes it:
//   her gut file    Gut.configure, set_age, tune, tune_person, forget, write_side, drop_side, lock_side, unlock_side
//                   (mneme_llm/gut.py); its state rows are gzip-compressed UTF-8 JSON
//   her memory file Relations._of, set, lock, unlock and Config.set (mneme_llm/relations.py, config.py); its config
//                   values are plain JSON
// Times are seconds. A function that changes the file throws a TuneError (a `code` the page words, and `values`) for a
// value Python would refuse, before anything is written.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory()
  else root.Tune = factory()
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict'

  // Her feelings (`BARS` in gut.py): [bar, 中文, the end that leans away or null, the other end]; an end is
  // [the word, 中文].
  const BARS = [
    ['mood', '心情', ['sad', '难过'], ['happy', '开心']],
    ['security', '安心', ['worried', '担心'], ['secure', '踏实']],
    ['composure', '理智', ['hysterical', '慌乱·崩溃'], ['calm', '平静']],
    ['warmth', '亲近', ['scornful', '嫌弃'], ['sweet', '甜蜜']],
    ['manner', '态度', ['stern', '严厉'], ['tender', '温柔']],
    ['temper', '脾气', ['irritable', '易怒'], ['peaceable', '平和']],
    ['stance', '姿态', ['wronged', '委屈'], ['defiant', '不服']],
    ['pride', '骄傲', ['ashamed', '羞愧'], ['proud', '得意']],
    ['playfulness', '举止', ['shy', '害羞'], ['cheeky', '调皮']],
    ['courage', '胆量', ['timid', '胆小'], ['bold', '大胆']],
    ['sociability', '社交', ['withdrawn', '内向'], ['outgoing', '外向']],
    ['jealousy', '吃醋', null, ['jealous', '吃醋']],
    ['aching', '心疼', null, ['aching', '心疼']],
    ['trust', '信任', ['suspicious', '猜疑'], ['trusting', '信任']]
  ]
  const ENDS = BARS.flatMap(([, , left, right]) => (left ? [left[0], right[0]] : [right[0]]))
  const CHINESE = Object.fromEntries(BARS.flatMap(([bar, zh, left, right]) =>
    [[bar, zh], ...(left ? [left] : []), right]))

  // Every name a side can have (`NAMES` in gut.py), in its order.
  const NAMES = [
    '傲娇', '傲沉', '病娇', '病切', '弱娇', '冰美人', '酷娇', '率直冷', '凛娇', '暴娇', '郁娇', '慵懒', '急性子', '三无', '无口', '文静',
    '直率', '诚实', '刺头', 'KY', '读空气', '无铁炮', '凶暴', '高飞车', '高傲', '笨蛋', '天然呆', '天然疯', '天然黑', '天然萌', '认真',
    '电波', '冒失', '调皮', '工口', '毒舌', '元气', '强气', '狂气', '弱气', '怕羞', '爱哭鬼', '醋缸', '好奇', '耿直', '八卦', '变态',
    '变态萌', '恶心萌', '迟钝', '富有正义感', '地雷系', '博学', '情绪化', '无感情', '自来熟', '怕生', '怕麻烦', '情种', '阳角', '阴角', '多疑',
    '幸灾乐祸', '任性', '贪玩', '暴躁', '勇敢', '腹黑', '腹白', '复合型腹黑', '可靠', '无心', '热血', '外柔内刚', '外热内冷', '外冷内热', '女王',
    '戏精', '猥琐', '不懂爱', '多重人格', '性格切换', '无节操', '温柔', '玻璃心', '老好人', '优柔寡断', 'S属性', 'M属性', '支配者', '服从者',
    '小恶魔', '贱萌', '常识人', '无常识', '坦率', '别扭', '单纯', '清纯', '清楚系', '孤僻', '厌世', '护短', '闷骚', '恋爱脑', '酒品差',
    '醉酒变纯情', '反社会人格', '恶德', '不择手段', '有原则', '执着', '固执', '偏执', '脱线', '自负', '自卑', '谨慎', '神经质', '大智若愚',
    '自我意识过剩', '亦正亦邪', '墙头草', '欺软怕硬', '鬼畜', '沉重', '老实人', '愉悦犯', '高攻低防', '小天使', '和平主义者', '节能主义', '完美主义者',
    '贪婪', '吝啬', '野心家', '伪阳角', '伪阴角', '专一', '反战', '御姐', '软妹', '熟女', '小绿茶'
  ]

  const TAU = 150 // lessons: how fast her heart grows up (`TAU` in gut.py)
  const FLOOR = 0.04 // the share of her young pace left once grown (`FLOOR`)
  const COUNTS = 20, MOST = 0.7 // what is different with a person counts half at 20 lessons, never more than MOST
  const GROWS = 6 // how much of her a side that has just grown is (`GROWS`)
  const HOLD = 30 * 86400 // she stays in a side this long at least (`HOLD`)
  const DAY = 86400
  // The roles mneme-llm has built in (`ROLES` in relations.py), for a space whose config has none.
  const ROLES = [
    { key: 'creator', floor: 80, ceiling: 100, start: 100, fades: false, unique: true, names: {} },
    { key: 'family', floor: 60, ceiling: 100, start: 80, fades: true, unique: false, names: {} },
    { key: 'friend', floor: 20, ceiling: 90, start: 50, fades: true, unique: false, names: {} },
    { key: 'acquaintance', floor: 0, ceiling: 60, start: 20, fades: true, unique: false, names: {} }
  ]
  const LIKING = 0.25, FADE_DAYS = 30 // `relations.liking` and `relations.fade_days` by default
  const SCHEMA = '2' // the memory file's schema this page reads

  class TuneError extends Error {
    constructor (code, values = {}) {
      super(`${code}${Object.keys(values).length ? ' ' + JSON.stringify(values) : ''}`)
      this.name = 'TuneError'
      this.code = code
      this.values = values
    }
  }
  const fail = (code, values) => { throw new TuneError(code, values) }
  const isNumber = value => typeof value === 'number' && Number.isFinite(value)
  const within = (value, low, high) => isNumber(value) && value >= low && value <= high
  const isTable = value => value !== null && typeof value === 'object' && !Array.isArray(value)
  const nowSeconds = () => Date.now() / 1000

  // ---- the file -----------------------------------------------------------------------------------------------------
  /** The file's bytes ready for sql.js: a file in WAL mode (header bytes 18 and 19 both 2) is marked as a rollback-
   * journal file (both 1). That is right only while no -wal file holds changes, which is why she is stopped first;
   * Python sets WAL again when it next opens the file. A copy: the bytes given are left as they are. */
  function unwal (bytes) {
    const copy = new Uint8Array(bytes)
    if (copy.length >= 100 && copy[18] === 2 && copy[19] === 2) copy[18] = copy[19] = 1
    return copy
  }

  /** Whether the bytes begin as an SQLite file does. */
  function isSqlite (bytes) {
    const magic = 'SQLite format 3\u0000'
    return bytes.length >= 100 && [...magic].every((char, at) => bytes[at] === char.charCodeAt(0))
  }

  function tables (db) {
    return new Set(rows(db, "select name from sqlite_master where type = 'table'").map(row => row.name))
  }

  /** 'gut', 'memory', or null for a file that is neither, read from its tables. */
  function kindOf (db) {
    const found = tables(db)
    if (['lessons', 'people', 'sightings', 'sides', 'state'].every(name => found.has(name))) return 'gut'
    if (['meta', 'config', 'relationships'].every(name => found.has(name))) return 'memory'
    return null
  }

  /** An opened file: sql.js's `SQL` (from initSqlJs) and the file's bytes. {db, kind}; a memory file of another
   * schema is refused. */
  function open (SQL, bytes) {
    const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
    if (!isSqlite(data)) fail('notSqlite')
    const db = new SQL.Database(unwal(data))
    try {
      const kind = kindOf(db)
      if (!kind) fail('notHers')
      if (kind === 'memory') checkMemory(db)
      return { db, kind }
    } catch (error) {
      db.close()
      throw error
    }
  }

  function rows (db, sql, params = []) {
    const statement = db.prepare(sql)
    try {
      statement.bind(params)
      const found = []
      while (statement.step()) found.push(statement.getAsObject())
      return found
    } finally {
      statement.free()
    }
  }
  const row = (db, sql, params) => rows(db, sql, params)[0] ?? null

  /** Several writes that land together or not at all (sql.js is one thread: nothing else runs in between). */
  function together (db, write) {
    db.run('begin')
    try {
      const result = write()
      db.run('commit')
      return result
    } catch (error) {
      db.run('rollback')
      throw error
    }
  }

  // ---- gzip ---------------------------------------------------------------------------------------------------------
  async function through (bytes, stream) {
    const piped = new Blob([bytes]).stream().pipeThrough(stream)
    return new Uint8Array(await new Response(piped).arrayBuffer())
  }
  const gzip = text => through(new TextEncoder().encode(text), new CompressionStream('gzip'))
  const gunzip = async bytes => new TextDecoder().decode(await through(bytes, new DecompressionStream('gzip')))

  /** A state row of her gut (`Gut._get`): the JSON it keeps, or null. */
  async function getState (db, key) {
    const found = row(db, 'select value from state where key = ?', [key])
    return found ? JSON.parse(await gunzip(found.value)) : null
  }

  /** Values to write, compressed first, then written together (`Gut._put`). */
  async function packed (values) {
    return Promise.all(Object.entries(values).map(async ([key, value]) => [key, await gzip(JSON.stringify(value))]))
  }
  function putPacked (db, pairs) {
    for (const [key, blob] of pairs) db.run('insert or replace into state values (?, ?)', [key, blob])
  }
  async function putState (db, values) {
    const pairs = await packed(values)
    together(db, () => putPacked(db, pairs))
  }

  // ---- her gut: reading ---------------------------------------------------------------------------------------------
  const DEFAULTS = () => ({ tau: TAU, sensitivity: 0, nudge: {}, locked: false, people: {}, side: null })

  /** Her settings, an older file's merged over the defaults as `Gut.wake` does. */
  async function settingsOf (db) {
    const kept = await getState(db, 'settings')
    return { ...DEFAULTS(), ...(isTable(kept) ? kept : {}) }
  }

  /** Her slow levels as `Tone` keeps them. */
  function toneOf (kept) {
    kept = isTable(kept) ? kept : {}
    return { lately: { ...(kept.lately || {}) }, usual: { ...(kept.usual || {}) }, shift: { ...(kept.shift || {}) },
      seen: Math.trunc(Number(kept.seen) || 0) }
  }

  /** Where a bar is (`Tone.level`): its second end less its first (nothing for a one-sided bar), lately (with what
   * was set by hand) or usually. */
  function level (tone, bar, which = 'lately') {
    const [, , left, right] = BARS.find(item => item[0] === bar)
    const at = end => which === 'lately' ? (tone.lately[end] || 0) + (tone.shift[end] || 0) : (tone.usual[end] || 0)
    return at(right[0]) - (left ? at(left[0]) : 0)
  }

  /** How much of how she is with a person is theirs (`Net.weight`): set by hand, or learned as she comes to know them,
   * at most MOST, less for every talking day without them. */
  function personWeight (heart, settings, subject) {
    const found = heart?.people?.[subject]
    const hand = settings.people?.[subject] || {}
    if (found && hand.weight !== undefined && hand.weight !== null) return Number(hand.weight)
    return found ? Math.min(MOST, found.n / (found.n + COUNTS)) * found.fade : 0
  }
  const learnedWeight = found => found ? Math.min(MOST, found.n / (found.n + COUNTS)) * found.fade : 0

  /** Everything the page shows of her gut. */
  async function gutView (db, now = nowSeconds()) {
    const settings = await settingsOf(db)
    const heart = await getState(db, 'heart')
    const tone = toneOf(await getState(db, 'feelings'))
    const held = { names: [], since: 0, ...(await getState(db, 'held') || {}) }
    const tau = Number(settings.tau)
    const age = heart ? Number(heart.age) || 0 : 0
    const subjects = new Set([...Object.keys(heart?.people || {}), ...Object.keys(settings.people || {}),
      ...rows(db, 'select subject from people').map(item => item.subject),
      ...rows(db, 'select distinct subject from sightings').map(item => item.subject)])
    subjects.delete('')
    const language = Object.fromEntries(rows(db, 'select subject, language from people')
      .map(item => [item.subject, item.language]))
    const people = [...subjects].sort().map(subject => {
      const found = heart?.people?.[subject] || null
      const hand = settings.people?.[subject] || {}
      return { subject, known: Boolean(found), lessons: found ? Math.round(found.n) : 0, fade: found ? found.fade : 1,
        learned: learnedWeight(found), weight: personWeight(heart, settings, subject),
        set: hand.weight === undefined || hand.weight === null ? null : Number(hand.weight),
        locked: Boolean(hand.locked), nudge: { ...(hand.nudge || {}) }, language: language[subject] || '' }
    })
    const bars = BARS.map(([bar, zh, left, right]) => ({ bar, zh, ends: [left ? left[0] : null, right[0]],
      lately: level(tone, bar), usual: level(tone, bar, 'usual') }))
    const ends = ENDS.map(end => ({ end, zh: CHINESE[end], nature: Number(settings.nudge?.[end] || 0),
      now: Number(tone.shift[end] || 0), lately: (tone.lately[end] || 0) + (tone.shift[end] || 0),
      usual: tone.usual[end] || 0 }))
    const sides = rows(db, 'select name, what, own from sides order by rowid')
    const side = settings.side ? { name: settings.side.name, often: Number(settings.side.often) } : null
    const keep = side && sides.some(item => item.name === side.name) ? [side.name]
      : (held.names || []).filter(name => sides.some(item => item.name === name))
    return {
      settings, hasHeart: Boolean(heart), tau, age, lessons: heart ? heart.lessons : 0,
      grown: 1 - Math.exp(-age / tau), learning: FLOOR + (1 - FLOOR) * Math.exp(-age / tau),
      sensitivity: Number(settings.sensitivity), locked: Boolean(settings.locked), people, bars, ends, tone, sides,
      side, held: { names: held.names || [], since: Number(held.since) || 0 }, holding: keep,
      days: Math.max(0, Math.round((Number(held.since || 0) + HOLD - now) / DAY))
    }
  }

  // ---- her gut: changing --------------------------------------------------------------------------------------------
  // Python settles the lessons waiting for her sleep before her heart or a person is locked or unlocked, before her age
  // is set and before a person is forgotten (`Gut._settle`); a page cannot, since only a sleep teaches them. That is
  // fine: the heart in the file is as of her last sleep, and the lessons since are taught again when she wakes, under
  // what is saved here.

  /** `Gut.configure`: tau (lessons, above 0), sensitivity (-1 to 1), her heart locked. The settings as they are now. */
  async function configure (db, { tau, sensitivity, locked } = {}) {
    if (locked !== undefined && typeof locked !== 'boolean') fail('locked')
    if (tau !== undefined && !(isNumber(tau) && tau > 0)) fail('tau')
    if (sensitivity !== undefined && !within(sensitivity, -1, 1)) fail('sensitivity')
    const settings = await settingsOf(db)
    if (locked !== undefined) settings.locked = locked
    if (tau !== undefined) settings.tau = tau
    if (sensitivity !== undefined) settings.sensitivity = sensitivity
    await putState(db, { settings })
    return settings
  }

  /** `Gut.set_age`: how grown up her heart is, in lessons; 0 makes her young again, forgetting nothing. */
  async function setAge (db, lessons = 0) {
    if (!(isNumber(lessons) && lessons >= 0)) fail('age')
    const heart = await getState(db, 'heart')
    if (!heart) fail('noHeart')
    heart.age = lessons
    await putState(db, { heart })
  }

  /** `Gut.tune`: one end by hand. `now` (-1 to 1): how much more or less of it she feels lately than usual, fading as
   * she lives; 0 takes it away. `nature` (-3 to 3): a nudge to who she is; 0 removes it. */
  async function tune (db, end, { now, nature } = {}) {
    if (!ENDS.includes(end)) fail('end', { end })
    if (now !== undefined && !within(now, -1, 1)) fail('now')
    if (nature !== undefined && !within(nature, -3, 3)) fail('nature')
    const values = {}
    if (now !== undefined) {
      const tone = toneOf(await getState(db, 'feelings'))
      if (now) tone.shift[end] = now
      else delete tone.shift[end]
      values.feelings = tone
    }
    if (nature !== undefined) {
      const settings = await settingsOf(db)
      settings.nudge = { ...(settings.nudge || {}), [end]: nature }
      if (!nature) delete settings.nudge[end]
      values.settings = settings
    }
    await putState(db, values)
  }

  /** `Gut.tune_person`: how she is with one person, by hand. `end` with `nature` (-3 to 3; 0 removes it), `weight`
   * (0 to 1, or 'learned'), `locked`. What is set for them, as it is now (a person with nothing set is removed). */
  async function tunePerson (db, subject, { end, nature, weight, locked } = {}) {
    if (typeof subject !== 'string' || !subject.trim()) fail('subject')
    if ((end === undefined) !== (nature === undefined)) fail('nudge')
    if (end !== undefined && !ENDS.includes(end)) fail('end', { end })
    if (nature !== undefined && !within(nature, -3, 3)) fail('nature')
    if (weight !== undefined && weight !== 'learned' && !within(weight, 0, 1)) fail('weight')
    if (locked !== undefined && typeof locked !== 'boolean') fail('locked')
    const settings = await settingsOf(db)
    settings.people = { ...(settings.people || {}) }
    let hand = { ...(settings.people[subject] || {}) }
    if (nature !== undefined) {
      const nudge = { ...(hand.nudge || {}), [end]: nature }
      hand.nudge = Object.fromEntries(Object.entries(nudge).filter(([, value]) => value))
    }
    if (weight !== undefined) hand.weight = weight === 'learned' ? null : weight
    if (locked !== undefined) hand.locked = locked
    hand = Object.fromEntries(Object.entries(hand).filter(([, value]) => value !== null && value !== undefined &&
      value !== false && !(isTable(value) && !Object.keys(value).length)))
    if (Object.keys(hand).length) settings.people[subject] = hand
    else delete settings.people[subject]
    await putState(db, { settings })
    return hand
  }

  /** `Gut.forget`: how she is with them goes, their name leaves the lessons they taught, and so do the sides only they
   * wanted. What they did to her heart stays. How many lessons lost their name. */
  async function forget (db, subject) {
    if (typeof subject !== 'string' || !subject) fail('subject')
    const settings = await settingsOf(db)
    const heart = await getState(db, 'heart')
    const values = {}
    if (heart) {
      delete (heart.people || {})[subject]
      values.heart = heart
    }
    if (settings.people && Object.hasOwn(settings.people, subject)) {
      delete settings.people[subject]
      values.settings = settings
    }
    const pairs = await packed(values)
    return together(db, () => {
      db.run("update lessons set subject = '' where subject = ?", [subject])
      const gone = db.getRowsModified()
      db.run('delete from people where subject = ?', [subject])
      db.run('delete from sightings where subject = ?', [subject])
      db.run('delete from sides where own = 0 and name not in (select name from sightings where more = 1)')
      putPacked(db, pairs)
      return gone
    })
  }

  const sentence = what => String(what ?? '').split(/\s+/).filter(Boolean).join(' ')
  function sideRow (db, name) {
    return row(db, 'select name, what, own from sides where name = ?', [name])
  }

  /** A side's sentence by hand (`Gut.write_side`), a new side or a better sentence: how much of her it is stays as it
   * was (0 for a new one; `sideWeight` sets it). One line: whitespace runs become one space, as `Gut.lock_side`
   * writes a sentence. */
  function writeSide (db, name, what) {
    if (!NAMES.includes(name)) fail('name', { name })
    const text = sentence(what)
    if (!text) fail('what')
    const found = sideRow(db, name)
    db.run('insert or replace into sides values (?, ?, ?)', [name, text, found ? found.own : 0])
  }

  /** How much of her a side is, as a person set it (`own`, 0 or more; 0 is as if nobody had). */
  function sideWeight (db, name, own) {
    if (!within(own, 0, Infinity)) fail('own')
    if (!sideRow(db, name)) fail('notSide', { name })
    db.run('update sides set own = ? where name = ?', [own, name])
  }

  /** `Gut.drop_side`: gone, and what taught it with it, so growing it again starts over. Locked, it is unlocked.
   * Whether it was one of her sides. */
  async function dropSide (db, name) {
    const settings = await settingsOf(db)
    const pairs = settings.side && settings.side.name === name ? await packed({ settings: { ...settings, side: null } })
      : []
    return together(db, () => {
      putPacked(db, pairs)
      db.run('delete from sides where name = ?', [name])
      const found = db.getRowsModified() > 0
      db.run('delete from sightings where name = ?', [name])
      return found
    })
  }

  /** `Gut.lock_side`: she is in this side from now on, shown in `often` of her turns (0 to 1). `what`: its sentence,
   * for a side she does not have yet or a better one. */
  async function lockSide (db, name, often = 1, what = undefined) {
    if (!NAMES.includes(name)) fail('name', { name })
    if (!within(often, 0, 1)) fail('often')
    const settings = await settingsOf(db)
    if (!sentence(what) && !sideRow(db, name)) fail('notSide', { name })
    settings.side = { name, often }
    const pairs = await packed({ settings })
    together(db, () => {
      if (sentence(what)) writeSide(db, name, what)
      putPacked(db, pairs)
    })
  }

  /** `Gut.unlock_side`: her sides are drawn by weight again; she stays in the one she was locked in for a month
   * first. */
  async function unlockSide (db, now = nowSeconds()) {
    const settings = await settingsOf(db)
    const fixed = settings.side
    if (!fixed) return
    settings.side = null
    await putState(db, { settings, held: { names: [fixed.name], since: now } })
  }

  // ---- her memory: reading ------------------------------------------------------------------------------------------
  function checkMemory (db) {
    const found = row(db, "select value from meta where key = 'schema_version'")
    if (!found || String(found.value) !== SCHEMA) fail('schema', { found: found ? String(found.value) : '' })
  }

  /** The spaces (companions) the file holds. */
  function spaces (db) {
    return rows(db, 'select space from relationships union select space from config order by space')
      .map(item => item.space)
  }

  /** A config value as stored (JSON), or undefined. */
  function stored (db, space, key) {
    const found = row(db, 'select value from config where space = ? and key = ?', [space, key])
    if (!found) return undefined
    try {
      return JSON.parse(found.value)
    } catch {
      return undefined
    }
  }

  /** The space's roles (`Config.roles`), the built-in ones when its config has none that pass. */
  function rolesOf (db, space) {
    const kept = stored(db, space, 'roles')
    if (!Array.isArray(kept) || !kept.length || !kept.every(item => isTable(item) && typeof item.key === 'string')) {
      return ROLES.map(item => ({ ...item }))
    }
    const found = kept.map(item => ({ key: item.key, floor: item.floor ?? 0, ceiling: item.ceiling ?? 100,
      start: item.start ?? 50, fades: item.fades ?? true, unique: item.unique ?? false, names: item.names || {} }))
    const sound = found.every(item => [item.floor, item.ceiling, item.start].every(isNumber) &&
      item.floor >= 0 && item.floor <= item.start && item.start <= item.ceiling && item.ceiling <= 100)
    return sound ? found : ROLES.map(item => ({ ...item }))
  }

  /** A role by its key; one the space does not know has the widest band (`Relations._role`). */
  function roleOf (roles, key) {
    return roles.find(item => item.key === key) ||
      { key, floor: 0, ceiling: 100, start: 50, fades: true, unique: false, names: {} }
  }

  /** Closeness locked by hand (`relations.locked`): subject → where they stay. Nothing, for a value that does not
   * pass (as Python takes the default then). */
  function locksOf (db, space) {
    const kept = stored(db, space, 'relations.locked')
    if (!isTable(kept)) return {}
    const sound = Object.entries(kept).every(([subject, value]) => subject.trim() && subject.length <= 200 &&
      within(value, 0, 100))
    return sound ? { ...kept } : {}
  }

  function numberOf (db, space, key, low, high, otherwise) {
    const kept = stored(db, space, key)
    return within(kept, low, high) ? kept : otherwise
  }
  const likingOf = (db, space) => numberOf(db, space, 'relations.liking', 0, 100, LIKING)
  const fadeDaysOf = (db, space) => numberOf(db, space, 'relations.fade_days', 0, 1000000, FADE_DAYS)

  /** Closeness now (`Relations._of`): the locked value, else faded by the days without them when the role fades,
   * and always within the role's band. */
  function closenessOf (relationship, role, locks, fadeDays, now) {
    let closeness = relationship.closeness
    const locked = locks[relationship.subject]
    if (locked !== undefined) closeness = locked
    else if (role.fades && fadeDays > 0) closeness -= Math.max(0, now - relationship.updated_at) / (fadeDays * DAY)
    return Math.min(role.ceiling, Math.max(role.floor, closeness))
  }

  /** Everything the page shows of one space of her memory. */
  function memoryView (db, space, now = nowSeconds()) {
    const roles = rolesOf(db, space), locks = locksOf(db, space), fadeDays = fadeDaysOf(db, space)
    const people = rows(db, 'select * from relationships where space = ?', [space]).map(item => {
      const role = roleOf(roles, item.role)
      return { subject: item.subject, role: item.role, names: role.names, floor: role.floor, ceiling: role.ceiling,
        fades: role.fades, stored: item.closeness, closeness: closenessOf(item, role, locks, fadeDays, now),
        locked: Object.hasOwn(locks, item.subject) ? locks[item.subject] : null, since: item.since,
        updated_at: item.updated_at }
    }).sort((a, b) => b.closeness - a.closeness || (a.subject < b.subject ? -1 : 1))
    return { space, roles, locks, liking: likingOf(db, space), fadeDays, people }
  }

  // ---- her memory: changing -----------------------------------------------------------------------------------------
  function relationship (db, space, subject) {
    return row(db, 'select * from relationships where space = ? and subject = ?', [space, subject])
  }

  function band (db, space, found, value) {
    const role = roleOf(rolesOf(db, space), found.role)
    if (!within(value, role.floor, role.ceiling)) fail('band', { floor: role.floor, ceiling: role.ceiling })
    return role
  }

  /** `Config.set` for one key: written as Python writes it, origin 'set', at `now`. */
  function setConfig (db, space, key, value, now = nowSeconds()) {
    db.run('insert or replace into config (space, key, value, origin, updated_at) values (?, ?, ?, ?, ?)',
      [space, key, JSON.stringify(value), 'set', now])
  }

  /** A person's closeness by hand, within their role's band (`Relations.set` with the same role): their day of
   * contact is now (never earlier than it was: a clock set back moves no time back). */
  function setCloseness (db, space, subject, value, now = nowSeconds()) {
    const found = relationship(db, space, subject)
    if (!found) fail('noRole', { subject })
    band(db, space, found, value)
    db.run('update relationships set closeness = ?, updated_at = ? where space = ? and subject = ?',
      [value, Math.max(now, found.updated_at), space, subject])
  }

  /** `Relations.lock`: closeness stays at `value` (within the band) until unlocked. */
  function lockCloseness (db, space, subject, value, now = nowSeconds()) {
    const found = relationship(db, space, subject)
    if (!found) fail('noRole', { subject })
    band(db, space, found, value)
    setConfig(db, space, 'relations.locked', { ...locksOf(db, space), [subject]: value }, now)
  }

  /** `Relations.unlock`: closeness moves again, from where it was locked. */
  function unlockCloseness (db, space, subject, now = nowSeconds()) {
    const locks = locksOf(db, space)
    if (!Object.hasOwn(locks, subject)) return
    const found = relationship(db, space, subject)
    const present = found
      ? closenessOf(found, roleOf(rolesOf(db, space), found.role), locks, fadeDaysOf(db, space), now) : null
    delete locks[subject]
    together(db, () => {
      setConfig(db, space, 'relations.locked', locks, now)
      if (found) {
        db.run('update relationships set closeness = ?, updated_at = ? where space = ? and subject = ?',
          [present, Math.max(now, found.updated_at), space, subject])
      }
    })
  }

  /** `relations.liking` (0 to 100): how many points closeness moves for each level of how an exchange moved her. */
  function setLiking (db, space, value, now = nowSeconds()) {
    if (!within(value, 0, 100)) fail('liking')
    setConfig(db, space, 'relations.liking', value, now)
  }

  /** `relations.fade_days` (0 to 1,000,000): closeness fades a point for every this many days without them; 0:
   * never. */
  function setFadeDays (db, space, value, now = nowSeconds()) {
    if (!within(value, 0, 1000000)) fail('fadeDays')
    setConfig(db, space, 'relations.fade_days', value, now)
  }

  return {
    BARS, ENDS, CHINESE, NAMES, TAU, FLOOR, MOST, COUNTS, GROWS, HOLD, ROLES, SCHEMA, TuneError,
    unwal, isSqlite, kindOf, open, rows, gzip, gunzip, getState, putState,
    settingsOf, personWeight, level, gutView, configure, setAge, tune, tunePerson, forget, writeSide, sideWeight,
    dropSide, lockSide, unlockSide,
    checkMemory, spaces, rolesOf, roleOf, locksOf, closenessOf, memoryView, setCloseness, lockCloseness,
    unlockCloseness, setLiking, setFadeDays, setConfig
  }
})

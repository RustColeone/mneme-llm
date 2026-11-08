// Her memory sky, for the tuner: what reminds her of what, from her memory file as it is open here (mneme_llm.links).
// Plain functions with no page in sight, so they run in node as well as in the browser; the drawing takes the canvas
// it draws on.
//
// Every exchange she keeps with one person is a star, as bright as it is kept (its R, as episodes.py reckons it: e^(−t/S)
// over the person's talking days since it was said or last recalled). Every link between two of them is a line, as
// strong as the link is kept (its own R, from links.py), gold once it has been used again since it was born. Stars
// start where they sit in meaning (the first two directions their vectors spread along most), and the links then pull
// the stars they join together, so memories that come to mind together end up near each other. A group is a set of
// stars its links hold together more than they hold anything else (label propagation, weighed by each link's R ×
// (1 + its uses)); the largest few are tinted. The layout and the groups are worked out the same way every time: the
// same file draws the same sky.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory()
  else root.MemorySky = factory()
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict'

  const DAY_STARTS = 4 // a person's day turns at 4 in the morning (`dates.DAY_STARTS`)
  const EPOCH_DAY = 719163 // Python's ordinal of 1 January 1970
  const STARS = 600 // the newest exchanges drawn
  const SPINE = 2 // each star's heaviest links that hold the sky's shape (with every link used again)
  const HOLD = 0.004 // how hard every star is held toward the middle
  const GROUPS = 6, SMALLEST = 6 // groups tinted, and the fewest stars one needs
  const HUES = { dark: ['#8fb8ff', '#ffb38a', '#9be3b0', '#e3a6ff', '#ffe08a', '#8fe3e0'],
    light: ['#2f5fb3', '#b55a1f', '#2c8a4b', '#8a3fb0', '#9a7a00', '#1f8a86'] }

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

  const hasTable = (db, name) => rows(db, "select 1 as one from sqlite_master where type = 'table' and name = ?",
    [name]).length > 0

  /** The talking day of a moment in this browser's time zone, as Python's `dates.talking_day` numbers it. */
  function talkingDay (seconds) {
    const local = new Date((seconds - DAY_STARTS * 3600) * 1000)
    return EPOCH_DAY + Math.floor(Date.UTC(local.getFullYear(), local.getMonth(), local.getDate()) / 86400000)
  }

  /** R of something last renewed on talking day `since` (`links.retention`, `Episodes._kept`). */
  function retention (since, stability, today, days) {
    if (today <= since) return 1
    let after = 0, before = 0 // talking days after `since`, and before `today`
    for (const day of days) {
      if (day > since) after++
      if (day >= today) before++
    }
    const passed = after - before + 1
    return Math.exp(-passed / Math.max(stability, 1e-6))
  }

  /** The people she keeps exchanges with in `space`, the most first: {subject, name, exchanges, links}. */
  function people (db, space) {
    if (!hasTable(db, 'episodes')) return []
    const names = hasTable(db, 'aliases')
      ? Object.fromEntries(rows(db, 'select subject, alias from aliases where space = ?', [space])
        .map(item => [item.subject, item.alias]))
      : {}
    const links = hasTable(db, 'links')
      ? Object.fromEntries(rows(db, 'select subject, count(*) as n from links where space = ? group by subject',
        [space]).map(item => [item.subject, item.n]))
      : {}
    return rows(db, 'select subject, count(*) as n from episodes where space = ? group by subject order by n desc, ' +
      'subject', [space]).map(item => ({ subject: item.subject, name: names[item.subject] || item.subject,
      exchanges: item.n, links: links[item.subject] || 0 }))
  }

  /** The first two directions a set of vectors spreads along most (power iteration, from a fixed start). */
  function plane (vectors) {
    const n = vectors.length, size = vectors[0].length
    const mean = new Float64Array(size)
    for (const vector of vectors) for (let k = 0; k < size; k++) mean[k] += vector[k] / n
    const centred = vectors.map(vector => Float64Array.from(vector, (value, k) => value - mean[k]))
    const directions = []
    for (let which = 0; which < 2; which++) {
      let direction = Float64Array.from({ length: size }, (_, k) => Math.sin(k * 12.9898 + which * 78.233))
      for (let step = 0; step < 40; step++) {
        const next = new Float64Array(size)
        for (const vector of centred) {
          let dot = 0
          for (let k = 0; k < size; k++) dot += vector[k] * direction[k]
          for (let k = 0; k < size; k++) next[k] += dot * vector[k]
        }
        for (const earlier of directions) { // (the second is held apart from the first)
          let dot = 0
          for (let k = 0; k < size; k++) dot += next[k] * earlier[k]
          for (let k = 0; k < size; k++) next[k] -= dot * earlier[k]
        }
        const length = Math.hypot(...next) || 1
        direction = next.map(value => value / length)
      }
      directions.push(direction)
    }
    return centred.map(vector => directions.map(direction => {
      let dot = 0
      for (let k = 0; k < size; k++) dot += vector[k] * direction[k]
      return dot
    }))
  }

  /** Her sky for one person: {subject, stars: [{id, at, day, x, y, kept, recalls, who, said, links}], lines: [{from,
   * to (star indexes), strength, uses}], total (exchanges in all), linked (links in all)}. `now` in seconds. */
  function memorySky (db, space, subject, now = Date.now() / 1000) {
    const all = rows(db, 'select id, at, day, lines, stability, recalled_at, recalls from episodes where space = ? and ' +
      'subject = ? order by at, id', [space, subject])
    const kept = all.slice(-STARS)
    const days = [...new Set(all.map(item => item.day))].sort((a, b) => a - b)
    const today = talkingDay(now)
    const index = new Map(kept.map((item, at) => [item.id, at]))
    const stars = kept.map(item => {
      let lines = []
      try { lines = JSON.parse(item.lines) } catch {}
      const first = lines[0] || ['', '']
      const since = item.recalled_at !== null && item.recalled_at > item.at ? talkingDay(item.recalled_at) : item.day
      return { id: item.id, at: item.at, day: item.day, x: 0, y: 0, kept: retention(since, item.stability, today, days),
        recalls: item.recalls, who: String(first[0]), said: String(first[1]).slice(0, 240), links: 0 }
    })
    const lines = []
    let linked = 0
    if (hasTable(db, 'links')) {
      for (const link of rows(db, 'select a, b, day, stability, uses from links where space = ? and subject = ?',
        [space, subject])) {
        linked++
        if (!index.has(link.a) || !index.has(link.b)) continue
        const from = index.get(link.a), to = index.get(link.b)
        lines.push({ from, to, strength: retention(link.day, link.stability, today, days), uses: link.uses })
        stars[from].links++
        stars[to].links++
      }
    }
    place(db, stars, lines)
    const groups = group(stars, lines)
    return { subject, stars, lines, groups, total: all.length, linked }
  }

  const heft = line => line.strength * (1 + line.uses)

  /** Each star's group (`star.group`: 0 for the largest, …; −1 for a star in none of the tinted ones); the sizes of
   * the tinted groups, the largest first. */
  function group (stars, lines) {
    const n = stars.length
    const near = stars.map(() => [])
    for (const line of lines) {
      if (!line.spine) continue
      near[line.from].push([line.to, heft(line)])
      near[line.to].push([line.from, heft(line)])
    }
    const label = stars.map((_, i) => i)
    for (let round = 0; round < 12; round++) {
      let moved = 0
      for (let i = 0; i < n; i++) {
        if (!near[i].length) continue
        const votes = new Map()
        for (const [j, weight] of near[i]) votes.set(label[j], (votes.get(label[j]) || 0) + weight)
        let best = label[i], most = votes.get(label[i]) || 0
        for (const [which, weight] of votes) if (weight > most + 1e-12 || (Math.abs(weight - most) <= 1e-12 && which < best)) { best = which; most = weight }
        if (best !== label[i]) { label[i] = best; moved++ }
      }
      if (!moved) break
    }
    const sizes = new Map()
    for (const which of label) sizes.set(which, (sizes.get(which) || 0) + 1)
    const largest = [...sizes].filter(([, size]) => size >= SMALLEST).sort((a, b) => b[1] - a[1] || a[0] - b[0])
      .slice(0, GROUPS)
    const rank = new Map(largest.map(([which], at) => [which, at]))
    stars.forEach((star, i) => { star.group = rank.has(label[i]) ? rank.get(label[i]) : -1 })
    return largest.map(([, size]) => size)
  }

  /** The links that hold the sky's shape: each star's `SPINE` heaviest, and every link used again since it was born.
   * The rest are drawn, fainter, but pull nothing. */
  function backbone (stars, lines) {
    const mine = stars.map(() => [])
    lines.forEach((line, at) => { mine[line.from].push(at); mine[line.to].push(at) })
    const kept = new Set(lines.flatMap((line, at) => line.uses ? [at] : []))
    for (const own of mine) {
      own.sort((a, b) => heft(lines[b]) - heft(lines[a]) || a - b)
      for (const at of own.slice(0, SPINE)) kept.add(at)
    }
    lines.forEach((line, at) => { line.spine = kept.has(at) })
    return lines.filter(line => line.spine)
  }

  /** Where each star sits: in meaning first, then pulled by its backbone, pushed apart by every other star
   * (Fruchterman and Reingold), the same every time. */
  function place (db, stars, lines) {
    const n = stars.length
    if (!n) return
    const vectors = new Map()
    if (hasTable(db, 'episode_vectors')) {
      const wanted = new Set(stars.map(star => star.id))
      for (const item of rows(db, 'select episode_id, vector from episode_vectors')) {
        if (!wanted.has(item.episode_id) || vectors.has(item.episode_id)) continue
        const bytes = item.vector
        vectors.set(item.episode_id, new Float32Array(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset +
          bytes.byteLength)))
      }
    }
    const size = vectors.size ? [...vectors.values()][0].length : 0
    const usable = size ? stars.filter(star => vectors.get(star.id)?.length === size) : []
    const meaning = usable.length >= n / 2 && usable.length >= 3
    if (meaning) {
      const flat = plane(usable.map(star => vectors.get(star.id)))
      const spread = Math.max(1e-9, ...flat.map(([x, y]) => Math.hypot(x, y)))
      usable.forEach((star, k) => { star.x = flat[k][0] / spread; star.y = flat[k][1] / spread; star.placed = true })
    }
    stars.forEach((star, k) => { // without a vector: on a spiral, in the order they were said
      if (star.placed) return
      const turn = k * 2.399963, reach = Math.sqrt((k + 0.5) / n)
      star.x = reach * Math.cos(turn)
      star.y = reach * Math.sin(turn)
    })
    const spine = backbone(stars, lines)
    const x = Float64Array.from(stars, star => star.x), y = Float64Array.from(stars, star => star.y)
    const dx = new Float64Array(n), dy = new Float64Array(n)
    const k = 1.6 / Math.sqrt(n), ticks = n > 500 ? 160 : 260
    for (let tick = 0; tick < ticks; tick++) {
      const heat = 0.12 * (1 - tick / ticks) + 0.002
      dx.fill(0)
      dy.fill(0)
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const ex = x[i] - x[j], ey = y[i] - y[j], far = Math.max(1e-4, Math.hypot(ex, ey))
          const push = k * k / far / far
          dx[i] += ex * push; dy[i] += ey * push
          dx[j] -= ex * push; dy[j] -= ey * push
        }
        dx[i] -= x[i] * HOLD * n * k
        dy[i] -= y[i] * HOLD * n * k
      }
      for (const line of spine) {
        const i = line.from, j = line.to
        const ex = x[j] - x[i], ey = y[j] - y[i], far = Math.hypot(ex, ey)
        const pull = far / k * (0.4 + Math.min(1, heft(line) / 2))
        dx[i] += ex * pull; dy[i] += ey * pull
        dx[j] -= ex * pull; dy[j] -= ey * pull
      }
      for (let i = 0; i < n; i++) {
        const moved = Math.hypot(dx[i], dy[i])
        const scale = moved > heat ? heat / moved : 1
        x[i] += dx[i] * scale
        y[i] += dy[i] * scale
      }
    }
    // the stars the backbone holds fill the sky; the rest are dust on a ring round it, in the order they were said
    const held = new Set(spine.flatMap(line => [line.from, line.to]))
    const inner = [...held]
    let mx = 0, my = 0
    for (const i of inner) { mx += x[i] / inner.length; my += y[i] / inner.length }
    const reach = inner.map(i => Math.hypot(x[i] - mx, y[i] - my)).sort((a, b) => a - b)
    const outer = reach[Math.floor(0.99 * (reach.length - 1))] || 1
    const loose = stars.map((_, i) => i).filter(i => !held.has(i))
    stars.forEach((star, i) => {
      delete star.placed
      star.x = Math.max(-1, Math.min(1, (x[i] - mx) / outer * 0.86))
      star.y = Math.max(-1, Math.min(1, (y[i] - my) / outer * 0.86))
    })
    loose.forEach((i, at) => {
      const turn = -Math.PI / 2 + 2 * Math.PI * (at + 0.5) / loose.length
      stars[i].x = 0.97 * Math.cos(turn)
      stars[i].y = 0.97 * Math.sin(turn)
    })
  }

  // ---- drawing ----------------------------------------------------------------------------------------------------
  // `look`: { dark, ink }. `upTo`: the stars shown (the first that many, in the order they were said); `chosen`: a
  // star's index, drawn with its links brighter.

  function canvasOf (canvas) {
    const width = Math.max(120, Math.round(canvas.getBoundingClientRect().width))
    const ratio = (typeof window !== 'undefined' && window.devicePixelRatio) || 1
    if (canvas.width !== width * ratio) {
      canvas.width = width * ratio
      canvas.height = width * ratio
    }
    const g = canvas.getContext('2d')
    g.setTransform(ratio, 0, 0, ratio, 0, 0)
    g.clearRect(0, 0, width, width)
    return { g, width }
  }

  const spot = (star, width) => [width / 2 + star.x * width * 0.47, width / 2 + star.y * width * 0.47]

  function draw (canvas, sky, look, upTo = sky.stars.length, chosen = null) {
    const { g, width } = canvasOf(canvas)
    g.fillStyle = look.dark ? '#0a0d16' : 'rgba(127, 127, 127, 0.07)'
    g.beginPath()
    if (g.roundRect) g.roundRect(0, 0, width, width, 12)
    else g.rect(0, 0, width, width)
    g.fill()
    const near = chosen === null ? null : new Set([chosen])
    if (near) for (const line of sky.lines) if (line.from === chosen || line.to === chosen) near.add(line.from === chosen ? line.to : line.from)
    g.lineCap = 'round'
    const hues = HUES[look.dark ? 'dark' : 'light']
    for (const line of sky.lines) {
      if (line.from >= upTo || line.to >= upTo) continue
      const lit = chosen !== null && (line.from === chosen || line.to === chosen)
      const [x1, y1] = spot(sky.stars[line.from], width), [x2, y2] = spot(sky.stars[line.to], width)
      const weight = Math.min(1, heft(line) / 3)
      const one = sky.stars[line.from].group, other = sky.stars[line.to].group
      g.globalAlpha = (lit ? 0.9 : near ? 0.05 : line.spine ? 0.1 + 0.35 * weight + (line.uses ? 0.2 : 0) : 0.035) *
        (look.dark ? 1 : 0.85)
      g.strokeStyle = one >= 0 && one === other ? hues[one] : (look.dark ? '#93a7d6' : '#4a5a80')
      g.lineWidth = lit ? 1.6 : line.spine ? 0.6 + 0.8 * weight + (line.uses ? 0.5 : 0) : 0.5
      g.beginPath()
      g.moveTo(x1, y1)
      g.lineTo(x2, y2)
      g.stroke()
    }
    g.globalAlpha = 1
    for (let i = 0; i < Math.min(upTo, sky.stars.length); i++) {
      const star = sky.stars[i]
      const [x, y] = spot(star, width)
      const shine = (near && !near.has(i) ? 0.3 : 1) * (0.18 + 0.82 * star.kept)
      const radius = 1.1 + 1.5 * Math.min(1, Math.log1p(star.links + star.recalls) / 2.5)
      const hue = star.group >= 0 ? hues[star.group] : (look.dark ? '#ebf2ff' : '#1d1d1f')
      if (look.dark && star.kept > 0.6 && (!near || near.has(i))) { // a soft glow round the brightest
        g.globalAlpha = 0.12 * shine
        g.fillStyle = hue
        g.beginPath()
        g.arc(x, y, radius * 3, 0, Math.PI * 2)
        g.fill()
      }
      g.globalAlpha = shine
      g.fillStyle = hue
      g.beginPath()
      g.arc(x, y, i === chosen ? radius + 2 : radius, 0, Math.PI * 2)
      g.fill()
    }
    g.globalAlpha = 1
  }

  /** The star nearest a point on the canvas (in CSS pixels from its corner), within `reach` pixels, or null. */
  function starAt (canvas, sky, px, py, upTo = sky.stars.length, reach = 12) {
    const width = canvas.getBoundingClientRect().width
    let best = null, nearest = reach * reach
    for (let i = 0; i < Math.min(upTo, sky.stars.length); i++) {
      const [x, y] = spot(sky.stars[i], width)
      const far = (x - px) ** 2 + (y - py) ** 2
      if (far < nearest) { nearest = far; best = i }
    }
    return best
  }

  return { STARS, HUES, people, memorySky, draw, starAt, talkingDay, retention }
})

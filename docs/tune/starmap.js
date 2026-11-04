// Her star map, for the tuner: her heart as a sky, made and drawn as the DeepSeek Harness plugin makes and draws it
// (dsh-mneme-llm, lib/starmap.js and plugin/client.js), from her gut file as it is open here. Plain functions with no
// page in sight, so they run in node as well as in the browser; the drawing takes the canvas it draws on.
//
// Her 24 ends sit evenly around a circle, the first at the top. Every row of her heart (one thing she can notice, such
// as topic=rain or close=high, with a weight for each end) is a star: it sits where that row alone pulls her (a softmax
// of its weights, each end's share drawn out along that end's arm), as bright as the row leans at all (its strongest
// weight less its weakest), in the colour of the bar of its strongest end. The arms are how much more or less she
// feels each end now than the day she was born, over her own latest lessons; the day she was born is her starter, a
// file her host gives her, lived again here as mneme_llm.gut's `Net.start` lives it (the same seeded shuffle). Each
// person she knows is one star more, placed the same way by what is different with them (their table's bias).
// In three dimensions her 13 bars are spread evenly over a sphere, the first at the top, and the two ends of a bar sit
// side by side, a little apart.
//
// Her heart is as the file keeps it: as of her last sleep. The lessons since are learned again when she wakes.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./tune.js'))
  else root.StarMap = factory(root.Tune)
})(typeof self !== 'undefined' ? self : this, function (T) {
  'use strict'

  const ENDS = T.ENDS
  const SPREAD = 8.0 // how far a leaning row travels toward its end (her rows lean little: mostly under 1)
  const STARS = 1500 // stars drawn: the rows that lean most
  const PROBE = 300 // her own latest lessons, which her arms are measured on
  const LEAST = 20 // with fewer lessons than this, every arm is as she was born
  const SHORTEST = 0.3, LONGEST = 2.4 // how far an arm can shrink or grow
  const GAIN = 3.0 // an arm grows by this much for each 1 of strength she has gained on an end (0 to 1)
  const APART = 12 * Math.PI / 180 // in 3D, each end of a bar this far from the bar's own direction
  // and how each bar's pair is turned about its direction, in degrees (`TURNS` in the plugin's lib/starmap.js)
  const TURNS = [108, 163, 173, 173, 165, 163, 160, 163, 173, 178, 173, 0, 0]
  const BLANK = -3.0 // where every end starts before anything is learned (`BLANK` in gut.py)
  const BORN_PASSES = 4, BORN_RATE = 0.15 // her starter, lived again (`BORN_PASSES`, `BORN_RATE`)
  const OLD = ['happy', 'calm', 'sweet', 'tender', 'worried', 'sad', 'jealous'] // a starter from 0.4 knew these
  const ARM = 2.0 // an arm is drawn at most this many base radii long
  const LABELS = 2.2 // and the names of the ends no further out than this
  const EYE = 6.0 // in 3D, the eye is this many base radii from the middle: what is near looks a little bigger
  const ONE = ENDS.map(() => 1.0)

  // ---- what she notices, as gut.py reads it ---------------------------------------------------------------------
  const isTable = value => value !== null && typeof value === 'object' && !Array.isArray(value)
  const truthy = value => Array.isArray(value) ? value.length > 0 : isTable(value) ? Object.keys(value).length > 0
    : Boolean(value)
  /** Python's str() of a value from JSON, as far as its letters go. */
  const str = value => typeof value === 'string' ? value : value === null || value === undefined ? 'None'
    : value === true ? 'True' : value === false ? 'False' : typeof value === 'number' ? String(value)
      : JSON.stringify(value).replace(/\bnull\b/g, 'None').replace(/\btrue\b/g, 'True').replace(/\bfalse\b/g, 'False')
  /** Python's order of two strings: by code point. */
  function compare (one, other) {
    const a = Array.from(one), b = Array.from(other)
    for (let i = 0; i < Math.min(a.length, b.length); i++) {
      const difference = a[i].codePointAt(0) - b[i].codePointAt(0)
      if (difference) return difference < 0 ? -1 : 1
    }
    return a.length - b.length
  }

  const band = closeness => closeness >= 60 ? 'high' : closeness >= 25 ? 'mid' : 'low'
  const tier = closeness => (0.5 + closeness / 100) ** 2

  function tags (form) {
    const found = []
    for (const field of ['people', 'gender', 'topic', 'event']) {
      const values = truthy(form[field]) ? form[field] : []
      for (const value of Array.isArray(values) ? values : [values]) {
        for (const word of str(value).toLowerCase().match(/[a-z]+/g) || []) found.push(`${field}=${word}`)
      }
    }
    for (const field of ['sender_feels', 'toward_you']) {
      const value = (truthy(form[field]) ? str(form[field]) : '').toLowerCase().trim()
      if (value) found.push(`${field}=${value}`)
    }
    return [...new Set(found)]
  }

  /** The form's tags, alone and crossed with how close the person is (`features` in gut.py). */
  function features (form, closeness) {
    const words = tags(form), near = band(closeness)
    const keys = [...words, ...words.map(word => `${near}:${word}`), `close=${near}`]
    const value = 1 / Math.sqrt(keys.length || 1), out = {}
    for (const key of keys) out[key] = value
    return out
  }

  const squash = score => 1 / (1 + Math.exp(-Math.max(-30.0, Math.min(30.0, score))))
  const target = feel => ENDS.map(end => Math.max(0.0, Math.min(1.0, Number(truthy(feel[end]) ? feel[end] : 0.0))))
  const asFeel = feel => isTable(feel) ? feel : { [feel === 'none' ? 'calm' : feel]: 1.0 }

  /** One row of weights for each thing she can notice, one column for each end, and a bias (`Table` in gut.py). */
  class Table {
    constructor (kept = null, blank = BLANK) {
      this.w = new Map(Object.entries(kept?.w || {}))
      this.b = kept?.b ? [...kept.b] : ENDS.map(() => blank)
    }

    scores (x) {
      const scores = [...this.b]
      for (const [key, value] of Object.entries(x)) {
        const row = this.w.get(key)
        if (row) row.forEach((weight, k) => { scores[k] += weight * value })
      }
      return scores
    }

    strengths (x) {
      return this.scores(x).map(squash)
    }

    step (x, wanted, known, rate) {
      const got = this.scores(x).map(squash)
      const entries = Object.entries(x)
      for (const [key] of entries) if (!this.w.has(key)) this.w.set(key, ENDS.map(() => 0.0))
      for (const k of known) {
        const gradient = rate * (got[k] - wanted[k])
        this.b[k] -= gradient * 0.25
        for (const [key, value] of entries) this.w.get(key)[k] -= gradient * value
      }
    }
  }

  // ---- her birth --------------------------------------------------------------------------------------------------
  /** Python's random.Random(seed) for a small whole number, as far as `shuffle` goes: the Mersenne Twister. */
  class Random {
    constructor (seed = 0) {
      this.mt = new Uint32Array(624)
      this._byArray([seed >>> 0])
    }

    _byArray (key) {
      const mt = this.mt, N = 624
      mt[0] = 19650218
      for (let i = 1; i < N; i++) mt[i] = (Math.imul(1812433253, mt[i - 1] ^ (mt[i - 1] >>> 30)) + i) >>> 0
      let i = 1, j = 0
      for (let k = Math.max(N, key.length); k; k--) {
        mt[i] = ((mt[i] ^ Math.imul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1664525)) + key[j] + j) >>> 0
        i++
        j++
        if (i >= N) { mt[0] = mt[N - 1]; i = 1 }
        if (j >= key.length) j = 0
      }
      for (let k = N - 1; k; k--) {
        mt[i] = ((mt[i] ^ Math.imul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1566083941)) - i) >>> 0
        i++
        if (i >= N) { mt[0] = mt[N - 1]; i = 1 }
      }
      mt[0] = 0x80000000
      this.index = N
    }

    uint32 () {
      const mt = this.mt, N = 624, M = 397
      if (this.index >= N) {
        for (let k = 0; k < N; k++) {
          const y = (mt[k] & 0x80000000) | (mt[(k + 1) % N] & 0x7fffffff)
          mt[k] = mt[(k + M) % N] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0)
        }
        this.index = 0
      }
      let y = mt[this.index++]
      y ^= y >>> 11
      y ^= (y << 7) & 0x9d2c5680
      y ^= (y << 15) & 0xefc60000
      y ^= y >>> 18
      return y >>> 0
    }

    randbelow (n) {
      const k = 32 - Math.clz32(n)
      let r = this.uint32() >>> (32 - k)
      while (r >= n) r = this.uint32() >>> (32 - k)
      return r
    }

    shuffle (list) {
      for (let i = list.length - 1; i > 0; i--) {
        const j = this.randbelow(i + 1)
        ;[list[i], list[j]] = [list[j], list[i]]
      }
    }
  }

  /** A starter's bytes (gzip-compressed JSON): her born lessons [form, feel, mood, closeness] and the ends its notes
   * knew (`read_starter` in gut.py). Throws for bytes that are not one. */
  async function readStarter (bytes) {
    const data = JSON.parse(await T.gunzip(bytes))
    if (!isTable(data) || !Array.isArray(data.rows) || !isTable(data.words)) throw new Error('not a starter')
    const rows = data.rows.map(([form, feel, mood, closeness]) => [form, asFeel(feel), mood, closeness])
    return { rows, known: Array.isArray(data.ends) && data.ends.length ? data.ends : OLD }
  }

  /** Whether bytes begin as a gzip file does. */
  const isGzip = bytes => bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b

  /** Her heart as she was born from a starter: a few gentle passes over its lessons, as a lean (`Net.start`). */
  function born ({ rows, known }, seed = 0) {
    const heart = new Table()
    const pack = rows.map(([form, feel, mood, closeness]) => [features(form, closeness), target(asFeel(feel)),
      (1 + Math.abs(mood)) / 3 * tier(closeness)])
    const mask = ENDS.flatMap((end, k) => known.includes(end) ? [k] : [])
    const rng = new Random(seed)
    for (let pass = 0; pass < BORN_PASSES; pass++) {
      rng.shuffle(pack)
      for (const [x, wanted, weight] of pack) heart.step(x, wanted, mask, BORN_RATE * weight)
    }
    return heart
  }

  // ---- the map ----------------------------------------------------------------------------------------------------
  const ANGLES = ENDS.map((end, k) => -Math.PI / 2 + 2 * Math.PI * k / ENDS.length)

  /** In 3D, each end's direction: the bars on a sphere (a Fibonacci spiral from the top, y up), and a bar's two ends
   * side by side, turned by TURNS. */
  const DIRECTIONS = (() => {
    const unit = ([x, y, z]) => {
      const length = Math.hypot(x, y, z)
      return [x / length, y / length, z / length]
    }
    const cross = ([a, b, c], [d, e, f]) => [b * f - c * e, c * d - a * f, a * e - b * d]
    const golden = Math.PI * (3 - Math.sqrt(5))
    return T.BARS.flatMap(([, , left], index) => {
      const y = 1 - 2 * (index + 0.5) / T.BARS.length, r = Math.sqrt(1 - y * y), turn = index * golden
      const centre = [Math.cos(turn) * r, y, Math.sin(turn) * r]
      if (!left) return [centre]
      const across = unit(cross(centre, Math.abs(y) > 0.99 ? [1, 0, 0] : [0, 1, 0])), up = cross(centre, across)
      const phi = TURNS[index] * Math.PI / 180
      const side = across.map((value, k) => value * Math.cos(phi) + up[k] * Math.sin(phi))
      return [-1, 1].map(sign => unit(centre.map((value, k) => value * Math.cos(APART) + sign * side[k] *
        Math.sin(APART))))
    })
  })()

  /** Each end's share of where a row sits: a softmax of its weights. */
  function shares (row) {
    const top = Math.max(...row)
    const pulls = row.map(weight => Math.exp(SPREAD * (weight - top)))
    const total = pulls.reduce((sum, pull) => sum + pull, 0)
    return pulls.map(pull => pull / total)
  }

  /** Where a row sits: each end's share, along that end's arm. */
  function spot (row, reach = ONE) {
    let x = 0, y = 0
    shares(row).forEach((share, k) => {
      x += share * reach[k] * Math.cos(ANGLES[k])
      y += share * reach[k] * Math.sin(ANGLES[k])
    })
    return [x, y]
  }

  /** Where a row sits in 3D: the same shares, along each end's direction on the sphere. */
  function spot3 (row, reach = ONE) {
    const at = [0, 0, 0]
    shares(row).forEach((share, k) => DIRECTIONS[k].forEach((value, axis) => { at[axis] += share * reach[k] * value }))
    return at
  }

  const brightness = row => Math.max(...row) - Math.min(...row)
  const strongest = row => row.indexOf(Math.max(...row))

  /** How strongly a table feels each end, on average over some moments ([form, closeness] each). */
  function strengths (table, probe) {
    const sums = ENDS.map(() => 0.0)
    for (const [form, closeness] of probe) {
      table.strengths(features(form, closeness)).forEach((value, k) => { sums[k] += value })
    }
    return sums.map(value => value / Math.max(1, probe.length))
  }

  /** Her arms: 1 as she was born, longer by GAIN for each 1 of strength she has gained on an end since, shorter for
   * what she has lost, from SHORTEST to LONGEST. With fewer than LEAST moments to measure on, each is 1. */
  function arms (heart, birth, probe) {
    if (probe.length < LEAST) return [...ONE]
    const now = strengths(heart, probe), then = strengths(birth, probe)
    return now.map((value, k) => Math.min(LONGEST, Math.max(SHORTEST, 1 + GAIN * (value - then[k]))))
  }

  /** The moments of her own latest lessons, [form, closeness] each, the newest first. */
  function probeOf (db, count = PROBE) {
    return T.rows(db, 'select form, closeness from lessons order by id desc limit ?', [count]).flatMap(item => {
      try {
        const form = JSON.parse(item.form)
        return isTable(form) ? [[form, item.closeness]] : []
      } catch {
        return []
      }
    })
  }

  /** Her star map from her open gut file, or null before she has a heart. `starter`: her starter as `readStarter`
   * read it, or null. `birth` says what her arms are measured from: 'starter'; 'blank' for a heart born without one
   * (as the file says); 'unknown' for one born from a starter that is not open (each arm is 1 then). `waiting`: her
   * lessons since her last sleep, not in her heart yet. */
  async function starmap (db, { starter = null, born: birth = null, most = STARS } = {}) {
    const kept = await T.getState(db, 'heart')
    if (!kept) return null
    const settings = await T.settingsOf(db)
    const heart = new Table(kept.heart), probe = probeOf(db)
    const from = birth || (starter ? born(starter) : null)
    const status = from ? 'starter' : kept.born ? 'unknown' : 'blank'
    const reach = status === 'unknown' ? [...ONE] : arms(heart, from || new Table(), probe)
    const rows = [...heart.w].map(([key, row]) => [key, row, brightness(row)])
      .sort((one, other) => other[2] - one[2] || compare(one[0], other[0])).slice(0, most)
    const stars = rows.map(([key, row, bright]) => [...spot(row, reach), bright, strongest(row), key,
      ...spot3(row, reach)])
    const people = Object.entries(kept.people || {}).map(([subject, found]) => {
      const b = found.table?.b || ENDS.map(() => 0.0)
      return { subject, x: spot(b, reach)[0], y: spot(b, reach)[1], at: spot3(b, reach),
        weight: T.personWeight(kept, settings, subject), lessons: Math.round(found.n), end: strongest(b) }
    }).sort((one, other) => other.weight - one.weight || compare(one.subject, other.subject))
    const total = T.rows(db, 'select count(*) as n from lessons')[0].n
    return { ends: ENDS, reach, probed: probe.length, rows: heart.w.size, directions: DIRECTIONS, stars, people,
      birth: status, waiting: Math.max(0, total - (Number(kept.lessons) || 0)) }
  }

  // ---- drawing ----------------------------------------------------------------------------------------------------
  // `look`: { dark, ink, names (each end's name, in ENDS order), colours (each end's), label (subject → the name
  // shown) }.

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

  function sky (g, width, dark) {
    g.fillStyle = dark ? '#0a0d16' : 'rgba(127, 127, 127, 0.07)'
    g.beginPath()
    if (g.roundRect) g.roundRect(0, 0, width, width, 12)
    else g.rect(0, 0, width, width)
    g.fill()
  }

  /** How bright each star is drawn: against the brighter stars of this map. */
  function topOf (map) {
    const brights = map.stars.map(star => star[2]).sort((one, other) => one - other)
    return Math.max(0.05, brights[Math.floor(brights.length * 0.97)] ?? 1)
  }

  function personDot (g, { px, py, size, person }, look, colour, width, font) {
    if (look.dark) {
      g.fillStyle = 'rgba(255, 255, 255, 0.14)'
      g.beginPath()
      g.arc(px, py, size * 2.4, 0, 2 * Math.PI)
      g.fill()
    }
    g.fillStyle = look.dark ? '#ffffff' : '#1d1d1f'
    g.strokeStyle = colour[person.end] ?? look.ink
    g.lineWidth = 2
    g.beginPath()
    g.arc(px, py, size, 0, 2 * Math.PI)
    g.fill()
    g.stroke()
    const label = look.label ? look.label(person.subject) : person.subject
    g.font = `600 ${font + 1}px system-ui, -apple-system, sans-serif`
    g.textBaseline = 'middle'
    const left = px + size + 4 + g.measureText(label).width > width - 4
    g.textAlign = left ? 'right' : 'left'
    g.lineWidth = 3
    g.strokeStyle = look.dark ? '#0a0d16' : 'rgba(255, 255, 255, 0.9)'
    g.strokeText(label, left ? px - size - 4 : px + size + 4, py)
    g.fillStyle = look.ink
    g.fillText(label, left ? px - size - 4 : px + size + 4, py)
    g.lineWidth = 1
  }

  /** The base radius of the flat map: as big as fits, with each end's name at its arm's tip, read outward. */
  function baseRadius (half, arms, widths, gap = 0.12) {
    return Math.min(...arms.map((arm, k) => (half - 4 - widths[k] - 6) / Math.min(LABELS, Math.min(ARM, arm) + gap)))
  }

  /** Her star map, flat. */
  function drawFlat (canvas, map, look) {
    const { g, width } = canvasOf(canvas)
    const half = width / 2, font = Math.max(9, Math.min(12, width / 36))
    const scale = Math.max(0.55, Math.min(1, width / 520)) // (stars smaller on a small map)
    sky(g, width, look.dark)
    g.font = `${font}px system-ui, -apple-system, sans-serif`
    const arms = map.reach.map(reach => Math.min(ARM, reach))
    const R = Math.max(10, baseRadius(half, arms, look.names.map(name => g.measureText(name).width)))
    const colour = look.colours
    // the ring: as she was born; then her arms, and the names of her ends at their tips
    g.strokeStyle = look.dark ? 'rgba(255, 255, 255, 0.16)' : 'rgba(0, 0, 0, 0.14)'
    g.setLineDash([3, 4])
    g.beginPath()
    g.arc(half, half, R, 0, 2 * Math.PI)
    g.stroke()
    g.setLineDash([])
    map.ends.forEach((end, k) => {
      const a = ANGLES[k], x = half + arms[k] * R * Math.cos(a), y = half + arms[k] * R * Math.sin(a)
      g.strokeStyle = colour[k]
      g.globalAlpha = 0.45
      g.beginPath()
      g.moveTo(half, half)
      g.lineTo(x, y)
      g.stroke()
      g.globalAlpha = 1
      g.fillStyle = colour[k]
      g.beginPath()
      g.arc(x, y, 2.2, 0, 2 * Math.PI)
      g.fill()
      const out = Math.min(LABELS, arms[k] + 0.12) * R, back = Math.cos(a) < -1e-6
      g.save()
      g.translate(half, half)
      g.rotate(back ? a + Math.PI : a)
      g.fillStyle = look.ink
      g.globalAlpha = 0.8
      g.textBaseline = 'middle'
      g.textAlign = back ? 'right' : 'left'
      g.fillText(look.names[k], back ? -out : out, 0)
      g.restore()
    })
    // the stars, dimmest first
    const top = topOf(map)
    const place = (x, y) => {
      const far = Math.hypot(x, y), cut = far > ARM ? ARM / far : 1 // (inside the map, whatever her arms)
      return [half + x * cut * R, half + y * cut * R]
    }
    for (let i = map.stars.length - 1; i >= 0; i--) {
      const [x, y, bright, end] = map.stars[i], [px, py] = place(x, y)
      const lean = Math.min(1, bright / top), size = (0.7 + 2.3 * lean) * scale
      g.fillStyle = colour[end]
      if (look.dark && lean > 0.5) { // (a glow on the dark sky, for the stars that lean most)
        g.globalCompositeOperation = 'lighter'
        g.globalAlpha = 0.12 * lean
        g.beginPath()
        g.arc(px, py, size * 3.2, 0, 2 * Math.PI)
        g.fill()
        g.globalCompositeOperation = 'source-over'
      }
      g.globalAlpha = 0.25 + 0.75 * lean
      g.beginPath()
      g.arc(px, py, size, 0, 2 * Math.PI)
      g.fill()
    }
    g.globalAlpha = 1
    // the people she knows: one big star each, as big as how much of how she is with them is theirs
    const people = map.people.map(person => {
      const [px, py] = place(person.x, person.y)
      return { px, py, size: (4 + 8 * Math.min(1, person.weight / T.MOST)) * scale, person }
    })
    for (const item of people) personDot(g, item, look, colour, width, font)
  }

  /** A point of the 3D map seen from where it is turned: across, down the screen, toward the eye, and how much nearer
   * things look bigger. */
  function project ([x, y, z], { yaw, pitch }) {
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
    const x1 = x * cy + z * sy, z1 = z * cy - x * sy
    const y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp
    const near = EYE / (EYE - z2)
    return [x1 * near, -y2 * near, z2, near]
  }

  /** Where each end's name goes in 3D, the front ones first: a line up or down off a nearer name it would cover, or
   * left out while it cannot be (it is further back; as the map turns, it comes back). k → {x, y, align}. */
  function placeNames (g, tips, names, half, font) {
    const taken = [], places = new Map(), tall = font + 2
    for (const tip of [...tips].sort((one, other) => other.z - one.z)) {
      const [x, at] = tip.label, wide = g.measureText(names[tip.k]).width
      const align = x < half - 2 ? 'right' : x > half + 2 ? 'left' : 'center'
      const left = align === 'right' ? x - wide : align === 'center' ? x - wide / 2 : x
      const free = y => !taken.some(([x0, y0, x1, y1]) => left < x1 && left + wide > x0 && y - tall / 2 < y1 &&
        y + tall / 2 > y0)
      const y = [at, at - tall, at + tall].find(free)
      if (y === undefined) continue
      taken.push([left - 2, y - tall / 2, left + wide + 2, y + tall / 2])
      places.set(tip.k, { x, y, align })
    }
    return places
  }

  /** Her star map in 3D, turned by `turn` ({yaw, pitch}): the nearer, the brighter. */
  function drawRound (canvas, map, look, turn) {
    const { g, width } = canvasOf(canvas)
    const half = width / 2, font = Math.max(9, Math.min(12, width / 36))
    const scale = Math.max(0.55, Math.min(1, width / 520))
    sky(g, width, look.dark)
    g.font = `${font}px system-ui, -apple-system, sans-serif`
    const longest = Math.max(1, ...map.reach.map(reach => Math.min(ARM, reach)))
    // (as big as fits, names too, however it is turned: a point this far out is drawn at most far / √(1 − (far/EYE)²)
    // from the middle, when it leans toward the eye by far/EYE)
    const out = Math.min(LABELS, longest + 0.15), seen = out / Math.sqrt(1 - (out / EYE) ** 2)
    const R = Math.max(10, (half - 6 - 5 * font) / seen)
    const colour = look.colours
    const depth = z => Math.max(0, Math.min(1, (z + ARM) / (2 * ARM))) // 0 at the back, 1 at the front
    const screen = at => {
      const far = Math.hypot(...at), cut = far > ARM ? ARM / far : 1
      const [x, y, z, near] = project(at.map(value => value * cut), turn)
      return [half + x * R, half + y * R, z, near]
    }
    // the sphere she was born with, seen from outside; then her arms, the far ones fainter
    g.strokeStyle = look.dark ? 'rgba(255, 255, 255, 0.16)' : 'rgba(0, 0, 0, 0.14)'
    g.setLineDash([3, 4])
    g.beginPath()
    g.arc(half, half, R * EYE / Math.sqrt(EYE * EYE - 1), 0, 2 * Math.PI)
    g.stroke()
    g.setLineDash([])
    const tips = map.directions.map((direction, k) => {
      const arm = Math.min(ARM, map.reach[k])
      const [x, y, z] = screen(direction.map(value => value * arm))
      g.strokeStyle = colour[k]
      g.globalAlpha = 0.15 + 0.4 * depth(z)
      g.beginPath()
      g.moveTo(half, half)
      g.lineTo(x, y)
      g.stroke()
      g.globalAlpha = 1
      return { k, x, y, z, label: screen(direction.map(value => value * Math.min(LABELS, arm + 0.15))) }
    })
    // the stars, from the back to the front
    const top = topOf(map)
    const placed = map.stars.map(star => [star, screen(star.slice(5, 8))]).sort((one, other) => one[1][2] - other[1][2])
    for (const [star, [px, py, z, near]] of placed) {
      const lean = Math.min(1, star[2] / top), size = (0.7 + 2.3 * lean) * scale * near, front = depth(z)
      g.fillStyle = colour[star[3]]
      if (look.dark && lean > 0.5) {
        g.globalCompositeOperation = 'lighter'
        g.globalAlpha = 0.12 * lean * (0.4 + 0.6 * front)
        g.beginPath()
        g.arc(px, py, size * 3.2, 0, 2 * Math.PI)
        g.fill()
        g.globalCompositeOperation = 'source-over'
      }
      g.globalAlpha = (0.25 + 0.75 * lean) * (0.35 + 0.65 * front)
      g.beginPath()
      g.arc(px, py, size, 0, 2 * Math.PI)
      g.fill()
    }
    g.globalAlpha = 1
    // the tips of her arms and the names of her ends, the front ones over the back
    g.textBaseline = 'middle'
    const places = placeNames(g, tips, look.names, half, font)
    for (const tip of [...tips].sort((one, other) => one.z - other.z)) {
      const front = depth(tip.z), place = places.get(tip.k)
      g.fillStyle = colour[tip.k]
      g.globalAlpha = 0.4 + 0.6 * front
      g.beginPath()
      g.arc(tip.x, tip.y, 2.2, 0, 2 * Math.PI)
      g.fill()
      if (!place) continue
      g.fillStyle = look.ink
      g.globalAlpha = 0.3 + 0.6 * front
      g.textAlign = place.align
      g.fillText(look.names[tip.k], place.x, place.y)
    }
    g.globalAlpha = 1
    // the people she knows, from the back to the front
    const people = map.people.map(person => {
      const [px, py, z, near] = screen(person.at)
      return { px, py, z, size: (4 + 8 * Math.min(1, person.weight / T.MOST)) * scale * near, person }
    }).sort((one, other) => one.z - other.z)
    for (const item of people) {
      g.globalAlpha = 0.55 + 0.45 * depth(item.z)
      personDot(g, item, look, colour, width, font)
      g.font = `${font}px system-ui, -apple-system, sans-serif`
    }
    g.globalAlpha = 1
  }

  return {
    SPREAD, STARS, PROBE, LEAST, SHORTEST, LONGEST, GAIN, APART, TURNS, ANGLES, DIRECTIONS, OLD,
    tags, features, Table, Random, readStarter, isGzip, born, shares, spot, spot3, brightness, strongest, strengths,
    arms, probeOf, starmap, drawFlat, drawRound, project, placeNames
  }
})

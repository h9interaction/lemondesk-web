// 2.3.3 폰 아래 띠의 텃밭·목장·바닷가 장면: 맥 LemonDesk/FarmScene.swift(윈도우 SceneFarm.cs)를 그대로 옮긴 것.
// 배치·동작표·고르기 규칙은 맥과 같게 둔다(바꾸면 세 곳을 같이). 좌표는 맥과 같은 pt(왼쪽 아래 원점, 띠 높이 72pt), 그릴 때 1pt = 2px.
// 맥처럼 프레임 넘김·걷기·떠다니기는 Web Animations 로 걸어 두고, 동물·일꾼이 다음 행동을 고를 때(몇 초에 한 번)만 깨어난다.
// 그림: sprites/farm.json(띠별 목록·닿는 점), 이름 규칙은 docs/research/phone-career-2.3.3.md '장면 그림'.
// 순수 규칙(Interact·동작표·seaWork)은 node 로도 돈다(점검: node scripts/m-motion-check.js).
(function (root) {
  // ── 맥 Interact.swift: 칸 일 고르기(점수 = 필요 × 가까움 × 새로움, 위 셋 중 점수 비례) ──
  const Interact = {
    harvest: new Set(['pull', 'cut', 'snip', 'milk', 'shear', 'egg', 'haul', 'scoop']),
    plant: new Set(['stake', 'pour']),
    need(verb, g) { return Interact.harvest.has(verb) ? (g >= 2 ? 1.6 : 0.5) : Interact.plant.has(verb) ? (g === 0 ? 1.5 : 0.6) : 1; },
    near(d) { return 0.25 + 0.75 * Math.exp(-Math.abs(d) / 220); },
    novelty(key, recent) { return recent.slice(-3).includes(key) ? 0.3 : recent.slice(-6).includes(key) ? 0.6 : 1; },
    key: o => `${o.verb}@${o.pen}`,
    score(o, x, recent) { return (o.weight ?? 1) * (o.need ?? 1) * Interact.near(o.x - x) * Interact.novelty(Interact.key(o), recent); },
    /** 동률이면 먼저 나온 후보가 앞(맥·윈도우와 같게). u: 0..<1 */
    choose(opts, x, recent, u, top = 3) {
      const ranked = opts.map((o, i) => ({i, o, s: Interact.score(o, x, recent)})).sort((a, b) => a.s !== b.s ? b.s - a.s : a.i - b.i).slice(0, top);
      const total = ranked.reduce((t, c) => t + c.s, 0);
      if (!(total > 0)) return null;
      let r = u * total;
      for (const c of ranked) { r -= c.s; if (r < 0) return c.o; }
      return ranked[ranked.length - 1].o;
    },
    remember(key, recent) { recent.push(key); if (recent.length > 8) recent.splice(0, recent.length - 8); },
    moments: {pratfall: ['pull', 0.06], taste: ['snip', 0.06], crab: ['haul', 0.08], chase: ['feed', 0.05]},
    moment(verb, u) {
      let r = u;
      for (const name of Object.keys(Interact.moments).sort()) {
        const [v, chance] = Interact.moments[name]; if (v !== verb) continue;
        if (r < chance) return name;
        r -= chance;
      }
      return null;
    },
  };
  // 맥 FarmScene.motion: 칸 종류 → 역할별 동작 그림
  const MOTION = {};
  for (const k of ['lettuce', 'cabbage']) MOTION[k] = {harvester: 'cut'};
  for (const k of ['potato', 'radish', 'ginseng']) MOTION[k] = {harvester: 'pull'};
  for (const k of ['tomato', 'cucumber', 'pepper']) MOTION[k] = {planter: 'stake', caretaker: 'tie', harvester: 'snip'};
  MOTION.strawberry = {harvester: 'snip'}; MOTION.watermelon = {caretaker: 'thump'};
  for (const k of ['chicken', 'duck', 'goose']) MOTION[k] = {caretaker: 'feed', harvester: 'egg'};
  MOTION.cow = {caretaker: 'brush', harvester: 'milk'}; MOTION.sheep = {caretaker: 'brush', harvester: 'shear'}; MOTION.pig = {caretaker: 'brush'};
  for (const k of ['calf', 'lamb']) MOTION[k] = {caretaker: 'bottle'};
  MOTION.bee = {caretaker: 'smoke'};
  const ROPE = new Set(['laver', 'seaweed', 'kelp', 'oyster', 'abalone', 'pearl']), PEN = new Set(['shrimp', 'flatfish', 'seabream', 'fry']);
  /** 맥 FarmScene.seaWork: 배 위 일(해조·조개 줄 끌어올리기, 심는 일꾼은 거꾸로 = 내리기, 가두리는 뜰채·치어 붓기). exists: 그림 있음 */
  function seaWork(kind, role, exists) {
    const rope = ROPE.has(kind || ''), pen = PEN.has(kind || '');
    const want = role === 'harvester' ? (rope ? ['haul', null] : pen ? ['scoop', null] : null)
      : role === 'planter' ? (rope ? ['haul', [7, 6, 5, 4, 3, 2, 1, 0]] : pen ? ['pour', null] : null) : null;
    if (want && exists(`${role}-${want[0]}-0`)) return want;
    return [role === 'planter' ? 'seed' : 'pick', null];
  }
  const PEN_W = 72, LEFT = 64, SEA_LEFT = 152, SEA_YARD = 72, SEA_LIFT = 35, RIGHT = 72, H = 72;
  const SEA_DOCK = 112; // 2.3.3 부두 가운데(폭 110pt, 사다리는 +34), 맥 FarmScene.seaDockX 와 같게
  const left = strip => strip === 'sea' ? SEA_LEFT : LEFT;
  /** 장면 폭(pt): 왼쪽 마당 + 칸들 + 오른쪽 마당 */
  const width = s => left(s.strip) + Math.max(1, s.pens.length) * PEN_W + RIGHT;
  const YIELD = {chicken: 'egg', duck: 'duckEgg', cow: 'milk', sheep: 'wool', pig: 'compost', bee: 'honey', goose: 'down'};
  const itemOf = k => k ? 'item-' + (YIELD[k] || k) : null;
  const blink = Array(22).fill(0).concat([1, 2, 1]), blink2 = Array(24).fill(0).concat([1, 1]);
  const A = (anim, o) => ({anim, order: null, per: 0.14, hold: null, weight: 1, emote: null, walk: false, hop: 0, turn: false, ...o});
  const ACTS = {
    cow: [A('idle', {order: blink, per: 0.12, hold: [3, 6], weight: 3}), A('graze', {order: [0, 1, 2, 3, 2, 3, 3, 2, 3, 3, 1, 0], per: 0.32, weight: 3}),
      A('tail', {order: [0, 1, 2, 1, 2, 3, 0], per: 0.15, weight: 2}), A('idle', {order: [0, 3, 3, 3, 0], per: 0.25, weight: 0.6, emote: 'emote-note'}), A('idle', {order: [0], per: 1, weight: 0.8, turn: true})],
    sheep: [A('idle', {order: blink, per: 0.12, hold: [3, 6], weight: 3}), A('eat', {order: [0, 1, 2, 2, 3, 2, 2, 3, 1, 0], per: 0.28, weight: 3}),
      A('rest', {order: [0], per: 1, hold: [6, 10], weight: 1}), A('rest', {order: [1], per: 1, hold: [8, 14], weight: 0.8}),
      A('shorn', {order: [0, 0, 1, 1, 1, 0], per: 0.3, weight: 0.4, emote: 'emote-heart'}), A('idle', {order: [0, 3, 3, 0], per: 0.25, weight: 0.6, emote: 'emote-note'}), A('idle', {order: [0], per: 1, weight: 0.8, turn: true})],
    pig: [A('idle', {order: blink, per: 0.12, hold: [2, 5], weight: 2}), A('eat', {order: [0, 1, 2, 3, 2, 3, 2, 1, 0], per: 0.25, weight: 2}), A('walk', {per: 0.11, weight: 2, walk: true}),
      A('mud', {order: [0, 0, 1, 0, 2, 0, 3, 0], per: 0.4, hold: [5, 9], weight: 1.5, emote: 'emote-heart'}), A('idle', {order: [0, 3, 3, 3, 0], per: 0.2, weight: 0.8})],
    goose: [A('idle', {order: blink, per: 0.12, hold: [2, 5], weight: 2.5}), A('walk', {per: 0.13, weight: 2.5, walk: true}), A('flap', {order: [0, 1, 2, 1, 2, 3], per: 0.12, weight: 0.7}),
      A('idle', {order: [0, 3, 3, 0, 3, 3, 0], per: 0.14, weight: 0.8, emote: 'emote-note'})],
    young: [A('', {order: blink2, per: 0.12, hold: [2, 4], weight: 2}), A('', {order: [2, 3], per: 0.16, weight: 3, walk: true, hop: 1.5}),
      A('', {order: [0, 2, 3, 0, 2, 3, 0], per: 0.14, weight: 1, emote: 'emote-heart'}), A('', {order: [0], per: 1, weight: 0.6, turn: true})],
  };
  const stamped = new Set(); // 도장을 찍어 보인 피해 카드(페이지를 연 동안 한 번만, 맥 FarmScene.stamped)

  // ── 장면(브라우저에서만) ──
  // ctx: {pan, calm, art(name, dye, lit) → Promise<url>, index() → sprites/index.json, url(file), nowSec(), quiet()}
  function create(ctx) {
    const calm = ctx.calm, pan = ctx.pan;
    const P = v => Math.round(v * 2), r2 = v => Math.round(v * 2) / 2;
    const rnd = (a, b) => a + Math.random() * (b - a), coin = () => Math.random() < 0.5, anyOf = a => a[Math.floor(Math.random() * a.length)];
    const inR = (r, x) => x >= r[0] && x <= r[1];
    const I = () => ctx.index() || {};
    // 맥 그림 이름 → [폰 그림 이름, 프레임]. 일꾼 띠 동작은 w-<역할>-0-<동작>, 여러 장은 번호 뗀 가로 시트
    const phone = n => n.replace(/^(planter|caretaker|harvester)-(.+)$/, 'w-$1-0-$2');
    function res(mac) { const n = phone(mac), d = I(); if (d[n]) return [n, 0]; const m = /^(.*)-(\d+)$/.exec(n); return m && d[m[1]] && +m[2] < d[m[1]][2] ? [m[1], +m[2]] : null; }
    const sheetOf = prefix => { const n = phone(prefix), d = I(); return d[n] ? n : d[n + '-0'] ? n + '-0' : null; }; // 맥 Sprite.frames(prefix)
    const exists = mac => !!res(mac);

    const root = document.createElement('div');
    Object.assign(root.style, {position: 'relative', top: '28px', height: P(H) + 'px', overflow: 'hidden'}); root.style.overflow = 'clip'; // 아래를 띠(172px)에 맞추고 맥처럼 72pt 위는 자른다
    root.hidden = true; pan.append(root);
    let meta = null, farmJson = {groups: {}, anchors: {}}; const ready = {};
    function prepare(strip) { // 그 띠 그림을 처음 고를 때만 받는다(farm.json groups)
      meta = meta || fetch(ctx.url('farm.json')).then(r => r.json()).then(m => { farmJson = m; }).catch(() => {});
      return ready[strip] = ready[strip] || meta.then(() => Promise.all([...(farmJson.groups.common || []), ...(farmJson.groups[strip] || [])].map(n => ctx.art(n).catch(() => {}))));
    }

    let gen = 0, st = null, W = 0, on = false, builtKey = '', lastStrip = '', extra = {};
    let swaying, anchors, held, busyPens, recents, flocks, crewList, working, restSpots, storeX, eaves, touring, lifted, riding, mailbox, notesSeen, stampsSeen = null, peddlerUntil = 0;
    const later = (s, f) => { const g = gen; setTimeout(() => { if (g === gen) f(); }, s * 1000); };
    const penX = i => left(st.strip) + i * PEN_W;
    const growth = i => Math.min(Math.max(st.growth[i] ?? 2, 0), 2);
    const cold = () => st.disaster === 'cold';
    const coop = () => extra.coop || null;

    // ── 그림 요소 ──
    function node(cls, z, host = root) { const e = document.createElement('div'); e.className = cls; e.style.zIndex = Math.round(z * 100); host.append(e); return e; }
    function paint(e, name, frame = 0, dye = null, lit = false) {
      const [w, h] = I()[name], tok = e.tok = (e.tok || 0) + 1;
      Object.assign(e.style, {width: w + 'px', height: h + 'px', backgroundPosition: `${-frame * w}px 0`});
      ctx.art(name, dye, lit).then(u => { if (e.tok === tok) e.style.backgroundImage = `url("${u}")`; });
      return [w, h];
    }
    /** 프레임을 seq 순서로 넘긴다(맥 Sprite.flipbook). once 면 한 번 하고 마지막 프레임에 머문다. 걸리는 초 */
    function flipbook(e, name, seq, per, {once = false, dye = null, lit = false} = {}) {
      const w = paint(e, name, once ? seq[seq.length - 1] : seq[0], dye, lit)[0];
      if (e.fa) { e.fa.cancel(); e.fa = null; }
      if (seq.length < 2) return per;
      const kf = seq.map((f, i) => ({backgroundPosition: `${-f * w}px 0`, offset: i / seq.length, easing: 'steps(1, end)'}));
      kf.push({backgroundPosition: `${-seq[seq.length - 1] * w}px 0`, offset: 1});
      e.fa = e.animate(kf, {duration: seq.length * per * 1000, iterations: once ? 1 : Infinity});
      return seq.length * per;
    }
    /** 고정 그림(맥 prop: 아래 가운데가 x, y). 돌려주는 것: {el, x, y, w, h, top}(pt) */
    function prop(name, x, y, z, lit = false) {
      const r = res(name); if (!r) return null;
      const e = node('sp', z), [w, h] = paint(e, r[0], r[1], null, lit); x = r2(x);
      Object.assign(e.style, {left: P(x) - w / 2 + 'px', bottom: P(y) + 'px', transformOrigin: '50% 100%'});
      return {el: e, name: r[0], x, y, w: w / 2, h: h / 2, top: y + h / 2};
    }
    const hang = (name, x, top, z) => { const r = res(name); return r ? prop(name, x, r2(top - I()[r[0]][1] / 2), z) : null; };
    /** 가로로 이어 깐다. 하나 걸러 뒤집어 이음새를 맞추고, step 이면 뒤집지 않고 그 간격. part: 그림 아래쪽 이만큼만 */
    function tile(name, y, z, {step = null, host = root, part = 1} = {}) {
      const r = res(name); if (!r) return;
      const [iw, ih] = I()[r[0]], tw = step ?? iw / 2;
      for (let x = step == null ? 0 : -2, k = 0; x < W; x += tw, k++) {
        const e = node('sp', z, host); paint(e, r[0], r[1]);
        Object.assign(e.style, {left: P(x) + 'px', bottom: P(y) + 'px'});
        if (part < 1) { e.style.height = Math.round(ih * part) + 'px'; e.style.backgroundPositionY = '100%'; }
        if (step == null && k % 2 === 1) e.style.transform = 'scaleX(-1)';
      }
    }
    /** 텃밭 상자처럼 가운데를 이어 붙여 넓힌다(양 끝 cap 은 그대로) */
    function wide(name, x, y, z, width, cap) {
      const r = res(name); if (!r) return null;
      const [iwp, ihp] = I()[r[0]], iw = iwp / 2, mid = iw - cap * 2, x0 = r2(x - width / 2);
      const box = node('sp', z); Object.assign(box.style, {left: P(x0) + 'px', bottom: P(y) + 'px', width: P(width) + 'px', height: ihp + 'px'});
      const pieces = [[0, 0, cap]];
      for (let d = cap; d < width - cap - 0.01; d += mid) pieces.push([cap, d, Math.min(mid, width - cap - d)]);
      pieces.push([iw - cap, width - cap, cap]);
      for (const [src, dst, pw] of pieces) {
        const e = node('sp', 0, box); paint(e, r[0], r[1]);
        Object.assign(e.style, {left: P(dst) + 'px', width: P(pw) + 'px', backgroundPosition: `${-(r[1] * iwp + P(src))}px 0`});
      }
      return {el: box, x, y, w: width, h: ihp / 2, top: y + ihp / 2};
    }
    /** 제자리에서 화면 픽셀 단위로 오르내린다(맥 bob). 돌려주는 것: 애니메이션(멈출 때 cancel) */
    function bob(e, d, period) {
      const v = [0, d / 2, d, d / 2].map(x => ({translate: `0 ${-P(x)}px`, easing: 'steps(1, end)'}));
      return e.animate(v.map((k, i) => ({...k, offset: i / 4})).concat({translate: v[3].translate, offset: 1}), {duration: period * 1000, iterations: Infinity, delay: -rnd(0, period) * 1000});
    }
    const pulse = (e, a, b, period, delay = 0) => e.animate([{opacity: a}, {opacity: b}], {duration: period / 2 * 1000, direction: 'alternate', iterations: Infinity, easing: 'ease-in-out', delay: -delay * 1000});
    const sway = (e, d, period) => e.animate([{transform: 'translateX(0)'}, {transform: `translateX(${P(d)}px)`}], {duration: period / 2 * 1000, direction: 'alternate', iterations: Infinity, easing: 'ease-in-out'}); // 맥 drift(돛단배)
    function waver(e) { const p = rnd(2.4, 3.4); e.animate([{rotate: '-0.05rad'}, {rotate: '0.05rad'}], {duration: p * 1000, direction: 'alternate', iterations: Infinity, easing: 'ease-in-out', delay: -rnd(0, 3) * 1000}); }
    function lean(e) { // 태풍: 아랫면을 붙인 채 오른쪽으로 비스듬히, 끊어 흔들린다. 동작 줄이기면 기운 채로
      const m = k => `matrix(1, 0, ${-k}, 1, 0, 0)`;
      if (calm) { e.style.transform = m(0.15); return; }
      const v = [0.06, 0.16, 0.24, 0.16];
      e.animate(v.map((k, i) => ({transform: m(k), offset: i / 4, easing: 'steps(1, end)'})).concat({transform: m(0.16), offset: 1}), {duration: 1600, iterations: Infinity, delay: -rnd(0, 1600)});
    }

    // 장면 속 동물·사람 하나(맥 Critter). el 이 자리(translateX), body 가 그림·방향
    class Critter {
      constructor(sheet, x, y, range, dye = null) {
        Object.assign(this, {sheet, dye, x: r2(x), y, range, facing: 1, w: 0, h: 0});
        this.el = document.createElement('div'); this.el.className = 'ent';
        this.body = document.createElement('div'); this.body.className = 'bd'; this.el.append(this.body);
        this.el.style.bottom = P(y) + 'px'; this.el.style.transform = `translateX(${P(this.x)}px)`;
        this.face(coin() ? 1 : -1);
      }
      face(d) { this.facing = d; this.body.style.transform = `scaleX(${d})`; }
      size(name) { const [w, h] = I()[name]; this.w = w / 2; this.h = h / 2; this.body.style.marginLeft = -w / 2 + 'px'; }
      /** 동작 프레임을 order 순서로 되풀이하거나 한 번. 걸리는 초(그림이 없으면 1) */
      play(anim, order, per, once = false) {
        const name = sheetOf(anim ? `${this.sheet}-${anim}` : this.sheet); if (!name) return 1;
        const n = I()[name][2], seq = (order || [...Array(n).keys()]).map(i => Math.min(i, n - 1));
        this.size(name);
        return flipbook(this.body, name, seq, per, {once, dye: this.dye});
      }
      still(mac, lit = false) { const r = res(mac); if (!r) return false; this.size(r[0]); flipbook(this.body, r[0], [r[1]], 1, {lit}); return true; }
      walk(tx, speed, delay = 0) {
        tx = r2(tx); if (Math.abs(tx - this.x) < 0.5) return 0;
        this.face(tx > this.x ? 1 : -1);
        const d = Math.abs(tx - this.x), dur = d / Math.max(speed, 1);
        if (this.mv) this.mv.cancel();
        this.mv = this.el.animate([{transform: `translateX(${P(this.x)}px)`}, {transform: `translateX(${P(tx)}px)`}],
          {duration: dur * 1000, delay: delay * 1000, easing: `steps(${Math.max(1, Math.round(d * 2))}, end)`, fill: 'backwards'});
        this.el.style.transform = `translateX(${P(tx)}px)`; this.x = tx;
        return dur + delay;
      }
      hop(h, every, t) { this.unhop(); this.hp = this.el.animate([{translate: `0 ${-P(h)}px`, easing: 'steps(1, end)'}, {translate: '0 0', offset: 0.5}, {translate: '0 0'}], {duration: every * 1000, iterations: Math.max(1, t / every)}); }
      unhop() { if (this.hp) { this.hp.cancel(); this.hp = null; } }
      bob() { this.el.animate([{translate: '0 0', easing: 'steps(1, end)'}, {translate: '0 1px', offset: 0.5, easing: 'steps(1, end)'}, {translate: '0 1px'}], {duration: 1600, iterations: Infinity, delay: -rnd(0, 1600)}); }
      remove() { this.dead = true; this.el.remove(); }
    }
    const add = (c, z) => { c.el.style.zIndex = Math.round((z ?? 20 - c.y) * 100); root.append(c.el); return c; };
    /** 한 장짜리 움직이는 것(구름·편지·물방울): y 0 에 두고 path 로 옮긴다 */
    const thing = (mac, z, lit = false) => { const c = new Critter(null, 0, 0, [0, 0]); c.face(1); if (!c.still(mac, lit)) return null; return add(c, z); };
    /** pts(pt) 를 따라 끊어 옮기고 끝 자리에 둔다(맥 position 키프레임 discrete). 걸리는 초 */
    function path(c, pts, dur, loop = false) {
      const tf = ([x, y]) => `translate(${P(x)}px, ${P(c.y) - P(y)}px)`, last = pts[pts.length - 1];
      const kf = pts.map((p, i) => ({transform: tf(p), offset: i / pts.length, easing: 'steps(1, end)'})).concat({transform: tf(loop ? pts[0] : last), offset: 1});
      if (c.mv) c.mv.cancel();
      c.mv = c.el.animate(kf, {duration: dur * 1000, iterations: loop ? Infinity : 1});
      c.el.style.transform = tf(loop ? pts[0] : last); c.x = last[0];
      return dur;
    }
    function fly(c, p, q) { // 위로 휘어지게, 1초에 15번 끊어 난다
      const m = [(p[0] + q[0]) / 2, Math.max(p[1], q[1]) + 6], n = Math.max(2, Math.floor(Math.hypot(q[0] - p[0], q[1] - p[1]) / 45 * 15));
      const bez = (a, b, mm, t) => r2((1 - t) * (1 - t) * a + 2 * (1 - t) * t * mm + t * t * b);
      return path(c, Array.from({length: n + 1}, (_, k) => [bez(p[0], q[0], m[0], k / n), bez(p[1], q[1], m[1], k / n)]), n / 15);
    }

    // ── 효과 ──
    function emote(name, c) { // 머리 위에 기분 그림이 톡 튀어나왔다 사라진다
      if (calm) return;
      const top = c.y + c.h, e = prop(name, r2(c.x + c.facing * 3), top, 40, true); if (!e) return;
      e.el.animate([{translate: '0 4px', easing: 'steps(1, end)'}, {translate: '0 -6px', offset: 0.33, easing: 'steps(1, end)'}, {translate: '0 -2px', offset: 0.66}, {translate: '0 -2px'}], {duration: 180, fill: 'forwards'});
      later(1.3, () => e.el.remove());
    }
    function pop(name, p, q) { // 거둔 것이 대상에서 톡 튀어 올라 일꾼 쪽으로(아이콘은 9pt 로 줄여)
      if (calm) return; const r = res(name); if (!r) return;
      const [iw, ih] = I()[r[0]], c = new Critter(null, 0, 0, [0, 0]); c.face(1);
      flipbook(c.body, r[0], [r[1]], 1, {lit: true});
      const ph = Math.round(18 * ih / Math.max(iw, 1));
      Object.assign(c.body.style, {width: '18px', height: ph + 'px', marginLeft: '-9px', backgroundSize: `${Math.round(18 * I()[r[0]][2])}px ${ph}px`, backgroundPosition: `${-18 * r[1]}px 0`});
      add(c, 30);
      path(c, Array.from({length: 13}, (_, k) => { const t = k / 12; return [r2(p[0] + (q[0] - p[0]) * t), r2(p[1] + (q[1] - p[1]) * t + 22 * t * (1 - t))]; }), 0.75);
      later(0.75, () => c.el.animate([{opacity: 1}, {opacity: 0}], {duration: 250, fill: 'forwards'}));
      later(1.1, () => c.remove());
    }
    function breath(c) { // 입김
      const n = sheetOf('farm-fx-breath'); if (!n) return;
      const e = prop('farm-fx-breath-0', c.x + c.facing * (c.w / 2 - 2), c.y + c.h * 0.55, (20 - c.y) + 0.1); if (!e) return;
      const d = flipbook(e.el, n, [0, 1, 2], 0.22, {once: true, lit: true}); later(d, () => e.el.remove());
    }
    function zzz(c) { // 고양이 머리 위 zzz(몸을 따라간다)
      const n = sheetOf('fx-zzz'); if (!n) return;
      const z = document.createElement('div'); z.className = 'bd'; c.body.append(z);
      const w = paint(z, n, 0, null, true)[0];
      Object.assign(z.style, {left: `calc(50% + 12px - ${w / 2}px)`, bottom: P(c.h) - 4 + 'px'});
      flipbook(z, n, [...Array(I()[n][2]).keys()], 0.5, {lit: true});
    }
    function egg(x, y) { const l = prop('farm-ranch-egg-0', x, y, 20 - y - 0.1); if (l) later(6, () => l.el.remove()); }

    // ── 짓기 ──
    function stop() {
      gen++; root.replaceChildren();
      swaying = []; anchors = new Map(); held = new Set(); busyPens = new Set(); recents = new Map(); flocks = new Map(); crewList = []; working = new Set();
      restSpots = []; storeX = null; eaves = []; touring = false; lifted = 0; riding = new Set(); mailbox = null;
    }
    function rebuild() {
      stop(); W = width(st);
      root.style.width = P(W) + 'px'; place();
      if (st.strip === 'ranch') ranch(); else if (st.strip === 'field') field(); else if (st.strip === 'sea') sea();
      trophies(); weather(); postbox(7); coopGuests();
      if (!calm && st.disaster !== 'typhoon') cloud(true);
    }
    function place() { // 장면이 화면보다 좁으면 가운데(맥 FarmSceneView.relayout)
      root.style.marginLeft = Math.max(0, Math.round((pan.clientWidth - P(W)) / 2)) + 'px';
    }

    // ── 조합 손님·우체통(게임 값은 보기만) ──
    function coopGuests() {
      const c = coop(); if (c) { stampsSeen = c.stamps || 0; peddlerUntil = c.peddler ? c.peddler.until : 0; }
      later(rnd(3, 8), peddler); later(2, () => clerk());
    }
    function coopChanged() { // 상태가 새로 올 때(맥 watchCoop)
      const c = coop(); if (!c) return;
      if (stampsSeen != null && (c.stamps || 0) > stampsSeen) delivered();
      stampsSeen = c.stamps || 0;
      const until = c.peddler ? c.peddler.until : 0;
      if (until !== peddlerUntil) { peddlerUntil = until; peddler(); }
      clerk();
    }
    function peddler() { // 행상: 와 있는 동안 가끔 수레를 밀고 지나가다 가운데쯤 멈춰 종을 울린다
      const p = coop() && coop().peddler;
      if (touring || !p || !(p.until > ctx.nowSec()) || !exists('farm-guest-peddler-cart-0')) return;
      touring = true;
      const sea = lifted > 0, x0 = calm ? (sea ? 18 : W - 64) : -40, gap = 25, speed = 11.5;
      const m = new Critter('farm-guest-peddler', x0, 1 + lifted, [x0, W + 90]), cart = new Critter('farm-guest-peddler-cart', x0 + gap, 1 + lifted, m.range);
      m.face(1); cart.face(1); add(cart, 18.6); add(m, 18.7);
      if (calm) { m.play('bell', [0], 1); cart.play('', [0], 1); return; }
      const roll = () => { m.play('walk', null, 0.2); cart.play('', null, 0.2); };
      roll();
      const stopX = Math.round((sea ? rnd(12, 20) : rnd(W * 0.35, W * 0.6)) * 2) / 2;
      const t1 = m.walk(stopX, speed); cart.walk(stopX + gap, speed);
      later(t1, () => { m.play('bell', [0], 1); cart.play('', [0], 1); m.hop(0.5, 0.3, 2.4); });
      later(t1 + 3, () => {
        roll();
        const out = sea ? -60 : W + 50, t2 = m.walk(out, speed); cart.walk(out + gap, speed);
        if (sea) cart.face(1);
        later(t2, () => { m.remove(); cart.remove(); });
        later(t2 + rnd(40, 90), () => { touring = false; peddler(); });
      });
    }
    function clerk() { // 보험금: 이 띠의 끝난 피해 카드에 보험금이 나왔으면 직원이 와서 도장을 쾅(카드마다 한 번)
      if (calm || !exists('farm-guest-clerk-0')) return;
      const c = ((coop() || {}).losses || []).find(l => l.paid > 0 && l.strip === st.strip); if (!c) return;
      const id = `${c.strip}-${c.kind}-${c.lost}`; if (stamped.has(id)) return; stamped.add(id);
      const m = add(new Critter('farm-guest-clerk', -20, 1 + lifted, [-30, W]), 18.7);
      m.play('walk', null, 0.14);
      let t = m.walk(Math.round(rnd(...(lifted > 0 ? [24, 40] : [80, 120])) * 2) / 2, 10);
      later(t, () => m.play('', [0], 1)); t += 0.6;
      later(t, () => m.play('stamp', [0, 1, 1, 0, 1, 1, 0], 0.25, true)); t += 1.75 + 0.8;
      later(t, () => { m.play('walk', null, 0.14); const back = m.walk(-30, 10); later(back, () => m.remove()); });
    }
    function delivered() { // 납품: 도장이 늘면 직원이 조합 수레를 밀고 떠난다
      if (calm || !exists('farm-coop-cart-0')) return;
      const sea = lifted > 0, x0 = Math.round((sea ? 22 : rnd(W * 0.3, W * 0.5)) * 2) / 2, gap = 26, dir = sea ? -1 : 1;
      const m = new Critter('farm-guest-clerk', x0, 1 + lifted, [-200, W + 90]), cart = new Critter('farm-coop-cart', x0 + gap * dir, 1 + lifted, m.range);
      m.face(dir); cart.face(dir); add(cart, 18.6); add(m, 18.7);
      m.play('walk', null, 0.14); cart.play('', null, 0.2);
      const out = sea ? -60 : W + 50, t = m.walk(out, 10); cart.walk(out + gap * dir, 10);
      later(t, () => { m.remove(); cart.remove(); });
    }
    function postbox(x) { mailbox = prop(`farm-mailbox-${extra.notes > 0 ? 1 : 0}`, x, 2 + lifted, 9.5); notesSeen = extra.notes || 0; }
    function mailChanged() { // 쪽지가 새로 오면 편지가 팔랑이며 내려와 우체통에 쏙, 깃발이 올라간다
      const n = extra.notes || 0, before = notesSeen; notesSeen = n;
      const box = mailbox; if (!box) return;
      const flag = () => { const r = res(`farm-mailbox-${n > 0 ? 1 : 0}`); if (r) flipbook(box.el, r[0], [r[1]], 1); };
      const l = n > before && !calm && thing('farm-fx-letter-0', 40);
      if (!l) return flag();
      const to = [box.x, box.top - 6], from = [to[0] + 46, H + 6], k = 30;
      const d = path(l, Array.from({length: k + 1}, (_, i) => { const t = i / k; return [r2(from[0] + (to[0] - from[0]) * t + Math.sin(t * 9) * 3 * (1 - t)), r2(from[1] + (to[1] - from[1]) * t)]; }), k / 15);
      later(d, () => {
        l.remove(); flag();
        box.el.animate([1.5, 0.5, 0, 0.5, 0].map((v, i) => ({translate: `0 ${-P(v)}px`, offset: i / 5, easing: 'steps(1, end)'})).concat({translate: '0 0', offset: 1}), {duration: 400});
      });
    }

    // ── 목장: 언덕·울타리·건초 마당, 칸마다 우리 하나 ──
    function ranch() {
      tile('farm-ranch-far-0', 18, 0.5); tile('farm-ranch-hills-0', 13, 1); tile('farm-ranch-ground-0', 0, 2);
      tile('farm-ranch-fence-0', 10, 3, {step: 17.5});
      prop('farm-ranch-haystack-0', 22, 7, 4); prop('farm-ranch-crate-0', 46, 3, 9); storeX = 46;
      const stage = Math.min(Math.max(st.stage, 1), 5);
      if (stage >= 3) prop('farm-ranch-windmill-0', 40, 10, 2.5);
      for (let i = 1; i < st.pens.length; i += 2) { prop('farm-ranch-tree-0', penX(i + 1) - 2, 10, 2.5); restSpots.push(penX(i + 1) - 2); }
      let mother = null;
      st.pens.forEach((kind, i) => {
        const x0 = penX(i), x1 = x0 + PEN_W;
        switch (kind) {
          case 'chicken':
            eave(prop('farm-ranch-coop-0', x0 + 22, 6, 5), 0.53);
            if (i === 0) prop('farm-ranch-trough-0', x0 + 52, 6, 6);
            for (let k = 0; k < 2; k++) {
              const c = add(new Critter('farm-ranch-chicken', x0 + 34 + k * 18, [4, 2.5][k], [x0 + 30, x1 - 4]));
              if (!flocks.has(i)) flocks.set(i, []); flocks.get(i).push(c);
              later(rnd(0, 1.5), () => chicken(c));
            }
            break;
          case 'duck': {
            prop('farm-ranch-pond-0', x0 + PEN_W / 2, 6, 5);
            const s = add(new Critter('farm-ranch-duck', x0 + 44, 9.5, [x0 + 36, x0 + 60]), 6); s.bob();
            later(rnd(0, 1), () => swimmer(s));
            const d = add(new Critter('farm-ranch-duck', x0 + 20, 1.5, [x0 + 6, x1 + 10]));
            let kids = [];
            if (!mother) { // 첫 오리 우리의 어미 뒤에는 새끼 오리 셋이 줄지어 따라다닌다
              mother = d;
              kids = [0, 1, 2].map(k => add(new Critter('farm-ranch-duckling', d.x - (8 + 7 * k), 1, d.range)));
              for (const k of kids) k.play('walk', [0], 1);
            }
            later(rnd(0, 2), () => duck(d, kids));
            break;
          }
          case 'cow': eave(prop('farm-ranch-barn-0', x0 + 26, 6, 5), 0.5); anchors.set(i, animal('farm-ranch-cow', x0 + 52, 2, [x0 + 44, x1 - 6], ACTS.cow)); break;
          case 'calf': prop('farm-ranch-haybale-0', x0 + 16, 6, 5); prop('farm-ranch-milkcan-0', x0 + 32, 5, 6); anchors.set(i, animal('farm-ranch-calf', x0 + 50, 2, [x0 + 24, x1 - 6], ACTS.young)); break;
          case 'sheep': prop('farm-ranch-shelter-0', x0 + 20, 6, 5); prop('farm-ranch-woolbasket-0', x0 + 40, 4, 7); anchors.set(i, animal('farm-ranch-sheep', x0 + 56, 2, [x0 + 50, x1 - 8], ACTS.sheep)); break;
          case 'lamb': prop('farm-ranch-shelter-0', x0 + 20, 6, 5); anchors.set(i, animal('farm-ranch-lamb', x0 + 50, 2, [x0 + 24, x1 - 6], ACTS.young)); break;
          case 'pig': prop('farm-ranch-sty-0', x0 + 24, 6, 5); prop('farm-ranch-compost-0', x0 + 62, 6, 5); anchors.set(i, animal('farm-ranch-pig', x0 + 46, 2, [x0 + 36, x1 - 14], ACTS.pig)); break;
          case 'goose': eave(prop('farm-ranch-goosehouse-0', x0 + 18, 6, 5), 0.6); anchors.set(i, animal('farm-ranch-goose', x0 + 48, 2, [x0 + 34, x1 - 4], ACTS.goose)); break;
          case 'bee': {
            prop('farm-ranch-flowers-0', x0 + 46, 4, 6); prop('farm-ranch-flowers-0', x0 + 62, 3, 7);
            const hive = prop('farm-ranch-beehive-0', x0 + 24, 5, 5);
            if (hive && !calm) for (let k = 0; k < 3; k++) hover('farm-ranch-bee', [x0 + 36, hive.top - 2], 12 + k * 6, 5, 5 + k * 1.7, -1);
            break;
          }
          case 'ricotta': prop('farm-ranch-cheesetable-0', x0 + 28, 4, 6); prop('farm-ranch-milkcan-0', x0 + 54, 4, 6); break;
        }
      });
      const right = W - RIGHT;
      prop(stage >= 4 ? 'farm-ranch-haystack-1' : 'farm-ranch-haybale-0', right + 26, 6, 4);
      const flowers = prop('farm-ranch-dandelion-0', right + 54, 2, 9);
      guestCat([right + 8, W - 10], right + 40);
      crew({planter: 'seed', caretaker: 'water', harvester: 'pick'}, [12, W - 20]);
      if (calm) return;
      if (flowers) later(1, () => seed(flowers));
      later(rnd(2, 5), () => sparrow([{x: [20, W - 30], y: 19.5, z: 3.5}]));
    }

    // ── 텃밭: 조각보 언덕·검은 흙, 비닐하우스, 칸마다 이랑 하나에 작물 셋(자람), 오른쪽 허수아비 ──
    function field() {
      tile('farm-field-far-0', 18, 0.5); tile('farm-field-hills-0', 13, 1); tile('farm-field-ground-0', 0, 2);
      eave(prop('farm-field-greenhouse-0', 37, 7, 3), 0.42); restSpots.push(46);
      prop('farm-field-can-0', 60, 3, 9);
      const dry = st.disaster === 'drought';
      const tall = ['farm-field-sunflower-0', 'farm-field-corn-0', 'farm-field-hollyhock-0', 'farm-field-beanteepee-0', 'farm-field-birdpole-0', 'farm-field-pinwheel-0'].filter(exists);
      st.pens.forEach((kind, i) => {
        const x0 = penX(i), bed = wide('farm-field-bed-0', x0 + PEN_W / 2, 3, 4, PEN_W - 6, 14);
        if (!kind) return;
        const g = growth(i);
        if (['tomato', 'cucumber', 'pepper'].includes(kind)) prop(`farm-field-trellis-${g}`, x0 + PEN_W / 2, 6, 3.5);
        else if (g > 0 && tall.length) { const name = tall[i % tall.length], l = prop(name, x0 + PEN_W / 2, 6, 3.5); if (l && name !== 'farm-field-birdpole-0') swaying.push(l); }
        if (i % 2 === 0) { const l = prop('farm-field-cosmos-0', x0 + 1, 2, 4.6); if (l) swaying.push(l); }
        if (i === 1) prop('farm-guest-ladybug-0', x0 + 14, 6.5, 6);
        if (i === 3) prop('farm-guest-rabbit-0', x0 + PEN_W - 6, 2, 8);
        const top = (bed ? bed.top : 9) - 4.5;
        if (kind === 'kimchi') { for (let k = 0; k < 2; k++) prop(`crop-kimchi-${g}`, x0 + 24 + k * 24, top, 5); return; }
        for (let k = 0; k < 3; k++) {
          const wilt = g > 0 && (dry ? (i + k) % 3 === 0 : st.poor.includes(kind) && (i + k) % 2 === 0);
          const l = prop(wilt ? 'farm-fx-wilt-0' : `crop-${kind}-${g}`, x0 + PEN_W / 2 + (k - 1) * 20, top, 5 + k * 0.01); if (l) swaying.push(l);
        }
      });
      const right = W - RIGHT, crow = prop('farm-field-scarecrow-0', right + 20, 3, 4);
      if (crow) swaying.push(crow);
      prop('farm-field-crate-0', right + 44, 2, 8); storeX = right + 44;
      prop('farm-field-barrow-0', right + 60, 2, 7);
      guestCat([right + 30, W - 8], right + 52);
      crew({planter: 'dig', caretaker: 'water', harvester: 'pick'}, [40, W - 30]);
      if (calm) return;
      for (let k = 0; k < 2; k++) hover(k === 0 ? 'farm-guest-butterfly-y' : 'farm-guest-butterfly-w', [rnd(60, Math.max(61, W - 60)), rnd(26, 34)], rnd(26, 40), 6, rnd(9, 13), -1);
      later(rnd(3, 6), earthworm);
      const perch = crow ? [{x: [crow.x, crow.x], y: crow.top - 3, z: 4.5}] : [];
      later(rnd(2, 5), () => sparrow(perch));
    }

    // ── 바닷가: 왼쪽 육지(모래 마당·비탈), 그 오른쪽 바다. 말뚝 줄에 해조·조개, 가두리 물고기, 일꾼은 배를 타고 칸으로 ──
    function sea() {
      const ebb = st.tide === 'ebb', surface = ebb ? 26 : 38, flood = 38, red = st.disaster === 'redtide', lift = SEA_LIFT, still = calm, right = W - RIGHT;
      lifted = lift;
      const water = node('sp', 2); Object.assign(water.style, {left: 0, bottom: 0, width: P(W) + 'px', height: P(H) + 'px', overflow: 'hidden'});
      if (red) { // 적조: 붉은 물 띠
        tile('farm-sea-redtide-0', surface - 26, 2, {host: water});
        for (let y = surface - 26; y > 0;) { y -= 26 * 0.4 - 1.5; tile('farm-sea-redtide-0', y, 2, {host: water, part: 0.4}); }
      } else tile('farm-sea2-water-0', surface - 37, 2, {host: water});
      if (ebb && !red) { // 썰물엔 내려간 물과 먼 바다 사이를 옅은 물로
        const fill = node('sp', 0.45); Object.assign(fill.style, {left: 0, bottom: P(surface) + 'px', width: P(W) + 'px', height: P(flood - surface) + 'px', overflow: 'hidden', opacity: 0.75});
        tile('farm-sea2-water-0', flood - surface - 37, 0, {host: fill});
      }
      tile('farm-sea2-far-0', flood - 3, 0.5); tile('farm-sea2-bed-0', 0, 2.5);
      prop('farm-sea2-lighthouse-0', Math.round(W * 0.58 * 2) / 2, flood - 3, 0.6);
      const sail = prop('farm-sea2-sailboat-0', penX(0) + 150, surface - 3, 1.6);
      if (sail && !still) { bob(sail.el, 0.5, 3); sway(sail.el, 120, 90); }
      for (let i = 0; i <= st.pens.length; i++) { // 바다 밑 산호 정원
        const x = penX(i);
        if (i < st.pens.length) { const back = prop(`farm-sea2-coral-${(i + 3) % 6}`, x + PEN_W / 2, 4, 2.6); if (back) back.el.style.opacity = 0.5; }
        const c = prop(`farm-sea2-coral-${i % 6}`, x, 2, 3.4); if (c && !still && (i % 6 === 3 || i % 6 === 5)) waver(c.el);
        if (i < st.pens.length) { prop(`farm-sea2-bit-${(i * 2) % 6}`, x + 26, 2, 3.5); if (i % 2 === 1) prop(`farm-sea2-bit-${(i * 2 + 1) % 6}`, x + 46, 2, 3.5); }
      }
      if (!red) for (let x = penX(0) + 60, k = 0; x < right; x += 230, k++) { // 햇살 줄기
        const b = hang(`farm-sea2-beam-${k % 2}`, x, surface, 2.2);
        if (b) { b.el.style.opacity = 0.25; if (!still) pulse(b.el, 0.18, 0.38, 5); }
      }
      const perches = [];
      st.pens.forEach((kind, i) => {
        const x0 = penX(i), mid = x0 + PEN_W / 2, g = growth(i);
        if (!kind) return;
        const sign = exists(`farm-sea-sign-${kind}`) ? `farm-sea-sign-${kind}` : 'farm-sea-sign-blank';
        if (ROPE.has(kind)) {
          const rope = hang('farm-sea2-rope-0', mid, surface + 15, 4.9);
          if (rope) { rope.el.style.transform = 'scaleX(-1)'; if (!still) bob(rope.el, 0.5, 2.6); }
          const shell = ['oyster', 'abalone', 'pearl'].includes(kind);
          if (shell || g > 0) for (const dx of [-12, 12]) { const l = hang(`crop2-${kind}-${shell ? (g === 2 ? 2 : 1) : g}`, mid + dx, surface - 0.5, 4.8); if (l && !still) bob(l.el, 0.5, 2.4); }
          prop(sign, mid - 24, surface + 2.5, 5.0);
        } else if (kind === 'giftSet') {
          const l = prop('farm-sea-giftraft-0', mid, surface - 2, 4.6); if (l && !still) bob(l.el, 0.5, 2.8);
        } else if (PEN.has(kind)) {
          const cage = hang(kind === 'fry' ? 'farm-sea2-nursery-0' : 'farm-sea2-pen-0', mid, surface + 4, 4.5);
          if (cage && !still) bob(cage.el, 0.5, 2.8);
          prop(sign, mid - 26, surface + 1, 5.0);
          const h = cage ? cage.h : 20, half = (cage ? cage.w : 40) / 2 - 7, cageTop = (cage ? cage.top : surface + 4) - 4, tight = red ? 0.4 : 1;
          const sheet = kind === 'fry' ? 'farm-sea2-school' : kind === 'seabream' ? 'farm-sea2-bream' : `farm-sea-${kind}`;
          for (let k = 0; k < (kind === 'fry' ? 1 : 2); k++) {
            const fy = Math.round((cageTop - h * (0.4 + 0.25 * k)) * 2) / 2;
            const f = add(new Critter(sheet, mid + (k * 2 - 1) * 4, fy, [mid - half * tight, mid + half * tight]), 4.5 + 0.2);
            later(rnd(0, 1.5), () => swim(f));
          }
        }
        if (i % 3 === 2 && i + 1 < st.pens.length) { // 칸 경계 몇 곳에 깃발 부표(갈매기 쉼터)
          const buoy = prop('farm-sea2-buoy-0', penX(i + 1), surface - 5, 5.2);
          if (buoy) { if (!still) bob(buoy.el, 0.5, 2.2); perches.push([buoy.x, buoy.top - 1]); }
        }
      });
      // 해안: 풀 덮인 갯바위, 레몬나무·깃발 줄·파라솔·굴 상자, 잔교
      const land = res('farm-sea2-land-0');
      prop('farm-sea2-land-0', (land ? I()[land[0]][0] / 2 : 175) / 2, lift - 34, 5.5);
      prop('farm-sea2-tree-0', 14, lift - 2, 6.5); prop('farm-sea2-bunting-0', 40, lift + 14, 6.6);
      const para = prop('farm-sea2-parasol-0', 60, lift - 1, 7);
      if (para && !still) flipbook(para.el, para.name, [0, 1], 1.2);
      restSpots.push(56);
      prop('farm-sea2-towel-0', 68, lift - 1, 7.1); prop('farm-sea2-crate-0', 48, lift - 1, 8); if (exists('farm-sea2-dock-0')) prop('farm-sea2-dock-0', SEA_DOCK, 1, 4.7); else prop('farm-sea2-pier-0', 138, surface - 5, 4.8);
      const hut = prop('farm-sea2-cottage-0', W - 22, surface - 4, 4.4);
      if (hut) { if (!still) bob(hut.el, 0.5, 3); perches.push([hut.x - 4, hut.top - 3]); }
      const otter = add(new Critter('farm-sea2-otter', right + 18, surface - 6, [right + 10, right + 26]), 5.5);
      otter.play('', null, 1.4); if (!still) bob(otter.el, 0.5, 2.6);
      const dock = exists('farm-sea2-dock-0') ? SEA_DOCK + 34 : ebb ? 128 : 116, skiff = new Critter(exists('farm-sea-rowboat-0') ? 'farm-sea-rowboat' : 'farm-sea-skiff', dock, surface - 5, [dock, right]);
      skiff.face(1); add(skiff, 4.9); skiff.play('', [0], 1);
      if (!calm) skiff.bobA = bob(skiff.el, 0.5, 3);
      const crewOnLand = [];
      for (const role of st.workers) {
        if (role === 'caretaker') continue;
        const range = [6, SEA_YARD - 10], c = add(new Critter(role, rnd(...range), lift + 1, range, OUTFIT.sea), 19);
        c.play('idle', null, 0.15); crewOnLand.push(c); crewList.push(c);
        const yardAct = role === 'planter' ? (exists('planter-rake-0') ? 'rake' : 'dig') : (exists('harvester-crate-0') ? 'crate' : 'carry');
        later(rnd(0.5, 3), () => work(c, yardAct));
      }
      const sand = [8, SEA_YARD - 8];
      const crab = add(new Critter('farm-guest-crab', 40, lift + 1, sand), 19.5); crab.play('', [0], 1);
      const hermit = add(new Critter('farm-guest-hermit', rnd(...sand), lift + 1, sand), 19.4); hermit.play('', [0], 1);
      const piper = add(new Critter('farm-guest-sandpiper', rnd(...sand), lift + 1, sand), 19.3); piper.play('', [2], 1);
      const bed = [penX(0), right - 8], top = Math.max(8, surface - 9), swimmers = [];
      [['farm-sea2-stripe', 12], ['farm-sea2-yellow', 20], ['farm-sea2-blue', 9], ['farm-sea2-puffer', 16], ['farm-sea2-school', 24], ['farm-sea2-stripe', 26], ['farm-sea2-blue', 15]].forEach(([sheet, y], k) => {
        if (!exists(`${sheet}-0`)) return;
        const f = add(new Critter(sheet, rnd(...bed), Math.min(y, top), bed), k % 2 === 0 ? 3.6 : 5.3); f.play('', null, 0.3); swimmers.push(f);
      });
      const turtle = add(new Critter(exists('farm-sea2-turtle-0') ? 'farm-sea2-turtle' : 'farm-guest-turtle', rnd(...bed), Math.min(18, top - 4), bed), 3.7);
      turtle.play('', null, 0.35); swimmers.push(turtle);
      for (const [sheet, x, y, per] of [['farm-sea2-seahorse', penX(0) + 80, 12, 0.5], ['farm-sea2-seahorse', penX(0) + 6 * PEN_W - 8, 16, 0.55], ['farm-sea2-octopus', penX(0) + 4.6 * PEN_W, 4, 0.7],
        ['farm-sea2-jelly', penX(0) + 5.5 * PEN_W, Math.min(22, top), 0.7], ['farm-sea2-crab', penX(0) + 3.2 * PEN_W, 3, 0.6]]) {
        if (!(x < right) || !exists(`${sheet}-0`)) continue;
        const c = add(new Critter(sheet, x, y, [x, x]), 3.6); c.play('', null, still ? 1 : per);
        if (!still && sheet !== 'farm-sea2-crab' && sheet !== 'farm-sea2-octopus') bob(c.el, 0.5, 2.5);
      }
      for (let k = 0; k < 2; k++) {
        const s = add(new Critter('farm-guest-starfish', rnd(...bed), 3, bed), 3.7);
        s.play('', calm ? [0] : Array(Math.floor(rnd(10, 17))).fill(0).concat([1, 1, 0, 1]), 0.5); // 가끔 팔 끝을 들어 흔든다
      }
      if (!still && !red) for (let k = 0; k < 8 && penX(0) + 40 + k * 97 < right; k++) { const t = prop(`farm-sea2-twinkle-${k % 2}`, penX(0) + 40 + k * 97, surface - 1 - k % 3, 5.7); if (t) pulse(t.el, 0, 1, 2.4, k * 0.6); }
      later(rnd(1, 3), () => crabWalk(crab));
      if (calm) return;
      later(rnd(1, 3), () => hermitLife(hermit));
      later(rnd(0.5, 2), () => sandpiper(piper));
      for (const f of swimmers) later(rnd(0, 3), () => cruise(f));
      later(rnd(6, 12), () => trip(skiff, crewOnLand, dock, surface));
      later(rnd(2, 5), () => gull(perches));
      later(rnd(3, 6), () => leap(surface, penX(0)));
      later(rnd(0.3, 1), () => bubbles(surface, penX(0), right));
    }
    const OUTFIT = {field: 112, ranch: 38, sea: 50}; // 맥 FarmScene.outfit(farm.json outfit 과 같다)
    function cruise(f) { const t = Math.max(2, f.walk(rnd(...f.range), rnd(4, 9))); later(t + rnd(0.5, 3), () => cruise(f)); }
    function swim(f) { f.play('', null, 0.25); const t = Math.max(1.5, f.walk(rnd(...f.range), rnd(2, 4))); later(t + rnd(0.5, 2), () => swim(f)); }
    function trip(boat, crewOnLand, dock, surface) { // 일꾼이 육지 끝으로 가서 배를 타고 칸 하나 앞으로 가서 일하고 돌아온다
      const c = anyOf(crewOnLand); if (!c || !st.pens.length) return;
      riding.add(c); c.play('walk', null, 0.1);
      later(c.walk(SEA_YARD - 6, 10), () => {
        c.el.hidden = true;
        const rider = add(new Critter(c.sheet, dock, surface - 3.5, [dock, W], c.dye), 4.85); rider.face(1); rider.play('idle', null, 0.15);
        const i = Math.floor(Math.random() * st.pens.length), to = r2(penX(i) + PEN_W / 2);
        const rows = exists(`${rider.sheet}-row-0`), speed = rows ? 18 : 30, wake = rows ? null : wakeOn(boat);
        if (rows) rider.play('row', null, 0.12);
        if (boat.bobA) { boat.bobA.cancel(); boat.bobA = null; }
        let t = boat.walk(to, speed); rider.walk(to, speed);
        if (rows) rider.face(-rider.facing); // 노 젓는 사람은 배가 가는 반대쪽을 본다
        const [act, order] = seaWork(st.pens[i], rider.sheet, exists), kind = st.pens[i];
        later(t, () => { if (wake) wake.hidden = true; rider.face(1); rider.play(act, order, 0.14); });
        if ((act === 'haul' && !order || act === 'scoop') && kind) { // 끌어올리면 거둔 것이 물에서 톡, 가끔 게가 매달려 올라온다
          const crab = act === 'haul' && Interact.moment('haul', Math.random()) === 'crab' && exists('farm-sea2-crab-0');
          later(t + 2.2, () => { pop(crab ? 'farm-sea2-crab-0' : itemOf(kind), [to + 8, surface - 8], [to, surface + 14]); if (crab) emote('emote-bang', rider); });
        }
        t += rnd(3, 5);
        later(t, () => {
          rider.play(rows ? 'row' : 'idle', null, rows ? 0.12 : 0.15);
          if (wake) wake.hidden = false;
          const back = boat.walk(dock, speed); rider.walk(dock, speed);
          if (rows) rider.face(-rider.facing);
          later(back, () => {
            if (wake) wake.remove();
            boat.face(1); boat.bobA = bob(boat.el, 0.5, 3); rider.remove();
            c.el.hidden = false; c.face(-1); riding.delete(c);
            later(rnd(14, 30), () => trip(boat, crewOnLand, dock, surface));
          });
        });
      });
    }
    function wakeOn(boat) { // 배 엔진 뒤 물보라(배 몸에 붙여 같이 움직이고 뒤집힌다)
      const r = res('farm-fx-splash-0'); if (!r) return null;
      const e = document.createElement('div'); e.className = 'bd'; boat.body.append(e);
      const w = paint(e, r[0], r[1])[0];
      Object.assign(e.style, {left: -4 - w / 2 + 'px', bottom: '2px'});
      e.animate([{transform: 'scaleX(1)', easing: 'steps(1, end)'}, {transform: 'scaleX(-1)', offset: 0.5, easing: 'steps(1, end)'}, {transform: 'scaleX(-1)'}], {duration: 300, iterations: Infinity});
      return e;
    }
    function hermitLife(c) { // 소라게: 느릿느릿 걷다가 가끔 껍데기에 쏙 숨었다가 다시 나온다
      let t; const r = Math.random();
      if (r < 0.55) { c.play('', [0, 1], 0.25); t = c.walk(rnd(...c.range), rnd(2.5, 4)); later(t, () => c.play('', [0], 1)); }
      else if (r < 0.8) { c.play('', [2], 1); t = rnd(2, 5); later(t, () => c.play('', [3, 3, 3, 0], 0.4, true)); t += 1.6; }
      else t = rnd(1, 3);
      later(t + rnd(0.5, 2), () => hermitLife(c));
    }
    function sandpiper(c) { // 물떼새: 종종걸음으로 달리다 멈춰 콕콕
      let t;
      if (coin()) { c.play('', [0, 1], 0.08); t = c.walk(rnd(...c.range), rnd(18, 24)); later(t, () => c.play('', [2], 1)); }
      else t = c.play('', [2, 3, 2, 3, 3, 2], 0.22, true);
      later(t + rnd(0.6, 2.5), () => sandpiper(c));
    }
    function crabWalk(c) { // 게: 옆걸음으로 오가다 멈춰 집게를 든다
      let t;
      if (coin()) { c.play('', [0, 1], 0.12); t = c.walk(rnd(...c.range), rnd(6, 9)); c.face(1); later(t, () => c.play('', [0], 1)); }
      else { c.play('', [0, 1, 0, 1, 0], 0.3, true); t = 1.5; }
      later(t + rnd(1, 3), () => crabWalk(c));
    }
    function gull(perches) { // 갈매기: 날아 지나가다 가끔 부표·오두막에 내려앉는다
      later(rnd(9, 16), () => gull(perches));
      const n = sheetOf('farm-guest-gull'); if (!n || I()[n][2] < 4) return;
      const l = add(new Critter('farm-guest-gull', 0, 0, [0, 0]), 31), fromLeft = coin(), y = rnd(52, 62);
      l.face(fromLeft ? 1 : -1); l.play('', [0, 1], 0.2);
      const start = [fromLeft ? -20 : W + 20, y];
      if (!perches.length || Math.random() >= 0.45) { later(fly(l, start, [fromLeft ? W + 20 : -20, y + rnd(-6, 6)]), () => l.remove()); return; }
      const p = anyOf(perches);
      let t = fly(l, start, p);
      later(t, () => l.play('', [2, 2, 2, 3, 2, 2], 0.5));
      t += rnd(4, 8);
      later(t, () => { l.play('', [0, 1], 0.2); later(fly(l, p, [p[0] + (fromLeft ? 120 : -120), H + 10]), () => l.remove()); });
    }
    function leap(surface, x0) { // 물고기(가끔 돌고래)가 물 밖으로 휘어 뛰었다가 퐁
      later(rnd(6, 12), () => leap(surface, x0));
      const sheet = exists('farm-sea2-dolphin-0') && coin() ? 'farm-sea2-dolphin' : 'farm-sea-jumper', n = sheetOf(sheet);
      if (!n || I()[n][2] < 2 || !(W - 20 > x0 + 20)) return;
      const x = rnd(x0 + 20, W - 20), dir = coin() ? 1 : -1, k = 14;
      const l = add(new Critter(sheet, 0, 0, [0, 0]), 3.5); l.face(dir); l.play('', [0, 1], k / 15 / 2, true);
      const d = path(l, Array.from({length: k + 1}, (_, i) => { const t = i / k; return [r2(x + dir * 14 * t), r2(surface - 4 + 12 * 4 * t * (1 - t))]; }), k / 15);
      later(d, () => { l.remove(); const sp = prop('farm-fx-splash-0', x + dir * 14, surface - 2, 3.6); if (sp) later(0.5, () => sp.el.remove()); });
    }
    function bubbles(surface, x0, x1) { // 바다 밑에서 작은 방울이 흔들리며 올라와 물 위에서 사라진다
      later(rnd(0.5, 1.4), () => bubbles(surface, x0, x1));
      if (!(x1 - 10 > x0 + 10) || !(surface > 20)) return;
      const l = thing(anyOf(['farm-fx-bubble-0', 'farm-fx-bubble-0', 'farm-fx-bubble-1', 'farm-fx-bubbles-0']), 5.3); if (!l) return;
      const x = rnd(x0 + 10, x1 - 10), y0 = rnd(5, surface - 14), n = Math.floor((surface - y0 - 4) * 2), phase = rnd(0, 6);
      if (n <= 2) return l.remove();
      later(path(l, Array.from({length: n + 1}, (_, k) => [r2(x + Math.sin(k / 4 + phase) * 1.5), y0 + k / 2]), n / 10), () => l.remove());
    }

    // ── 날씨(무섭지 않게) ──
    function weather() {
      if (st.disaster === 'cold') {
        if (st.strip !== 'sea') prop('farm-ranch-snowman-0', W - RIGHT + 8, 2, 9);
        for (const p of eaves) hang('farm-fx-icicle-0', p.x, p.y, 5.5);
        particles('fx-snow');
      } else if (st.disaster === 'typhoon') {
        particles('fx-rain');
        for (const l of swaying) lean(l.el);
        if (!calm) { for (let k = 0; k < 2; k++) storm(rnd(46, 54), k * W / 2); later(rnd(0.5, 2), gust); }
      } else if (st.disaster === 'drought') {
        prop('farm-fx-heat-0', 24, 50, 0.5);
        if (st.strip !== 'sea') st.pens.forEach((_, i) => { if (i % 2 === 0) prop('farm-fx-crack-0', penX(i) + PEN_W / 2, 0.5, 2.5); });
      }
      if (st.forecast) { const l = prop('farm-fx-forecast-0', W - 22, 54, 0.6); if (l && !calm) bob(l.el, 1, 2); }
    }
    const eave = (l, k) => { if (l) eaves.push({x: l.x, y: r2(l.y + l.h * k)}); };
    function trophies() { // 단계 보상 소품(3·4단계)과 명인 깃발(5단계). 꾸미기만
      const s = st.stage, right = W - RIGHT;
      if (st.strip === 'field') { if (s >= 3) prop('farm-field-pumpkins-0', 12, 2, 8.5); if (s >= 4) prop('farm-field-seedstand-0', right + 36, 3, 3.5); }
      else if (st.strip === 'ranch') { if (s >= 3) prop('farm-ranch-churns-0', 54, 3, 8.5); if (s >= 4) prop('farm-ranch-weathervane-0', 36, 7, 3.5); }
      else if (st.strip === 'sea') {
        const surface = st.tide === 'ebb' ? 26 : 38;
        if (s >= 3) { const l = hang('farm-sea-floats-0', right + 62, surface + 4, 4.8); if (l && !calm) bob(l.el, 0.5, 2.2); }
        if (s >= 4) prop('farm-sea-lighthouse-0', W - 12, 36, 1.5);
      } else return;
      if (s >= 5) prop(`farm-flag-${st.strip}-0`, st.strip === 'sea' ? 40 : W - 19, st.strip === 'sea' ? 2 + lifted : 4, st.strip === 'sea' ? 8.6 : 3.6);
    }
    /** 비·눈(맥 CAEmitterLayer 와 같은 양·빠르기): 떨어지는 알갱이를 되풀이 애니메이션으로. 동작 줄이기면 4분의 1 */
    function particles(name) {
      const r = res(name); if (!r) return;
      const rain = name === 'fx-rain', life = rain ? 1.6 : 5.5, rate = W * (rain ? 0.08 : 0.025) * (calm ? 0.25 : 1);
      const n = Math.min(150, Math.round(rate * life)); // ponytail: 알갱이 150개 상한(아주 긴 띠에서 맥보다 성김), 모자라 보이면 올린다
      const box = node('sp', 35); Object.assign(box.style, {left: 0, bottom: 0, width: P(W) + 'px', height: P(H) + 'px'});
      for (let k = 0; k < n; k++) {
        const e = node('sp', 0, box); paint(e, r[0], r[1]);
        const v = rain ? 60 + rnd(-8, 8) : 16 + rnd(-2.4, 2.4), a = rain ? 0.35 : rnd(-0.175, 0.175), x = rnd(-20, W + 20), dur = rain ? life : (H + 10) / (v * Math.cos(a));
        const dx = v * Math.sin(a) * dur, dy = v * Math.cos(a) * dur, spin = rain ? 0 : (0.4 + rnd(-0.5, 0.5)) * dur;
        e.style.left = P(x) + 'px'; e.style.bottom = P(H + 6) + 'px';
        e.animate([{transform: 'translate(0, 0) rotate(0rad)'}, {transform: `translate(${P(dx)}px, ${P(dy)}px) rotate(${spin}rad)`}], {duration: dur * 1000, iterations: Infinity, delay: -rnd(0, dur) * 1000});
      }
    }
    function storm(y, start) { // 먹구름이 천천히 지나간다
      const l = thing('farm-fx-storm-0', 0.5); if (!l) return;
      l.el.style.bottom = P(y) + 'px'; l.y = y; l.x = start; l.el.style.transform = `translateX(${P(start)}px)`;
      later(l.walk(W + 40, 6), () => { l.remove(); storm(y, -40); });
    }
    function gust() { // 바람결이 띠를 가로질러 불고, 가끔 빨래·밀짚모자가 굴러 날아간다
      later(rnd(2.5, 5), gust);
      const name = anyOf(['farm-fx-gust', 'farm-fx-gust', 'farm-fx-shirt', 'farm-fx-hat']), sheet = sheetOf(name); if (!sheet) return;
      const l = add(new Critter(name, 0, 0, [0, 0]), 32); l.face(1); l.play('', null, 0.12);
      const y0 = rnd(18, 48), n = Math.floor((W + 60) / 3), dur = n / 25;
      if (name !== 'farm-fx-gust') l.body.animate(Array.from({length: n + 1}, (_, k) => ({rotate: `${(k % 8) * 45}deg`, offset: k / (n + 1), easing: 'steps(1, end)'})).concat({rotate: '0deg', offset: 1}), {duration: dur * 1000});
      later(path(l, Array.from({length: n + 1}, (_, k) => [r2(-30 + k * 3), r2(y0 + 4 * Math.sin(k / 5))]), dur), () => l.remove());
    }

    // ── 손님 생물 ──
    function guestCat(range, x) { const c = add(new Critter('farm-guest-cat', x, 1, range)); c.play('sit', [0], 1); later(rnd(1, 3), () => cat(c)); }
    function cat(c) { // 앉아서 꼬리를 흔들다가, 웅크려 자다가, 가끔 자리를 옮긴다
      const r = Math.random(); let t;
      c.body.replaceChildren();
      if (r < 0.4) { c.play('sit', [0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 1], 0.35); t = rnd(5, 10); }
      else if (r < 0.7) { c.play('sleep', null, 1); t = rnd(10, 20); if (!calm) zzz(c); }
      else { c.play('walk', null, 0.14); t = c.walk(rnd(...c.range), rnd(5, 7)); later(t, () => c.play('sit', [0], 1)); t += 1; }
      later(t, () => cat(c));
    }
    function hover(sheet, c, rx, ry, period, facing = 1, z = 30) { // 벌·나비가 한 점 둘레를 8자로 맴돈다(모두 되풀이 애니메이션)
      if (!sheetOf(sheet)) return;
      const l = add(new Critter(sheet, 0, 0, [0, 0]), z); l.face(1);
      const n = Math.max(8, Math.floor(period * 15)), phase = rnd(0, 2 * Math.PI), pts = [], turns = [];
      for (let k = 0; k <= n; k++) {
        const t = k / n * 2 * Math.PI + phase;
        pts.push([r2(c[0] + rx * Math.sin(t)), r2(c[1] + ry * Math.sin(2 * t))]);
        turns.push({transform: `scaleX(${Math.cos(t) >= 0 ? facing : -facing})`, offset: k / (n + 1), easing: 'steps(1, end)'});
      }
      path(l, pts, period, true);
      l.play('', null, 0.08);
      l.body.animate(turns.concat({transform: turns[0].transform, offset: 1}), {duration: period * 1000, iterations: Infinity});
    }
    function earthworm() { // 지렁이가 이랑 끝 흙구멍에서 고개를 내밀었다가 쏙
      later(rnd(8, 15), earthworm);
      const n = sheetOf('farm-guest-worm'); if (!st.pens.length || !n || I()[n][2] < 2) return;
      const i = Math.floor(Math.random() * st.pens.length), l = prop('farm-guest-worm-1', penX(i) + (coin() ? 4 : PEN_W - 4), 1, 19); if (!l) return;
      flipbook(l.el, n, [1, 0, 0, 0, 1, 0, 0, 1], 0.5, {once: true});
      later(4.6, () => l.el.remove());
    }
    function sparrow(perches) { // 참새가 날아와 땅이나 울타리 위에서 깡충·쪼기·두리번 하다 날아간다
      later(rnd(9, 18), () => sparrow(perches));
      if (!sheetOf('farm-guest-sparrow')) return;
      const p = coin() || !perches.length ? {x: [20, W - 30], y: 3, z: 19} : anyOf(perches), onFence = p.z < 19;
      const land = [r2(rnd(...p.x)), p.y], s = add(new Critter('farm-guest-sparrow', land[0], land[1], [land[0] - 6, land[0] + 6]), p.z), fromLeft = coin();
      s.face(fromLeft ? 1 : -1); s.play('', [3, 4], 0.08);
      let t = fly(s, [land[0] + (fromLeft ? -70 : 70), H + 8], land);
      later(t, () => s.play('', [0], 1));
      for (let j = 0, m = 3 + Math.floor(Math.random() * 4); j < m; j++) {
        const r = Math.floor(Math.random() * 3);
        later(t, () => {
          if (r === 0) s.play('', [1, 0, 1, 0], 0.15, true);
          else if (r === 1) { s.play('', [2, 0], 0.2, true); if (!onFence) s.walk(Math.min(Math.max(s.x + rnd(-4, 4), 10), W - 10), 20); }
          else { s.face(-s.facing); s.play('', [0], 1); }
        });
        t += rnd(0.7, 1.3);
      }
      later(t, () => {
        const away = [s.x + (coin() ? 80 : -80), H + 8];
        s.face(away[0] > s.x ? 1 : -1); s.play('', [3, 4], 0.08);
        later(fly(s, [s.x, s.y], away), () => s.remove());
      });
    }
    function seed(flowers) { // 민들레 씨가 하나씩 바람에 실려 위로
      later(rnd(3, 6), () => seed(flowers));
      const l = thing('farm-fx-seed-0', 30); if (!l) return;
      const x0 = flowers.x, y0 = flowers.y + flowers.h - 2, dir = coin() ? -1 : 1, n = 150, dur = n / 15;
      path(l, Array.from({length: n + 1}, (_, k) => { const t = k / n; return [r2(x0 + dir * t * 70 + Math.sin(t * 9) * 3), r2(y0 + t * 44)]; }), dur);
      l.el.animate([{opacity: 0}, {opacity: 1, offset: 0.05}, {opacity: 1, offset: 0.8}, {opacity: 0}], {duration: dur * 1000, fill: 'forwards'});
      later(dur, () => l.remove());
    }
    function cloud(start) { // 구름이 하늘을 천천히 지나간다(과수원 구름 그림 그대로)
      const l = thing(`cloud-${Math.floor(Math.random() * 3)}`, 0); if (!l) return;
      const from = start ? rnd(0, W * 0.6) : -30, y = r2(rnd(44, 52));
      l.y = y; l.el.style.bottom = P(y) + 'px'; l.x = r2(from); l.el.style.transform = `translateX(${P(l.x)}px)`; l.el.style.opacity = 0.92;
      const d = l.walk(W + 30, rnd(1.4, 2.4));
      later(d, () => { l.remove(); cloud(false); });
      if (start) later(d * 0.5, () => cloud(false));
    }

    // ── 동물(행동 하나가 끝나면 다음 행동을 고른다) ──
    function animal(sheet, x, y, range, acts) {
      const c = add(new Critter(sheet, x, y, range)); c.play(acts[0].anim, [0], 1);
      later(rnd(0, 2), () => live(c, acts));
      return c;
    }
    function live(c, acts) {
      if (held.has(c)) return later(1, () => live(c, acts)); // 일꾼이 젖 짜기·털 깎기·솔질 중이면 기다린다
      let r = Math.random() * acts.reduce((t, a) => t + a.weight, 0);
      const a = acts.find(x => (r -= x.weight) < 0) || acts[0];
      c.unhop();
      let t;
      if (a.turn) { c.face(-c.facing); c.play(a.anim, a.order, a.per); t = rnd(1, 2); }
      else if (a.walk) {
        c.play(a.anim, a.order, a.per); t = c.walk(rnd(...c.range), rnd(4, 6));
        if (a.hop > 0 && t > 0) c.hop(a.hop, a.per * (a.order ? a.order.length : 2), t);
        if (t > 0) later(t, () => c.play(acts[0].anim, [0], 1));
      } else if (a.hold) { c.play(a.anim, a.order, a.per); t = rnd(...a.hold); }
      else t = c.play(a.anim, a.order, a.per, true);
      if (a.emote) emote(a.emote, c);
      if (cold() && Math.random() < 0.3) later(0.5, () => breath(c));
      if (st.disaster === 'drought' && Math.random() < 0.15) emote('emote-sweat', c);
      later(t + rnd(0.3, 1.2), () => live(c, acts));
    }
    function chicken(c) {
      if (held.has(c)) return later(1, () => chicken(c)); // 모이 먹으러 몰려간 동안
      const r = Math.random(); let t;
      if (cold() && r < 0.5) { c.play('rest', [0], 1); t = rnd(4, 8); later(rnd(0.8, 2), () => breath(c)); if (coin()) emote('fx-snow', c); }
      else if (r < 0.35) { c.play('walk', null, 0.12); t = c.walk(rnd(...c.range), rnd(6, 9)); }
      else if (r < 0.65) t = c.play('peck', Array(2 + Math.floor(Math.random() * 3)).fill([0, 1, 2, 2, 3]).flat(), 0.11, true);
      else if (r < 0.9) { c.play('idle', blink.concat(coin() ? [3, 3, 3, 3] : []), 0.12); t = rnd(2, 5); }
      else if (r < 0.96 || cold()) { t = c.play('rest', [2, 3, 2, 3, 2, 3], 0.14, true); emote(coin() ? 'emote-heart' : 'emote-note', c); }
      else { c.play('rest', [0], 1); later(3, () => { egg(c.x - c.facing * 5, c.y); c.play('rest', [2, 3, 2, 3], 0.14, true); emote('emote-star', c); }); t = 4.2; }
      later(t + rnd(0.2, 1.2), () => chicken(c));
    }
    function swimmer(c) { // 연못 오리: 떠다니며 꼬리를 흔들고, 가끔 부리를 물에 담근다
      let t;
      if (Math.random() < 0.3) t = c.play('swim', [0, 1, 1, 2, 2, 2, 1, 0, 3, 0], 0.18, true);
      else { c.play('swim', [0, 0, 3, 0, 0, 0], 0.3); t = Math.max(2, c.walk(rnd(...c.range), rnd(2.5, 4))); }
      if (cold() && Math.random() < 0.3) later(0.5, () => breath(c));
      later(t + rnd(0.5, 2), () => swimmer(c));
    }
    function duck(c, kids) { // 마당 오리(새끼가 있으면 줄지어 따라온다)
      const r = Math.random(); let t;
      if (r < 0.45) {
        c.play('walk', null, 0.13); t = c.walk(rnd(...c.range), rnd(4.5, 6.5));
        kids.forEach((kid, k) => {
          const target = Math.min(Math.max(c.x - c.facing * (9 + 7 * k), 4), W - 4);
          kid.play('walk', null, 0.1);
          const d = kid.walk(target, Math.abs(target - kid.x) / Math.max(0.5, t) + 0.5, 0.3 * (k + 1));
          later(d, () => { kid.play('walk', [0], 1); kid.face(c.facing); });
        });
      } else if (r < 0.85) { c.play('idle', blink, 0.12); t = rnd(2, 5); }
      else { t = c.play('idle', [0, 3, 3, 0, 3, 3, 0], 0.14, true); emote('emote-note', c); if (cold()) later(0.3, () => breath(c)); }
      later(t + rnd(0.3, 1.5), () => duck(c, kids));
    }

    // ── 일꾼(맥 crew·work·stand·perform) ──
    function crew(acts, range) {
      st.workers.forEach((role, k) => {
        const act = acts[role]; if (!act || !exists(`${role}-idle-0`)) return;
        const c = add(new Critter(role, range[0] + (range[1] - range[0]) * (k + 0.5) / st.workers.length, 1, range, OUTFIT[st.strip]));
        crewList.push(c); c.play('idle', null, 0.15);
        later(rnd(0.5, 3), () => work(c, act));
      });
    }
    const reach = m => { const r = farmJson.anchors.reach || {}, k = Object.keys(r).find(x => x.endsWith('-' + m)); return k ? r[k] : {pull: 13, snip: 13.5, scoop: 14.5, haul: 13.5, egg: 11}[m] ?? 9.5; };
    /** 일꾼이 서는 자리: 도구 끝이 대상에 닿게(맥 stand, 값 근거 docs/research/art-pass-2.0.8.md '자리 맞춤') */
    function stand(i, kind, m) {
      const x0 = penX(i), mid = x0 + PEN_W / 2, rc = reach(m), half = farmJson.anchors.half || {}, a = anchors.get(i);
      if (a && ['milk', 'shear', 'brush', 'bottle', 'feed'].includes(m)) {
        const h = half[a.sheet] ?? 10;
        const gap = m === 'milk' ? h - 2.5 : m === 'shear' || m === 'brush' ? h + rc - 3 : m === 'bottle' ? h + rc - 1 : h + rc + 3.5;
        return {pen: i, x: a.x - gap, face: 1, hold: a};
      }
      if (['pull', 'cut', 'thump', 'snip', 'tie', 'stake'].includes(m)) {
        const plant = mid + (Math.floor(Math.random() * 3) - 1) * 20, h = half[`crop-${kind}`] ?? 8;
        const d = m === 'pull' || m === 'cut' ? rc - 2.5 : m === 'thump' ? h + rc - 3 : m === 'snip' ? h + rc - 5 : m === 'tie' ? rc + 3 : rc + 4;
        return {pen: i, x: plant - d, face: 1, hold: null};
      }
      if (m === 'feed') return {pen: i, x: x0 + (kind === 'duck' ? 14 : 26), face: 1, hold: null};
      if (m === 'egg') return kind === 'duck' ? {pen: i, x: x0 + 14, face: 1, hold: null} : {pen: i, x: x0 + (kind === 'goose' ? 38 : 44), face: -1, hold: null};
      if (m === 'smoke') return {pen: i, x: x0 + 38.5, face: -1, hold: null};
      return {pen: i, x: mid, face: 1, hold: null};
    }
    function deliver(c, item, act) { // 거둔 것을 손에 들고 상자까지 걸어가 톡 넣는다
      const r = storeX != null && res(item);
      if (!r) { working.delete(c); later(0.4, () => work(c, act)); return; }
      const [iw, ih] = I()[r[0]], icon = document.createElement('div'); icon.className = 'bd'; c.body.append(icon);
      flipbook(icon, r[0], [r[1]], 1, {lit: true});
      const ph = Math.round(16 * ih / Math.max(iw, 1));
      Object.assign(icon.style, {width: '16px', height: ph + 'px', left: 'calc(50% + 2px)', bottom: P(13) - ph / 2 + 'px', backgroundSize: `${16 * I()[r[0]][2]}px ${ph}px`, backgroundPosition: `${-16 * r[1]}px 0`});
      c.play('walk', null, 0.1);
      const t = c.walk(storeX + 10, rnd(8, 10));
      later(t, () => { icon.remove(); c.face(-1); c.play('idle', null, 0.15); pop(item, [c.x - 6, c.y + 13], [storeX, 8]); });
      later(t + 1, () => { working.delete(c); work(c, act); });
    }
    function highFive(a, b, act) { // 두 일꾼이 가운데에서 만나 하이파이브(별 반짝)
      const [l, r] = a.x <= b.x ? [a, b] : [b, a], mid = r2((l.x + r.x) / 2);
      working.add(a); working.add(b);
      for (const w of [l, r]) w.play('walk', null, 0.1);
      const tl = l.walk(mid - 11, 10), tr = r.walk(mid + 11, 10), t = Math.max(tl, tr);
      later(tl, () => l.play('idle', null, 0.15)); later(tr, () => r.play('idle', null, 0.15));
      later(t + 0.2, () => { l.face(1); r.face(-1); l.play('cheer', null, 0.11, true); r.play('cheer', null, 0.11, true); later(0.45, () => emote('emote-star', l)); });
      later(t + 1.4, () => { for (const w of [l, r]) w.play('idle', null, 0.15); working.delete(a); working.delete(b); work(a, act); });
    }
    function rest(c, x, anim, act) { // 쉬는 자리에 가서 앉아 쉰다(6~10초), 가끔 꾸벅
      working.add(c); c.play('walk', null, 0.1);
      const go = c.walk(x + rnd(-4, 4), rnd(8, 10)), stay = rnd(6, 10);
      later(go, () => { c.face(coin() ? 1 : -1); c.play(anim, null, 0.18); if (coin()) later(stay / 2, () => emote('emote-dots', c)); });
      later(go + stay, () => { c.play('idle', null, 0.15); working.delete(c); later(0.4, () => work(c, act)); });
    }
    function perform(m, c, s, kind, dur) { // 일꾼 동작 + 대상 반응 + 거둔 것 + 가끔 드문 장면
      const a = s.hold, front = s.x + s.face * 12, item = itemOf(kind), top = c.y + 18;
      const popItem = (t, x, y = 6) => { if (item) later(t, () => pop(item, [x, y], [c.x, top])); };
      let moment = Interact.moment(m, Math.random());
      if (moment === 'pratfall' || moment === 'taste') { if (!exists(`${c.sheet}-${moment}-0`)) moment = null; }
      else if (moment !== 'chase' || kind !== 'goose') moment = null;
      if (moment === 'pratfall') { c.play('pratfall', null, 0.16, true); later(0.7, () => emote('emote-bang', c)); popItem(0.9, front); later(2.2, () => emote('emote-star', c)); }
      else if (moment === 'taste') { c.play('taste', null, 0.16, true); later(1.4, () => emote('emote-heart', c)); }
      else c.play(m, null, 0.12);
      const who = a ? a.sheet : '';
      switch (m) {
        case 'milk':
          later(1, () => a && a.play('tail', [0, 1, 2, 1, 2, 3, 0], 0.15, true));
          later(2.2, () => { if (!a) return; if (exists('farm-ranch-cow-moo-0')) a.play('moo', [0, 1, 2, 2, 2, 3], 0.2, true); if (coin()) emote('emote-note', a); });
          popItem(dur - 0.8, s.x + s.face * 6, 4); break;
        case 'shear':
          later(dur - 1.2, () => { if (!a) return; a.play('shorn', [0, 0, 1, 1, 1, 0], 0.3, true); emote('emote-heart', a); if (exists('farm-ranch-sheep-shake-0')) later(0.9, () => a.play('shake', [0, 1, 2, 1, 2, 3, 3], 0.13, true)); });
          popItem(dur - 1, s.x + s.face * 10, 8); break;
        case 'brush':
          later(1.5, () => {
            if (!a) return;
            if (who === 'farm-ranch-pig') a.play('mud', [0, 0, 1, 0, 2, 0, 3, 0], 0.4, true);
            else if (who === 'farm-ranch-cow') a.play('tail', [0, 1, 2, 1, 2, 3, 0], 0.15, true);
            else a.play('idle', [0, 3, 3, 3, 0], 0.25, true);
            if (coin()) emote('emote-heart', a);
          }); break;
        case 'bottle':
          if (a && a.sheet === 'farm-ranch-calf' && exists('farm-ranch-calf-drink-0')) later(0.6, () => a.play('drink', [0, 1, 2, 1, 2, 1, 2, 3], 0.22, true));
          later(dur - 1.4, () => { if (!a) return; a.play('', [0, 2, 3, 0, 2, 3, 0], 0.14, true); emote('emote-heart', a); }); break;
        case 'feed':
          if (kind === 'goose' && a) {
            later(1.2, () => exists('farm-ranch-goose-honk-0') ? a.play('honk', [0, 1, 1, 2, 3], 0.16, true) : a.play('flap', [0, 1, 2, 1, 2, 3], 0.12, true));
            if (moment === 'chase') chase(a, c, dur);
          } else (flocks.get(s.pen) || []).forEach((h, k) => { // 닭이 모이 쪽으로 몰려와 쪼기
            held.add(h); later(dur, () => held.delete(h));
            later(0.6 + k * 0.3, () => { h.play('walk', null, 0.12); const w = h.walk(front + 4 + k * 7, 10); later(w, () => h.play('peck', Array(3).fill([0, 1, 2, 2, 3]).flat(), 0.11, true)); });
          }); break;
        case 'egg': { popItem(dur * 0.5, s.x + s.face * 10, 3); const h = (flocks.get(s.pen) || [])[0]; if (h) later(1, () => emote('emote-note', h)); break; }
        case 'pull': case 'cut': case 'snip': if (!moment) popItem(dur - 0.9, front, 10); break;
        case 'thump': for (const t of [1, 2.3]) later(t, () => emote('emote-note', c)); break;
        case 'tie': case 'stake': if (Math.random() < 0.4) later(dur - 0.6, () => emote('emote-star', c)); break;
      }
    }
    function chase(g, c, t) { // 드문 장면: 거위가 일꾼을 졸졸 쫓아간다
      later(t + 0.1, () => {
        emote('emote-bang', c);
        const away = Math.min(c.range[1], c.x + 70);
        c.play('walk', null, 0.07); c.walk(away, 18);
        g.play('walk', null, 0.08);
        later(g.walk(away - 10, 16, 0.4), () => exists('farm-ranch-goose-honk-0') ? g.play('honk', [0, 1, 2, 1, 2, 3], 0.14, true) : g.play('flap', [0, 1, 2, 1, 2, 3], 0.12, true));
      });
    }
    function work(c, act) {
      if (riding.has(c) || working.has(c)) return later(1, () => work(c, act)); // 배를 타러 간 동안·하이파이브에 불려 간 동안
      if (ctx.quiet()) { c.play('idle', null, 0.15); return later(5, () => work(c, act)); } // Mac 이 잠들면 레몬 과수원처럼 서서 쉰다
      const role = c.sheet;
      if (!calm && Math.random() < 0.07) { // 가끔 쉬는 자리(그늘 나무·비닐하우스 앞·파라솔)에 가서 앉는다
        const anim = role === 'harvester' ? 'sit' : 'rest', spots = restSpots.filter(x => inR(c.range, x));
        if (exists(`${role}-${anim}-0`) && spots.length) return rest(c, anyOf(spots), anim, act);
      }
      if (!calm && Math.random() < 0.1 && exists(`${role}-cheer-0`)) { // 가까이 한가한 동료가 있으면 하이파이브
        const mate = crewList.find(m => m !== c && !working.has(m) && !riding.has(m) && Math.abs(m.x - c.x) < 120 && exists(`${m.sheet}-cheer-0`));
        if (mate) return highFive(c, mate, act);
      }
      const r = Math.random(), spots = [];
      st.pens.forEach((k, i) => { // 칸 하나를 골라 그 종류·역할에 맞는 도구와 동작
        const m = k && !busyPens.has(i) && MOTION[k] && MOTION[k][role];
        if (!m || !exists(`${role}-${m}-0`)) return;
        const s = stand(i, k, m);
        if (inR(c.range, s.x) && !(s.hold && held.has(s.hold))) spots.push([s, m]);
      });
      const opts = spots.map(([s, m]) => ({pen: s.pen, verb: m, x: s.x, need: Interact.need(m, growth(s.pen))}));
      const o = r < 0.6 ? Interact.choose(opts, c.x, recents.get(c) || [], Math.random()) : null, hit = o && spots.find(([s, m]) => s.pen === o.pen && m === o.verb);
      if (hit) {
        const [s, m] = hit;
        if (!recents.has(c)) recents.set(c, []);
        Interact.remember(Interact.key(o), recents.get(c));
        working.add(c); if (s.hold) held.add(s.hold); busyPens.add(s.pen);
        c.play('walk', null, 0.1);
        const go = c.walk(s.x, rnd(8, 11)), dur = rnd(3.5, 6), kind = st.pens[s.pen];
        later(go, () => { c.face(s.face); if (s.hold && (m === 'bottle' || m === 'feed')) s.hold.face(-s.face); perform(m, c, s, kind, dur); });
        const t = go + dur, item = itemOf(kind), carry = Interact.harvest.has(m) && item && storeX != null && inR(c.range, storeX + 10) && coin();
        later(t, () => { c.play('idle', null, 0.15); if (s.hold) held.delete(s.hold); busyPens.delete(s.pen); if (carry) deliver(c, item, act); else working.delete(c); });
        if (!carry) later(t + 0.4, () => work(c, act));
        return;
      }
      let t;
      if (r < 0.35) { c.play('walk', null, 0.1); t = c.walk(rnd(...c.range), rnd(8, 11)); later(t, () => c.play('idle', null, 0.15)); t += rnd(0.5, 1.5); }
      else if (r < 0.85) {
        const walking = act === 'carry' || act === 'crate'; // 걷는 동작(나르기·상자)은 걸으면서
        c.play(act, null, walking ? 0.1 : 0.12);
        t = walking ? c.walk(rnd(...c.range), rnd(7, 9)) : rnd(3, 6);
        later(t, () => c.play('idle', null, 0.15)); t += 0.4;
      } else { c.play('idle', null, 0.15); t = rnd(2, 4); if (st.forecast) emote('emote-bang', c); } // 예보: 하늘을 올려다본다
      if (st.disaster === 'drought' && Math.random() < 0.3) emote('emote-sweat', c);
      later(t, () => work(c, act));
    }

    // 안 보일 때(앱을 내림)는 장면을 비우고, 다시 보이면 새로 짓는다(레몬 과수원의 쉬기와 같은 뜻)
    let last = null, keyExtra = '';
    const key = s => JSON.stringify(s) + '|' + keyExtra;
    function build(s, k) {
      builtKey = k;
      if (document.visibilityState !== 'visible') { builtKey = ''; return; }
      prepare(s.strip).then(() => { if (on && builtKey === k) { st = s; rebuild(); } });
    }
    document.addEventListener('visibilitychange', () => {
      if (!on || !last) return;
      if (document.visibilityState !== 'visible') { stop(); builtKey = ''; } else if (!builtKey) build(last, key(last));
    });
    return {
      get on() { return on; },
      /** 띠 장면을 건다(같은 상태면 그대로 두고 손님·우체통만 본다). s: 맥 FarmSceneState(재해·예보까지 채운 것), x: {key 색 보정, coop, notes}. 장면 폭(px) */
      show(s, x) {
        extra = x; keyExtra = x.key || ''; last = s;
        if (!on) { on = true; root.hidden = false; }
        if (s.strip !== lastStrip) { lastStrip = s.strip; pan.scrollLeft = 0; }
        const k = key(s);
        if (k !== builtKey) build(s, k); else if (st) { coopChanged(); mailChanged(); }
        W = width(s); root.style.width = P(W) + 'px'; place();
        return P(W);
      },
      stop() { if (!on) return; on = false; stop(); builtKey = ''; lastStrip = ''; st = last = null; root.hidden = true; },
    };
  }

  const Farm = {Interact, motion: MOTION, seaWork, width, create};
  if (typeof module === 'object' && module.exports) module.exports = Farm; else root.Farm = Farm;
})(this);

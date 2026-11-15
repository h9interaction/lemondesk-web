// 일꾼·강아지 움직임 규칙: 맥 LemonDesk/Motion.swift(윈도우 Motion.cs)와 같은 규칙을 폰 페이지로 옮긴 것.
// 순수 로직이라 node 로도 돈다(점검: node scripts/m-motion-check.js). 규칙·프레임 시간을 바꾸면 세 곳을 같이 바꾼다.
// 단위는 맥과 같다(pt, pt/s, 초). 폰 그림은 1pt = 2px.
(function (root) {
  const sum = a => a.reduce((x, y) => x + y, 0);
  const clip = (hold, loops = false, cues = {}) => ({
    hold, loops, cues,
    get duration() { return sum(hold); },
    start(frame) { return sum(hold.slice(0, frame)); },          // 그 프레임이 시작되는 시각(초)
    get keyTimes() { const t = this.duration; return hold.map((_, i) => this.start(i) / t).concat(1); },
  });
  const even = (n, perFrame, loops = true) => clip(Array(n).fill(perFrame), loops);
  const between = (rng, a, b) => a + rng() * (b - a);
  const any = (rng, a) => a.length ? a[Math.floor(rng() * a.length)] : undefined;

  const Motion = {
    even,
    /** 동작 이름과 프레임 수로 프레임 진행표를 고른다(Motion.clip). */
    clip(anim, n) {
      switch (anim + '/' + n) {
        case 'dig/8': return clip([0.14, 0.20, 0.07, 0.24, 0.12, 0.14, 0.12, 0.18], false, {2: 'hit', 6: 'toss'});
        case 'dig/6': return clip([0.18, 0.08, 0.20, 0.12, 0.10, 0.20], false, {1: 'hit', 4: 'toss'});
        case 'water/6': return clip([0.14, 0.12, 0.20, 0.26, 0.18, 0.16], false, {2: 'pour'});
        case 'water/8': return clip([0.14, 0.12, 0.12, 0.24, 0.26, 0.16, 0.12, 0.16], false, {3: 'pour'});
        case 'wave/8': return clip([0.12, 0.10, 0.14, 0.12, 0.12, 0.16, 0.12, 0.16]);
        case 'habit/8': return clip([0.14, 0.14, 0.14, 0.14, 0.30, 0.40, 0.20, 0.16]);
        case 'pick/6': return clip([0.16, 0.16, 0.09, 0.14, 0.16, 0.30], false, {2: 'pluck'});
        case 'seed/8': return clip([0.14, 0.12, 0.12, 0.26, 0.12, 0.14, 0.12, 0.16], false, {5: 'drop'});
        case 'tamp/8': return clip([0.12, 0.10, 0.14, 0.07, 0.10, 0.14, 0.07, 0.20], false, {3: 'pat', 6: 'pat'});
        case 'wipe/8': return clip([0.12, 0.10, 0.10, 0.14, 0.30, 0.22, 0.12, 0.16], false, {4: 'sweat'});
        case 'idle/8': return clip([0.5, 0.5, 0.5, 0.10, 0.08, 0.5, 0.5, 0.5], true);
      }
      return anim === 'sit' ? even(n, 0.35) : even(n, 0.12);
    },

    baseSpeed: 18, baseCycle: 0.8,
    speed(role, slot) { return 18 * ({planter: 1, caretaker: 0.92, harvester: 1.08}[role] || 1) * (slot === 0 ? 1 : 0.94); },
    cycle(speed) { return 0.8 * 18 / speed; },
    /** 0.5pt 씩 끊어 걷는 자리마다의 도착 시각(초). 출발·정지에서 ramp(pt) 동안 천천히. 걸음 수+1 개. */
    walkTimes(distance, speed, ramp = 3, slowest = 0.45) {
      const n = Math.max(1, Math.round(distance / 0.5)), out = [0];
      let t = 0;
      for (let i = 0; i < n; i++) {
        const mid = (i + 0.5) * 0.5, edge = Math.min(mid, distance - mid);
        t += 0.5 / (speed * (slowest + (1 - slowest) * Math.min(1, edge / ramp)));
        out.push(t);
      }
      return out;
    },

    restAfter: 3,
    restAnims(role) { return {planter: ['wave', 'habit', 'wipe'], caretaker: ['yawn', 'habit'], harvester: ['sniff', 'habit']}[role]; },
    workAnims(role, young) { return role === 'planter' ? (young ? ['dig'] : ['tamp', 'dig']) : role === 'caretaker' ? ['water'] : ['pick']; },
    plantingOrder: ['dig', 'seed', 'tamp'],

    /** 다음 행동(Motion.choose). s: {role, fruit[], young[], crateFull, night, season, streak, last, lastTree, has: Set}.
     *  돌려주는 값: {kind: 'work', tree, anim, reps} | {kind: 'rest', anim} | {kind: 'idle', secs} | {kind: 'look'} | {kind: 'stroll', tree} | {kind: 'sit'} */
    choose(s, rng = Math.random) {
      const roll = p => rng() < p;
      const pick = items => {
        const total = sum(items.map(i => i[1]));
        if (!(total > 0)) return undefined;
        let r = rng() * total;
        for (const [item, w] of items) { r -= w; if (r < 0) return item; }
        return items[items.length - 1][0];
      };
      const last = s.last || null, has = s.has || new Set();
      if (s.role === 'harvester' && s.crateFull && has.has('sit')) return {kind: 'sit'};
      const rests = Motion.restAnims(s.role)
        .filter(a => has.has(a) && !(last && last.kind === 'rest' && last.anim === a))
        .map(a => [a, a === 'wipe' ? (s.season === 'summer' ? 3 : s.season === 'winter' ? 0.3 : 1) : a === 'yawn' ? (s.night ? 3 : 1) : 1]);
      const rest = () => { const a = pick(rests); return a ? {kind: 'rest', anim: a} : {kind: 'idle', secs: between(rng, 3, 5)}; };
      if ((s.streak || 0) >= Motion.restAfter) return rest();
      const young = s.young || [], fruit = s.fruit || [];
      if (s.role === 'planter' && last && last.kind === 'work' && young[last.tree]) {
        const k = Motion.plantingOrder.indexOf(last.anim);
        if (k >= 0 && k + 1 < Motion.plantingOrder.length && has.has(Motion.plantingOrder[k + 1])) return {kind: 'work', tree: last.tree, anim: Motion.plantingOrder[k + 1], reps: 1};
      }
      const trees = fruit.map((_, i) => i);
      let targets, chance;
      if (s.role === 'harvester') { targets = s.crateFull ? [] : trees.filter(i => fruit[i] > 0); chance = 1; }
      else if (s.role === 'caretaker') { targets = trees; chance = 0.82; }
      else { const y = trees.filter(i => young[i]); targets = y.length ? y : trees; chance = y.length ? 1 : 0.4; }
      if (s.night) chance *= 0.6;
      let lastTree = s.lastTree ?? null, lastAnim = null;
      if (last && last.kind === 'work') { lastTree = last.tree; lastAnim = last.anim; }
      if (targets.length > 1) targets = targets.filter(i => i !== lastTree);
      if (targets.length && roll(chance)) {
        const tree = any(rng, targets);
        let anims = Motion.workAnims(s.role, !!young[tree]).filter(a => has.has(a));
        if (new Set(anims).size > 1) anims = anims.filter(a => a !== lastAnim);
        const anim = any(rng, anims);
        if (!anim) return rest();
        return {kind: 'work', tree, anim, reps: anim === 'dig' || anim === 'water' ? 1 + Math.floor(rng() * 2) : 1};
      }
      const options = [[{kind: 'idle', secs: between(rng, 2.5, 5.5)}, 4]];
      if (rests.length) options.push([rest(), 3.5]);
      if (!(last && last.kind === 'look')) options.push([{kind: 'look'}, 1.2]);
      if (trees.length > 1) {
        const t = any(rng, trees.filter(i => i !== lastTree));
        if (t !== undefined && !(last && last.kind === 'stroll')) options.push([{kind: 'stroll', tree: t}, 1.3]);
      }
      return pick(options) || {kind: 'idle', secs: 3};
    },

    // 강아지: 0 진돗개, 1 웰시코기, 2 삽살개. 행동 kind: 0 sit, 1 wag, 2 trot, 3 trick, 4 bark
    dogPace(dog) { return dog === 1 ? {speed: 30, cycle: 0.30} : dog === 2 ? {speed: 15, cycle: 0.46} : {speed: 22, cycle: 0.38}; },
    dogRange(dog) { return dog === 1 ? 0.6 : dog === 2 ? 0.3 : 1; },
    /** 다음 행동. {kind, secs} 또는 trot 이면 {kind: 2, at: 0~1(자기 구역의 그 자리)} */
    dogNext(dog, barking, night, last, rng = Math.random) {
      const sec = (a, b) => between(rng, a, b);
      let w = dog === 1 ? [1, 2.5, 4.5, 3] : dog === 2 ? [3.5, 1.5, 2, 3.5] : [3, 1.5, 3, 1.5], bark = 0;
      if (barking) { w = [0.5, 0, 3, 0]; bark = 6; }
      else if (night) { w[2] *= 0.4; if (dog === 0) w[3] = 6; }
      const options = [
        [{kind: 0, secs: sec(2, 5)}, w[0]], [{kind: 1, secs: sec(1.5, 3)}, w[1]], [{kind: 2, at: sec(0, 1)}, w[2]],
        [{kind: 3, secs: dog === 0 ? (night ? sec(8, 14) : sec(3, 6)) : sec(1.2, 2.2)}, w[3]], [{kind: 4, secs: sec(1, 2)}, bark],
      ].filter(([a, weight]) => weight > 0 && !(last && a.kind === last.kind && a.kind !== 2));
      let r = rng() * sum(options.map(o => o[1]));
      for (const [act, weight] of options) { r -= weight; if (r < 0) return act; }
      return {kind: 2, at: 0.5};
    },
  };
  if (typeof module === 'object' && module.exports) module.exports = Motion; else root.Motion = Motion;
})(this);

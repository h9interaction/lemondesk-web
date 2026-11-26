// 복사본: 원본 art/preview/workshop/core.js (scripts/m-sprites.py 가 그대로 복사, 고치지 말고 원본을 고친다)
// 레몬 공방 그리기 엔진(원본). DOM 없음, 브라우저 <script src="core.js"> → 전역 WorkshopCore, Node → require('./core.js').
// 형식·알고리즘 설명 docs/research/workshop-format.md, 기준 예제 windows/cases/workshop(scripts/workshop-cases.mjs).
// 그림 값을 정하는 계산은 모두 정수(맥·윈도우가 비트 단위로 같게). 난수는 rng(mulberry32)만 쓴다.
(function (root, factory) {
  const M = factory();
  if (typeof module === 'object' && module.exports) module.exports = M; else root.WorkshopCore = M;
  // 브라우저에서 catalog.js 를 먼저 불렀으면 바로 부품 목록을 만든다
  if (typeof CATALOG !== 'undefined') M.setCatalog({ CATALOG, WS: typeof WS !== 'undefined' ? WS : {}, WS_ANCH: typeof WS_ANCH !== 'undefined' ? WS_ANCH : {} });
})(this, function () {
  'use strict';
  const W = 144, H = 144, GROUND = 136, MAXL = 8, DOTCAP = 200, PARTS_VER = 1;
  const BENCHES = ['tree', 'friend', 'prop'], SB = { tree: 't', friend: 'f', prop: 'p' };
  const sbOf = w => SB[w.b];

  // ---------- 정수 도우미 ----------
  const floorDiv = (a, b) => Math.floor(a / b); // b > 0, |a| < 2^53 → 정확
  const r100 = v => Math.floor((v + 50) / 100); // v ≥ 0 의 v/100 반올림(반은 올림)
  const opaque = a => a > 20;
  // 정수 HSV: [h(0~359 정수 도), d = max−min, mx = max]. 채도 = d/mx, 명도 = mx/255
  function hsvI(r, g, b) {
    const mx = Math.max(r, g, b), d = mx - Math.min(r, g, b);
    if (!d) return [0, 0, mx];
    const off = mx === r ? 0 : mx === g ? 120 : 240, num = mx === r ? g - b : mx === g ? b - r : r - g;
    return [Math.floor(((360 + off) * d + 60 * num) / d) % 360, d, mx];
  }
  // h 도, s ‰(0~1000), vN = 명도×255×1000(0~255000) → [r,g,b]
  function hsvToRgbI(h, s, vN) {
    return [5, 3, 1].map(n => { const k = (n * 60 + h) % 360, f = Math.max(0, Math.min(k, 240 - k, 60)); return Math.floor((vN * (60000 - s * f) + 30000000) / 60000000); });
  }
  const hd = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };
  const lumY = (r, g, b) => 299 * r + 587 * g + 114 * b; // 0~255000
  const isSkin = (h, d, mx) => h >= 8 && h <= 38 && 100 * d >= 12 * mx && 10 * d <= 6 * mx && 100 * mx >= 15810;

  // ---------- 팔레트 24색 (보라 없음) ----------
  const PAL = [
    ['구름', 'f6f4ee'], ['크림', 'fff1c9'], ['레몬', 'f5d03a'], ['해바라기', 'f2a91c'], ['귤', 'ff8a2a'], ['살구', 'ffbe7a'],
    ['산호', 'ff7f66'], ['체리', 'dc3c55'], ['딸기우유', 'ff9fb0'], ['벽돌', 'a8443a'], ['모래', 'e4c898'], ['나무', 'b27a45'],
    ['초코', '6b4630'], ['연두', 'a6dc48'], ['잎새', '4fae5a'], ['숲', '2f7a4a'], ['민트', '6fdcbc'], ['청록', '2a9bb0'],
    ['하늘', '6cc2f2'], ['파랑', '3a78d0'], ['밤바다', '24456e'], ['돌', 'a9b0b4'], ['먹', '4a5058'], ['숯', '2a2d33'],
  ].map(([name, hex], i) => {
    const rgb = [0, 2, 4].map(k => parseInt(hex.substr(k, 2), 16)), [h, d, mx] = hsvI(...rgb);
    return { i, name, hex: '#' + hex, rgb, h, s: mx ? Math.floor(1000 * d / mx) : 0, v: mx, chroma: 10 * d > 3 * mx && 100 * mx > 11475 };
  });
  const CHROMA = PAL.filter(c => c.chroma).map(c => c.i);
  // 아래 세 표는 시제품의 실수 계산으로 한 번 만든 값(팔레트가 바뀌지 않는 한 고정)
  // 그림자 칸 자동: 더 어둡고 청록·파랑 쪽으로 옮겨 간 색
  const SHADE = [21, 11, 11, 11, 11, 11, 9, 9, 9, 12, 11, 12, 23, 14, 15, 23, 17, 20, 17, 20, 23, 22, 23, 23];
  // 밝기 사다리 양 끝: DEEP[그림자 칸] = 가장 어두운 곳, LIGHT[바탕 칸] = 빛
  const DEEP = [[103, 103, 92], [106, 107, 75], [94, 103, 12], [102, 97, 0], [107, 82, 5], [107, 94, 40], [107, 31, 41], [92, 14, 27], [107, 56, 65], [71, 16, 28], [96, 93, 55], [75, 63, 21], [45, 17, 15], [44, 92, 20], [25, 73, 45], [14, 51, 39], [37, 92, 92], [9, 47, 74], [34, 74, 102], [14, 57, 87], [10, 31, 46], [65, 71, 76], [28, 33, 37], [16, 19, 21]];
  const LIGHT = [[255, 254, 251], [255, 251, 228], [255, 242, 158], [255, 240, 142], [255, 221, 148], [255, 238, 189], [255, 209, 179], [255, 169, 162], [255, 210, 207], [215, 168, 145], [255, 249, 212], [226, 207, 157], [148, 132, 107], [244, 255, 169], [169, 222, 161], [114, 165, 121], [192, 255, 222], [139, 224, 218], [184, 246, 255], [163, 223, 255], [101, 135, 152], [222, 228, 229], [117, 124, 127], [79, 83, 87]];
  const shadeOf = i => SHADE[i];
  // 가장 가까운 색상(동률이면 pool 에서 먼저 나온 색)
  const nearestHue = (h, pool = CHROMA) => pool.reduce((b, i) => hd(PAL[i].h, h) < hd(PAL[b].h, h) ? i : b, pool[0]);

  // ---------- 씨앗 PRNG (mulberry32) ----------
  function rng(seed) {
    let a = seed >>> 0;
    const u = () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return (t ^ (t >>> 14)) >>> 0; };
    const r = { u };
    r.int = n => Math.floor(u() * n / 4294967296); // ⌊u·n / 2^32⌋
    r.pick = arr => arr[r.int(arr.length)];
    r.chance = pct => u() * 100 < pct * 4294967296; // 정수 퍼센트
    return r;
  }
  const mixSeed = (seed, k) => k ? (seed ^ Math.imul(k, 0x9E3779B1)) >>> 0 : seed >>> 0;
  const B32 = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
  const enc32 = n => Array.from({ length: 5 }, (_, k) => B32[(n >>> (k * 5)) & 31]).reverse().join('');
  const dec32 = s => [...s].reduce((n, ch) => n * 32 + B32.indexOf(ch), 0);
  const seedCode = (b, th, seed) => `${'TFP'[BENCHES.indexOf(b)]}${th}-${enc32(seed)}`;
  function parseSeed(s) {
    const m = /^([TFP])(\d)-?([2-9A-HJ-NP-Z]{5})$/.exec(String(s).trim().toUpperCase());
    return m && +m[2] < THEMES.length ? { b: BENCHES['TFP'.indexOf(m[1])], th: +m[2], seed: dec32(m[3]) } : null;
  }
  function fnv1a32(str) {
    const bytes = new TextEncoder().encode(str);
    let h = 0x811C9DC5;
    for (const x of bytes) h = Math.imul(h ^ x, 0x01000193) >>> 0;
    return h >>> 0;
  }

  // ---------- 이름(한국어) ----------
  const KO = { dog: '강아지', cat: '고양이', sheep: '양', pig: '돼지', cow: '젖소', chicken: '닭', duck: '오리', duckling: '아기오리', goose: '거위', calf: '송아지', lamb: '아기양', bee: '꿀벌', crab: '게', gull: '갈매기', hermit: '소라게', sandpiper: '도요새', sparrow: '참새', starfish: '불가사리', turtle: '거북', worm: '꼬물이', rabbit: '토끼', ladybug: '무당벌레', butterfly: '나비', octopus: '문어', otter: '수달', dolphin: '돌고래', seahorse: '해마', puffer: '복어', jelly: '해파리', bream: '도미', blue: '파랑 물고기', yellow: '노랑 물고기', stripe: '줄 물고기', bird: '새', cloud: '구름', snowman: '눈사람', jester: '광대 인형', scarecrow: '허수아비', cart: '수레', truck: '트럭', planter: '심는 일꾼', planterb: '심는 일꾼 B', harvester: '따는 일꾼', harvesterb: '따는 일꾼 B', caretaker: '돌보는 일꾼', caretakerb: '돌보는 일꾼 B', manager: '가게 일꾼', clerk: '집배원', peddler: '방물장수', visitor: '구경꾼', leaves: '낙엽', flowers: '꽃밭', guest: '손님', shadow: '그림자', dust: '흙먼지', sparkle: '반짝', heart: '하트', star: '별', note: '음표', bang: '느낌표', dots: '말줄임', sweat: '땀방울', hat: '밀짚모자', crown: '왕관', lemonade: '레모네이드 병', syrup: '시럽 병', jam: '잼 병', egg: '달걀', milkcan: '우유통', oldcan: '물뿌리개', letter: '편지', lantern: '등불', parasol: '파라솔', bench: '벤치', fountain: '분수', sign: '간판', signpost: '이정표', well: '우물', windmill: '풍차', mailbox: '우체통', stonelamp: '석등', birdhouse: '새집', arch: '꽃 아치', chest: '보물 상자', jar: '항아리', picnic: '소풍 자리', stand: '가판대', coffeecart: '커피 수레', coffee: '커피', flowerpots: '화분', sapling: '묘목', beehive: '벌통', doghouse: '개집', wheelbarrow: '손수레', clothesline: '빨랫줄', songpyeon: '송편', tteokguk: '떡국', crate: '상자', castle: '모래성', cottage: '오두막', towel: '수건', buoy: '부표', sailboat: '돛단배', lighthouse: '등대', haybale: '건초', haystack: '건초 더미', trough: '여물통', weathervane: '풍향계', woolbasket: '털 바구니', churns: '우유 단지', candy: '사탕', sunflower: '해바라기', cosmos: '코스모스', pumpkins: '호박', pinwheel: '바람개비', greenhouse: '온실', corn: '옥수수', hollyhock: '접시꽃', barrow: '수레', seedstand: '씨앗 판', lemonsign: '레몬 간판', birdpole: '새 기둥', can: '물통', tomatocage: '토마토 지지대', beanteepee: '콩 지지대', carpet: '레드카펫', basket: '바구니', gold: '금', battery: '건전지', bubble: '말풍선', clapflag: '박수 깃발', footprints: '발자국', frame: '액자', friendbench: '친구 벤치', giftbasket: '선물 바구니', jack: '깜짝 상자', mentorflag: '스승 깃발', oneplate: '한 접시', plaque: '명패', rankflag: '순위 깃발', sack: '자루', sacks: '자루들', sealflag: '인장 깃발', starflag: '별 깃발', sticks: '장작', taskboard: '할 일 판', trophy: '트로피', villageflag: '마을 깃발', visitorbox: '방명록함', drying: '말림대', crocks: '단지', shelf: '선반', flag: '깃발', cheesetable: '치즈 탁자', compost: '퇴비', twinkle: '반짝 물결', coral: '산호', bunting: '가랜드', xmas: '전구', lights: '줄', shirt: '셔츠', zzz: '쿨쿨', snow: '눈', leaf: '잎새', icicle: '고드름', floats: '부표 줄', icebox: '아이스박스', rowboat: '나룻배', dandelion: '민들레', fence: '울타리', shelter: '쉼터', sty: '돼지우리', coop: '닭장' };
  const FRUIT = { eureka: '유레카', meyer: '마이어', pink: '분홍 레몬', lime: '라임', yuja: '유자', kumquat: '금귤', buddha: '불수감', calamansi: '깔라만시', cheonhye: '천혜향', hallabong: '한라봉', redhyang: '레드향', grapefruit: '자몽', pomelo: '포멜로', bergamot: '베르가못', blood: '블러드 오렌지', fingerlime: '핑거라임', golden: '황금 레몬', moonlemon: '달 레몬', rainbow: '무지개 레몬', snowyuja: '눈 유자', trifoliate: '탱자' };
  const CORE = ['씨앗', '별', '하트', '잎', '물방울', '꽃', '해', '달', '구름', '조개', '발자국', '벌', '열쇠', '왕관', '음표', '새싹'];
  const SPECIAL = { first: '첫 열매', heart: '하트 레몬', moonpair: '달 쌍둥이', rain: '빗방울 레몬', rainbow: '무지개', snow: '눈 레몬', sunset: '노을 레몬', twin: '쌍둥이' };
  const SEASON = { spring: '봄', summer: '여름', autumn: '가을', winter: '겨울' };
  function labelOf(name) {
    let m;
    if ((m = /^lab-trunk-(\d)$/.exec(name))) return '줄기';
    if ((m = /^lab-crown-(\d)-(\d)$/.exec(name))) return `수관 ${['동글', '뾰족', '보송'][m[1]]}`;
    if ((m = /^lab-fruit-(\d)$/.exec(name))) return `열매 ${['동글', '길쭉', '물방울', '조롱박', '별', '하트'][m[1]] || m[1]}`;
    if ((m = /^lab-blossom-(\d)$/.exec(name))) return `꽃 ${['흰', '노랑', '주황', '하늘', '연두'][m[1]] || m[1]}`;
    if ((m = /^tree-(\w+)-\d$/.exec(name))) return `${FRUIT[m[1]] || m[1]} 나무`;
    if ((m = /^fruit-(\w+)$/.exec(name))) return FRUIT[m[1]] || m[1];
    if ((m = /^seal-core-(\d+)$/.exec(name))) return `${CORE[m[1]]} 무늬`;
    if ((m = /^special-(\w+)$/.exec(name))) return SPECIAL[m[1]] || m[1];
    if ((m = /^season-(\w+)$/.exec(name))) return `${SEASON[m[1]]} 그림`;
    if ((m = /^(?:badge|task)-(\w+)$/.exec(name))) return `배지 ${m[1]}`;
    const toks = name.replace(/^(farm-(guest|ranch|sea2|sea|field|orchard|fx)-|prop-|farm-|fx-|emote-|good-)/, '').split('-').filter(t => !/^\d+$/.test(t) && !/^[abc]$/.test(t));
    return toks.map(t => KO[t] || t).join(' ') + (/^(dog-[abc]|guest-[ab])/.test(name) ? ' ' + name.split('-')[1].toUpperCase() : '');
  }
  const WS_KO = { blob: '동글이', slime: '말랑이', cloudbot: '구름봇', quad: '네발이', long: '길쭉이', biped: '두발이', robot: '로봇',
    eyeround: '동글 눈', eyedot: '점 눈', eyehappy: '웃는 눈', eyesleepy: '졸린 눈', eyesparkle: '반짝 눈', eyewide: '놀란 눈', eyewink: '윙크', eyeheart: '하트 눈',
    mouthsmile: '웃는 입', mouthlaugh: '깔깔 입', moutho: '오 입', mouthcat: '고양이 입', mouthflat: '일자 입', mouthtongue: '메롱', mouthgrin: '이 보이는 입', cheekblush: '발그레 볼', cheeklines: '빗금 볼',
    straw: '밀짚모자', lemoncap: '레몬 모자', ribbon: '리본', flowercrown: '꽃관', beanie: '털모자', helmet: '헬멧', antenna: '더듬이', bearears: '곰 귀', foxears: '여우 귀', sprout: '새싹', chef: '요리사 모자', crown: '작은 왕관',
    basket: '바구니', umbrella: '우산', flag: '깃발', can: '물뿌리개', balloon: '풍선', lantern: '등불', bag: '가방', pinwheel: '바람개비', bouquet: '꽃다발', backpack: '배낭',
    headbox: '네모 머리', headdome: '둥근 머리', headcapsule: '캡슐 머리', bodybox: '네모 몸', bodybarrel: '통 몸', bodyegg: '알 몸', legstubby: '짧은 다리', legspring: '용수철 다리', legtall: '긴 다리', wheelmono: '외바퀴', wheelduo: '두 바퀴', wheeltread: '무한궤도', armclaw: '집게 팔', armhose: '호스 팔', armwrench: '렌치 팔', backjet: '제트팩', backkey: '태엽', backdish: '안테나 접시',
    ball: '공', flame: '불꽃', heart: '하트', puff: '세 송이', weeping: '늘어진', curvy: '굽은', twin: '두 갈래', birch: '하얀 껍질', stump: '그루터기', log: '통나무', shadow: '그림자', grass: '풀',
    lemon: '레몬', round: '동글', drop: '물방울', star: '별', pear: '배', berries: '송이', cube: '네모', moon: '달', bell: '종', tangerine: '귤',
    five: '다섯 잎 꽃', four: '네 잎 꽃', daisy: '데이지', tulip: '튤립', starflower: '별꽃', bellflower: '초롱꽃', pompom: '방울꽃', sprig: '꽃가지',
    bottle: '병', cup: '컵', lamp: '가로등', crate: '상자', sign: '간판', bench: '벤치', fountain: '분수', cart: '수레', planter: '화단', mailbox: '우체통', barrel: '통',
    shell: '조개', snowflake: '눈송이', leaf: '잎', sparkle: '반짝', notes: '음표', sun: '해', cloud: '구름', flower: '꽃', paw: '발바닥' };

  // ---------- 주제 ----------
  const THEMES = [
    { name: '아무거나' },
    { name: '바닷가풍', re: /sea|crab|gull|hermit|turtle|starfish|sandpiper|octopus|dolphin|otter|parasol|buoy|boat|towel|castle|coral|puffer|jelly|seahorse|bream|twinkle|core-9|core-4|lime|yuja/, pal: [18, 17, 16, 10, 6, 0, 19] },
    { name: '겨울', re: /snow|xmas|icicle|winter|lantern|moon|cloud|core-7|core-1|stonelamp|well|sweat|zzz/, pal: [0, 18, 19, 20, 21, 7, 16] },
    { name: '로봇', re: /robot|battery|jack|lantern|windmill|truck|weathervane|mailbox|stonelamp|well|trophy|cart|can|clapflag|core-12|bang|crate|icebox/, pal: [21, 22, 17, 18, 16, 3, 23] },
    { name: '과자', re: /candy|songpyeon|tteokguk|jam|syrup|lemonade|strawberry|pink|heart|chest|gift|basket|picnic|bubble|rainbow|core-2|core-5|star|note|sacks|stand/, pal: [8, 1, 5, 6, 7, 12, 16, 2] },
    { name: '목장', re: /ranch|cow|sheep|pig|chicken|duck|goose|calf|lamb|hay|egg|milk|dog|cat|rabbit|fence|barrow|wheelbarrow|hat|core-10|scarecrow|sack/, pal: [10, 11, 12, 14, 13, 1, 6] },
    { name: '노을', re: /sunset|lantern|blossom|orange|redhyang|hallabong|cheonhye|kumquat|blood|core-6|heart|parasol/, pal: [4, 6, 7, 3, 5, 9, 20] },
    { name: '숲속', re: /leaves|leaf|tree|crown|trunk|sapling|bird|sparrow|butterfly|ladybug|worm|rabbit|birdhouse|beehive|bee|core-3|core-15|lime|flowerpots|arch/, pal: [14, 15, 13, 12, 11, 2, 16] },
  ];
  const TH_SEA = 1, TH_WINTER = 2, TH_ROBOT = 3, TH_SWEET = 4, TH_FOREST = 7;

  // ---------- 부품 창고 ----------
  // part = { id, label, bench('tfp' 부분), cat, cat2?, role, roleBy?, acts{act: [그림 이름]}, crop?, size?, sz?{g,k,names}, ws?, wsz?, noAuto?, tags, th[], vw, vh, skin }
  const PARTS = {};
  let ANCHORS = {}; // 그림 이름 → 자리(수관 fruits·blossoms 는 ‰ 정수로 바꿔 둔다)
  const SML = ['작게', '중간', '크게'], WS_SZ = { s: '작게', m: '중간', l: '크게' };
  function setCatalog({ CATALOG: C, WS: WSD = {}, WS_ANCH: WSA = {} }) {
    for (const k in PARTS) delete PARTS[k];
    const framesOf = g => { const c = C[g]; if (!c) return []; return c.f ? (c.ids || [...Array(c.f).keys()]).map(i => `${g}-${i}`) : [g]; };
    const add = (id, o) => { PARTS[id] = Object.assign({ id, label: labelOf(o.label || id), tags: id }, o); if (o.label && !/[a-z]/.test(o.label)) PARTS[id].label = o.label; return PARTS[id]; };
    const keys = Object.keys(C), TREES = Object.keys(FRUIT);
    const sizeGroup = (ids, names) => { ids = ids.filter(id => PARTS[id]); ids.forEach((id, k) => { PARTS[id].sz = { g: ids, k, names }; }); };
    // 품종대
    for (let s = 0; s < 3; s++) add(`lab-trunk-${s}`, { bench: 't', cat: '줄기', role: 'trunk', acts: { '': [`lab-trunk-${s}`] }, size: s });
    ['eureka', 'meyer', 'pink', 'kumquat', 'buddha', 'yuja'].forEach(k => add(`tree-${k}-7#trunk`, { bench: 't', cat: '줄기', role: 'trunk', label: `${FRUIT[k]} 줄기(빌림)`, acts: { '': [`tree-${k}-7`] }, crop: 'trunk', tags: `tree ${k} trunk` }));
    for (let l = 0; l < 3; l++) for (let s = 0; s < 3; s++) add(`lab-crown-${l}-${s}`, { bench: 't', cat: '수관', role: 'crown', acts: { '': [`lab-crown-${l}-${s}`] }, size: s });
    TREES.forEach(k => add(`tree-${k}-7#crown`, { bench: 't', cat: '수관', role: 'crown', label: `${FRUIT[k]} 수관(빌림)`, acts: { '': [`tree-${k}-7`] }, crop: 'crown', tags: `tree ${k} crown` }));
    TREES.forEach(k => add(`tree-${k}-7`, { bench: 't', cat: '통나무', role: 'whole', acts: { '': [`tree-${k}-7`] } }));
    for (let i = 0; i < 6; i++) add(`lab-fruit-${i}`, { bench: 't', cat: '열매', role: 'fruit', acts: { '': [`lab-fruit-${i}`] } });
    TREES.forEach(k => add(`fruit-${k}`, { bench: 'tfp', cat: '열매', role: 'fruit', acts: { '': [`fruit-${k}`] } }));
    for (let i = 0; i < 5; i++) add(`lab-blossom-${i}`, { bench: 'tfp', cat: '꽃', role: 'blossom', acts: { '': [`lab-blossom-${i}`] } });
    // 붙임 장식(여러 작업대 공용). role 은 ROLE 표의 자리 규칙, roleBy 는 작업대마다 다른 역할
    const deco = (id, cat, role, bench = 'tfp', o = {}) => C[id] && add(id, Object.assign({ bench, cat, role, acts: { '': framesOf(id) } }, o));
    ['leaves-0', 'leaves-1', 'weeds-0', 'weeds-1', 'weeds-2'].forEach(n => add(n, { bench: 'tfp', cat: '땅', role: 'ground', acts: { '': [n] }, label: n.startsWith('leaves') ? '낙엽 ' + (+n.slice(-1) + 1) : '풀', tags: n + ' ground' }));
    ['farm-ranch-flowers', 'farm-ranch-dandelion', 'prop-footprints', 'fx-shadow', 'fx-dust'].forEach(n => deco(n, '땅', 'ground', 'tfp', { tags: n + ' ground' }));
    ['xmas-lights', 'farm-sea2-bunting'].forEach(n => deco(n, '매달기', 'hang', 'tp'));
    ['fx-sparkle', 'farm-sea2-twinkle', 'fx-snow', 'fx-leaf'].forEach(n => deco(n, '장식', 'deco'));
    ['emote-heart', 'emote-star', 'emote-note', 'emote-bang', 'emote-dots', 'emote-sweat', 'fx-zzz'].forEach(n => deco(n, '기분', 'above'));
    ['farm-fx-hat', 'prop-crown'].forEach(n => deco(n, '머리', 'hat'));
    ['prop-sack', 'prop-basket-gold', 'farm-ranch-woolbasket', 'farm-sea2-parasol'].forEach(n => C[n] && add('back:' + n, { bench: 'f', cat: '등에', role: 'back', label: labelOf(n), acts: { '': framesOf(n) }, tags: n }));
    ['good-lemonade', 'good-syrup', 'good-jam', 'farm-ranch-egg', 'prop-oldcan', 'farm-fx-letter', 'farm-ranch-milkcan'].forEach(n => deco(n, '들 것', 'hand', 'f'));
    for (let i = 0; i < 16; i++) add(`seal-core-${i}`, { bench: 'tfp', cat: '스티커', role: 'sticker', acts: { '': [`seal-core-${i}`] } });
    keys.filter(k => /^(special|season)-/.test(k)).forEach(n => add(n, { bench: 'p', cat: '스티커', role: 'sticker', acts: { '': [n] } }));
    // 공방 부품(ws-*): 크기마다 따로 그린 부품을 크기 묶음으로
    const WS_MAP = {
      'tree-crown': ['crown', 't', '수관'], 'tree-trunk': ['trunk', 't', '줄기'], 'tree-ground': ['ground', 'tfp', '땅'], 'all-ground': ['ground', 'tfp', '땅'],
      'tree-fruit': ['fruit', 'tfp', '열매'], 'tree-blossom': ['blossom', 'tfp', '꽃'], 'friend-body': ['body', 'f', '공방 친구'], 'friend-face': ['face', 'f', '얼굴'],
      'friend-head': ['hat', 'tfp', '머리'], 'friend-held': ['hand', 'f', '들 것'], 'friend-back': ['back', 'f', '등에'], 'friend-robot': ['robot', 'f', '로봇 부품'],
      'prop-base': ['prop', 'p', '바탕'], 'all-sticker': ['sticker', 'tfp', '스티커'] };
    Object.entries(WSD).forEach(([gid, w]) => {
      const [role0, bench, cat] = WS_MAP[`${w.bench}-${w.role}`] || [];
      if (!role0) return;
      let role = role0;
      if (role0 === 'robot') role = /^head/.test(w.thing) ? 'top' : /^(leg|wheel)/.test(w.thing) ? 'under' : /^arm/.test(w.thing) ? 'hand' : /^back/.test(w.thing) ? 'back' : 'body';
      const ids = ['s', 'm', 'l'].filter(z => w.sizes[z]).map(z => {
        const fr = w.sizes[z], id = `${gid}-${z}`;
        const acts = role === 'body' && fr.length > 1 ? { idle: [fr[0]], walk: fr } : { [role === 'body' ? 'idle' : '']: fr };
        const P = add(id, { bench, cat, role, acts, label: (WS_KO[w.thing] || w.thing) + (Object.keys(w.sizes).length > 1 ? ' ' + WS_SZ[z] : ''), tags: `${id} ${w.thing} ws`, wsz: z, ws: w.thing });
        if (role === 'trunk') P.size = { s: 0, m: 1, l: 2 }[z];
        if (w.thing === 'bottle') P.cat2 = '병';
        if (role0 === 'robot' || w.thing === 'shadow') P.noAuto = true; // 로봇 부품은 로봇 조립에서만, 그림자는 발밑 전용
        return id;
      });
      if (ids.length > 1) sizeGroup(ids, ids.map(id => WS_SZ[PARTS[id].wsz]));
    });
    TREES.forEach(k => { add(`tree-${k}-2`, { bench: 't', cat: '통나무', role: 'whole', acts: { '': [`tree-${k}-2`] }, label: `${FRUIT[k]} 나무` }); sizeGroup([`tree-${k}-2`, `tree-${k}-7`], ['작게', '크게']); });
    sizeGroup([0, 1, 2].map(s => `lab-trunk-${s}`), SML);
    for (let l = 0; l < 3; l++) sizeGroup([0, 1, 2].map(s => `lab-crown-${l}-${s}`), SML);
    sizeGroup(['weeds-0', 'weeds-1', 'weeds-2'], SML);
    sizeGroup(['body:cloud-2', 'body:cloud-1', 'body:cloud-0'], SML);
    // 손으로는 쓸 수 있지만 자동 조립에서는 빼는 부품
    ['prop-crown', 'back:farm-sea2-parasol'].concat(keys.filter(k => /^season-/.test(k))).forEach(n => { if (PARTS[n]) PARTS[n].noAuto = true; });
    Object.values(PARTS).forEach(P => { if (P.role === 'fruit') P.roleBy = { f: 'hand', p: 'sticker' }; if (P.role === 'blossom') P.roleBy = { f: 'hat', p: 'sticker' }; });
    // 친구대 몸통
    const ACT = /^(walk|idle|sit|bark|trick|eat|graze|moo|tail|peck|rest|swim|flap|honk|mud|shake|shorn|drink|sleep|stamp|bell|cart|habit|wave|cheer|carry|yawn|water|pick|sniff)$/;
    const BODY_MULTI = [['dog-a', '동물'], ['dog-b', '동물'], ['dog-c', '동물'], ['farm-guest-cat', '동물'], ['farm-ranch-sheep', '목장'], ['farm-ranch-pig', '목장'], ['farm-ranch-cow', '목장'], ['farm-ranch-chicken', '목장'], ['farm-ranch-duck', '목장'], ['farm-ranch-duckling', '목장'], ['farm-ranch-goose', '목장'], ['farm-ranch-calf', '목장'],
      ['guest-a', '사람'], ['guest-b', '사람'], ['planter', '사람'], ['planterb', '사람'], ['harvester', '사람'], ['harvesterb', '사람'], ['caretaker', '사람'], ['caretakerb', '사람'], ['manager', '사람'], ['farm-guest-clerk', '사람'], ['farm-guest-peddler', '사람'], ['visitor', '사람']];
    BODY_MULTI.forEach(([p, cat]) => {
      const acts = {};
      keys.forEach(k => { if (k.startsWith(p + '-')) { const a = k.slice(p.length + 1); if (ACT.test(a)) acts[a] = framesOf(k); } });
      if (C[p] && !acts.idle) acts.idle = framesOf(p);
      if (p === 'farm-ranch-calf') acts.idle = framesOf('farm-ranch-calf');
      if (!Object.keys(acts).length) return;
      add('body:' + p, { bench: 'f', cat, role: 'body', label: labelOf(p), acts, tags: p });
    });
    const BODY_ONE = [['farm-ranch-lamb', '목장'], ['farm-ranch-bee', '하늘'], ['farm-guest-crab', '바다'], ['farm-guest-gull', '하늘'], ['farm-guest-hermit', '바다'], ['farm-guest-sandpiper', '바다'], ['farm-guest-sparrow', '하늘'], ['farm-guest-starfish', '바다'], ['farm-guest-turtle', '바다'], ['farm-guest-worm', '동물'], ['farm-guest-rabbit', '동물'], ['farm-guest-ladybug', '동물'], ['farm-guest-butterfly-y', '하늘'], ['farm-guest-butterfly-w', '하늘'],
      ['farm-sea2-octopus', '바다'], ['farm-sea2-turtle', '바다'], ['farm-sea2-crab', '바다'], ['farm-sea2-otter', '바다'], ['farm-sea2-dolphin', '바다'], ['farm-sea2-seahorse', '바다'], ['farm-sea2-puffer', '바다'], ['farm-sea2-jelly', '바다'], ['farm-sea2-duck', '바다'], ['farm-sea2-hermit', '바다'], ['farm-sea2-bream', '바다'], ['farm-sea2-yellow', '바다'],
      ['bird', '하늘'], ['butterfly', '하늘'], ['farm-ranch-snowman', '기타'], ['prop-dog', '동물'], ['prop-jester', '기타'], ['prop-scarecrow', '기타'], ['guest-cart', '기타'], ['farm-ranch-truck', '기타'], ['prop-battery', '기타'], ['prop-jack', '기타']];
    BODY_ONE.forEach(([g, cat]) => C[g] && add('body:' + g, { bench: 'f', cat, role: 'body', label: labelOf(g), acts: { idle: framesOf(g) }, tags: g }));
    ['cloud-0', 'cloud-1', 'cloud-2', 'farm-sea2-cloud-0', 'farm-sea2-cloud-1'].forEach(n => C[n.replace(/-\d$/, '')] && add('body:' + n, { bench: 'f', cat: '하늘', role: 'body', label: '구름 ' + n.slice(-1), acts: { idle: [n] }, tags: n + ' cloud sky' }));
    // 소품대 바탕
    const PROP_BASE = keys.filter(k => /^prop-/.test(k) && !/^prop-(dog|jester|scarecrow|battery|jack|crown|oldcan|footprints)$/.test(k))
      .concat(['lantern', 'crate', 'farm-mailbox', 'farm-orchard-candy', 'farm-orchard-crocks', 'farm-orchard-drying', 'farm-orchard-shelf', 'farm-orchard-flag',
        'farm-field-barrow', 'farm-field-beanteepee', 'farm-field-birdpole', 'farm-field-can', 'farm-field-cosmos', 'farm-field-hollyhock', 'farm-field-lemonsign', 'farm-field-pinwheel', 'farm-field-pumpkins', 'farm-field-seedstand', 'farm-field-sunflower', 'farm-field-greenhouse',
        'farm-ranch-beehive', 'farm-ranch-churns', 'farm-ranch-haybale', 'farm-ranch-haystack', 'farm-ranch-trough', 'farm-ranch-weathervane', 'farm-ranch-woolbasket', 'farm-ranch-cheesetable', 'farm-ranch-snowman',
        'farm-sea2-buoy', 'farm-sea2-castle', 'farm-sea2-cottage', 'farm-sea2-parasol', 'farm-sea2-towel', 'farm-sea2-crate', 'farm-sea2-sailboat', 'farm-sea2-coral', 'farm-sea-floats', 'farm-sea-icebox', 'farm-sea-rowboat']);
    PROP_BASE.forEach(g => {
      if (!C[g]) return;
      const fr = framesOf(g);
      if (/^(crate|farm-sea2-coral)$/.test(g)) fr.forEach(n => add(n, { bench: 'p', cat: '바탕', role: 'prop', acts: { '': [n] } }));
      else add(g, { bench: 'p', cat: '바탕', role: 'prop', acts: { '': fr } });
    });
    ['good-lemonade', 'good-syrup', 'good-jam'].forEach(n => { if (PARTS[n]) { PARTS[n].bench = 'fp'; PARTS[n].cat2 = '병'; } });
    // 미리 계산: 주제 소속(th), 보이는 크기(vw·vh, @2x), 사람 피부 지키기(skin)
    Object.values(PARTS).forEach(P => {
      P.th = THEMES.map((t, i) => t.re && t.re.test(P.tags + ' ' + P.id) ? i : -1).filter(i => i >= 0);
      if (P.crop) [P.vw, P.vh] = P.crop === 'crown' ? [90, 70] : [34, 40];
      else {
        const n = Object.values(P.acts)[0][0], m = /^(.*)-(\d+)$/.exec(n), g = C[n] ? n : m && m[1], c = C[g] || { bw: 40, bh: 40 };
        let wh = [c.bw, c.bh];
        if (c.fb && m && g !== n) { const k = (c.ids || [...Array(c.f).keys()]).indexOf(+m[2]); if (k >= 0) wh = c.fb[k]; }
        [P.vw, P.vh] = wh;
      }
      P.skin = P.cat === '사람';
      P.nw = nounIndex(P);
    });
    ANCHORS = {};
    Object.entries(WSA).forEach(([k, v]) => {
      if (k === '_doc') return;
      const o = Object.assign({}, v);
      ['fruits', 'blossoms'].forEach(f => { if (o[f]) o[f] = o[f].map(([x, y]) => [Math.round(x * 1000), Math.round(y * 1000)]); });
      ANCHORS[k] = o;
    });
  }

  // ---------- 역할·자리 ----------
  // z = 앞뒤 순서(작을수록 뒤), at = 붙는 자리('sc' = 흩뿌리기), one = 한 작품에 하나만
  const ROLE = {
    face: { z: { f: 4 }, at: { f: 'face' }, ko: '얼굴' },
    top: { z: { f: 3 }, at: { f: 'top' }, ko: '로봇 머리' },
    under: { z: { f: 1 }, at: { f: 'under' }, ko: '로봇 다리' },
    ground: { z: { t: 1, f: 0, p: 1 }, at: { t: 'ground', f: 'feet', p: 'ground' }, ko: '땅' },
    back: { z: { f: 1 }, at: { f: 'back' }, ko: '등에' },
    trunk: { z: { t: 0 }, at: {}, one: true, ko: '줄기' },
    whole: { z: { t: 0 }, at: {}, one: true, ko: '나무' },
    body: { z: { f: 2 }, at: {}, one: true, ko: '몸통' },
    prop: { z: { p: 0, f: 2 }, at: {}, one: true, ko: '바탕' },
    crown: { z: { t: 2 }, at: { t: 'trunk' }, one: true, ko: '수관' },
    blossom: { z: { t: 3 }, at: { t: 'sc' }, ko: '꽃' },
    fruit: { z: { t: 4 }, at: { t: 'sc' }, ko: '열매' },
    hang: { z: { t: 5, p: 3 }, at: { t: 'hang', p: 'hang' }, ko: '매달기' },
    sticker: { z: { t: 6, f: 3, p: 2 }, at: { t: 'on', f: 'on', p: 'on' }, ko: '스티커' },
    deco: { z: { t: 6, f: 3, p: 2 }, at: { t: 'on', f: 'on', p: 'on' }, ko: '장식' },
    hand: { z: { f: 5 }, at: { f: 'hand' }, ko: '들 것' },
    hat: { z: { t: 7, f: 6, p: 4 }, at: { t: 'head', f: 'head', p: 'head' }, ko: '머리' },
    above: { z: { t: 8, f: 7, p: 5 }, at: { t: 'above', f: 'above', p: 'above' }, ko: '기분' },
  };
  const CONFLICT = { trunk: ['trunk', 'whole'], crown: ['crown', 'whole'], whole: ['trunk', 'crown', 'whole'], body: ['body', 'prop'], prop: ['prop', 'body'] };
  const ANCHOR_KO = { head: '머리', above: '위', hand: '손', on: '안쪽', back: '등 뒤', hang: '아래 가장자리', ground: '땅선', feet: '발밑', trunk: '줄기 위', face: '얼굴', top: '몸 위', under: '몸 아래' };
  const AT_KINDS = Object.keys(ANCHOR_KO);
  const MODES = [['o', '원래 색'], ['map', '물들이기'], ['hue', '색만 바꾸기']];
  const PATS = [['none', '민'], ['stripe', '줄'], ['dot', '점'], ['check', '체크'], ['wave', '물결'], ['spark', '반짝']];
  const MOVES = ['walk', 'hop', 'fly', 'follow', 'idle'];
  // 아래 도우미의 b 는 작업대 한 글자(t|f|p)
  const roleOf = (P, b) => (P.roleBy && P.roleBy[b]) || P.role;
  const zOf = (L, b) => { const P = PARTS[L.p], R = P && ROLE[roleOf(P, b)]; return R && R.z[b] != null ? R.z[b] : 5; };
  const atOf = (P, b) => (ROLE[roleOf(P, b)] || { at: {} }).at[b] || null;
  const catOf = (P, b) => (b === 'p' && P.cat2) ? P.cat2 : P.cat;
  const partsIn = (b, cat) => Object.values(PARTS).filter(P => P.bench.includes(b) && (!cat || catOf(P, b) === cat));
  const firstAct = P => Object.keys(P.acts)[0];

  // ---------- 그림 다루기 (그림 = {w, h, data: RGBA 바이트}) ----------
  const blank = (w, h) => ({ w, h, data: new Uint8ClampedArray(w * h * 4) });
  // 빌린 나무 그림에서 수관(위)·줄기(아래)만 잘라 낼 칸
  const CROP = new WeakMap();
  function cropRect(src, kind) {
    let m = CROP.get(src); if (!m) CROP.set(src, m = {});
    if (m[kind]) return m[kind];
    const { w, h, data: d } = src;
    const rows = []; for (let y = 0; y < h; y++) { let n = 0; for (let i = 0; i < w; i++) if (opaque(d[(y * w + i) * 4 + 3])) n++; rows.push(n); }
    const mx = Math.max(...rows), at = rows.indexOf(mx);
    let s = at; while (s < h && 100 * rows[s] >= 33 * mx) s++;
    const [y0, y1] = kind === 'crown' ? [0, Math.min(h, s + 6)] : [Math.max(0, s - 4), h];
    let x0 = w, x1 = 0;
    for (let y = y0; y < y1; y++) for (let i = 0; i < w; i++) if (opaque(d[(y * w + i) * 4 + 3])) { x0 = Math.min(x0, i); x1 = Math.max(x1, i + 1); }
    return (m[kind] = { x: x0 & ~1, y: y0 & ~1, w: (x1 - (x0 & ~1) + 1) & ~1, h: (y1 - (y0 & ~1) + 1) & ~1 });
  }
  // 층의 원본 그림(자르기 포함, 알파는 0 또는 255 로 맞춘다)
  function layerSource(name, crop, getPart) {
    const src = getPart(name); if (!src) return null;
    const r = crop ? cropRect(src, crop) : { x: 0, y: 0, w: src.w, h: src.h }, o = blank(r.w, r.h);
    for (let y = 0; y < r.h; y++) for (let x = 0; x < r.w; x++) {
      const sx = r.x + x, sy = r.y + y; if (sx >= src.w || sy >= src.h) continue;
      const i = (sy * src.w + sx) * 4, j = (y * r.w + x) * 4;
      if (opaque(src.data[i + 3])) { o.data[j] = src.data[i]; o.data[j + 1] = src.data[i + 1]; o.data[j + 2] = src.data[i + 2]; o.data[j + 3] = 255; }
    }
    return o;
  }
  function bbox(img) {
    const { w, h, data: d } = img;
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (opaque(d[(y * w + x) * 4 + 3])) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    if (x1 < 0) return { x: 0, y: 0, w, h, headX: w >> 1 };
    // 머리: 맨 위 4줄의 불투명 픽셀 x 평균(반올림)
    let hx = 0, hn = 0; for (let y = y0; y < Math.min(h, y0 + 4); y++) for (let x = x0; x <= x1; x++) if (opaque(d[(y * w + x) * 4 + 3])) { hx += x; hn++; }
    return { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1, headX: Math.floor((2 * hx + hn) / (2 * hn)) };
  }

  // ---------- 물들이기 ----------
  // 밝기 단계: 쓰인 밝기 수만큼(최대 kmax) 1차원 k-평균, 정수 중심
  function lumSteps(sorted, kmax) {
    let distinct = 0, prev = -1;
    for (const v of sorted) { const q = Math.floor((v + 500) / 1000); if (q !== prev) { distinct++; prev = q; } }
    const k = Math.min(kmax, distinct), N = sorted.length;
    let c = [...Array(k)].map((_, i) => sorted[Math.floor((2 * i + 1) * N / (2 * k))]);
    for (let it = 0; it < 8; it++) {
      const s = c.map(() => 0), n = c.map(() => 0);
      for (const v of sorted) { let j = 0; for (let q = 1; q < k; q++) if (Math.abs(v - c[q]) < Math.abs(v - c[j])) j = q; s[j] += v; n[j]++; }
      c = c.map((x, j) => n[j] ? Math.floor(s[j] / n[j]) : x);
    }
    return c.sort((a, b) => a - b);
  }
  // 명암 사다리: t ‰. 0 = DEEP[S], 330 = 그림자 칸, 660 = 바탕 칸, 1000 = LIGHT[B]
  function rampAt(Bi, Si, t) {
    const st = [[0, DEEP[Si]], [330, PAL[Si].rgb], [660, PAL[Bi].rgb], [1000, LIGHT[Bi]]];
    for (let k = 1; k < st.length; k++) if (t <= st[k][0]) {
      const [t0, a] = st[k - 1], [t1, b] = st[k], den = t1 - t0, u = t - t0;
      return a.map((av, q) => Math.floor((2 * (av * (den - u) + b[q] * u) + den) / (2 * den)));
    }
    return LIGHT[Bi];
  }
  const nearestIdx = (v, cs) => { let j = 0; for (let q = 1; q < cs.length; q++) if (Math.abs(v - cs[q]) < Math.abs(v - cs[j])) j = q; return j; };
  function recolor(img, L, skin) {
    if (L.m === 'o') return;
    const p = img.data, n = p.length >> 2, Bi = L.c[0], Si = L.c[1], Ai = L.c[2];
    if (L.m === 'map') {
      // 주된 색상(10° 칸 36개에 채도 무게, 이웃 칸까지 합해 가장 큰 칸의 가운데)과 50° 넘게 다른 진한 색 영역은 포인트 칸 사다리로
      const hsv = new Array(n), bins = new Array(36).fill(0);
      for (let i = 0; i < n; i++) {
        if (!opaque(p[i * 4 + 3])) continue;
        const q = hsv[i] = hsvI(p[i * 4], p[i * 4 + 1], p[i * 4 + 2]);
        if (4 * q[1] > q[2] && 4 * q[2] > 255) bins[Math.floor(q[0] / 10)] += Math.floor(256 * q[1] / q[2]);
      }
      let best = -1, bk = 0;
      for (let k = 0; k < 36; k++) { const s = bins[(k + 35) % 36] + bins[k] + bins[(k + 1) % 36]; if (s > best) { best = s; bk = k; } }
      const dom = bk * 10 + 5, hasDom = best > 256;
      const groups = [[], []];
      for (let i = 0; i < n; i++) {
        const q = hsv[i]; if (!q) continue;
        if (skin && isSkin(...q)) continue;
        groups[hasDom && 10 * q[1] > 3 * q[2] && 4 * q[2] > 255 && hd(q[0], dom) > 50 ? 1 : 0].push(i);
      }
      groups.forEach((idx, g) => {
        if (!idx.length) return;
        const ys = idx.map(i => lumY(p[i * 4], p[i * 4 + 1], p[i * 4 + 2])), cs = lumSteps([...ys].sort((a, b) => a - b), 7);
        const lo = cs[0], span = cs[cs.length - 1] - lo;
        const [Bc, Sc] = g ? [Ai, SHADE[Ai]] : [Bi, Si];
        const ramp = cs.map(v => rampAt(Bc, Sc, span > 5100 ? Math.floor((v - lo) * 1000 / span) : 660));
        idx.forEach((i, k) => { const c = ramp[nearestIdx(ys[k], cs)]; p[i * 4] = c[0]; p[i * 4 + 1] = c[1]; p[i * 4 + 2] = c[2]; });
      });
    } else { // 'hue': 색상만 칸 색으로, 채도·명도는 섞어서
      for (let i = 0; i < n; i++) {
        const j = i * 4; if (!opaque(p[j + 3])) continue;
        const [h, d, mx] = hsvI(p[j], p[j + 1], p[j + 2]);
        if (100 * d <= 18 * mx || 100 * mx < 4080 || (skin && isSkin(h, d, mx))) continue;
        const T = PAL[100 * mx < 11475 ? Si : Bi];
        const s = Math.min(1000, Math.floor((35 * Math.floor(1000 * d / mx) + 65 * T.s) / 100));
        const vN = Math.min(255000, Math.floor(mx * (191250 + 300 * T.v) / 255));
        const c = hsvToRgbI(T.h, s, vN); p[j] = c[0]; p[j + 1] = c[1]; p[j + 2] = c[2];
      }
    }
  }
  // 무늬(그림 픽셀 1칸 단위, 층 그림 안 좌표)
  const WAVE12 = [0, 1, 1, 1, 1, 1, 0, 0, -1, -1, -1, -1];
  function patHit(pt, x, y) {
    switch (pt) {
      case 'stripe': return y % 3 === 0;
      case 'dot': return (x % 4 === 1 && y % 4 === 1) || (x % 4 === 3 && y % 4 === 3);
      case 'check': return ((x >> 1) + (y >> 1)) % 2 === 0;
      case 'wave': return (y + WAVE12[x % 12] + 4) % 4 === 0;
      case 'spark': {
        const cu = Math.floor(x / 7), cv = Math.floor(y / 7), hsh = (Math.imul(cu, 73856093) ^ Math.imul(cv, 19349663)) >>> 0;
        if (hsh % 3) return false;
        const du = Math.abs(x - (cu * 7 + 2 + (hsh >>> 3) % 3)), dv = Math.abs(y - (cv * 7 + 2 + (hsh >>> 7) % 3));
        return (du <= 1 && dv === 0) || (du === 0 && dv <= 1);
      }
    }
    return false;
  }
  function pattern(img, L, skin) {
    if (L.pt === 'none' && L.pa !== 'band') return;
    const { w, h, data: p } = img, A = PAL[L.c[2]].rgb, Sd = PAL[L.c[1]].rgb, Bs = PAL[L.c[0]].rgb, band = L.pa === 'band';
    let y0 = 0, y1 = h;
    if (band) { // 라벨: 그림 높이 38%~74% 띠
      let t = h, b = -1; for (let i = 0; i < w * h; i++) if (opaque(p[i * 4 + 3])) { const yy = Math.floor(i / w); t = Math.min(t, yy); b = Math.max(b, yy); }
      if (b < 0) return;
      const hh = b - t + 1; y0 = t + r100(hh * 38); y1 = t + r100(hh * 74);
    }
    for (let y = y0; y < y1; y++) for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4; if (!opaque(p[i + 3])) continue;
      const Y = lumY(p[i], p[i + 1], p[i + 2]); if (Y < (band ? 61200 : 91800)) continue; // 외곽선·그늘은 그대로
      if (skin && isSkin(...hsvI(p[i], p[i + 1], p[i + 2]))) continue; // 사람 피부에는 무늬 없음
      const on = patHit(L.pt, x, y);
      let col = band ? (on ? Bs : A) : on ? A : null;
      if (!col) continue;
      if (Y < 107100) col = col.map((v, q) => Math.floor((55 * v + 45 * Sd[q] + 50) / 100));
      p[i] = col[0]; p[i + 1] = col[1]; p[i + 2] = col[2];
    }
  }
  // 층 그림: 자르기 → 뒤집기 → 물들이기 → 무늬. 같은 입력이면 다시 쓰도록 getPart 마다 기억
  const LCACHE = new WeakMap();
  function layerImg(L, P, name, getPart) {
    let cache = LCACHE.get(getPart); if (!cache) LCACHE.set(getPart, cache = new Map());
    const key = [name, P.crop, L.m, L.c, L.pt, L.pa, L.fl, P.skin].join('|');
    if (cache.has(key)) return cache.get(key);
    const src = layerSource(name, P.crop, getPart); if (!src) return null;
    let img = src;
    if (L.fl) { img = blank(src.w, src.h); for (let y = 0; y < src.h; y++) for (let x = 0; x < src.w; x++) { const i = (y * src.w + x) * 4, j = (y * src.w + src.w - 1 - x) * 4; for (let q = 0; q < 4; q++) img.data[j + q] = src.data[i + q]; } }
    recolor(img, L, P.skin);
    pattern(img, L, P.skin);
    const o = { img, bb: bbox(img) };
    if (cache.size > 3000) cache.clear();
    cache.set(key, o); return o;
  }
  // dst(144×144)에 그림을 (sx, sy)에 불투명 픽셀만 덮어 그린다
  function blit(dst, img, sx, sy) {
    for (let y = 0; y < img.h; y++) { const ty = sy + y; if (ty < 0 || ty >= H) continue;
      for (let x = 0; x < img.w; x++) { const tx = sx + x; if (tx < 0 || tx >= W) continue;
        const i = (y * img.w + x) * 4; if (!opaque(img.data[i + 3])) continue;
        const j = (ty * W + tx) * 4; dst.data[j] = img.data[i]; dst.data[j + 1] = img.data[i + 1]; dst.data[j + 2] = img.data[i + 2]; dst.data[j + 3] = 255; } }
  }

  // ---------- 조립 ----------
  const ANCH = { fruits: [[180, 580], [800, 540], [440, 760], [620, 340], [300, 340], [900, 780], [100, 800], [640, 800]], blossoms: [[480, 180], [220, 860], [780, 300], [540, 560], [360, 500], [700, 660]] };
  function actOf(P, L, move) {
    if (move && P.role === 'body') {
      const want = { walk: ['walk', 'swim', 'flap'], hop: ['idle', 'sit', 'walk'], fly: ['flap', 'walk', 'swim'], follow: ['walk', 'swim'], idle: [L.a] }[move] || [];
      const a = want.find(w => P.acts[w]); if (a) return a;
    }
    return P.acts[L.a] ? L.a : firstAct(P);
  }
  // compose(work, getPart, {tick, move}) → {w, h, data, layers: [{data, spots, r} | null]}
  // 두 번에 나눠 놓는다: ① 자유 자리 층과 줄기 위 수관으로 기준(발·위)을 잡고 ② 붙임·흩뿌리기를 그 기준에 놓는다
  function compose(work, getPart, opt = {}) {
    const b = sbOf(work), tick = opt.tick || 0, out = blank(W, H);
    const items = work.L.map(L => {
      const P = PARTS[L.p]; if (!P) return null;
      const fr = P.acts[actOf(P, L, opt.move)], name = fr[tick % fr.length], o = layerImg(L, P, name, getPart);
      return o ? { L, P, o, w: o.img.w, h: o.img.h, name } : null;
    });
    const box = (it, sx, sy) => ({ x: sx + it.o.bb.x, y: sy + it.o.bb.y, w: it.o.bb.w, h: it.o.bb.h, headX: sx + it.o.bb.headX, fl: it.L.fl });
    const find = rs => items.find(it => it && it.ref && rs.includes(roleOf(it.P, b))) || null;
    items.forEach(it => { if (it && !it.L.at && !it.L.sc) { it.spots = [[it.L.x - (it.w >> 1), it.L.y - it.h]]; it.ref = box(it, ...it.spots[0]); } });
    const footIt = find(['trunk', 'whole', 'body', 'prop']) || items.find(it => it && it.ref) || null;
    const F0 = footIt ? footIt.ref : { x: W / 2 - 10, y: GROUND - 30, w: 20, h: 30, headX: W / 2, fl: false };
    items.forEach(it => {
      if (!it || it.L.at !== 'trunk') return;
      const k = footIt && footIt.P.crop ? 12 : 35;
      const sx = F0.headX + it.L.x - (it.w >> 1), sy = F0.y + r100(F0.h * k) + it.L.y - it.h;
      it.spots = [[sx, sy]]; it.ref = box(it, sx, sy);
    });
    const topIt = find(['crown']) || find(['whole', 'body', 'prop']) || [...items].reverse().find(it => it && it.ref) || null;
    const R = topIt ? topIt.ref : F0, Fo = footIt ? footIt.ref : R;
    // 공방 부품의 자리(오른쪽을 보는 그림 기준. 뒤집으면 x 를 거울로)
    const anc = k => { const it = topIt && topIt.spots.length === 1 ? topIt : null, A = it && ANCHORS[it.name]; if (!A || !A[k]) return null; const [ax, ay] = A[k]; return [it.spots[0][0] + (it.L.fl ? it.w - 1 - ax : ax), it.spots[0][1] + ay]; };
    items.forEach(it => {
      if (!it || it.spots) return;
      const { L } = it, ob = it.o.bb, w = ob.w, h = ob.h;
      if (L.sc > 0) {
        const WA = topIt && ANCHORS[topIt.name], bl = it.P.role === 'blossom', pts = WA && WA.fruits ? (bl ? WA.blossoms : WA.fruits) : bl ? ANCH.blossoms : ANCH.fruits;
        it.spots = pts.slice(0, L.sc).map(([fx, fy]) => [R.x + L.x + floorDiv(2 * fx * R.w - 1000 * w + 1000, 2000) - ob.x, R.y + L.y + floorDiv(2 * fy * R.h - 1000 * h + 1000, 2000) - ob.y]);
        return;
      }
      const cxIn = cx => w >= R.w ? R.x + (R.w >> 1) : Math.max(R.x + (w >> 1), Math.min(R.x + R.w - (w >> 1), cx));
      const cyIn = cy => h >= R.h ? R.y + (R.h >> 1) : Math.max(R.y + (h >> 1), Math.min(R.y + R.h - (h >> 1), cy));
      let cx, by; // 가운데 x, 아래 y
      switch (L.at) {
        case 'head': { const a = anc('head'); cx = (a ? a[0] : R.headX) + L.x; by = (a ? a[1] : R.y) + r100(h * 45) + L.y; break; }
        case 'face': { const a = anc('face') || [R.x + r100(R.w * (R.fl ? 38 : 62)), R.y + r100(R.h * 38)]; cx = a[0] + L.x; by = a[1] + (h >> 1) + L.y; break; }
        case 'top': cx = R.x + (R.w >> 1) + L.x; by = R.y + 2 + L.y; break;
        case 'under': cx = Fo.x + (Fo.w >> 1) + L.x; by = Fo.y + Fo.h + h - 2 + L.y; break;
        case 'above': cx = R.headX + 4 + L.x; by = R.y - 2 + L.y; break;
        case 'hand': { const a = anc('hand'); if (a) { cx = a[0] + L.x; by = a[1] + (h >> 1) + L.y; } else { cx = (R.fl ? R.x + 4 : R.x + R.w - 4) + L.x; by = R.y + r100(R.h * 72) + (h >> 1) + L.y; } break; }
        case 'on': cx = cxIn(R.x + (R.w >> 1) + L.x); by = cyIn(R.y + (R.h >> 1) + L.y) + (h >> 1); break;
        case 'back': cx = R.x + (R.w >> 1) + (R.fl ? 1 : -1) * r100(R.w * 30) + L.x; by = R.y + r100(R.h * 78) + L.y; break;
        case 'hang': cx = cxIn(R.x + (R.w >> 1) + L.x); by = R.y + r100(R.h * 70) + h + L.y; break;
        case 'ground': cx = Fo.x + (Fo.w >> 1) + L.x; by = GROUND + 2 + L.y; break;
        case 'feet': cx = Fo.x + (Fo.w >> 1) + L.x; by = Fo.y + Fo.h + r100(h * 30) + L.y; break;
        default: cx = W / 2 + L.x; by = GROUND + L.y;
      }
      it.spots = [[cx - (w >> 1) - ob.x, by - h - ob.y]];
    });
    let mask = null;
    if (topIt) { mask = blank(W, H); topIt.spots.forEach(([sx, sy]) => blit(mask, topIt.o.img, sx, sy)); }
    const layers = items.map(it => {
      if (!it) return null;
      const lc = blank(W, H), d = lc.data;
      it.spots.forEach(([sx, sy]) => blit(lc, it.o.img, sx, sy));
      if (it.L.cl && mask && it !== topIt) for (let i = 3; i < d.length; i += 4) if (!mask.data[i]) d[i - 3] = d[i - 2] = d[i - 1] = d[i] = 0;
      if (it.L.mi) { const cp = d.slice(); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const s = (y * W + W - 1 - x) * 4; if (!cp[s + 3]) continue; const t = (y * W + x) * 4; d[t] = cp[s]; d[t + 1] = cp[s + 1]; d[t + 2] = cp[s + 2]; d[t + 3] = 255; } }
      blit(out, lc, 0, 0);
      return { w: W, h: H, data: d, r: { x: it.spots[0][0], y: it.spots[0][1], w: it.w, h: it.h }, spots: it.spots };
    });
    // 도트 다듬기(맨 마지막)
    const e = decodeDots(work.dot);
    for (const k in e) { const j = +k * 4; if (e[k] < 0) out.data.fill(0, j, j + 4); else { const c = PAL[e[k]].rgb; out.data[j] = c[0]; out.data[j + 1] = c[1]; out.data[j + 2] = c[2]; out.data[j + 3] = 255; } }
    out.layers = layers;
    return out;
  }

  // ---------- 규칙 알림(섞기가 다시 뽑는 기준) ----------
  function hintsOf(work) {
    const b = sbOf(work), zs = work.L.map(L => zOf(L, b));
    // 순서 알림은 '가장 긴 바른 순서'에서 빠진 층만
    const len = zs.map(() => 1), prev = zs.map(() => -1);
    zs.forEach((z, i) => { for (let j = 0; j < i; j++) if (zs[j] <= z && len[j] + 1 > len[i]) { len[i] = len[j] + 1; prev[i] = j; } });
    const ok = new Set(); for (let i = len.indexOf(Math.max(0, ...len)); i >= 0; i = prev[i]) ok.add(i);
    return work.L.map((L, i) => {
      const P = PARTS[L.p]; if (!P) return null;
      const ro = roleOf(P, b), Rr = ROLE[ro]; if (!Rr) return null;
      if (Rr.one) { const g = CONFLICT[ro] || [ro]; if (work.L.some((M, j) => j !== i && PARTS[M.p] && g.includes(roleOf(PARTS[M.p], b)))) return `${Rr.ko} 자리가 겹쳐요(하나만 두는 층)`; }
      const want = Rr.at[b];
      if (want === 'sc') { if (!L.sc && L.at !== 'on') return '보통은 흩뿌리기로 수관 위에 둬요'; }
      else if (want && L.at !== want) return `보통은 ‘${ANCHOR_KO[want]}’에 붙여요`;
      if ((L.at === 'ground' || L.at === 'feet') && L.y < -4) return '땅에서 떠 있어요';
      const z = zOf(L, b);
      if (ok.has(i)) return null;
      const j1 = work.L.findIndex((M, j) => j > i && zOf(M, b) < z), j2 = work.L.findIndex((M, j) => j < i && zOf(M, b) > z);
      if (j1 >= 0) return `보통은 ‘${PARTS[work.L[j1].p].label}’보다 앞이에요`;
      if (j2 >= 0) return `보통은 ‘${PARTS[work.L[j2].p].label}’보다 뒤예요`;
      return null;
    });
  }

  // ---------- 작품·층 기본값 ----------
  const LAYER_KEYS = ['p', 'm', 'c', 'pt', 'pa', 's', 'x', 'y', 'fl', 'mi', 'lk', 'sl', 'sc', 'at', 'cl', 'a'];
  const SHARE_KEYS = LAYER_KEYS.filter(k => k !== 'lk' && k !== 'sl');
  const WORK_KEYS = ['v', 'id', 'b', 'L', 'n', 'pub', 'seal', 'par', 'pseal', 'seed', 'dot', 'mv', 'parts', 'day'];
  const newLayer = (p, o = {}) => Object.assign({ p, m: 'o', c: [2, 3, 0], pt: 'none', pa: 'all', s: 1, x: W / 2, y: GROUND, fl: false, mi: false, lk: false, sl: [false, false, false], sc: 0, at: null, cl: false, a: firstAct(PARTS[p]) }, (o.at || o.sc) ? { x: 0, y: 0 } : {}, o);
  const newWork = (b, L = [], o = {}) => Object.assign({ v: 1, id: null, b, L, n: [0, 0, 0], pub: false, seal: null, par: null, pseal: null, seed: null, dot: null, mv: b === 'friend' ? 'walk' : null, parts: PARTS_VER, day: null }, o);
  const clone = o => JSON.parse(JSON.stringify(o));
  // 저장·전송 모양: 정해진 키만, 정해진 순서로, 빠진 값은 기본값
  function normalize(w) {
    const base = newWork(BENCHES.includes(w.b) ? w.b : 'tree');
    const o = {};
    WORK_KEYS.forEach(k => { o[k] = w[k] !== undefined ? clone(w[k]) : base[k]; });
    o.L = (Array.isArray(w.L) ? w.L : []).map(L => {
      const P = PARTS[L.p], d = P ? newLayer(L.p) : { p: L.p, m: 'o', c: [2, 3, 0], pt: 'none', pa: 'all', s: 1, x: W / 2, y: GROUND, fl: false, mi: false, lk: false, sl: [false, false, false], sc: 0, at: null, cl: false, a: '' };
      const n = {}; LAYER_KEYS.forEach(k => { n[k] = L[k] !== undefined ? clone(L[k]) : d[k]; });
      if (P && !P.acts[n.a]) n.a = firstAct(P);
      return n;
    });
    if (o.dot === '') o.dot = null;
    if (!validWords(o.n)) o.n = nameWords(o);
    return o;
  }

  // ---------- 검증(앱·서버 같음) ----------
  const isInt = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
  const isBool = v => v === true || v === false;
  const HEX8 = /^[0-9a-f]{8}$/;
  function validate(w) {
    const E = [];
    if (!w || typeof w !== 'object') return ['작품이 아님'];
    if (w.v !== 1) E.push('v');
    if (!(typeof w.id === 'string' && HEX8.test(w.id))) E.push('id');
    if (!BENCHES.includes(w.b)) E.push('b');
    const b = SB[w.b];
    if (!Array.isArray(w.L) || w.L.length > MAXL) E.push('L');
    else w.L.forEach((L, i) => {
      const P = L && PARTS[L.p], f = k => E.push(`L${i}.${k}`);
      if (!P) return f('p');
      if (b && !P.bench.includes(b)) f('p.bench');
      if (!MODES.some(m => m[0] === L.m)) f('m');
      if (!Array.isArray(L.c) || L.c.length !== 3 || !L.c.every(c => isInt(c, 0, 23))) f('c');
      if (!PATS.some(m => m[0] === L.pt)) f('pt');
      if (L.pa !== 'all' && L.pa !== 'band') f('pa');
      if (L.s !== 1) f('s');
      if (!isInt(L.x, -144, 288)) f('x');
      if (!isInt(L.y, -144, 288)) f('y');
      ['fl', 'mi', 'lk', 'cl'].forEach(k => { if (!isBool(L[k])) f(k); });
      if (!Array.isArray(L.sl) || L.sl.length !== 3 || !L.sl.every(isBool)) f('sl');
      if (!isInt(L.sc, 0, 8)) f('sc');
      if (L.at !== null && !AT_KINDS.includes(L.at)) f('at');
      if (typeof L.a !== 'string' || L.a.length > 16) f('a');
    });
    if (!validWords(w.n)) E.push('n');
    if (!isBool(w.pub)) E.push('pub');
    if (w.seal !== null && !(typeof w.seal === 'string' && w.seal.length <= 64)) E.push('seal');
    if (w.par !== null && !(typeof w.par === 'string' && HEX8.test(w.par))) E.push('par');
    if (w.pseal !== null && !(typeof w.pseal === 'string' && w.pseal.length <= 64)) E.push('pseal');
    if (w.seed !== null && !(typeof w.seed === 'string' && parseSeed(w.seed) && seedCode(parseSeed(w.seed).b, parseSeed(w.seed).th, parseSeed(w.seed).seed) === w.seed)) E.push('seed');
    if (w.dot !== null) { try { if (typeof w.dot !== 'string' || encodeDots(decodeDots(w.dot)) !== w.dot) E.push('dot'); } catch (e) { E.push('dot'); } }
    if (w.mv !== null && !(w.b === 'friend' && MOVES.includes(w.mv))) E.push('mv');
    if (!isInt(w.parts, 1, 9999)) E.push('parts');
    if (w.day !== null && !(typeof w.day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(w.day))) E.push('day');
    if (new TextEncoder().encode(JSON.stringify(w)).length > 4096) E.push('size');
    return E;
  }

  // ---------- 도트 고침 압축 ----------
  // 고친 픽셀마다 4글자(base64url): 번호(y·144+x) 3글자(큰 자리부터) + 색 1글자(0~23 = 팔레트, 24 = 지우기). 번호 오름차순, 없으면 null
  const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  function encodeDots(e) {
    const ks = Object.keys(e || {}).map(Number).sort((a, b) => a - b);
    if (!ks.length) return null;
    return ks.map(k => B64[k >> 12] + B64[(k >> 6) & 63] + B64[k & 63] + B64[e[k] < 0 ? 24 : e[k]]).join('');
  }
  function decodeDots(s) {
    const e = {};
    if (!s) return e;
    if (s.length % 4 || s.length / 4 > DOTCAP) throw new Error('dot');
    let last = -1;
    for (let i = 0; i < s.length; i += 4) {
      const v = [...s.slice(i, i + 4)].map(ch => B64.indexOf(ch));
      if (v.some(x => x < 0)) throw new Error('dot');
      const k = v[0] * 4096 + v[1] * 64 + v[2];
      if (k >= W * H || k <= last || v[3] > 24) throw new Error('dot');
      e[k] = v[3] === 24 ? -1 : v[3]; last = k;
    }
    return e;
  }

  // ---------- 무작위 만들기 ----------
  const SCHEMES = [['비슷한 색', [0, 30, -30]], ['보색', [0, 180, 25]], ['세 색', [0, 120, 240]]];
  function harmony(r, th) {
    const [name, offs] = r.pick(SCHEMES);
    const pool = th.pal ? th.pal.filter(i => CHROMA.includes(i)) : CHROMA;
    const b0 = r.pick(pool.length ? pool : CHROMA), h0 = PAL[b0].h;
    const near = h => { const inTheme = th.pal ? nearestHue(h, th.pal) : null; const all = nearestHue(h); return inTheme != null && hd(PAL[inTheme].h, h) < 50 ? inTheme : all; };
    const cols = offs.map((o, k) => k ? near((h0 + o + 360) % 360) : b0);
    // 세 칸이 겹치면 겹친 칸은 크림·구름 같은 밝은 색으로
    const soft = [1, 0, 10, 5].filter(i => !cols.includes(i));
    for (let k = 1; k < 3; k++) if (cols.indexOf(cols[k]) < k) cols[k] = soft.shift();
    return { name, cols };
  }
  const cols3 = (b, a) => [b, SHADE[b], a];
  const pW = P => P.vw, pH = P => P.vh;
  const groundy = P => !/shadow|dust|footprints/.test(P.id);
  // 역할 순서(z)대로 줄 세우되(같으면 원래 순서), 잠근 층은 원래 번호 자리에 그대로 둔다
  function arrangeKeep(b, L) {
    const out = L.map((l, i) => [l, i]).filter(([l]) => !l.lk).sort((a, c) => zOf(a[0], b) - zOf(c[0], b) || a[1] - c[1]).map(a => a[0]);
    L.forEach((l, i) => { if (l.lk) out.splice(Math.min(i, out.length), 0, l); });
    return out;
  }
  // 크기 비율은 배율이 아니라 '어울리는 크기의 부품 고르기'로 맞춘다. 비교는 모두 정수(10배·100배)로
  function rollOnce(bench, thi, seed) {
    const b = SB[bench], r = rng(seed), th = THEMES[thi], hm = harmony(r, th), [c0, c1, c2] = hm.cols, L = [];
    const all = () => Object.values(PARTS);
    const mode = (pm, ph) => { const x = r.u() * 100; return x < pm * 4294967296 ? 'map' : x < (pm + ph) * 4294967296 ? 'hue' : 'o'; };
    const pat = p => r.chance(p) ? r.pick(['stripe', 'dot', 'check', 'wave', 'spark']) : 'none';
    const pool = (roles, filt) => {
      const a = all().filter(P => P.bench.includes(b) && !P.noAuto && roles.includes(roleOf(P, b)) && (!filt || filt(P)));
      if (th.re) { const f = a.filter(P => P.th.includes(thi)); if (f.length && r.chance(75)) return f; }
      return a;
    };
    const pk = a => a.length ? r.pick(a) : null;
    const side = (lo, hi) => (r.chance(50) ? -1 : 1) * (lo + r.int(Math.max(1, hi - lo + 1)));
    const done = mv => ({ ...newWork(bench, arrangeKeep(b, L).slice(0, MAXL), { seed: seedCode(bench, thi, seed), mv }), scheme: hm.name, theme: thi });
    if (b === 't') {
      let whole = false, crownW = 60, tw = 30, th0 = 60;
      if (r.chance(10)) {
        whole = true; const t = r.pick(pool(['whole']));
        L.push(newLayer(t.id, { m: r.chance(40) ? 'o' : 'hue', c: cols3(r.pick([14, 13, 16, 15]), c1) }));
        crownW = pW(t); tw = 20;
      } else {
        const s = r.int(3), borrowT = r.chance(25), borrowC = (borrowT || s === 2) && r.chance(35);
        const wsT = all().filter(P => P.ws && P.role === 'trunk' && P.size === s);
        const trunk = borrowT ? r.pick(partsIn('t', '줄기').filter(P => P.crop)) : wsT.length && r.chance(50) ? r.pick(wsT) : PARTS[`lab-trunk-${s}`];
        const tb = thi === TH_ROBOT ? r.pick([21, 22]) : thi === TH_WINTER ? r.pick([11, 12, 21]) : r.pick([11, 12, 11, 9, 10]);
        L.push(newLayer(trunk.id, { m: r.chance(50) ? 'o' : 'map', c: cols3(tb, c2) }));
        tw = pW(trunk); th0 = pH(trunk);
        let crown;
        if (borrowC) crown = r.pick(pool(['crown'], P => P.crop));
        else { const s2 = borrowT ? 2 : Math.max(0, Math.min(2, s + (r.chance(30) ? r.pick([-1, 1]) : 0))); const wsC = all().filter(P => P.ws && P.role === 'crown' && P.wsz === 'sml'[s2]); crown = wsC.length && r.chance(50) ? r.pick(wsC) : PARTS[`lab-crown-${r.int(3)}-${s2}`]; }
        crownW = pW(crown);
        const green = th.re && thi !== TH_FOREST && r.chance(50) ? c0 : r.pick([13, 14, 15, 16, 14]);
        L.push(newLayer(crown.id, { at: 'trunk', m: r.chance(75) ? 'map' : 'hue', c: cols3(green, c1), pt: pat(22) }));
      }
      const fit = P => crownW < 45 ? P.wsz === 's' : crownW < 70 ? !!P.wsz : true;
      if (r.chance(whole ? 30 : 70)) { const bp = pool(['blossom'], fit), bl = r.pick(bp.length ? bp : pool(['blossom'])); L.push(newLayer(bl.id, { sc: 2 + r.int(4), m: r.chance(60) ? 'map' : 'o', c: cols3(r.pick([0, 1, 8, 5, 2, 18]), c2) })); }
      if (!whole || r.chance(30)) { const fp = pool(['fruit'], fit), fr = r.pick(fp.length ? fp : pool(['fruit'])); L.push(newLayer(fr.id, { sc: (crownW < 50 ? 2 : 3) + r.int(crownW < 50 ? 2 : 6), m: r.chance(55) ? 'hue' : 'map', c: cols3(c0 === L[L.length - 1].c[0] ? c1 : c0, c2) })); }
      if (r.chance(50)) { const g = pk(pool(['ground'], P => groundy(P) && 10 * pW(P) <= 12 * tw + 160 && 10 * pH(P) <= 6 * th0 + 40)); if (g) { const off = r100(45 * tw + 30 * pW(g)); L.push(newLayer(g.id, { at: 'ground', x: side(off, off + 8), m: r.chance(60) ? 'o' : 'hue', c: cols3(c1, c2) })); } }
      if (r.chance(20)) { const hg = pk(pool(['hang'], P => 10 * pW(P) <= 11 * crownW)); if (hg) L.push(newLayer(hg.id, { at: 'hang', m: r.chance(50) ? 'o' : 'map', c: cols3(c2, c0) })); }
      if (r.chance(30)) { const dc = pk(pool(['deco', 'sticker'], P => 10 * pW(P) <= 4 * crownW)); if (dc) L.push(newLayer(dc.id, { at: 'on', x: side(0, 14), y: side(0, 10), m: r.chance(60) ? 'o' : 'hue', c: cols3(c2, c0) })); }
      if (r.chance(25)) { const tp = pk(pool(['hat', 'above'], P => 10 * pW(P) <= 6 * crownW)); if (tp) L.push(newLayer(tp.id, { at: atOf(tp, 't'), m: r.chance(50) ? 'o' : 'hue', c: cols3(c2, c0) })); }
      return done(null);
    }
    if (b === 'f') {
      // 로봇 주제면 부품으로 로봇을 조립(다른 주제는 가끔)
      if (r.chance(thi === TH_ROBOT ? 60 : 12)) {
        const part = re => pk(all().filter(P => P.ws && re.test(P.ws)));
        const tor = part(/^body(box|barrel|egg)$/);
        L.push(newLayer(tor.id, { a: 'idle', m: mode(60, 20), c: cols3(c0, c1), pt: pat(20) }));
        L.push(newLayer(part(/^head/).id, { at: 'top', m: mode(60, 20), c: cols3(c0, c1) }));
        L.push(newLayer(part(/^(leg|wheel)/).id, { at: 'under', m: mode(50, 20), c: cols3(c1, c2) }));
        if (r.chance(70)) L.push(newLayer(part(/^arm/).id, { at: 'hand', m: mode(50, 20), c: cols3(c1, c2) }));
        if (r.chance(40)) L.push(newLayer(part(/^back/).id, { at: 'back', m: mode(50, 20), c: cols3(c2, c1) }));
        const face = part(/^eye(round|dot|happy|sparkle|wide)$/); // 로봇 얼굴은 중간 크기만
        const fm = all().find(P => P.ws === face.ws && P.wsz === 'm');
        if (r.chance(80) && fm) L.push(newLayer(fm.id, { at: 'top', y: -4, m: 'o' }));
        return done('walk');
      }
      const wsBodies = pool(['body'], P => P.ws && P.bench.includes('f'));
      const body = wsBodies.length && r.chance(50) ? r.pick(wsBodies) : r.pick(pool(['body']));
      const acts = Object.keys(body.acts), a = ['idle', 'sit', 'walk'].find(k => body.acts[k]) || acts[0];
      L.push(newLayer(body.id, { a, m: body.skin ? (r.chance(75) ? 'hue' : 'o') : mode(45, 35), c: cols3(c0, c1), pt: pat(30), fl: r.chance(20) }));
      const bh = pH(body), bw = pW(body);
      const same = P => !body.wsz || !P.wsz || P.wsz === body.wsz; // 공방 몸통에는 같은 크기 부품
      if (body.wsz) { // 얼굴: 눈은 거의 늘, 입·볼은 가끔(몸과 같은 크기 부품)
        const fz = (re, p, dy) => { if (!r.chance(p)) return; const f = pk(all().filter(P => P.role === 'face' && P.wsz === body.wsz && re.test(P.ws))); if (f) L.push(newLayer(f.id, { at: 'face', y: dy, m: 'o' })); };
        fz(/^eye/, 90, 0); fz(/^mouth/, 70, { s: 4, m: 5, l: 7 }[body.wsz]); fz(/^cheek/, 40, { s: 3, m: 4, l: 5 }[body.wsz]);
      }
      if (r.chance(35)) { const g = r.chance(40) ? PARTS['fx-shadow'] : pk(pool(['ground'], P => P.id !== 'fx-shadow' && !/footprints/.test(P.id) && 10 * pW(P) <= 15 * bw + 60 && 100 * pH(P) <= 35 * bh + 400)); if (g) L.push(newLayer(g.id, { at: 'feet', m: 'o', c: cols3(c1, c2) })); }
      if (r.chance(25)) { const bk = pk(pool(['back'], P => same(P) && 10 * pH(P) <= 8 * bh)); if (bk) L.push(newLayer(bk.id, { at: 'back', m: mode(30, 40), c: cols3(c2, c1) })); }
      if (r.chance(55)) { const hat = pk(pool(['hat'], P => same(P) && 100 * pH(P) <= Math.max(1100, 55 * bh) && 10 * pW(P) <= 11 * bw + 40)); if (hat) L.push(newLayer(hat.id, { at: 'head', m: mode(30, 40), c: cols3(c1, c2), pt: pat(20) })); }
      if (r.chance(40)) { const it = pk(pool(['hand'], P => same(P) && 10 * pH(P) <= Math.max(110, 5 * bh))); if (it) L.push(newLayer(it.id, { at: 'hand', m: mode(20, 30), c: cols3(c2, c0) })); }
      if (r.chance(25)) { const st = pk(pool(['sticker', 'deco'], P => 100 * pW(P) <= 55 * bw && 100 * pH(P) <= 55 * bh)); if (st) L.push(newLayer(st.id, { at: 'on', cl: true, m: 'map', c: cols3(c2, c1), x: side(0, 6), y: side(0, 4) })); }
      if (r.chance(30)) { const em = pk(pool(['above'], P => pH(P) <= Math.max(26, bh))); if (em) L.push(newLayer(em.id, { at: 'above', m: r.chance(60) ? 'o' : 'hue', c: cols3(c2, c0) })); }
      return done('walk');
    }
    const bottle = r.chance(thi === TH_SWEET ? 40 : 12);
    const wsP = pool(['prop'], P => !P.cat2 && P.ws), base = bottle ? r.pick(partsIn('p', '병')) : wsP.length && r.chance(50) ? r.pick(wsP) : r.pick(pool(['prop'], P => !P.cat2));
    const bw = pW(base), bh = pH(base);
    L.push(newLayer(base.id, { m: mode(50, 30), c: [c0, SHADE[c0], c2], pt: bottle ? pat(50) : pat(20), pa: bottle ? 'band' : 'all' }));
    if (r.chance(35)) { const g = pk(pool(['ground'], P => groundy(P) && 10 * pW(P) <= 9 * bw + 100 && 10 * pH(P) <= 5 * bh + 40)); if (g) L.push(newLayer(g.id, { at: 'ground', x: side(r100(30 * bw), r100(50 * bw) + 4), m: r.chance(60) ? 'o' : 'hue', c: cols3(c1, c2) })); }
    const n = r.int(3);
    for (let k = 0; k < n; k++) { const st = pk(pool(['sticker', 'deco'], P => 2 * pW(P) <= bw && 2 * pH(P) <= bh)); if (st) L.push(newLayer(st.id, { at: 'on', cl: r.chance(40), m: r.chance(70) ? 'o' : 'hue', c: cols3(k ? c1 : c2, c0), x: side(0, r100(30 * bw)), y: side(0, r100(25 * bh)) })); }
    if (r.chance(25)) { const em = pk(pool(['above'], P => 10 * pH(P) <= Math.max(260, 6 * bh))); if (em) L.push(newLayer(em.id, { at: 'above', m: 'o', c: cols3(c2, c0) })); }
    return done(null);
  }
  // 규칙을 어긴 조합이 나오면 같은 씨앗에서 정해진 순서로 다시 뽑는다(최대 6번, 마지막 것을 쓴다)
  function roll(bench, thi, seed) {
    let d;
    for (let k = 0; k < 6; k++) { d = rollOnce(bench, thi, mixSeed(seed, k)); if (hintsOf(d).every(h => !h)) break; }
    d.seed = seedCode(bench, thi, seed);
    d.n = nameWords(d);
    return d;
  }
  // 잠금 합치기: 잠근 층은 원래 번호 자리에, 잠근 색 칸은 같은 역할의 첫 새 층으로. 잠근 층과 겹치는 '하나만' 역할은 새로 뽑은 쪽을 버린다
  function mergeLocks(old, nu) {
    if (!old || old.b !== nu.b) return nu;
    const b = SB[nu.b], rl = l => roleOf(PARTS[l.p], b), locked = old.L.filter(l => l.lk && PARTS[l.p]);
    let any = locked.length > 0;
    old.L.forEach(l => { if (!l.lk && PARTS[l.p] && l.sl.some(Boolean)) { const t = nu.L.find(n => rl(n) === rl(l)); if (t) l.sl.forEach((on, k) => { if (on) { t.c[k] = l.c[k]; t.sl[k] = true; any = true; } }); } });
    const taken = new Set(locked.flatMap(l => ROLE[rl(l)] && ROLE[rl(l)].one ? (CONFLICT[rl(l)] || [rl(l)]) : []));
    const merged = nu.L.filter(n => !taken.has(rl(n))).slice(0, MAXL - locked.length);
    old.L.forEach((l, i) => { if (l.lk && PARTS[l.p]) merged.splice(Math.min(i, merged.length), 0, clone(l)); });
    nu.L = merged;
    if (any) { nu.locked = true; nu.seed = null; } // 잠금이 들어가면 씨앗만으로는 다시 만들 수 없다
    if (old.dot && locked.length) nu.dot = old.dot;
    nu.n = nameWords(nu);
    return nu;
  }
  // 섞기: 작업대·주제·씨앗(+ 잠금이 있는 지금 작품)
  const shuffle = (bench, thi, seed, base = null) => mergeLocks(base ? clone(base) : null, roll(bench, thi, seed));
  function mutate(d0, seed) {
    const r = rng(seed), d = clone(d0), b = SB[d.b]; d.seed = null;
    const free = d.L.map((L, i) => i).filter(i => !d.L[i].lk && PARTS[d.L[i].p]);
    if (!free.length) { d.why = '그대로'; return d; }
    const done = [];
    const trunk = d.L.find(L => PARTS[L.p] && roleOf(PARTS[L.p], b) === 'trunk'), smallTrunk = !!trunk && PARTS[trunk.p].size != null && PARTS[trunk.p].size < 2;
    for (let k = 0; k < 2; k++) {
      const L = d.L[r.pick(free)], P = PARTS[L.p], ro = roleOf(P, b);
      const op = r.pick(['color', 'color', 'color', 'part', 'part', 'pattern', 'size', 'flip', 'mode', 'count', 'move']);
      if (op === 'color') { const slot = [0, 1, 2].filter(s => !L.sl[s]); if (!slot.length) continue; const s = r.pick(slot); const h = (PAL[L.c[s]].h + r.pick([-40, -25, 25, 40, 180]) + 360) % 360; L.c[s] = nearestHue(h); if (s === 0 && !L.sl[1]) L.c[1] = SHADE[L.c[0]]; if (L.m === 'o') L.m = 'map'; done.push('색'); }
      else if (op === 'part') {
        const same = Object.values(PARTS).filter(Q => Q.bench.includes(b) && !Q.noAuto && roleOf(Q, b) === ro && Q.id !== P.id && (ro !== 'ground' || groundy(Q) || b === 'f'));
        if (!same.length) continue;
        const near = ['trunk', 'crown', 'body', 'prop', 'whole'].includes(ro) ? same : same.filter(Q => 10 * pH(Q) <= 14 * pH(P) + 60 && 2 * pH(Q) >= pH(P));
        const Q = near.length ? r.pick(near) : null; if (!Q || (ro === 'crown' && Q.crop && smallTrunk)) continue;
        L.p = Q.id; L.a = ['idle', 'sit', 'walk'].find(a => Q.acts[a]) || firstAct(Q);
        done.push('부품');
      }
      else if (op === 'pattern') { L.pt = r.pick(PATS.map(p => p[0]).filter(p => p !== L.pt)); done.push('무늬'); }
      else if (op === 'move' && !['crown', 'trunk', 'whole'].includes(ro)) { L.x += r.pick([-6, -4, 4, 6]); if (ro !== 'ground') L.y += r.pick([-4, 0, 4]); done.push('자리'); }
      else if (op === 'size' && P.sz) { L.p = r.pick(P.sz.g.filter(id => id !== P.id)); if (!PARTS[L.p].acts[L.a]) L.a = firstAct(PARTS[L.p]); done.push('크기'); }
      else if (op === 'flip') { L.fl = !L.fl; done.push('뒤집기'); }
      else if (op === 'mode') { L.m = r.pick(MODES.map(m => m[0]).filter(m => m !== L.m)); done.push('칠하기'); }
      else if (op === 'count' && L.sc) { L.sc = Math.max(1, Math.min(8, L.sc + r.pick([-2, -1, 1, 2]))); done.push('개수'); }
    }
    d.L = arrangeKeep(b, d.L);
    d.why = done.join('·') || '그대로';
    d.n = nameWords(d);
    return d;
  }
  // 변이 여섯: 씨앗 하나에서 mixSeed(seed, 0..5)
  const mutations = (work, seed) => [0, 1, 2, 3, 4, 5].map(k => mutate(work, mixSeed(seed, k)));

  // ---------- 품종 교배(W5, 확률 없음) ----------
  // h = fnv1a32(작은 id + 큰 id). 비트 0 = 뼈대(줄기·통나무·수관 묶음), 비트 k = CROSS_ROLES[k]. 0 이면 작은 id 부모, 1 이면 큰 id 부모
  const CROSS_ROLES = ['frame', 'blossom', 'fruit', 'ground', 'hang', 'deco', 'sticker', 'hat', 'above'];
  function crossTrees(a, b) {
    const [A, B] = a.id < b.id ? [a, b] : [b, a], h = fnv1a32(A.id + B.id);
    const group = ro => ['trunk', 'whole', 'crown'].includes(ro) ? 'frame' : ro;
    const L = [];
    CROSS_ROLES.forEach((g, k) => { const src = (h >>> k) & 1 ? B : A; src.L.forEach(l => { const P = PARTS[l.p]; if (P && group(roleOf(P, 't')) === g) L.push(Object.assign(clone(l), { lk: false, sl: [false, false, false] })); }); });
    const child = newWork('tree', arrangeKeep('t', L).slice(0, MAXL), { id: fnv1a32(A.id + B.id + '+').toString(16).padStart(8, '0'), par: A.id, pseal: A.seal || null });
    child.n = nameWords(child);
    return child;
  }

  // ---------- 작품 이름: n = [꾸밈말, 색, 이름] 낱말 번호(언어와 무관) ----------
  // 표는 덧붙이기만 한다(저장된 작품이 번호로 가리킨다). 빈 칸 = 0(색·이름 표의 0번이 빈 낱말)
  const NAME_ADJ = [['말랑', 'Squishy'], ['새콤', 'Zesty'], ['포근', 'Cozy'], ['반짝', 'Sparkly'], ['동글', 'Roundy'], ['살랑', 'Breezy'], ['뽀득', 'Squeaky'], ['보송', 'Fluffy'], ['아삭', 'Crunchy'], ['달콤', 'Sweet'], ['몽글', 'Puffy'], ['총총', 'Twinkly']];
  // 1 + 팔레트 번호. 한국어는 '…빛'
  const NAME_COLOR = [['', ''], ['구름빛', 'Cloud'], ['크림빛', 'Cream'], ['레몬빛', 'Lemon'], ['해바라기빛', 'Sunflower'], ['귤빛', 'Tangerine'], ['살구빛', 'Apricot'], ['산호빛', 'Coral'], ['체리빛', 'Cherry'], ['딸기우유빛', 'Strawberry Milk'], ['벽돌빛', 'Brick'], ['모래빛', 'Sand'], ['나무빛', 'Wood'], ['초코빛', 'Cocoa'], ['연두빛', 'Lime Green'], ['잎새빛', 'Leaf'], ['숲빛', 'Forest'], ['민트빛', 'Mint'], ['청록빛', 'Teal'], ['하늘빛', 'Sky'], ['파랑빛', 'Blue'], ['밤바다빛', 'Night Sea'], ['돌빛', 'Stone'], ['먹빛', 'Ink'], ['숯빛', 'Charcoal']];
  const NAME_NOUN = [['', ''], ['동글', 'Round'], ['뾰족', 'Spiky'], ['보송', 'Downy'], ['유레카', 'Eureka'], ['마이어', 'Meyer'], ['분홍 레몬', 'Pink Lemon'], ['라임', 'Lime'], ['유자', 'Yuzu'], ['금귤', 'Kumquat'], ['불수감', "Buddha's Hand"], ['깔라만시', 'Calamansi'], ['천혜향', 'Cheonhye'], ['한라봉', 'Hallabong'], ['레드향', 'Red Hyang'], ['자몽', 'Grapefruit'], ['포멜로', 'Pomelo'], ['베르가못', 'Bergamot'], ['블러드 오렌지', 'Blood Orange'], ['핑거라임', 'Finger Lime'], ['황금 레몬', 'Golden Lemon'], ['달 레몬', 'Moon Lemon'], ['무지개 레몬', 'Rainbow Lemon'], ['눈 유자', 'Snow Yuzu'], ['탱자', 'Trifoliate'],
    ['두발이', 'Biped'], ['동글이', 'Blob'], ['구름봇', 'Cloudbot'], ['길쭉이', 'Longbody'], ['네발이', 'Quad'], ['로봇', 'Robot'], ['말랑이', 'Slime'], ['통 몸', 'Barrel Bot'], ['네모 몸', 'Box Bot'], ['알 몸', 'Egg Bot'], ['통', 'Barrel'], ['벤치', 'Bench'], ['병', 'Bottle'], ['수레', 'Cart'], ['상자', 'Crate'], ['컵', 'Cup'], ['분수', 'Fountain'], ['가로등', 'Lamppost'], ['우체통', 'Mailbox'], ['화단', 'Planter'], ['간판', 'Sign'], ['공', 'Ball'], ['불꽃', 'Flame'], ['하트', 'Heart'], ['세 송이', 'Triple Puff'], ['우산', 'Umbrella'], ['늘어진', 'Weeping'],
    ['강아지', 'Puppy'], ['고양이', 'Cat'], ['양', 'Sheep'], ['돼지', 'Pig'], ['젖소', 'Cow'], ['닭', 'Chicken'], ['오리', 'Duck'], ['아기오리', 'Duckling'], ['거위', 'Goose'], ['송아지', 'Calf'], ['손님', 'Guest'], ['심는 일꾼', 'Planter Helper'], ['따는 일꾼', 'Picker'], ['돌보는 일꾼', 'Caretaker'], ['가게 일꾼', 'Shopkeeper'], ['집배원', 'Mail Carrier'], ['방물장수', 'Peddler'], ['구경꾼', 'Visitor'], ['아기양', 'Lamb'], ['꿀벌', 'Bee'], ['게', 'Crab'], ['갈매기', 'Gull'], ['소라게', 'Hermit Crab'], ['도요새', 'Sandpiper'], ['참새', 'Sparrow'], ['불가사리', 'Starfish'], ['거북', 'Turtle'], ['꼬물이', 'Wiggly Worm'], ['토끼', 'Rabbit'], ['무당벌레', 'Ladybug'], ['나비', 'Butterfly'], ['문어', 'Octopus'], ['수달', 'Otter'], ['돌고래', 'Dolphin'], ['해마', 'Seahorse'], ['복어', 'Pufferfish'], ['해파리', 'Jellyfish'], ['도미', 'Sea Bream'], ['노랑 물고기', 'Yellow Fish'], ['새', 'Bird'], ['눈사람', 'Snowman'], ['광대 인형', 'Jester Doll'], ['허수아비', 'Scarecrow'], ['손님 수레', 'Guest Cart'], ['트럭', 'Truck'], ['건전지', 'Battery'], ['깜짝 상자', 'Jack-in-the-Box'], ['구름', 'Cloud'],
    ['꽃 아치', 'Flower Arch'], ['바구니 금', 'Golden Basket'], ['벌통', 'Beehive'], ['새집', 'Birdhouse'], ['말풍선', 'Speech Bubble'], ['레드카펫', 'Red Carpet'], ['보물 상자', 'Treasure Chest'], ['박수 깃발', 'Clap Flag'], ['빨랫줄', 'Clothesline'], ['커피', 'Coffee'], ['커피 수레', 'Coffee Cart'], ['개집', 'Doghouse'], ['화분', 'Flowerpots'], ['액자', 'Frame'], ['친구 벤치', 'Friend Bench'], ['선물 바구니', 'Gift Basket'], ['항아리', 'Jar'], ['스승 깃발', 'Mentor Flag'], ['한 접시', 'One Plate'], ['소풍 자리', 'Picnic Spot'], ['명패', 'Plaque'], ['순위 깃발', 'Rank Flag'], ['순위 깃발 금', 'Gold Rank Flag'], ['자루', 'Sack'], ['자루들', 'Sacks'], ['묘목', 'Sapling'], ['인장 깃발', 'Seal Flag'], ['이정표', 'Signpost'], ['송편', 'Songpyeon'], ['가판대', 'Stand'], ['별 깃발', 'Star Flag'], ['장작', 'Firewood'], ['석등', 'Stone Lantern'], ['할 일 판', 'Task Board'], ['트로피 금', 'Gold Trophy'], ['트로피', 'Trophy'], ['떡국', 'Tteokguk'], ['마을 깃발', 'Village Flag'], ['방명록함', 'Guestbook Box'], ['우물', 'Well'], ['손수레', 'Wheelbarrow'], ['풍차', 'Windmill'], ['등불', 'Lantern'], ['사탕', 'Candy'], ['단지', 'Crocks'], ['말림대', 'Drying Rack'], ['선반', 'Shelf'], ['깃발', 'Flag'], ['콩 지지대', 'Bean Teepee'], ['새 기둥', 'Bird Pole'], ['물통', 'Water Can'], ['코스모스', 'Cosmos'], ['접시꽃', 'Hollyhock'], ['레몬 간판', 'Lemon Sign'], ['바람개비', 'Pinwheel'], ['호박', 'Pumpkins'], ['씨앗 판', 'Seed Stand'], ['해바라기', 'Sunflower'], ['온실', 'Greenhouse'], ['우유 단지', 'Milk Churns'], ['건초', 'Hay Bale'], ['건초 더미', 'Haystack'], ['여물통', 'Trough'], ['풍향계', 'Weathervane'], ['털 바구니', 'Wool Basket'], ['치즈 탁자', 'Cheese Table'], ['부표', 'Buoy'], ['모래성', 'Sandcastle'], ['오두막', 'Cottage'], ['파라솔', 'Parasol'], ['수건', 'Towel'], ['돛단배', 'Sailboat'], ['산호', 'Coral'], ['부표 줄', 'Float Line'], ['아이스박스', 'Icebox'], ['나룻배', 'Rowboat']];
  // 작업대 꼬리(품종대는 늘 붙임)·이름이 빈 친구·소품의 대신 낱말
  const NAME_BENCH = { tree: ['나무', 'Tree'], friend: ['친구', 'Friend'], prop: ['소품', 'Trinket'] };
  const MAIN_ROLES = ['body', 'crown', 'prop', 'whole'];
  // 부품 → 이름 낱말 번호(nw). 주인공이 될 수 있는 역할만, 표에 없으면 0
  const nounKey = l => l.replace(/\(빌림\)/, '').replace(/ [A-C]$/, '').trim().replace(/ (작게|중간|크게)$/, '').replace(/^수관 /, '').replace(/ ?수관$/, '').replace(/ 나무$/, '').replace(/( [a-z0-9]+)+$/, '').trim();
  const nounIndex = P => { if (!MAIN_ROLES.includes(P.role)) return 0; const k = nounKey(P.label), i = NAME_NOUN.findIndex(w => w[0] === k); return i > 0 ? i : 0; };
  // 낱말 번호: 꾸밈말 = 층 [p, c] JSON 해시 % 12, 색 = 주인공이 원래 색이 아니면 1 + 바탕 칸, 이름 = 주인공 부품의 nw
  function nameWords(d) {
    const L0 = d.L.filter(L => PARTS[L.p]);
    const main = L0.find(L => MAIN_ROLES.includes(PARTS[L.p].role)) || L0[0];
    const h = [...JSON.stringify(d.L.map(L => [L.p, L.c]))].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) >>> 0, 7);
    return [h % NAME_ADJ.length, main && main.m !== 'o' ? 1 + main.c[0] : 0, main ? PARTS[main.p].nw : 0];
  }
  const validWords = n => Array.isArray(n) && n.length === 3 && n.every(x => isInt(x, 0, 999));
  // 이름 글자: lang 'ko'(기본) 또는 'en'. 표에 없는 번호(새 판의 낱말)는 빈 낱말로
  function nameOf(d, lang = 'ko') {
    const n = validWords(d.n) ? d.n : nameWords(d), q = lang === 'en' ? 1 : 0, w = (T, i) => (T[i] || ['', ''])[q];
    const bench = NAME_BENCH[d.b] || NAME_BENCH.prop;
    let noun = w(NAME_NOUN, n[2]);
    if (d.b === 'tree') noun = [noun, bench[q]].filter(Boolean).join(' '); else if (!noun) noun = bench[q];
    return [w(NAME_ADJ, n[0]), w(NAME_COLOR, n[1]), noun].filter(Boolean).join(' ');
  }

  // ---------- 나눔 코드 LD1 ----------
  // 'LD1.' + base64url(deflate-raw(UTF-8 JSON)), JSON = {v,id,b,L:[층 배열 SHARE_KEYS 순서],n,seal,par,pseal,seed,dot,mv,parts,day} (pub·lk·sl 은 빼고 보낸다)
  const shareJSON = w => { const o = {}; WORK_KEYS.forEach(k => { if (k !== 'pub') o[k] = k === 'L' ? w.L.map(L => SHARE_KEYS.map(s => L[s])) : (w[k] === undefined ? null : w[k]); }); return o; };
  const fromShareJSON = o => normalize(Object.assign({}, o, { pub: false, L: (o.L || []).map(a => Object.fromEntries(SHARE_KEYS.map((k, i) => [k, a[i]]))).filter(L => PARTS[L.p]) }));
  async function pipe(bytes, stream) { return new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(stream)).arrayBuffer()); }
  async function encodeShare(w) {
    const buf = await pipe(new TextEncoder().encode(JSON.stringify(shareJSON(normalize(w)))), new CompressionStream('deflate-raw'));
    let s = ''; for (const x of buf) s += String.fromCharCode(x);
    return 'LD1.' + btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  async function decodeShare(code) {
    const t = String(code).trim(); if (!t.startsWith('LD1.')) throw new Error('LD1');
    const b = atob(t.slice(4).replace(/-/g, '+').replace(/_/g, '/'));
    const raw = await pipe(Uint8Array.from(b, ch => ch.charCodeAt(0)), new DecompressionStream('deflate-raw'));
    return fromShareJSON(JSON.parse(new TextDecoder().decode(raw)));
  }

  return {
    W, H, GROUND, MAXL, DOTCAP, PARTS_VER, BENCHES, SB, PAL, CHROMA, SHADE, DEEP, LIGHT, THEMES, ROLE, CONFLICT, ANCHOR_KO, AT_KINDS, MODES, PATS, MOVES, SCHEMES, LAYER_KEYS, SHARE_KEYS, WORK_KEYS,
    PARTS, get ANCHORS() { return ANCHORS; }, setCatalog, labelOf,
    rng, mixSeed, seedCode, parseSeed, fnv1a32, hsvI, hsvToRgbI, nearestHue, shadeOf,
    roleOf, zOf, atOf, catOf, partsIn, actOf, firstAct,
    layerSource, bbox, recolor, pattern, patHit, compose, hintsOf,
    newLayer, newWork, normalize, validate, clone, encodeDots, decodeDots,
    arrangeKeep, rollOnce, roll, mergeLocks, shuffle, mutate, mutations, crossTrees, nameOf, nameWords, NAME_ADJ, NAME_COLOR, NAME_NOUN, NAME_BENCH,
    shareJSON, fromShareJSON, encodeShare, decodeShare,
  };
});

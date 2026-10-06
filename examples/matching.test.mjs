/** Eğitim amaçlı örnek testleridir; gerçek mevzuat kurallarını doğrulamaz. */
import test from "node:test";
import assert from "node:assert/strict";
import { canonicalRoute, discoverMatches, REVIEW } from "./matching.mjs";

const NOW = "2026-10-06T09:00:00.000Z";
const LATER = "2026-12-01T00:00:00.000Z";
const location = (provinceId, districtId = `${provinceId}-center`) => ({ provinceId, districtId });
const target = (provinceId, districtId) => ({ provinceId, ...(districtId && { districtId }) });

function ad(id, provinceId, targets, overrides = {}) {
  return {
    id, ownerId: `owner-${id}`, institutionId: "institution-1",
    titleId: "title-1", employmentType: "4B", status: "ACTIVE",
    expiresAt: LATER, version: 1, profileVersion: 1,
    current: location(provinceId), targets: targets.map(value =>
      typeof value === "string" ? target(value) : value),
    ...overrides,
  };
}

const eligible = {
  now: NOW, legalReview: () => REVIEW.ELIGIBLE,
  groupReview: () => REVIEW.ELIGIBLE,
};
const pair = () => [ad("a", "34", ["06"]), ad("b", "06", ["34"])];
const cycle = () => [
  ad("a", "34", ["06"]), ad("b", "06", ["35"]), ad("c", "35", ["34"]),
];

test("İkili karşılıklılık bir öneri üretir; tercih puanı hukuk durumundan ayrıdır", () => {
  const result = discoverMatches(pair(), eligible);
  assert.equal(result.length, 1);
  assert.deepEqual(result[0].route, ["a", "b"]);
  assert.equal(result[0].kind, 2);
  assert.equal(result[0].preferenceScore, 100);
  assert.equal(result[0].legalStatus, "eligible");
  assert.equal(result[0].requiresReview, false);
});

test("İl hedefi ilçeyi kapsar; ilçe hedefi yalnızca belirtilen ilçeyi kapsar", () => {
  const ads = pair();
  ads[1].current = location("06", "06-cankaya");
  assert.equal(discoverMatches(ads, eligible).length, 1);
  ads[0].targets = [target("06", "06-kecioren")];
  assert.equal(discoverMatches(ads, eligible).length, 0);
  ads[0].targets = [target("06", "06-cankaya")];
  assert.equal(discoverMatches(ads, eligible).length, 1);
});

test("Çoklu ve yinelenen hedefler rotaları çoğaltmaz; tek yön eşleşme üretmez", () => {
  const ads = pair();
  ads[0].targets = [target("35"), target("06"), target("06")];
  assert.equal(discoverMatches(ads, eligible).length, 1);
  ads[1].targets = [target("16")];
  assert.deepEqual(discoverMatches(ads, eligible), []);
});

test("Kapalı üçlü döngü tek öneridir; eksik kapanış kenarı öneri üretmez", () => {
  const ads = cycle();
  const result = discoverMatches(ads, eligible);
  assert.equal(result.length, 1);
  assert.equal(result[0].kind, 3);
  assert.deepEqual(result[0].route, ["a", "b", "c"]);
  ads[2].targets = [target("16")];
  assert.deepEqual(discoverMatches(ads, eligible), []);
});

test("Aynı üç katılımcının iki ters yönlü rotası ayrı kalır; rotasyonlar birleşir", () => {
  const ads = [
    ad("a", "34", ["06", "35"]),
    ad("b", "06", ["34", "35"]),
    ad("c", "35", ["34", "06"]),
  ];
  const triples = discoverMatches(ads, eligible).filter(match => match.kind === 3);
  assert.deepEqual(triples.map(match => match.route), [["a", "b", "c"], ["a", "c", "b"]]);
  assert.notEqual(triples[0].matchKey, triples[1].matchKey);
  assert.deepEqual(canonicalRoute(["b", "c", "a"]), ["a", "b", "c"]);
  assert.deepEqual(canonicalRoute(["c", "b", "a"]), ["a", "c", "b"]);
});

test("Üçlü grup değerlendirmesi varsayılan unknown; açık grup incelemesi gerekir", () => {
  const options = { now: NOW, legalReview: () => REVIEW.ELIGIBLE };
  const result = discoverMatches(cycle(), options);
  assert.equal(result[0].legalStatus, "unknown");
  assert.equal(result[0].review.group, "unknown");
  assert.equal(result[0].preferenceScore, 100);
  assert.equal(result[0].requiresReview, true);
  assert.equal(discoverMatches(pair(), options)[0].legalStatus, "eligible");
});

test("Bilinmeyen bireysel değerlendirme koşullu kalır; ineligible katılımcı elenir", () => {
  const ads = pair();
  const unknown = discoverMatches(ads, {
    ...eligible, legalReview: person => person.id === "a" ? REVIEW.UNKNOWN : REVIEW.ELIGIBLE,
  });
  assert.equal(unknown[0].legalStatus, "unknown");
  assert.equal(unknown[0].requiresReview, true);
  assert.equal(discoverMatches(ads, { now: NOW })[0].legalStatus, "unknown");
  const rejected = discoverMatches(ads, {
    ...eligible, legalReview: person => person.id === "a" ? REVIEW.INELIGIBLE : REVIEW.ELIGIBLE,
  });
  assert.deepEqual(rejected, []);
});

test("Grup ineligible ise öneri elenir; callback yönlü rotayı alır ve bir kez çağrılır", () => {
  let calls = 0;
  const result = discoverMatches(cycle(), {
    ...eligible,
    groupReview: (members, context) => {
      calls += 1;
      assert.deepEqual(members.map(member => member.id), ["a", "b", "c"]);
      assert.deepEqual(context.route, ["a", "b", "c"]);
      assert.equal(context.kind, 3);
      return REVIEW.INELIGIBLE;
    },
  });
  assert.equal(calls, 1);
  assert.deepEqual(result, []);
});

test("Kapalı, tam sınırda süresi biten ve geçersiz süreli ilanlar önerilmez", () => {
  for (const overrides of [
    { status: "CLOSED" },
    { expiresAt: NOW },
    { expiresAt: "2026-10-05T00:00:00.000Z" },
    { expiresAt: "invalid-date" },
  ]) {
    const ads = pair();
    Object.assign(ads[1], overrides);
    assert.deepEqual(discoverMatches(ads, eligible), []);
  }
});

test("Aynı sahibi içeren ikili veya üçlü rota yasaktır", () => {
  const two = pair();
  two[1].ownerId = two[0].ownerId;
  assert.deepEqual(discoverMatches(two, eligible), []);
  const three = cycle();
  three[2].ownerId = three[0].ownerId;
  assert.deepEqual(discoverMatches(three, eligible), []);
});

test("Kurum, unvan ve istihdam eşitliği teknik ön eleme olarak uygulanır", () => {
  for (const field of ["institutionId", "titleId", "employmentType"]) {
    const ads = pair();
    ads[1][field] = "different";
    assert.deepEqual(discoverMatches(ads, eligible), []);
  }
});

test("Snapshot kaynak sürümlerini taşır; sürüm değişimi ve rota yönü anahtarı değiştirir", () => {
  const ads = pair();
  const options = { ...eligible, rulesetVersion: "rules-2026-10" };
  const original = discoverMatches(ads, options)[0];
  assert.deepEqual(original.snapshot, {
    rulesetVersion: "rules-2026-10",
    participants: [
      { adId: "a", ownerId: "owner-a", adVersion: 1, profileVersion: 1 },
      { adId: "b", ownerId: "owner-b", adVersion: 1, profileVersion: 1 },
    ],
  });
  assert.equal(discoverMatches([...ads].reverse(), options)[0].matchKey, original.matchKey);
  ads[0].version += 1;
  assert.notEqual(discoverMatches(ads, options)[0].matchKey, original.matchKey);
  ads[0].version -= 1;
  ads[1].profileVersion += 1;
  assert.notEqual(discoverMatches(ads, options)[0].matchKey, original.matchKey);
  ads[1].profileVersion -= 1;
  assert.notEqual(discoverMatches(ads, { ...options, rulesetVersion: "rules-next" })[0].matchKey,
    original.matchKey);
  assert.equal(original.snapshot.participants[1].profileVersion, 1);
});

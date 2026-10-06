/**
 * Eğitim amaçlı, bağımsız Node.js örneğidir; gerçek bir mevzuat/rules engine değildir.
 * Kurum, unvan ve istihdam eşitliği yalnızca bu demonun teknik ön elemesidir.
 * %100 puanı kapalı döngüdeki yer tercihlerinin karşılandığını gösterir;
 * hukuki uygunluğu veya kurum onayını göstermez. Üçlü öneriler varsayılan olarak
 * ayrıca incelenmesi gereken "unknown" hukuki durumuyla oluşturulur.
 *
 * Ad biçimi:
 * { id, ownerId, institutionId, titleId, employmentType, status: "ACTIVE",
 *   expiresAt: ISO8601, version: pozitif tamsayı, profileVersion: pozitif tamsayı,
 *   current: { provinceId, districtId },
 *   targets: [{ provinceId, districtId?: string, priority?: pozitif tamsayı }] }
 *
 * A -> B: A, B'nin mevcut yerine gitmek istiyor. Eksik hedef districtId,
 * ilgili ilin tüm ilçelerini kapsar. İlan sahibinin kimliği ve kesin birimi
 * bu örneğin sonucundan doğrudan kamuya açılmamalıdır; DTO redaksiyonu gerekir.
 */
import { createHash } from "node:crypto";

export const REVIEW = Object.freeze({
  ELIGIBLE: "eligible",
  INELIGIBLE: "ineligible",
  UNKNOWN: "unknown",
});

const reviewValues = new Set(Object.values(REVIEW));
const compareText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const nonemptyString = value => typeof value === "string" && value.length > 0;

function checkReview(value, callbackName) {
  if (!reviewValues.has(value)) {
    throw new TypeError(`${callbackName} must return eligible, ineligible or unknown`);
  }
  return value;
}

function validateAd(ad) {
  for (const field of ["id", "ownerId", "institutionId", "titleId", "employmentType"]) {
    if (!nonemptyString(ad?.[field])) throw new TypeError(`Invalid ad.${field}`);
  }
  for (const field of ["version", "profileVersion"]) {
    if (!Number.isSafeInteger(ad[field]) || ad[field] < 1) {
      throw new TypeError(`Invalid ad.${field}`);
    }
  }
  if (!nonemptyString(ad.current?.provinceId) || !nonemptyString(ad.current?.districtId)) {
    throw new TypeError("Current provinceId and districtId are required");
  }
  if (!Array.isArray(ad.targets) || ad.targets.length === 0) {
    throw new TypeError("At least one target is required");
  }
  for (const target of ad.targets) {
    if (!nonemptyString(target.provinceId) ||
        (target.districtId != null && !nonemptyString(target.districtId)) ||
        (target.priority != null &&
         (!Number.isSafeInteger(target.priority) || target.priority < 1))) {
      throw new TypeError("Invalid target");
    }
  }
}

export function wants(a, b) {
  return a.targets.some(target =>
    target.provinceId === b.current.provinceId &&
    (target.districtId == null || target.districtId === b.current.districtId)
  );
}

function technicallyCompatible(a, b) {
  return a.ownerId !== b.ownerId &&
    a.institutionId === b.institutionId &&
    a.titleId === b.titleId &&
    a.employmentType === b.employmentType;
}

/** Rotasyonları birleştirir, yönü tersine çevirmez. */
export function canonicalRoute(route) {
  if (!Array.isArray(route) || route.length < 2 ||
      new Set(route).size !== route.length || !route.every(nonemptyString)) {
    throw new TypeError("Route must contain distinct ad IDs");
  }
  let best = [...route];
  for (let start = 1; start < route.length; start += 1) {
    const candidate = [...route.slice(start), ...route.slice(0, start)];
    for (let i = 0; i < route.length; i += 1) {
      const comparison = compareText(candidate[i], best[i]);
      if (comparison < 0) best = candidate;
      if (comparison !== 0) break;
    }
  }
  return best;
}

/**
 * Callback'ler senkron olmalıdır. Gerçek uygulamada gerekli veriler önceden
 * yüklenir; sürümlenmiş kurallar ve transaction içi kabul kontrolü kullanılır.
 * legalReview(ad, context): tek katılımcının uygunluk değerlendirmesi.
 * groupReview(members, context): yönlü rotanın/grubun uygunluk değerlendirmesi.
 * Açıkça ineligible olan katılımcı/grup önerilmez; unknown koşullu kalır.
 *
 * Bu sade örnek kenarları O(V²) kurar. Üretimde kurum/unvan bölümlendirmesi ve
 * il/ilçe indeksleriyle aday üretimi daraltılmalıdır. Döngü keşfi ikilide O(E),
 * üçlüde O(sum indegree(v) * outdegree(v)); yoğun grafikte O(V³) olur.
 */
export function discoverMatches(ads, {
  now = new Date(),
  rulesetVersion = "demo-v1",
  legalReview = () => REVIEW.UNKNOWN,
  groupReview = (_members, context) =>
    context.kind === 3 ? REVIEW.UNKNOWN : REVIEW.ELIGIBLE,
} = {}) {
  if (!Array.isArray(ads)) throw new TypeError("ads must be an array");
  const nowMs = new Date(now).getTime();
  if (!Number.isFinite(nowMs)) throw new TypeError("Invalid now");
  if (!nonemptyString(rulesetVersion)) throw new TypeError("Invalid rulesetVersion");

  const byId = new Map();
  const memberReviews = new Map();
  const context = { now: new Date(nowMs).toISOString(), rulesetVersion };

  for (const ad of ads) {
    validateAd(ad);
    if (byId.has(ad.id)) throw new TypeError(`Duplicate ad ID: ${ad.id}`);
    // Kimlik tekrarlarını, aktif olmayan ilanlar için de reddet.
    byId.set(ad.id, ad);
  }

  const active = [...byId.values()].filter(ad =>
    ad.status === "ACTIVE" && Number.isFinite(new Date(ad.expiresAt).getTime()) &&
    new Date(ad.expiresAt).getTime() > nowMs
  );
  for (const ad of active) {
    memberReviews.set(ad.id, checkReview(legalReview(ad, context), "legalReview"));
  }
  const candidates = active.filter(ad => memberReviews.get(ad.id) !== REVIEW.INELIGIBLE);
  const adj = new Map(candidates.map(ad => [ad.id, new Set()]));

  for (const a of candidates) {
    for (const b of candidates) {
      if (a.id !== b.id && technicallyCompatible(a, b) && wants(a, b)) {
        adj.get(a.id).add(b.id);
      }
    }
  }

  const seenRoutes = new Set();
  const matches = [];

  function emit(rawRoute) {
    const route = canonicalRoute(rawRoute);
    const routeKey = JSON.stringify(route);
    if (seenRoutes.has(routeKey)) return;
    seenRoutes.add(routeKey);

    const members = route.map(id => byId.get(id));
    if (new Set(members.map(ad => ad.ownerId)).size !== route.length) return;
    const group = checkReview(groupReview(members, {
      ...context, kind: route.length, route: [...route],
    }), "groupReview");
    if (group === REVIEW.INELIGIBLE) return;

    const legalStatus = group === REVIEW.UNKNOWN ||
      route.some(id => memberReviews.get(id) === REVIEW.UNKNOWN)
      ? REVIEW.UNKNOWN : REVIEW.ELIGIBLE;
    const snapshot = {
      rulesetVersion,
      participants: members.map(ad => ({
        adId: ad.id, ownerId: ad.ownerId,
        adVersion: ad.version, profileVersion: ad.profileVersion,
      })),
    };
    const matchKey = createHash("sha256")
      .update(JSON.stringify({ route, snapshot })).digest("hex");

    matches.push({
      matchKey,
      kind: route.length,
      route,
      preferenceScore: 100,
      legalStatus,
      requiresReview: legalStatus === REVIEW.UNKNOWN,
      review: {
        members: route.map(adId => ({ adId, status: memberReviews.get(adId) })),
        group,
      },
      snapshot,
    });
  }

  for (const [aId, outgoing] of adj) {
    for (const bId of outgoing) {
      if (adj.get(bId).has(aId)) emit([aId, bId]);
      for (const cId of adj.get(bId)) {
        if (cId !== aId && cId !== bId && adj.get(cId).has(aId)) {
          emit([aId, bId, cId]);
        }
      }
    }
  }

  return matches.sort((a, b) => a.kind - b.kind ||
    compareText(JSON.stringify(a.route), JSON.stringify(b.route)));
}

// Decoder for TC strings of TCF v2 (v2.0 to v2.3): "TC string in, IDs as JSON out".
//
// A self-contained function on top of @iabtechlabtcf/core (version pinned in package.json). It
// uses no Node API, no Selenium, no database and no GVL, so that it can be reused as it is, for
// example in a browser extension (docs/entscheidungen.md, E4). No code from Cookie Glasses.
//
// Every set of IDs is a sorted list of the IDs that are set. Cookinspect stored maxId_ and lost
// the sets in JSON.stringify (finding F1); here nothing is left implicit.
//
// TC strings v1 (first character "B") are not decoded, only marked: decodeTCString returns
// { version: 1, decoded: false }.

import { TCString } from "@iabtechlabtcf/core";

const BASE64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

// Segment types (first 3 bits of every segment after the core string)
const SEGMENT_TYPES = { 1: "disclosedVendors", 2: "allowedVendors", 3: "publisherTC" };

function ids(vector) {
  const out = [];
  if (!vector) return out;
  vector.forEach((value, id) => { if (value) out.push(Number(id)); });
  return out.sort((a, b) => a - b);
}

// Which segments the string contains, read from the string itself. The decoded model cannot tell
// a missing disclosedVendors segment from an empty one, but v2.2 and v2.3 strings differ exactly
// there (disclosedVendors is mandatory since v2.3).
export function segmentsOf(tcString) {
  const parts = tcString.split(".");
  const segments = ["core"];
  for (const part of parts.slice(1)) {
    const first = BASE64URL.indexOf(part[0]);
    segments.push(first < 0 ? "unknown" : (SEGMENT_TYPES[first >> 3] || `type_${first >> 3}`));
  }
  return segments;
}

// Fields of the core string as bit positions (start, length), from the specification
// ("Consent string and vendor list formats v2", The Core String).
export const CORE_FIELDS = { version: [0, 6], cmpId: [78, 12], policyVersion: [132, 6] };

function coreBits(core) {
  return [...core].map((c) => BASE64URL.indexOf(c).toString(2).padStart(6, "0")).join("");
}

export function readField(tcString, [start, length]) {
  return parseInt(coreBits(tcString.split(".")[0]).slice(start, start + length), 2);
}

export function writeField(tcString, [start, length], value) {
  const [core, ...rest] = tcString.split(".");
  const bits = coreBits(core);
  const patched = bits.slice(0, start) + value.toString(2).padStart(length, "0") + bits.slice(start + length);
  return [patched.match(/.{6}/g).map((b) => BASE64URL[parseInt(b, 2)]).join(""), ...rest].join(".");
}

export function versionOf(tcString) {
  const first = BASE64URL.indexOf((tcString || "")[0]);
  return first < 0 ? null : first;   // the first 6 bits are the version
}

function publisherRestrictions(model) {
  const out = [];
  const restrictions = model.publisherRestrictions;
  if (!restrictions || restrictions.isEmpty()) return out;
  for (const restriction of restrictions.getRestrictions()) {
    out.push({
      purposeId: restriction.purposeId,
      restrictionType: restriction.restrictionType,   // 0 not allowed, 1 require consent, 2 require LI
      vendorIds: restrictions.getVendors(restriction).sort((a, b) => a - b),
    });
  }
  return out;
}

export function decodeTCString(tcString) {
  const version = versionOf(tcString);
  if (version === 1) return { version: 1, decoded: false, reason: "TC string v1: stored raw only" };
  if (version !== 2) return { version, decoded: false, reason: "no TC string v2" };
  // The library refuses CMP IDs 0 and 1 (TCModel: cmpId must be > 1) and would lose the whole
  // string. Such IDs occur in real strings (Matte et al. 2020, Appendix F), so the library gets
  // a copy with CMP ID 2; the output keeps the real ID and marks the replacement.
  const cmpId = readField(tcString, CORE_FIELDS.cmpId);
  const forLibrary = cmpId < 2 ? writeField(tcString, CORE_FIELDS.cmpId, 2) : tcString;
  let model;
  try {
    model = TCString.decode(forLibrary);
  } catch (error) {
    return { version, decoded: false, cmpId, reason: `decoding failed: ${error.message}` };
  }
  const segments = segmentsOf(tcString);
  return {
    version: model.version,
    decoded: true,
    segments: segments,
    disclosedVendorsPresent: segments.includes("disclosedVendors"),
    publisherTCPresent: segments.includes("publisherTC"),
    created: model.created ? model.created.toISOString() : null,
    lastUpdated: model.lastUpdated ? model.lastUpdated.toISOString() : null,
    cmpId: cmpId,
    cmpIdReplacedForDecoding: cmpId < 2,
    cmpVersion: model.cmpVersion,
    consentScreen: model.consentScreen,
    consentLanguage: model.consentLanguage,
    vendorListVersion: model.vendorListVersion,
    policyVersion: model.policyVersion,
    isServiceSpecific: model.isServiceSpecific,
    useNonStandardTexts: model.useNonStandardTexts,
    purposeOneTreatment: model.purposeOneTreatment,
    publisherCountryCode: model.publisherCountryCode,
    specialFeatureOptins: ids(model.specialFeatureOptins),
    purposeConsents: ids(model.purposeConsents),
    purposeLegitimateInterests: ids(model.purposeLegitimateInterests),
    vendorConsents: ids(model.vendorConsents),
    vendorLegitimateInterests: ids(model.vendorLegitimateInterests),
    vendorsDisclosed: ids(model.vendorsDisclosed),
    publisherRestrictions: publisherRestrictions(model),
    publisherConsents: ids(model.publisherConsents),
    publisherLegitimateInterests: ids(model.publisherLegitimateInterests),
    numCustomPurposes: model.numCustomPurposes,
    publisherCustomConsents: ids(model.publisherCustomConsents),
    publisherCustomLegitimateInterests: ids(model.publisherCustomLegitimateInterests),
  };
}

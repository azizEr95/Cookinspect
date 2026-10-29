// Generates the TC strings used by the tests (tests/tc_fixtures.json), with @iabtechlabtcf/core
// and a small test GVL (vendors 755 and 793, all 11 purposes). Rerun after a decoder update:
//
//   node decode/fixtures.mjs > tests/tc_fixtures.json
//
// The cases follow the plan for the unit tests: no consent, purposes {1,10}, all purposes,
// only legitimate interest (incl. the forbidden purposes 3-6), no vendors, a v2.2 string without
// the disclosedVendors segment, an outdated policy version and invalid CMP IDs.

import { GVL, TCModel, TCString } from "@iabtechlabtcf/core";
import { CORE_FIELDS, writeField } from "./tcstring.mjs";

const ALL = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const vendor = (id) => ({ id, name: `Test vendor ${id}`, purposes: ALL, legIntPurposes: [2, 7, 8, 9, 10, 11],
  flexiblePurposes: [], specialPurposes: [], features: [], specialFeatures: [], policyUrl: "https://example.org" });
const gvlJson = { gvlSpecificationVersion: 3, vendorListVersion: 100, tcfPolicyVersion: 5,
  lastUpdated: "2026-10-01T00:00:00Z",
  purposes: Object.fromEntries(ALL.map((id) => [id, { id, name: `Purpose ${id}`, description: "" }])),
  specialPurposes: {}, features: {}, specialFeatures: {}, stacks: {}, dataCategories: {},
  vendors: { 755: vendor(755), 793: vendor(793) } };

function make({ purposes = [], li = [], vendors = [], vendorLi = [], disclosed = true, cmpId = 300, segments }) {
  const gvl = new GVL(gvlJson);
  const model = new TCModel(gvl);
  model.cmpId = cmpId;
  model.cmpVersion = 1;
  model.publisherCountryCode = "DE";
  model.isServiceSpecific = true;
  model.purposeConsents.set(purposes);
  model.purposeLegitimateInterests.set(li);
  model.vendorConsents.set(vendors);
  model.vendorLegitimateInterests.set(vendorLi);
  if (disclosed) model.vendorsDisclosed.set([755, 793]);
  return TCString.encode(model, segments ? { segments } : undefined);
}

// The library refuses invalid CMP IDs (e.g. 0), ignores the policy version set in the model (it
// takes the one of the GVL) and drops legitimate interest for purposes 3-6 when encoding. Such
// values appear in real strings, so they are written into the bits of a valid string.
// PurposesLITransparency starts at bit 176 (purpose n = bit 176 + n - 1).
function withLegitimateInterest(tcString, purposes) {
  return purposes.reduce((s, p) => writeField(s, [176 + p - 1, 1], 1), tcString);
}

const fixtures = {
  no_consent: make({}),
  purposes_1_10: make({ purposes: [1, 10], vendors: [755] }),
  all_purposes: make({ purposes: ALL, vendors: [755, 793] }),
  all_purposes_no_vendors: make({ purposes: ALL }),
  li_only: make({ li: [2, 7], vendorLi: [755] }),
  li_forbidden_3_to_6: withLegitimateInterest(make({ li: [2, 7], vendorLi: [755] }), [3, 4, 5, 6]),
  without_disclosed_vendors: make({ purposes: [1], vendors: [755], disclosed: false, segments: ["core"] }),
  policy_version_3: writeField(make({ purposes: [1], vendors: [755] }), CORE_FIELDS.policyVersion, 3),
  cmp_id_0: writeField(make({ purposes: [1] }), CORE_FIELDS.cmpId, 0),
  cmp_id_1: writeField(make({ purposes: [1] }), CORE_FIELDS.cmpId, 1),
  cmp_id_4095: writeField(make({ purposes: [1] }), CORE_FIELDS.cmpId, 4095),
  v1_specification_example: "BOEFEAyOEFEAyAAABAENAI4AAAB9vABAASA",
};
console.log(JSON.stringify(fixtures, null, 2));

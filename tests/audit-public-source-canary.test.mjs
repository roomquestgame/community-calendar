import test from 'node:test';
import assert from 'node:assert/strict';
import {GATES,validateBatch,evaluateBatch,evaluateSource} from '../docs/tools/audit-public-source-canary.mjs';
const mk=()=>({batch_size_limit:10,source_count:1,items:[{number:1,name:'Test source',calendar_url:'https://example.org/events',publisher_page:'https://example.org',
  gates:Object.fromEntries(GATES.map(k=>[k,'pending'])),source_registered:false,publication_verified:false,
  media:{image_candidate_verified:false,byte_and_mime_verified:false,publication_rights_verified:false,use_fallback_until_approved:true}}]});
test('at most ten, never eleven sources',()=>{const b=mk();b.items=Array.from({length:11},(_,i)=>({...b.items[0],number:i+1,name:'Source '+i}));b.source_count=11;assert.throws(()=>validateBatch(b),/one_to_ten_sources_required/)});
test('detect repeated source names',()=>{const b=mk();b.items.push({...b.items[0],number:2});b.source_count=2;assert.throws(()=>validateBatch(b),/duplicate_or_unordered_source/)});
test('HTTPS required',()=>{const b=mk();b.items[0].calendar_url='http://localhost';assert.throws(()=>validateBatch(b),/unsafe_or_missing_publisher_url/)});
test('unvalidated source is never eligible or published',()=>{const r=evaluateBatch(mk());assert.equal(r.summary.eligible_to_enable,0);assert.equal(r.summary.confirmed_public,0);assert.ok(r.sources[0].hold_reasons.includes('source_description_parity'))});
test('no media approval from image URL alone',()=>{const b=mk();b.items[0].gates.media_policy='passed';assert.throws(()=>validateBatch(b),/image_validation_missing/)});
test('missing event photo can use proper fallback with factual evidence',()=>{const b=mk();for(const k of GATES.slice(0,-1))b.items[0].gates[k]='passed';b.items[0].gates.media_policy='fallback';assert.equal(evaluateBatch(b).summary.eligible_to_enable,1);assert.equal(evaluateBatch(b).summary.confirmed_public,0)});
test('publication needs independent live receipt',()=>{const b=mk();for(const k of GATES.slice(0,-1))b.items[0].gates[k]='passed';b.items[0].gates.media_policy='fallback';b.items[0].source_registered=true;assert.equal(evaluateBatch(b).summary.confirmed_public,0);b.items[0].publication_verified=true;assert.equal(evaluateBatch(b).summary.confirmed_public,1)});
test('no venue/time/rights fallback',()=>{const b=mk();b.items[0].gates.venue_address_evidence='fallback';assert.throws(()=>validateBatch(b),/invalid_nonmedia_fallback/)});

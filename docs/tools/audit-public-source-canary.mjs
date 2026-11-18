#!/usr/bin/env node
// Offline publisher admission checker; no network, DB writes or image fetches.
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
export const GATES=Object.freeze(["exact_feed_access","future_occurrence_sample","source_description_parity","venue_address_evidence","timezone_and_recurrence","categories_and_audience","publisher_terms","cross_source_dedupe","media_policy"]);
export function validateBatch(batch) {
 if(!batch||typeof batch!=="object"||!Array.isArray(batch.items)||batch.items.length<1||batch.items.length>10||batch.source_count!==batch.items.length||batch.batch_size_limit!==10)throw Error("one_to_ten_sources_required");
 const names=new Set();
 for(let i=0;i<batch.items.length;i++){
  const x=batch.items[i];
  if(!x||x.number!==i+1||typeof x.name!=="string"||!x.name.trim()||names.has(x.name.toLowerCase()))throw Error("duplicate_or_unordered_source");
  names.add(x.name.toLowerCase());
  for(const k of ["calendar_url","publisher_page"]){if(typeof x[k]!=="string"||!/^https:\/\/[a-z0-9.-]+(?:[\/?:#]|$)/i.test(x[k]))throw Error("unsafe_or_missing_publisher_url")}
  if(!x.gates||Object.keys(x.gates).length!==GATES.length||GATES.some(k=>!["passed","pending","failed","fallback"].includes(x.gates[k])))throw Error("missing_review_gates");
  if(GATES.slice(0,-1).some(k=>x.gates[k]==="fallback"))throw Error("invalid_nonmedia_fallback");
  if(!x.media||x.media.use_fallback_until_approved!==true||["image_candidate_verified","byte_and_mime_verified","publication_rights_verified"].some(k=>typeof x.media[k]!=="boolean"))throw Error("unsafe_image_review_state");
  if(x.gates.media_policy==="passed"&&!(x.media.image_candidate_verified&&x.media.byte_and_mime_verified&&x.media.publication_rights_verified))throw Error("image_validation_missing");
 }
 return batch;
}

export function evaluateSource(x) {
 const holds=GATES.slice(0,-1).filter(k=>x.gates[k]!=="passed"),media=x.gates.media_policy;
 if(!["passed","fallback"].includes(media))holds.push("media_policy");
 if(media==="passed"&&!(x.media.image_candidate_verified&&x.media.byte_and_mime_verified&&x.media.publication_rights_verified))holds.push("image_rights_or_bytes");
 const canEnable=holds.length===0;
 return {name:x.name,stage:x.stage||"unspecified",can_enable:canEnable,public_verified:canEnable&&x.source_registered===true&&x.publication_verified===true,hold_reasons:holds};
}

export function evaluateBatch(batch){
 validateBatch(batch);
 const sources=batch.items.map(evaluateSource);
 return {summary:{checked:sources.length,eligible_to_enable:sources.filter(x=>x.can_enable).length,confirmed_public:sources.filter(x=>x.public_verified).length,review_or_blocked:sources.filter(x=>!x.can_enable).length},sources};
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{
  const args=process.argv.slice(2);
  if(args.length!==1&&!(args.length===3&&args[1]==='--out'))throw Error('usage: node docs/tools/audit-public-source-canary.mjs batch.json [--out report.json]');
  const report=JSON.stringify(evaluateBatch(JSON.parse(readFileSync(args[0],'utf8'))),null,2)+'\n';
  if(args.length===3)writeFileSync(args[2],report);else process.stdout.write(report);
 }catch(e){console.error(e.message);process.exitCode=1}
}

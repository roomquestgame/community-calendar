#!/usr/bin/env node
// Offline source-lead audit. No network, database writes, source activation or image fetching.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
function parseHttps(v){
 if(typeof v!=="string"||v.length>1500)return null;
 const m=v.trim().match(/^https:\/\/([a-z0-9.-]+)(\/[^?#]*)?(\?[^#]*)?$/i);
 if(!m||m[1].includes("..")||m[1].startsWith(".")||m[1].endsWith("."))return null;
 const host=m[1].toLowerCase().replace(/^www\./,""),path=(m[2]||"/").replace(/\/+$/,"")||"/";
 let query=[];
 try{query=(m[3]||"").slice(1).split("&").filter(Boolean).map(v=>{const i=v.indexOf("=");return [decodeURIComponent(i<0?v:v.slice(0,i)),decodeURIComponent(i<0?"":v.slice(i+1))]}).filter(([k])=>!["fbclid","gclid"].includes(k.toLowerCase())&&!k.toLowerCase().startsWith("utm_"))}catch{return null}
 query.sort((a,b)=>a[0].localeCompare(b[0])||a[1].localeCompare(b[1]));
 const q=query.length?"?"+query.map(([k,v])=>encodeURIComponent(k)+"="+encodeURIComponent(v)).join("&"):"";
 return {host,path,query,url:"https://"+host+path+q};
}

function identity(type,raw){
 const p=parseHttps(raw);if(!p)return null;
 const t=String(type||"").toLowerCase();
 if(t==="localist")return "localist:"+p.host;
 if(t==="bibliocommons"){
  const m=p.host==="gateway.bibliocommons.com"?p.path.match(/^\/v2\/libraries\/([a-z0-9-]+)\/events$/):p.host.match(/^([a-z0-9-]+)\.bibliocommons\.com$/);
  return m?"bibliocommons:"+m[1]:null;
 }
 if(t==="chambermate"){
  let m;
  if(p.host==="api.chambermate.com"){
   if(p.path!=="/core/biz/webPresence/getEventsInfo")return null;
   const domain=p.query.find(([k])=>k==="websiteDomain")?.[1]||"";
   m=domain.match(/^([a-z0-9-]+)\.chambermate\.com$/);
  }else m=p.host.match(/^([a-z0-9-]+)\.chambermate\.com$/);
  return m?"chambermate:"+m[1]:null;
 }
 return (t==="ics"?"ical":t)+":"+p.url;
}

function registryKind(row){
 const url=row.feed_url||row.url||row.config?.url||"";
 if(/\.bibliocommons\.com/i.test(url))return "bibliocommons";
 if(String(row.source_key||"").startsWith("localist_"))return "localist";
 return row.platform_adapter||row.platform||row.kind||"unknown";
}

function auditEvidence(raw){
 const v=raw&&typeof raw==="object"?raw:{};
 const required=["future_occurrence_checked","description_compared_to_publisher","timezone_checked","venue_checked","category_checked","terms_rights_checked","dedupe_checked"];
 const missing=required.filter(k=>v[k]!==true);
 const imageMissing=v.image_present===false?(v.no_image_verified===true?[]:["no_image_verified"]):
   (v.image_present===true?["image_url_checked","image_bytes_checked","image_rights_checked"].filter(k=>v[k]!==true):["image_presence_not_checked"]);
 return {event_checks_missing:missing,image_checks_missing:imageMissing,ready:missing.length===0&&imageMissing.length===0};
}

function reconcile(leads,registrations){
 if(!Array.isArray(leads)||!Array.isArray(registrations))throw Error("arrays_required");
 const map=new Map();
 for(const r of registrations){const key=identity(registryKind(r),r.feed_url||r.url||r.config?.url);if(!key)continue;if(!map.has(key))map.set(key,[]);map.get(key).push(String(r.source_key||"unnamed"))}
 const seen=new Set(),rows=[];
 for(const x of leads){
  const key=identity(x.platform,x.url),existing=key?(map.get(key)||[]):[];
  const status=!key?"exact_publisher_endpoint_unverified":existing.length?"already_registered":seen.has(key)?"batch_duplicate":
    ["drupal_html","socrata"].includes(x.platform)?"adapter_or_schema_review":"publisher_probe_required";
  if(key)seen.add(key);
  rows.push({name:x.name,platform:x.platform,url:x.url,reference:x.reference,identity:key,status,existing_source_keys:existing,
   quality:auditEvidence(x.verified),auto_register:false,auto_publish:false});
 }
 const counts={total:rows.length};for(const r of rows)counts[r.status]=(counts[r.status]||0)+1;
 return {counts,leads:rows};
}
export { parseHttps, identity, registryKind, auditEvidence, reconcile };
function main(args){
 const files={registry:[]};
 for(let i=0;i<args.length;i+=2){
  const key=args[i],value=args[i+1];if(!value||!['--leads','--registry','--output'].includes(key))throw Error('usage: --leads leads.json --registry source-export.json [--registry localist-export.json] [--output report.json]');
  if(key==='--registry')files.registry.push(value);else files[key.slice(2)]=value;
 }
 if(!files.leads||!files.registry.length)throw Error('lead_and_registry_files_required');
 const load=f=>JSON.parse(fs.readFileSync(f,'utf8'));
 const leadData=load(files.leads),candidates=Array.isArray(leadData)?leadData:leadData.candidates;
 const registrations=files.registry.flatMap(f=>{const v=load(f);return Array.isArray(v)?v:v.rows||v.sources||[]});
 const report=JSON.stringify(reconcile(candidates,registrations),null,2)+'\n';
 if(files.output)fs.writeFileSync(files.output,report);else process.stdout.write(report);
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{main(process.argv.slice(2));}catch(e){console.error(e.message);process.exitCode=1}
}

import test from 'node:test';
import assert from 'node:assert/strict';
import {identity,auditEvidence,reconcile} from '../scripts/reconcile-public-source-leads.mjs';
test('Localist host and API identity match',()=>assert.equal(identity('localist','https://campuscalendar.ucsb.edu'),identity('localist','https://campuscalendar.ucsb.edu/api/2/events')));
test('Biblio tenant and gateway identity match',()=>assert.equal(identity('bibliocommons','https://bpl.bibliocommons.com/v2/events'),identity('bibliocommons','https://gateway.bibliocommons.com/v2/libraries/bpl/events?limit=5')));
test('ChamberMate verified tenant matches its API identity',()=>assert.equal(identity('chambermate','https://currituckchamberofcommerce.chambermate.com'),identity('chambermate','https://api.chambermate.com/core/biz/webPresence/getEventsInfo?websiteDomain=currituckchamberofcommerce.chambermate.com')));
test('Standalone chamber sites do not fabricate a tenant',()=>assert.equal(identity('chambermate','https://grantspasschamber.org/'),null));
test('ICS category selectors are distinct feeds',()=>assert.notEqual(identity('ical','https://dallasparks.org/common/modules/iCalendar/iCalendar.aspx?catID=14&feed=calendar'),identity('ical','https://dallasparks.org/common/modules/iCalendar/iCalendar.aspx?catID=25&feed=calendar')));
test('Images require separate publication checks',()=>assert.equal(auditEvidence({future_occurrence_checked:true,image_present:true}).ready,false));
test('Existing Biblio and Localist matches prevent duplicate source proposals',()=>{
 const r=reconcile([{name:'UCSB',platform:'localist',url:'https://campuscalendar.ucsb.edu'},{name:'BPL',platform:'bibliocommons',url:'https://bpl.bibliocommons.com/v2/events'}],[
 {source_key:'localist_example',url:'https://campuscalendar.ucsb.edu/api/2/events'},
 {source_key:'boston',feed_url:'https://bpl.bibliocommons.com/v2/events',platform_adapter:'html'}]);
 assert.equal(r.counts.already_registered,2);assert.ok(r.leads.every(x=>!x.auto_register&&!x.auto_publish));
});

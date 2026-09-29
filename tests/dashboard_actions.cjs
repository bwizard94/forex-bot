// No browser, broker or network: exercise real handlers with expiring DOM events.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('src/dashboard/static/app.js', 'utf8');
const helpers = source.slice(0, source.indexOf('const fmt ='));
const handlers = source.slice(source.indexOf('document.getElementById("tabs").addEventListener'), source.lastIndexOf('\nsetClock();'));

async function run(id, failure) {
  const elements = new Map();
  const element = key => {
    if (!elements.has(key)) elements.set(key, {id:key, disabled:false, value:'', dataset:{}, hidden:true,
      textContent:'', handlers:{}, addEventListener(type, fn) {this.handlers[type]=fn;}});
    return elements.get(key);
  };
  const context = {
    document:{getElementById:element}, state:{tab:'overview'}, AbortController, setTimeout, clearTimeout,
    fetch:async () => {
      if (failure === 'network') throw new Error('Network unavailable');
      return new Response(JSON.stringify(failure ? {ok:false, detail:'Credential required'} : {ok:true}),
                          {status:failure === 'http' ? 400 : 200});
    },
  };
  for (const name of ['refreshOverview','refreshPlaybook','refreshGrowth','refreshHistory',
                      'refreshNews','refreshSheet']) context[name]=async () => {};
  vm.createContext(context);
  vm.runInContext(helpers+handlers, context);
  const button=element(id);
  const event={currentTarget:button};
  const pending=button.handlers.click(event);
  assert.equal(button.disabled,true,id+' disables during request');
  assert.equal(element(id+'-result').textContent,'Working…');
  event.currentTarget=null; // Browsers clear this when synchronous dispatch ends.
  await pending;
  assert.equal(button.disabled,false,id+' recovers after await');
  assert.equal(element('action-status').dataset.error,String(Boolean(failure)));
  assert.ok(element('action-status').textContent);
  assert.equal(element(id+'-result').hidden,false);
  assert.equal(element(id+'-result').dataset.error,String(Boolean(failure)));
  assert.notEqual(element(id+'-result').textContent,'Working…');
}

(async () => {
  const ids=['run-cycle','run-intel','run-growth','run-history','run-news-scan',
             'save-slack','save-sheets','sync-sheets','save-mt4','toggle-trading','run-morning','run-recap'];
  for (const id of ids) for (const failure of [null,'http','application','network']) await run(id,failure);
  const context=vm.createContext({});
  vm.runInContext(helpers,context);
  assert.match(context.actionConfirmation('/api/sheets/connect',{started:true}),/not yet confirmed/);
  assert.match(context.actionConfirmation('/api/sheets/sync',{started:false}),/No new Sheets sync/);
  assert.match(context.actionConfirmation('/api/slack/connect',{ready:true,channel:'#forex'}),/Connected to #forex/);
  assert.match(context.actionConfirmation('/api/slack/connect',{ready:false}),/not ready/);
  assert.match(context.actionConfirmation('/api/history',{started:true}),/started in the background/);
  console.log('48 dashboard action regression scenarios passed');
})().catch(error => {console.error(error); process.exitCode=1;});

// Requires Playwright + Chromium; see docs/DEPLOYMENT_KO.md.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE || undefined,headless:true,args:['--no-sandbox']});
 const context=await browser.newContext();await context.addInitScript(()=>sessionStorage.setItem('mpri-language','en'));
 const page=await context.newPage();const url=(process.env.MPRI_WEB_URL || 'http://127.0.0.1:3001')+'/portfolio';
 const hidden=()=>page.getByRole('heading',{name:'Hidden Risk Map',exact:true});
 const analyze=()=>page.getByRole('button',{name:'Analyze',exact:true});
 const compare=()=>page.getByRole('button',{name:'Compare',exact:true});
 const weight=()=>page.getByRole('spinbutton',{name:'Weight (%) 1',exact:true}).first();
 await page.goto(url);await hidden().waitFor();
 await compare().click();await page.getByRole('cell',{name:'16.94%',exact:true}).waitFor();
 await page.getByRole('spinbutton',{name:'Weight (%) 1',exact:true}).last().fill('22');
 assert.equal(await page.getByRole('cell',{name:'16.94%',exact:true}).count(),0);assert.equal(await hidden().count(),1);
 await page.getByRole('spinbutton',{name:'Portfolio value (USD)',exact:true}).fill('200000');assert.equal(await hidden().count(),0);assert.equal(await page.getByRole('heading',{name:'Stress Test',exact:true}).count(),0);
 // Delay an actual response and change the input after request dispatch.
 let release,entered;const gate=new Promise(r=>release=r);const started=new Promise(r=>entered=r);
 await page.route('**/api/portfolio/analyze',async route=>{const response=await route.fetch();entered();await gate;await route.fulfill({response});});
 await analyze().click();await started;await weight().fill('31');release();await page.waitForTimeout(500);assert.equal(await hidden().count(),0);await page.unrouteAll();
 await weight().fill('30');await analyze().click();await hidden().waitFor();
 // Compare recomputes both sides: its current must also replace the main panel.
 const editor=page.locator('section').filter({has:page.getByRole('heading',{name:'Portfolio input',exact:true})});
 while(await editor.getByRole('button',{name:'Remove',exact:true}).count()>1)await editor.getByRole('button',{name:'Remove',exact:true}).last().click();
 await editor.locator('select').first().selectOption('SPY');await editor.locator('tbody input').first().fill('100');
 await page.getByRole('spinbutton',{name:'Weight (%) 1',exact:true}).last().fill('21');
 await compare().click();await hidden().waitFor();
 assert.ok((await page.locator('main > .selected-metrics').innerText()).includes('15.2%'));
 await page.getByRole('cell',{name:'15.24%',exact:true}).waitFor();
 for(const [status,body] of [[503,{detail:{code:'portfolio_snapshot_unavailable'}}],[422,{detail:[{msg:'QA invalid'}]}]]){
  await page.route('**/api/portfolio/analyze',route=>route.fulfill({status,json:body}));await analyze().click();await page.locator('main').getByRole('alert').waitFor();assert.equal(await hidden().count(),0);await page.unrouteAll();
 }
 // Optional missing Stress data is explicitly shown, never estimated.
 await page.route('**/api/portfolio/analyze',async route=>{const r=await route.fetch();const a=await r.json();await route.fulfill({json:{...a,stress:null,factor_exposure:null}})});
 await analyze().click();await hidden().waitFor();await page.getByText('Stress results are unavailable. No losses have been estimated.',{exact:true}).waitFor();
 console.log('PASS: proposed/current/value invalidation, delayed-response race, compare/current synchronization, 503/422, missing stress');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});

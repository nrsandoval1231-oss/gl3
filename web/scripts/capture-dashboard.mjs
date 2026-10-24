// Run from web/ with the local API and Vite server running. Never prints credentials.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
const page=await browser.newPage({viewport:{width:1648,height:928}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(`${process.env.GRIDLENS_CAPTURE_URL ?? 'http://127.0.0.1:5173'}/?view=workspace`);
await page.getByLabel('Password',{exact:true}).waitFor();
const secret=fs.readFileSync('../.artifacts/local-auth.txt','utf8');
const password=secret.trim().split('\n').at(-1).trim();
if(await page.getByLabel('Password',{exact:true}).isVisible()){if(!password)throw Error('Local password format requires inspection');await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Continue',exact:true}).click();}
try { await page.locator('.wh-list').waitFor({timeout:15000}); } catch { console.log((await page.locator('body').innerText()).slice(0,1600)); await page.screenshot({path:'/tmp/login-block.png'}); throw Error('Login blocked'); }
await page.waitForTimeout(1500);
console.log('Rows',await page.locator('.opportunity-select').count());
if(await page.locator('.opportunity-select').count())await page.locator('.opportunity-select').first().click();
await page.waitForTimeout(1000);await page.evaluate(()=>document.fonts.ready);
fs.mkdirSync('../docs/design/screenshots',{recursive:true});
for(const [width,height] of [[1648,928],[1440,900],[1280,800],[768,1024],[390,844]]){await page.setViewportSize({width,height});await page.screenshot({path:`../docs/design/screenshots/dashboard-${width}x${height}.png`});console.log(width,await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,header:document.querySelector('.wh-header').getBoundingClientRect().height,table:document.querySelector('.wh-list').getBoundingClientRect().width,detail:document.querySelector('.wh-detail').getBoundingClientRect().width})));}
console.log('Errors',errors);await browser.close();

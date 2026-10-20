const { defineConfig } = require('./gl3-pr87-repair/web/node_modules/@playwright/test');
process.env.GRIDLENS_WEB_PORT = '5192';
module.exports = defineConfig({
  testDir: './gl3-title-enrichment/web/tests',
  testMatch: ['**/workspace.spec.ts','**/project_cards.spec.ts'],
  workers: 2,
  reporter: [['list']],
  outputDir: './title02-test-results',
  use: {baseURL:'http://127.0.0.1:5192',viewport:{width:1280,height:900},trace:'retain-on-failure'},
  webServer: {command:'npm run dev -- --host 127.0.0.1 --port 5192',cwd:'./gl3-title-enrichment/web',port:5192,reuseExistingServer:false},
});

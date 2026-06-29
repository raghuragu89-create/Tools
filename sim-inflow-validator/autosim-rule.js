var d = issue.description || '';
var id = _.sortBy(issue.aliases, function(a) { return a.precedence; }).pop().id;
var title = (issue.title || '').substring(0, 60);
var full = (title + ' ' + d).toLowerCase();
var fields = [{n:'Summary',k:'summary'},{n:'Build Details',k:'build details'},{n:'Environment',k:'environment'},{n:'Marketplace In Scope',k:'marketplace'},{n:'Start & End Date',k:'start & end date'},{n:'Test Priority',k:'priority'},{n:'Surfaces',k:'surfaces'},{n:'QA Unit/Smoke test',k:'smoke test'}];
var placeholders = ['tbd','tba','nil','none','to be confirmed'];
var vague = ['check quip','see wiki','ask team','details are here','refer to','will update','will provide'];
var validEnvs = ['beta','gamma','prod','uat','staging','dev','pre-prod','preprod','evt','dvt','production','development','stage','sandbox','test','qa','sit','perf','performance','live'];
var fails = [];
var i, j, f, val, ci, low, line, isP, isV, p, v;
for (i = 0; i < fields.length; i++) {
  f = fields[i];
  if (full.indexOf(f.k) === -1) { fails.push(f.n + ' - missing'); continue; }
  var lines = d.split('\n');
  val = '';
  for (j = 0; j < lines.length; j++) {
    line = lines[j];
    if (line.toLowerCase().indexOf(f.k) !== -1) {
      ci = line.indexOf(':');
      if (ci !== -1) val = line.substring(ci + 1).trim();
      break;
    }
  }
  if (!val || val.length < 2) { fails.push(f.n + ' - empty'); continue; }
  low = val.toLowerCase();
  if (low.indexOf('<<') !== -1) { fails.push(f.n + ' - placeholder'); continue; }
  isP = false;
  for (p = 0; p < placeholders.length; p++) { if (low === placeholders[p] || low.indexOf(placeholders[p]) !== -1) { isP = true; break; } }
  if (isP) { fails.push(f.n + ' - placeholder'); continue; }
  isV = false;
  for (v = 0; v < vague.length; v++) { if (low.indexOf(vague[v]) !== -1 && low.indexOf('http') === -1) { isV = true; break; } }
  if (isV) { fails.push(f.n + ' - vague ref without link'); continue; }
  if (f.k === 'smoke test' && low.indexOf('yes or no') !== -1) { fails.push(f.n + ' - must select Yes or No'); continue; }
  if (f.k === 'summary') {
    var words = val.trim().split(/\s+/);
    if (words.length < 3) { fails.push(f.n + ' - too vague (need 3+ words)'); continue; }
    var vowels = 0;
    for (j = 0; j < val.length; j++) { if ('aeiouAEIOU'.indexOf(val.charAt(j)) !== -1) vowels++; }
    if (val.length > 4 && vowels < val.length * 0.15) { fails.push(f.n + ' - appears to be gibberish'); continue; }
  }
  if (f.k === 'environment') {
    var envFound = false;
    for (j = 0; j < validEnvs.length; j++) { if (low.indexOf(validEnvs[j]) !== -1) { envFound = true; break; } }
    if (!envFound) {
      var evow = 0;
      for (j = 0; j < val.length; j++) { if ('aeiouAEIOU'.indexOf(val.charAt(j)) !== -1) evow++; }
      if (val.length > 4 && (evow < val.length * 0.15 || evow > val.length * 0.7)) { fails.push(f.n + ' - gibberish (not a valid environment)'); continue; }
      fails.push(f.n + ' - invalid (expected: Beta, Gamma, Prod, UAT, Dev, Staging, Pre-prod)'); continue;
    }
  }
  if (f.k === 'build details') {
    var hasVersion = false;
    if (low.indexOf('.') !== -1 || low.indexOf('#') !== -1 || low.indexOf('v') !== -1 || low.indexOf('r2') !== -1) hasVersion = true;
    if (!hasVersion && val.split(/\s+/).length < 2) {
      var bvow = 0;
      for (j = 0; j < val.length; j++) { if ('aeiouAEIOU'.indexOf(val.charAt(j)) !== -1) bvow++; }
      if (val.length > 4 && bvow < val.length * 0.15) { fails.push(f.n + ' - gibberish'); continue; }
    }
  }
}
if (fails.length > 0) {
  var failList = '';
  for (i = 0; i < fails.length; i++) { failList = failList + '  [!] ' + fails[i] + '\n'; }
  var msg = '[ACTION:HOLD][VALIDATOR:AUTOSIM]\n\n[FAILED] Inflow Validation\n\nTask: ' + id + ' - ' + title + '\nRoom: APS DBS Task Inflow\nAction: Move to Hold required\n\nFailed Fields:\n' + failList + '\nMandatory: Summary, Build, Environment, Marketplace, Dates, Priority, Surfaces, QA Smoke\n\nFix and move back to New-Inflow.\n-- SIM Inflow Validator';
  issue.addComment(msg);
  var slkMsg = '[FAILED] Inflow Validation\nTask: ' + id + ' - ' + title + '\nAction: Move to Hold required\nFailed: ' + fails.join(', ') + '\nhttps://taskei.example.com/tasks/' + id;
  await slack.sendMessageToWebhook('https://hooks.slack.com/triggers/YOUR/WORKFLOW/WEBHOOK', slkMsg);
}
if (fails.length === 0) {
  issue.addComment('[ACTION:AI-REVIEW][VALIDATOR:AUTOSIM]\n\nBasic validation passed. Queued for AI content review.\n-- SIM Inflow Validator');
}

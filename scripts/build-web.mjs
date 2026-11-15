// Build artifact delivery is separate from Git source sync. No dependencies or secrets in archive.
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readdirSync,readFileSync,writeFileSync} from 'node:fs';
import {join,relative,resolve} from 'node:path';
const root=resolve(import.meta.dirname,'..');
const dist=join(root,'frontend','dist');
const revision=execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const sha256={};
function walk(dir){for(const entry of readdirSync(dir,{withFileTypes:true})){const p=join(dir,entry.name);if(entry.isDirectory())walk(p);else if(entry.name!=='manifest.json')sha256[relative(dist,p).replaceAll('\\','/')]=createHash('sha256').update(readFileSync(p)).digest('hex')}}
walk(dist);
writeFileSync(join(dist,'manifest.json'),JSON.stringify({revision,sha256},null,2));
console.log(`Web artifact manifest: ${revision}, ${Object.keys(sha256).length} files`);

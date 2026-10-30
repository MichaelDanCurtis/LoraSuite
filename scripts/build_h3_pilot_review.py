"""Build a local blinded review from verified pilot previews; no automatic scores."""
import argparse
import hashlib
import json
from pathlib import Path
import random


def build(root):
    protocol = json.loads((root / "protocol.json").read_text())
    pairs = []
    for scene, prompt in protocol["scenes"]:
        for seed in protocol["seeds"]:
            for other in protocol["conditions"][1:]:
                labels = ["baseline-a", other]
                key = f"{scene}-{seed}-{other}"
                random.Random(key).shuffle(labels)
                clips = []
                for condition in labels:
                    folder = root / f"{condition}-{scene}-{seed}"
                    result = folder / "result.json"
                    if not result.exists() or not json.loads(result.read_text()).get("verified_decode"):
                        break
                    clips.append({"label": condition, "src": folder.name + "/output.mp4"})
                if len(clips) == 2:
                    pairs.append({"id": key, "scene": scene, "seed": seed, "prompt": prompt, "clips": clips})
    random.Random(protocol["proposal_sha256"]).shuffle(pairs)
    data = json.dumps({"protocol": protocol, "pairs": pairs}).replace("<", "\\u003c")
    html = TEMPLATE.replace("__DATA__", data)
    (root / "review.html").write_text(html)
    print(json.dumps({"review": str(root / "review.html"), "ready_pairs": len(pairs), "expected_pairs": 32}))


TEMPLATE = '''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Example Subject — H3 pilot comparison</title>
<style>
:root{color-scheme:dark;font:16px system-ui;background:#0c1119;color:#e8edf5}body{max-width:1160px;margin:auto;padding:24px}h1{font-size:28px}p{line-height:1.5;color:#b5c4d7}button,select,textarea{font:inherit;color:inherit;background:#172435;border:1px solid #405977;border-radius:9px;padding:10px}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.players{display:grid;grid-template-columns:1fr 1fr;gap:16px}video{width:100%;height:min(62vh,660px);object-fit:contain;background:#05070b;border-radius:12px}.card{background:#111c29;border:1px solid #273d55;border-radius:16px;padding:18px;margin:16px 0}.scores{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}label{display:grid;gap:7px}textarea{width:100%;box-sizing:border-box;min-height:80px}.reference{width:180px;max-height:300px;object-fit:contain}small{color:#a9bdd6}#reveal{color:#ffcf8c}@media(max-width:700px){body{padding:12px}.scores{grid-template-columns:1fr}video{height:45vh}.players{gap:8px}}
</style>
<h1>Example Subject — face & body pilot</h1>
<p>Training finished: 27 photos · rank 16 · 500 steps. These are short, low-resolution previews—not proof of final video quality. Compare visible face, body proportions, artifacts and scene following separately. Some pairs contain two baseline runs to show normal render variability.</p>
<details class="card"><summary>Reference and comparison limits</summary><div class="row"><img class="reference" src="reference.png" alt="Held-out reference used identically in every render"><p id="limits"></p></div><p>Each clip is 256 × 384, 22 frames, six sampling steps. The reference was not used for training. The corset in this reference changes the waist silhouette; it is not neutral body-shape ground truth. When an area is not visible, leave it unrated. Do not equate lower training loss with better likeness.</p></details>
<div class="row"><button id="previous">← Previous</button><strong id="counter"></strong><button id="next">Next →</button><button id="play">Play both</button><button id="download">Download my notes</button></div>
<div id="empty" class="card" hidden>Matching pairs are still rendering. Reopen this report after the comparison batch finishes.</div>
<section id="review"><div class="card"><h2 id="scene"></h2><p id="prompt"></p><div class="players"><div><h3>Left</h3><video id="left" controls playsinline preload="metadata"></video></div><div><h3>Right</h3><video id="right" controls playsinline preload="metadata"></video></div></div></div>
<div class="card"><div class="scores"><label>Face likeness<select data-score="face"></select></label><label>Body proportions<select data-score="body"></select></label><label>Visual quality / artifacts<select data-score="quality"></select></label><label>Scene following<select data-score="scene"></select></label></div><p><label>Notes<textarea id="notes" placeholder="What improved, what regressed, or what is not visible?"></textarea></label></p><small>Notes save in this browser only. Download them to keep an independent copy.</small><p><button id="labels">Reveal this pair’s labels</button> <span id="reveal"></span></p></div></section>
<script>
const data=__DATA__, pairs=data.pairs, storageKey='h3-pilot-review:'+data.protocol.proposal_sha256;
let index=0,ratings={};try{ratings=JSON.parse(localStorage.getItem(storageKey)||'{}')}catch{}
const byId=id=>document.getElementById(id),fields=[...document.querySelectorAll('[data-score]')];
for(const field of fields){for(const [value,text] of [['','Not rated / not visible'],['left','Left is better'],['tie','About the same'],['right','Right is better']]){const option=document.createElement('option');option.value=value;option.textContent=text;field.append(option)}}
function save(){if(!pairs.length)return;const row=ratings[pairs[index].id]||{};for(const field of fields)row[field.dataset.score]=field.value;row.notes=byId('notes').value;row.updatedAt=new Date().toISOString();ratings[pairs[index].id]=row;localStorage.setItem(storageKey,JSON.stringify(ratings))}
function show(){byId('empty').hidden=!!pairs.length;byId('review').hidden=!pairs.length;byId('counter').textContent=pairs.length?`${index+1} of ${pairs.length} ready pairs`:'0 of 32 pairs ready';byId('previous').disabled=index===0;byId('next').disabled=index>=pairs.length-1;byId('play').disabled=!pairs.length;if(!pairs.length)return;const pair=pairs[index],row=ratings[pair.id]||{};byId('scene').textContent=`${pair.scene} · seed ${pair.seed}`;byId('prompt').textContent=pair.prompt;['left','right'].forEach((id,i)=>{byId(id).src=pair.clips[i].src});fields.forEach(field=>field.value=row[field.dataset.score]||'');byId('notes').value=row.notes||'';byId('reveal').textContent=row.unblindedAt?`Left: ${pair.clips[0].label} · Right: ${pair.clips[1].label}`:''}
byId('previous').onclick=()=>{save();index--;show()};byId('next').onclick=()=>{save();index++;show()};byId('play').onclick=()=>{for(const id of ['left','right']){const video=byId(id);video.currentTime=0;video.play().catch(()=>{})}};fields.forEach(field=>field.onchange=save);byId('notes').oninput=save;
byId('labels').onclick=()=>{save();ratings[pairs[index].id].unblindedAt=new Date().toISOString();localStorage.setItem(storageKey,JSON.stringify(ratings));const pair=pairs[index];byId('reveal').textContent=`Left: ${pair.clips[0].label} · Right: ${pair.clips[1].label}`};
byId('download').onclick=()=>{save();const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify({protocol:data.protocol,ratings},null,2)],{type:'application/json'}));a.href=url;a.download='example-subject-h3-pilot-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
byId('limits').textContent=data.protocol.heldout_limitations;show();
</script>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("comparison", type=Path)
    build(parser.parse_args().comparison)

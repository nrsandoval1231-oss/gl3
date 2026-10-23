#!/usr/bin/env python3
"""Validate generated assets and active application references; approval is a separate gate."""
import hashlib
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'web/public/brand'
def luminance(h):
    c=[int(h[i:i+2],16)/255 for i in (1,3,5)]
    c=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in c]
    return sum(v*w for v,w in zip(c,[.2126,.7152,.0722]))
def contrast(a,b):
    a,b=sorted([luminance(a),luminance(b)])
    return (b+.05)/(a+.05)
def main():
    manifest=json.loads((OUT/'asset-manifest.json').read_text())
    assert manifest['source_sha256']==hashlib.sha256((ROOT/'tools/brand/masters/symbol.svg').read_bytes()).hexdigest(), 'Stale master exports'
    assert manifest['tokens_sha256']==hashlib.sha256((ROOT/'docs/design/brand.tokens.json').read_bytes()).hexdigest(), 'Stale token exports'
    for family,h in manifest['font_sha256'].items(): assert h==hashlib.sha256((ROOT/f'web/public/fonts/{family}.ttf').read_bytes()).hexdigest(), 'Stale font exports'
    rows=manifest['assets']; names=[r['path'] for r in rows]
    assert len(names)==len(set(names)), 'Duplicate asset paths'
    assert len({Path(n).name for n in names})==len(names), 'Duplicate asset basenames'
    for row in rows:
        p=OUT/row['path']; assert p.exists(), f'Missing {p}'
        assert hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],f'Stale export: {p}'
        if p.suffix=='.svg':
            svg=ET.parse(p).getroot()
            assert svg.get('viewBox'), f'No viewBox {p}'
            assert not svg.findall('.//{http://www.w3.org/2000/svg}image'),f'Raster in SVG {p}'
        if 'width' in row:
            im=Image.open(p); assert im.size==(row['width'],row['height']),f'Dimensions {p}'
            lo,hi=im.convert('RGBA').getextrema()[3]
            assert lo==0 if row['transparent'] else lo==255,f'Transparency {p}'
    assert set(names)|{'asset-manifest.json'}=={str(p.relative_to(OUT)) for p in OUT.rglob('*') if p.is_file()},'Unmanaged/orphan public assets'
    tokens=json.loads((ROOT/'docs/design/brand.tokens.json').read_text())
    css=(ROOT/'web/src/styles/brand-tokens.css').read_text()
    for name,h in tokens['colors'].items(): assert f'--gl-{name.replace("_","-")}: {h};' in css
    for family in ['inter','sora']:
        for suffix in ['ttf','woff2','-OFL.txt']:
            p=ROOT/'web/public/fonts'/f'{family}{suffix if suffix.startswith("-") else "."+suffix}'
            assert p.is_file() and p.stat().st_size>100,f'Missing font/license: {p}'
    definitions=set(re.findall(r'(--[\w-]+)\s*:',css))
    sources=list((ROOT/'web/src').rglob('*.css'))+list((ROOT/'web/src').rglob('*.tsx'))+[ROOT/'web/index.html',ROOT/'web/public/site.webmanifest']
    for p in sources:
        s=p.read_text()
        assert not re.search(r'aperture|Diatype|DejaVu|lockup-pursuits|#17324A|#3B82F6',s,re.I),f'Legacy identity {p}'
        assert not re.search(r'var\(--[^)]+\)[0-9a-f]{2}\b',s,re.I),f'Invalid variable alpha {p}'
        for ref in re.findall(r'[\"\'](/brand/[\w./-]+)',s): assert (ROOT/'web/public'/ref.lstrip('/')).is_file(),f'Broken {ref}'
        if p.suffix=='.css':
            for var in re.findall(r'var\((--gl-[\w-]+)\)',s): assert var in definitions,f'Undefined {var} in {p}'
    colors={**tokens['colors'], 'white':'#FFFFFF',**tokens['status_colors']}
    pairs=[('graphite','white'),('deep_slate','white'),('harbor_navy','fog'),('white','harbor_navy'),('white','deep_slate'),('danger','danger_surface'),('success','success_surface'),('warning','warning_surface')]
    for a,b in pairs: assert contrast(colors[a],colors[b])>=4.5,f'AA contrast failure {a}/{b}'
    print(f'PASS: {len(rows)} assets; hashes, SVG, dimensions, alpha, names, references, fonts, tokens and {len(pairs)} semantic AA pairs.')
    print(f'Visual fidelity approval: {manifest["approval"]}; this check does not authorize merge.')
if __name__=='__main__': main()

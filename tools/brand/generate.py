#!/usr/bin/env python3
"""Deterministic GridLens exports. Unverified geometry requires --review-candidate."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import cairosvg
from PIL import Image
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'web/public/brand'
TOKENS = ROOT / 'docs/design/brand.tokens.json'
MASTER = ROOT / 'tools/brand/masters/symbol.svg'
FONT = ROOT / 'web/public/fonts/inter.ttf'
NS = '{http://www.w3.org/2000/svg}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-candidate', action='store_true')
    args = parser.parse_args()
    for path in [TOKENS, MASTER, FONT, ROOT/'web/public/fonts/sora.ttf']:
        if not path.is_file():
            raise SystemExit(f'Missing required source: {path.relative_to(ROOT)}')
    tokens = json.loads(TOKENS.read_text(encoding='utf-8'))
    verified = tokens['source']['geometry_verified'] and tokens['source']['wordmark_verified']
    if not verified and not args.review_candidate:
        raise SystemExit('Unverified source geometry/wordmark: visual approval required. Use --review-candidate for review exports only.')
    colors = {**tokens['colors'], 'white': '#FFFFFF'}
    master = ET.parse(MASTER).getroot()
    if master.get('viewBox') != '0 0 200 200' or master.findall('.//'+NS+'image'):
        raise SystemExit('Master must be path geometry with viewBox 0 0 200 200, no raster images')
    font = instantiateVariableFont(TTFont(FONT, recalcTimestamp=False), {'wght': 300, 'opsz': 32}, inplace=False)
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    units = font['head'].unitsPerEm
    records = []
    OUT.mkdir(parents=True, exist_ok=True)

    def lettering(label, x, y, size=22, fill=None, tracking=0, split=False):
        pen_paths = []
        cursor = 0
        for index, char in enumerate(label):
            glyph = glyphs[cmap[ord(char)]]
            pen = SVGPathPen(glyphs); glyph.draw(pen)
            segment = f' fill="{colors["sea_cliff" if fill == colors["fog"] else "slate_steel"]}"' if split and index >= 4 else ''
            pen_paths.append(f'<path{segment} transform="translate({cursor:.4f} 0)" d="{pen.getCommands()}"/>')
            cursor += glyph.width + tracking * units / size
        return f'<g fill="{fill or colors["harbor_navy"]}" transform="translate({x} {y}) scale({size/units:.8f} {-size/units:.8f})">'+''.join(pen_paths)+'</g>'

    def symbol(x=0, y=0, size=200, treatment='light'):
        fills = {'light': [tokens['semantic']['logo_primary'],tokens['semantic']['logo_secondary'],tokens['semantic']['logo_primary']], 'dark': [tokens['semantic']['logo_dark_primary'],tokens['semantic']['logo_dark_secondary'],tokens['semantic']['logo_dark_primary']], 'navy':['harbor_navy']*3, 'white':['white']*3}[treatment]
        paths = ''.join(f'<path fill="{colors[c]}" d="{p.attrib["d"]}"/>' for p,c in zip(master.findall(NS+'path'), fills))
        return f'<g transform="translate({x} {y}) scale({size/200})">{paths}</g>'

    def svg(w, h, body, title='GridLens'):
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img"><title>{title}</title>{body}</svg>\n'

    def write(name, data, **meta):
        p=OUT/name; p.parent.mkdir(parents=True, exist_ok=True)
        data = data.encode() if isinstance(data,str) else data
        p.write_bytes(data)
        records.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),**meta})

    def raster(name, source, width, height, transparent=True):
        raw=cairosvg.svg2png(bytestring=source.encode(),output_width=width,output_height=height)
        im=Image.open(io.BytesIO(raw)).convert('RGBA')
        assert im.size == (width,height)
        if transparent and im.getextrema()[3][0] != 0:
            raise ValueError(f'{name} lacks transparency')
        for fmt in ['png','webp']:
            buf=io.BytesIO(); im.save(buf, format=fmt, **({'lossless':True,'method':6} if fmt=='webp' else {}))
            write(f'{name}.{fmt}',buf.getvalue(),width=width,height=height,transparent=transparent)
        return im

    for treatment in ['light','dark','navy','white']:
        ink=colors['fog' if treatment=='dark' else 'white' if treatment=='white' else 'harbor_navy']
        bodies={
            'symbol':(240,240,symbol(20,20,200,treatment)),
            'horizontal':(1000,240,symbol(20,20,200,treatment)+lettering('GRIDLENS',270,153,91,ink,12, treatment in ['light','dark'])),
            'primary-horizontal':(1000,240,symbol(20,20,200,treatment)+lettering('GRIDLENS',270,112,78,ink,11, treatment in ['light','dark'])+lettering('COMMERCIAL INTELLIGENCE',273,168,20,ink,4)+lettering('FOR CONSTRAINED POWER',273,204,20,ink,4)),
            'stacked':(660,400,symbol(240,20,180,treatment)+lettering('GRIDLENS',60,286,66,ink,10, treatment in ['light','dark'])+lettering('COMMERCIAL INTELLIGENCE',118,337,17,ink,3)+lettering('FOR CONSTRAINED POWER',126,370,17,ink,3)),
            'wordmark':(800,180,lettering('GRIDLENS',30,124,92,ink,12, treatment in ['light','dark'])),
        }
        for kind,(w,h,body) in bodies.items():
            source=svg(w,h,body)
            write(f'logos/{kind}-{treatment}.svg',source)
            for size in [256,512,1024,2048]:
                raster(f'rasters/{kind}-{treatment}-{size}',source,size,round(size*h/w))
    write('masters/symbol.svg',MASTER.read_bytes())
    icon=svg(512,512,f'<rect width="512" height="512" rx="100" fill="{colors["harbor_navy"]}"/>'+symbol(80,80,352,'dark'))
    write('icons/app-dark.svg',icon)
    write('icons/app-light.svg',svg(512,512,f'<rect width="512" height="512" rx="100" fill="{colors["white"]}"/>'+symbol(80,80,352,'light')))
    square_icon=svg(512,512,f'<rect width="512" height="512" fill="{colors["harbor_navy"]}"/>'+symbol(80,80,352,'dark'))
    write('icons/favicon.svg',svg(240,240,symbol(20,20,200)))
    for size in [16,32,48]:
        raster(f'icons/favicon-{size}',svg(240,240,symbol(20,20,200)),size,size)
    for name,size in [('apple-touch-icon',180),('pwa-192',192),('pwa-512',512)]:
        raster(f'icons/{name}',square_icon if name=='apple-touch-icon' else icon,size,size,name!='apple-touch-icon')
    mask=svg(512,512,f'<rect width="512" height="512" fill="{colors["harbor_navy"]}"/>'+symbol(116,116,280,'dark'))
    raster('icons/pwa-maskable-512',mask,512,512,False)
    im=Image.open(OUT/'icons/favicon-48.png'); buf=io.BytesIO(); im.save(buf,format='ICO',sizes=[(16,16),(32,32),(48,48)])
    write('icons/favicon.ico',buf.getvalue())
    social=svg(1200,630,f'<rect width="1200" height="630" fill="{colors["harbor_navy"]}"/>'+symbol(90,140,280,'dark')+lettering('GRIDLENS',440,290,79,colors['fog'],9)+lettering('COMMERCIAL INTELLIGENCE',444,357,23,colors['fog'],3)+lettering('FOR CONSTRAINED POWER',444,396,23,colors['fog'],3))
    write('social/sharing.svg',social); raster('social/sharing',social,1200,630,False)
    # Print templates use millimetre-sized SVG roots and outlined text.
    specifications={
        'business-card':(89,51,8,8,14,'NAME / TITLE'),
        'letterhead':(210,297,18,18,23,'COMMERCIAL INTELLIGENCE'),
        'presentation-cover':(320,180,24,30,45,'PRESENTATION TITLE'),
        'proposal-cover':(210,297,20,38,40,'PROPOSAL TITLE'),
        'notebook-cover':(148,210,34,50,70,''),
        'tshirt-placement':(300,350,110,70,80,''),
        'polo-embroidery':(80,60,20,10,40,''),
        'hat-embroidery':(100,50,33,8,34,''),
        'tumbler-mark':(60,100,10,26,40,''),
        'signage':(1000,300,30,50,200,''),
    }
    for name,(w,h,x,y,size,label) in specifications.items():
        body=symbol(x,y,size,'navy')
        if name=='signage': body+=lettering('GRIDLENS',280,183,80,None,10)
        elif label:
            body+=lettering('GRIDLENS',x+size+5,y+size*.68,min(size*.30,17),None,min(size*.04,2))
            body+=lettering(label,x,y+size+14,min(w*.035,6))
        if name=='business-card': body+=lettering('[EMAIL] / [PHONE]',x,44,2.8)
        source=svg(w,h,body).replace(f'width="{w}" height="{h}"',f'width="{w}mm" height="{h}mm"')
        write(f'production/{name}.svg',source)
    write('production/email-signature.html','<!doctype html><html lang="en"><meta charset="utf-8"><title>GridLens email signature template</title><table role="presentation" style="font-family:Arial,sans-serif;color:#0B1F33"><tr><td><img src="../rasters/horizontal-light-512.png" width="160" height="38" alt="GridLens"><br><strong>[Name]</strong><br>[Title] · GridLens<br><a href="mailto:replace@example.com" style="color:#23384C">[Email]</a><br>[Phone]</td></tr></table><!-- Replace placeholders and replace the relative image source with an absolute hosted rasters/horizontal-light-512.png URL before sending. -->\n')
    # The visual comparison sheet deliberately exposes uncertainty.
    board=svg(1200,700,f'<rect width="1200" height="700" fill="#FFFFFF"/>'+lettering('GRIDLENS / VECTOR REVIEW',50,60,28)+lettering('CANDIDATE - OWNER FIDELITY APPROVAL REQUIRED',50,100,17)+symbol(60,160,280)+f'<rect x="440" y="140" width="370" height="360" fill="{colors["harbor_navy"]}"/>'+symbol(480,180,280,'dark')+symbol(890,210,170,'navy')+lettering('LIGHT',60,545,19)+lettering('DARK',480,545,19)+lettering('ONE INK',890,545,19)+lettering('Review: rounded return, diagonal boundary, hidden-L continuity, wordmark spacing.',50,610,17)+lettering('Flat color interpretation of shaded reference; not an approved replacement master.',50,650,17))
    write('review/comparison.svg',board); raster('review/comparison',board,1200,700,False)
    # Pinned fonts are converted locally; no runtime external font requests.
    for family in ['inter','sora']:
        f=TTFont(ROOT/f'web/public/fonts/{family}.ttf', recalcTimestamp=False); f.flavor='woff2'; f.save(ROOT/f'web/public/fonts/{family}.woff2')
    css=['/* Generated by tools/brand/generate.py. */']
    for family,display in [('inter','Inter'),('sora','Sora')]:
        css.append(f'@font-face{{font-family:"{display}";src:url("/fonts/{family}.woff2") format("woff2");font-weight:100 900;font-style:normal;font-display:swap;}}')
    css.append(':root {')
    css.extend(f'  --gl-{k.replace("_","-")}: {v};' for k,v in colors.items())
    css.extend(f'  --gl-{k.replace("_","-")}: {v};' for k,v in tokens['status_colors'].items())
    css.extend(f'  --gl-{k.replace("_","-")}: var(--gl-{v.replace("_","-")});' for k,v in tokens['semantic'].items())
    css.extend(['  --gl-ink: var(--gl-text);','  --gl-muted-ink: var(--gl-text-secondary);','  --gl-line: var(--gl-border);','  --gl-type: "Inter", Arial, sans-serif;','  --gl-display-type: "Sora", "Inter", Arial, sans-serif;','  --gl-ui-accent: var(--gl-interactive);','  --gl-ui-selected: var(--gl-selected);','  --gl-shadow: rgb(11 31 51 / 8%);','}'])
    (ROOT/'web/src/styles/brand-tokens.css').write_text('\n'.join(css)+'\n', encoding='utf-8')
    names=[r['path'] for r in records]
    assert len(names)==len(set(names))
    write('asset-manifest.json',json.dumps({'version':tokens['version'],'approval':'owner-approved' if verified else 'review-candidate','source_sha256':hashlib.sha256(MASTER.read_bytes()).hexdigest(),'tokens_sha256':hashlib.sha256(TOKENS.read_bytes()).hexdigest(),'font_sha256':{family:hashlib.sha256((ROOT/f'web/public/fonts/{family}.ttf').read_bytes()).hexdigest() for family in ['inter','sora']},'assets':records},indent=2)+'\n')
    print(f'Generated {len(names)} assets; approval={"owner-approved" if verified else "review-candidate"}')

if __name__ == '__main__': main()

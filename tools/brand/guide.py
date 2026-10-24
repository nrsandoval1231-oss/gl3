#!/usr/bin/env python3
"""Build a reproducible review PDF from canonical tokens and generated artwork."""
import json
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from fontTools.ttLib import TTFont as Font
from fontTools.varLib.instancer import instantiateVariableFont
import tempfile
ROOT=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as temp:
    for family,axes in [('inter',{'wght':400,'opsz':14}),('sora',{'wght':500})]:
        f=instantiateVariableFont(Font(ROOT/f'web/public/fonts/{family}.ttf', recalcTimestamp=False),axes,inplace=False)
        p=Path(temp)/f'{family}.ttf'; f.save(p);pdfmetrics.registerFont(TTFont(family,str(p)))
    output=ROOT/'docs/brand/GRIDLENS_BRAND_GUIDE.pdf'
    c=canvas.Canvas(str(output),pagesize=(842,595),invariant=1)
    c.setTitle('GridLens brand system — review candidate')
    def page(title,number):
        c.setFillColor(HexColor('#FFFFFF'));c.rect(0,0,842,595,fill=1,stroke=0)
        c.setFillColor(HexColor('#0B1F33'));c.setFont('sora',26);c.drawString(44,536,title)
        c.setFont('inter',10);c.drawString(44,32,'GRIDLENS / 2.0 / REVIEW CANDIDATE — NOT APPROVED FOR PRODUCTION')
        c.drawRightString(798,32,str(number))
    def line(y,text,size=12):
        c.setFont('inter',size);c.setFillColor(HexColor('#23384C'));c.drawString(44,y,text)
    page('Commercial intelligence for constrained power',1)
    c.drawImage(ImageReader(ROOT/'web/public/brand/rasters/horizontal-light-1024.png'),44,330,700,168,mask='auto')
    line(270,'Real power. Real projects. Before they become obvious.',20)
    line(225,'Owner board: October 23, 2026. Seven printed sRGB labels; Sora and Inter typography.')
    line(197,'Exact G/L contours, flat segmentation and outlined wordmark require owner review.')
    line(169,'This PDF accompanies GRIDLENS_BRAND_GUIDELINES.md; it is not a visual approval.')
    c.showPage();page('One symbol / four treatments',2)
    c.drawImage(ImageReader(ROOT/'web/public/brand/review/comparison.png'),44,90,754,440)
    c.showPage();page('Seven colors / accessible application semantics',3)
    tokens=json.loads((ROOT/'docs/design/brand.tokens.json').read_text())
    for i,(name,value) in enumerate(tokens['colors'].items()):
        x=44+(i%4)*190;y=415-(i//4)*155
        c.setFillColor(HexColor(value));c.roundRect(x,y,170,75,5,fill=1,stroke=0)
        c.setFillColor(HexColor('#23384C'));c.setFont('inter',12);c.drawString(x,y-24,name.replace('_',' ').title());c.drawString(x,y-43,value)
    line(145,'White is a neutral surface. Graphite/Deep Slate text; navy buttons with white labels.')
    line(119,'Status exceptions are paired with text. No universal CMYK or Pantone equivalents claimed.')
    c.showPage();page('Typography / production / release control',4)
    c.setFont('sora',36);c.drawString(44,452,'Sora — Display & headings')
    line(400,'Inter — Interface, tables, body, labels and data',24)
    line(348,'Wordmark: outlined Inter Light reconstruction; exact lettering still needs confirmation.')
    for y,text in zip(range(298,99,-28),[
        'Keep 0.2 symbol heights of clear space; minimum symbol 24 px / 10 mm print.',
        'Embroidery: one ink, 34 mm minimum; stitch-out required for narrow diagonal.',
        'Templates use millimetre canvases. Obtain vendor bleed, dielines and material proofs.',
        'Do not stretch, rotate, add gradients, separate the L or use historical identity assets.',
        'Regenerate from tokens + SVG master; inspect asset manifest and browser captures.',
        'No final vendor release or merge before owner logo-fidelity and application acceptance.',
        'See the Markdown guidelines for the complete asset index and reproducible commands.'
    ]):line(y,text)
    c.save()
print(output)

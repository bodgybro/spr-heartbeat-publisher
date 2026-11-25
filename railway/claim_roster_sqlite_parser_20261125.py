#!/usr/bin/env python3
"""Private roster PDF row extraction for SQLite. No names or source PDFs in index.
Index current and archived PDF copies by SHA, exact printed dates and line.
Fail closed: incomplete/ambiguous rows are never served from SQLite.
"""
import argparse, datetime as dt, hashlib, json, re
import xml.etree.ElementTree as ET
from pathlib import Path
from functools import cmp_to_key
DEPOTS={'auburn','blacktown','campbelltown','central','cronulla','flemington','hornsby','leppington','mortdale','northsydney','north-sydney','penrith','richmond','waterfall'}
DATE=re.compile(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})')
NUM=re.compile(r'\d{1,4}')
def iso(s):
    m=DATE.fullmatch(s)
    if not m:return None
    try:return dt.date(int(m[3])+(2000 if len(m[3])==2 else 0),int(m[2]),int(m[1])).isoformat()
    except ValueError:return None
def tag(e):return e.tag.rsplit('}',1)[-1]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def page_rows(page):
    w,h=float(page.attrib['width']),float(page.attrib['height'])
    # PDF word coordinates are top-down. Use the lower glyph edge as a
    # baseline proxy and the same left-boundary/row midpoint geometry as
    # the established reader. Preserve complete words and reading order.
    items=[]
    for e in page.iter():
        if tag(e)!='word':continue
        t=''.join(e.itertext()).strip()
        if not t:continue
        x=float(e.attrib['xMin']);y=float(e.attrib['yMax'])
        items.append((x,y,float(e.attrib['xMax'])-x,t))
    dates=[x for x in items if iso(x[3])]
    clusters=[]
    for a in dates:
        c=next((c for c in clusters if abs(c[0]-a[1])<=4),None)
        if c is None:c=[a[1],[]];clusters.append(c)
        c[1].append(a);c[0]=sum(i[1] for i in c[1])/len(c[1])
    if not clusters:return []
    hdr=sorted(clusters,key=lambda c:(-len(c[1]),c[0]))[0]
    ds=sorted(hdr[1],key=lambda a:a[0])
    labels=[iso(x[3]) for x in ds]
    # Strict 14-day header requirement. The normal PDF reader is the
    # fallback for partial pages, malformed headers or split weeks.
    if len(ds)!=14 or len(set(labels))!=14:return []
    start=dt.date.fromisoformat(labels[0])
    if start.weekday()!=6 or labels!=[(start+dt.timedelta(days=i)).isoformat() for i in range(14)]:return []
    gaps=[b[0]-a[0] for a,b in zip(ds,ds[1:]) if b[0]-a[0]>8]
    if not gaps:return []
    gap=sorted(gaps)[len(gaps)//2]
    inset=max(.5,min(3,gap*.02));tol=max(1.5,w*.0015)
    cols=[(max(0,d[0]-inset),min(w,(ds[i+1][0] if i<13 else d[0]+gap)-inset)) for i,d in enumerate(ds)]
    linehdr=next((a for a in items if a[3].lower()=='line'),None)
    right=linehdr[0]+max(linehdr[2],8)+2.5 if linehdr else w*.055
    right=min(w*.075,max(w*.04,right))
    anchors=[a for a in items if a[0]<right and NUM.fullmatch(a[3]) and a[1]>hdr[0]+8]
    nums=sorted(a[1] for a in items if a[0]<w*.085 and NUM.fullmatch(a[3]))
    seen=set();out=[]
    for a in sorted(anchors,key=lambda a:a[1]):
        center=a[1]
        if round(center) in seen:continue
        seen.add(round(center))
        above=max((y for y in nums if y<center-2),default=None)
        below=min((y for y in nums if y>center+2),default=None)
        top=(above+center)/2 if above is not None else center-32
        bottom=(below+center)/2 if below is not None else center+32
        if bottom-top<36:top=center-22;bottom=center+22
        row=[i for i in items if max(hdr[0]+3,top-2)<=i[1]<=min(h,bottom+2)]
        cells=[]
        for label,(left,rightcol) in zip(labels,cols):
            words=[i for i in row if left-tol<=i[0]+min(4,max(0,i[2])*.12)<rightcol-tol]
            words.sort(key=cmp_to_key(lambda x,y: (x[1]>y[1])-(x[1]<y[1]) if abs(x[1]-y[1])>3 else (x[0]>y[0])-(x[0]<y[0])))
            cell=' '.join(i[3] for i in words)
            # Date cells should not contain adjacent date headers. A blank
            # cell isn't proof of an OFF day; decline the entire row.
            if not cell or len(cell)>500 or any(iso(i[3]) in labels for i in words):break
            cells.append({'date':label,'cell':cell})
        if len(cells)==14:out.append((start.isoformat(),str(int(a[3])),cells))
    return out
def parse_bytes(data):
    import fitz
    doc=fitz.open(stream=data,filetype='pdf')
    rows={};conflict=set()
    try:
        for pdfpage in doc:
            # Use the same word positions as the existing line-173 audit.
            page=ET.Element('page',width=str(pdfpage.rect.width),height=str(pdfpage.rect.height))
            for x0,y0,x1,y1,word,*_ in pdfpage.get_text("words",sort=False):
                e=ET.SubElement(page,'word',xMin=str(x0),yMin=str(y0),xMax=str(x1),yMax=str(y1))
                e.text=word
            for start,line,cells in page_rows(page):
                key=(start,line)
                if key in rows and rows[key]!=cells:conflict.add(key)
                rows[key]=cells
    finally:doc.close()
    for k in conflict:rows.pop(k,None)
    return rows
def payload(data,cache_path):
    if not data.startswith(b'%PDF-'):raise ValueError('Invalid PDF')
    parts=cache_path.split('/')
    if len(parts)!=4:raise ValueError('Unexpected roster path')
    depot,crew,kind,filename=parts
    if depot not in DEPOTS or crew not in ('drivers','guards') or kind not in ('daily','period','fortnight') or not re.fullmatch(r'[A-Za-z0-9-]{5,45}\.pdf',filename):raise ValueError('Unexpected roster filename')
    rows=parse_bytes(data)
    if not rows:raise ValueError('No complete unambiguous roster rows')
    return {'path':cache_path,'sha':hashlib.sha256(data).hexdigest(),'size':len(data),'rows':[{'start':start,'line':line,'days':cells} for (start,line),cells in sorted(rows.items())]}
if __name__=='__main__':
    import sys
    ap=argparse.ArgumentParser()
    ap.add_argument('pdf',type=Path);ap.add_argument('cache_path');ap.add_argument('output',type=Path)
    args=ap.parse_args()
    result=payload(args.pdf.read_bytes(),args.cache_path)
    args.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('ROSTER_SQLITE_PARSED '+args.cache_path+' rows='+str(len(result['rows'])))

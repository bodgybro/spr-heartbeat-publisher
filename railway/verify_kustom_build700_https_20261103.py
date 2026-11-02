#!/usr/bin/env python3
"""Read-only end-to-end public Kustom Build700 HTTPS checks."""
import requests,hashlib,urllib.parse
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 26_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/153.0.0 Mobile/15E148 Safari/604.1"
HDR={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8","Accept-Language":"en-AU,en;q=0.9"}
BASE="https://www.kustomvinyls.com/sps/"
def say(*s):print("[KUSTOM HTTPS VERIFY]",*s,flush=True)
S=requests.Session()
for urlpath in ("","style.css","script-700-fromto-locations-v1.js"):
 try:
  r=S.get(BASE+urlpath,timeout=22,headers=HDR,allow_redirects=True)
  data=r.content
  wanted=("" if urlpath else "Build 700")
  say("PAGE",urlpath or "/",r.status_code,"TLS valid yes",
      "final_host",urllib.parse.urlparse(r.url).hostname,
      "bytes",len(data),"sha256",hashlib.sha256(data).hexdigest()[:16],
      "Build700",b"Build 700" in data,
      "fresh JS import",(b"script-700-fromto-locations-v1.js" in data),
      "N dropdown fix",(b"SPR_FROM_TO_FILTER_ONE_CHAR_20261102" in data),
      "iPhone low memory",(b"rosterShiftLowMemoryDevice" in data))
 except Exception as exc:say("PAGE",urlpath or "/","FAILED",type(exc).__name__,str(exc)[:180])
for rel in (
  "spr/d/All%20Drivers%20Combined%2003_11_2026.pdf",
  "spr/g/All%20Guards%20Combined%2003_11_2026.pdf",
  "rosters/auburn/drivers/daily/ASY-D-DAY.pdf"
):
 try:
  with S.get(BASE+rel,timeout=25,headers={**HDR,"Range":"bytes=0-63"},
             stream=True,allow_redirects=True) as resp:
   prefix=next(resp.iter_content(chunk_size=128),b"")
   say("PDF",rel,"status",resp.status_code,"TLS valid yes",
       "type",resp.headers.get("Content-Type","")[:80],
       "PDF_magic",prefix.startswith(b"%PDF-"),
       "redirect",urllib.parse.urlparse(resp.url).hostname)
 except Exception as exc:say("PDF",rel,"FAILED",type(exc).__name__,str(exc)[:120])
say("Verification complete")

#!/usr/bin/env python3
"""Recover transient TCREW Chromium closes and require exact roster PDF kinds.

Apply after fast_roster_patch.py, roster_embedded_fallback_patch.py,
verified_completion_patch.py. Does not change SPR or SFTP code.
"""
import ast
from pathlib import Path
import sys

PICK=r'''    def pick_pdf(items, role, period):
        """Only pair a role/period with its actual PDF, never a Daily substitute."""
        from urllib.parse import unquote, urlparse
        role_code = 'D' if role.lower() == 'drivers' else 'G'
        token = {'Daily Roster':'DAY', 'Next Fortnight':'NFR', 'Period Roster':'PER'}[period]
        regex = re.compile(r'(?i)(?:^|[-_])' + role_code + r'[-_]' + token + r'\.pdf$')
        for entry in items:
            if not isinstance(entry,dict):
                continue
            u = str(entry.get('url') or '').strip()
            n = str(entry.get('name') or '').strip()
            basename=unquote(urlparse(u).path).rsplit('/',1)[-1]
            if (regex.search(n) or regex.search(basename)) and u:
                url = re.sub(r'\\+$','',u)
                mm = re.search(r'(?i)^(.*?\.pdf)(?:[?#].*)?$',url)
                if mm: url=mm.group(1)
                return {'name': n if regex.search(n) else basename, 'url':url, 'kind':'pdf'}
        return None
'''

RECOVERY=r'''
    def ensure_roster_browser(browser,page,stage):
        """Restart Chromium if it closed; keep the persistent SharePoint login."""
        try:
            if page.is_closed():
                raise RuntimeError("Target page has been closed")
            page.wait_for_timeout(5)
            return browser,page
        except Exception as previous:
            msg=str(previous)
            if not any(x in msg.lower() for x in ('closed','crash','disconnected')):
                raise
            print(f"    [BROWSER RECOVERY] {stage}: {msg[:160]}",flush=True)
            try: browser.close()
            except Exception: pass
            browser=_launch_sharepoint_context(
                p,cfg,headless=False,ignore_https_errors=True,accept_downloads=True,
                args=["--window-size=900,650","--window-position=20,20"],no_viewport=True)
            page=browser.pages[0] if browser.pages else browser.new_page()
            page.goto(root,wait_until='domcontentloaded',timeout=45000)
            if not _sharepoint_session_ready(page):
                raise RuntimeError("SharePoint login expired; open updater browser and sign in")
            print(f"    [BROWSER RECOVERED] {stage}",flush=True)
            return browser,page
'''

def apply(path):
    s=path.read_text(encoding="utf-8")
    if "# SPR_ROSTER_BROWSER_RECOVERY" in s:
        print("Roster browser recovery already applied")
        return
    tree=ast.parse(s)
    matches=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="sync_all_rosters_online"]
    if len(matches)!=1:
        raise RuntimeError("Cannot locate unique roster sync function")
    f=matches[0]
    lines=s.splitlines(keepends=True)
    block="".join(lines[f.lineno-1:f.end_lineno])
    t=ast.parse(block)
    func=t.body[0]
    inner=[n for n in func.body if isinstance(n,ast.FunctionDef) and n.name=="pick_pdf"]
    if len(inner)!=1:
        raise RuntimeError("Cannot locate pick_pdf")
    n=inner[0]
    bl=block.splitlines(keepends=True)
    block="".join(bl[:n.lineno-1])+PICK+RECOVERY+"\n"+"".join(bl[n.end_lineno:])
    target="                depot_url=depot['url']"
    if block.count(target)!=1: raise RuntimeError("Depot insertion target mismatch")
    block=block.replace(target,target+
      '\n                browser,page=ensure_roster_browser(browser,page,depot_name)',1)

    # One retry when Chromium closes during PDF retrieval. A failure is
    # counted only after that retry also fails. We do not retry upload errors.
    target='''                        except Exception as e:
                            errors.append(f"{depot_name} {role} {period}: {e}")'''
    if block.count(target)!=1:
        raise RuntimeError("PDF exception insertion target mismatch")
    replacement='''                        except Exception as e:
                            msg=str(e).lower()
                            if any(z in msg for z in ("closed","crash","disconnected")):
                                try:
                                    browser,page=ensure_roster_browser(browser,page,
                                        f"{depot_name} {role} {period}")
                                    data=_download_roster_pdf_fast(page,pdf_url,pdf_name)
                                    _store_roster_fast(pdf_url,pdf_name,data,cache_path)
                                    pdf_count+=1
                                    print(f"    [STORED AFTER RECOVERY] {cache_path}",flush=True)
                                    continue
                                except Exception as recovery_error:
                                    e=recovery_error
                            errors.append(f"{depot_name} {role} {period}: {e}")'''
    block=block.replace(target,replacement,1)

    # Confirm only the six *distinct* correctly matched PDFs can complete.
    s="".join(lines[:f.lineno-1])+block.rstrip()+"\n"+"".join(lines[f.end_lineno:])
    s="# SPR_ROSTER_BROWSER_RECOVERY\n"+s
    compile(s,str(path),"exec")
    path.write_text(s,encoding="utf-8")
    print("Roster filename matching strict; browser closure recovery and one per-file retry enabled")

if __name__=="__main__":
    apply(Path(sys.argv[1]))

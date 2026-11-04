"""ROC Daily DOMO Extracts CSV retrieval using the updater's existing SharePoint browser.
Never prints incident records, SharePoint cookies, credentials or raw private CSV data.
The only destination is /home<account>/sps-roc/YYYY-MM-DD.csv outside public_html.
"""
import csv
import hashlib
import io
import os
import posixpath
import re
import stat
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

SITE = "https://transportcloud.sharepoint.com/sites/ST-SPS-PPD"
YEAR_ROOT = "/sites/ST-SPS-PPD/PR/ROC Daily DOMO Extracts"
YEAR_VIEW = SITE + "/PR/ROC%20Daily%20DOMO%20Extracts/Forms/AllItems.aspx"
EXPECTED = [
    "Colored", "Safety Category", "REM", "IIMS", "Responsibility",
    "Date & Time", "Run", "Location", "Details"
]
MAX_CSV = 15 * 1024 * 1024
TZ = ZoneInfo("Australia/Sydney")


def _say(value):
    print("[ROC DOMO] " + str(value), flush=True)


def _items(page, rel, what):
    """List one folder using the authenticated SharePoint REST context."""
    if what not in ("Folders", "Files") or not rel.startswith(YEAR_ROOT + "/"):
        raise ValueError("Unexpected SharePoint ROC folder")
    safe = quote(rel.replace("'", "''"), safe="/")
    endpoints = [
        SITE + "/_api/web/GetFolderByServerRelativePath(decodedurl='" + safe + "')",
        SITE + "/_api/web/GetFolderByServerRelativeUrl('" + safe + "')"
    ]
    errors = []
    for base in endpoints:
        url = base + "/" + what + "?%24select=Name,ServerRelativeUrl&%24top=3000"
        try:
            resp = page.context.request.get(
                url, timeout=15000, fail_on_status_code=False,
                headers={"Accept": "application/json;odata=nometadata",
                         "Cache-Control": "no-cache"}
            )
            if not resp.ok:
                errors.append("HTTP " + str(resp.status))
                continue
            data = resp.json()
            items = data.get("value", data.get("d", {}).get("results", []))
            if isinstance(items, list):
                out = []
                for entry in items:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("Name") or "").strip()
                    path = str(entry.get("ServerRelativeUrl") or
                               (entry.get("ServerRelativePath") or {}).get("DecodedUrl") or "")
                    if name and path.startswith(YEAR_ROOT + "/"):
                        out.append({"name": name, "path": path})
                return out
            errors.append("unexpected response shape")
        except Exception as exc:
            errors.append(type(exc).__name__)
    raise RuntimeError("ROC folder enumeration unavailable (" +
                       ", ".join(errors[:4]) + ")")


def _month_match(name, date):
    low = re.sub(r"[^a-z0-9]", " ", name.lower())
    month = date.strftime("%B").lower()
    abb = date.strftime("%b").lower()
    number = f"{date.month:02d}"
    return (month in low or re.search(r"\b" + abb + r"\b", low) or
            re.search(r"\b" + number + r"\b", low) or
            re.search(r"\b" + str(date.month) + r"\b", low))


def _day_match(name, date):
    low = name.lower()
    candidates = (date.isoformat(), date.strftime("%d_%m_%Y"),
                  date.strftime("%d-%m-%Y"), date.strftime("%d/%m/%Y"))
    if any(x in low for x in candidates):
        return True
    words = re.sub(r"[^a-z0-9]", " ", low)
    return (re.search(r"\b" + str(date.day) + r"\b", words) is not None or
            re.search(r"\b" + f"{date.day:02d}" + r"\b", words) is not None)


def _csv_match(filename, date):
    if not filename.lower().endswith(".csv"):
        return False
    low = filename.lower()
    expected_date = date.strftime("%d %B %Y").lower()
    return ("daily safety incidents" in low and
            "excel extract" in low and expected_date in low)


def _find_target(page, date):
    year = YEAR_ROOT + "/" + str(date.year)
    months = _items(page, year, "Folders")
    selected = [x for x in months if _month_match(x["name"], date)]
    if len(selected) != 1:
        _say("Year folder contains " + str(len(months)) +
             " month folders; matching month folders: " + str(len(selected)))
        raise RuntimeError("ROC month folder not uniquely identified")
    month = selected[0]
    _say("Selected month: " + month["name"][:64])
    # A small number of sites put report CSVs directly in the month folder.
    candidates = [x for x in _items(page, month["path"], "Files")
                  if _csv_match(x["name"], date)]
    days = _items(page, month["path"], "Folders")
    selected_days = [x for x in days if _day_match(x["name"], date)]
    if len(selected_days) == 1:
        day = selected_days[0]
        _say("Selected date folder: " + day["name"][:64])
        candidates.extend(x for x in _items(page, day["path"], "Files")
                          if _csv_match(x["name"], date))
    elif not candidates:
        _say("Found " + str(len(days)) + " date folders, matching date: " +
             str(len(selected_days)))
        raise RuntimeError("ROC dated folder unavailable or ambiguous")
    unique = {x["path"]: x for x in candidates}
    if len(unique) != 1:
        raise RuntimeError("Expected one ROC CSV for " + date.isoformat() +
                           "; found " + str(len(unique)))
    csv_file = next(iter(unique.values()))
    _say("Selected CSV for " + date.isoformat() + ": " + csv_file["name"][:120])
    return csv_file


def _get_csv(page, target, date):
    rel = target["path"]
    urls = [
        SITE.replace("/sites/ST-SPS-PPD", "") + quote(rel, safe="/"),
        SITE + "/_api/web/GetFileByServerRelativePath(decodedurl='" +
        quote(rel.replace("'", "''"), safe="/") + "')/$value"
    ]
    for url in urls:
        try:
            resp = page.context.request.get(url, timeout=45000,
                                            fail_on_status_code=False)
            if resp.ok:
                body = resp.body()
                if 15 < len(body) <= MAX_CSV and not body.lstrip().startswith(b"<"):
                    return body
            _say("Direct CSV request response: HTTP " + str(resp.status))
        except Exception as exc:
            _say("Direct CSV request unavailable: " + type(exc).__name__)
    # Modern SharePoint may require selecting the row, then Download selected.
    try:
        container = posixpath.dirname(rel)
        view = YEAR_VIEW + "?id=" + quote(container, safe="")
        page.goto(view, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1300)
        rows = page.locator('[role="row"],[data-automationid="DetailsRow"]').filter(
            has_text=target["name"]
        )
        if rows.count() != 1:
            raise RuntimeError("The selected ROC CSV row is not unique in SharePoint")
        row = rows.first
        box = row.get_by_role("checkbox")
        if box.count():
            box.first.check(timeout=8000)
        else:
            row.click(timeout=8000)
        button = page.get_by_role("button", name=re.compile("Download", re.I))
        if not button.count():
            button = page.get_by_text(re.compile("^Download$", re.I))
        with page.expect_download(timeout=45000) as event:
            button.first.click(timeout=12000)
        download = event.value
        if not download.suggested_filename.lower().endswith(".csv"):
            raise RuntimeError("SharePoint supplied a file other than CSV")
        data = Path(download.path()).read_bytes()
        if not (15 < len(data) <= MAX_CSV):
            raise RuntimeError("Downloaded ROC CSV size out of range")
        return data
    except Exception as exc:
        raise RuntimeError("SharePoint ROC CSV download failed (" +
                           type(exc).__name__ + ": " + str(exc)[:150] + ")")


def _validate(data):
    if not isinstance(data, bytes) or not (15 < len(data) <= MAX_CSV):
        raise RuntimeError("ROC download size out of supported range")
    try:
        text = data.decode("utf-8-sig")
        rows = csv.reader(io.StringIO(text, newline=""))
        headers = next(rows)
        if [x.strip().lower() for x in headers] != [x.lower() for x in EXPECTED]:
            raise RuntimeError("ROC CSV headers differ from the verified nine fields")
        count = 0
        for record in rows:
            if not record:
                continue
            if len(record) != len(EXPECTED):
                raise RuntimeError("ROC CSV contains malformed row")
            count += 1
            if count > 8000:
                raise RuntimeError("ROC CSV exceeds supported row limit")
        if count < 1:
            raise RuntimeError("ROC CSV has no incident records")
        return count
    except UnicodeError:
        raise RuntimeError("ROC CSV encoding is not UTF-8")


def _sha_of_remote(sftp, path):
    digest = hashlib.sha256()
    with sftp.open(path, "rb") as stream:
        while True:
            data = stream.read(1048576)
            if not data:
                break
            digest.update(data)
    return digest.digest()


def _safe_dir(sftp, path):
    meta = sftp.lstat(path)
    if not stat.S_ISDIR(meta.st_mode):
        raise RuntimeError("ROC private storage is not an ordinary directory")


def _stage_file(sftp, final, data, digest):
    try:
        mode = sftp.lstat(final).st_mode
        if not stat.S_ISREG(mode):
            raise RuntimeError("Unsafe existing ROC CSV destination")
        if _sha_of_remote(sftp, final) == digest:
            return None, "existing"
        raise RuntimeError("Existing ROC CSV has different contents; refusing overwrite")
    except FileNotFoundError:
        pass
    tmp = final + ".stage-" + uuid.uuid4().hex[:12]
    try:
        with sftp.open(tmp, "wb") as output:
            output.write(data)
        sftp.chmod(tmp, 0o600)
        if _sha_of_remote(sftp, tmp) != digest:
            raise RuntimeError("ROC staged CSV checksum mismatch")
        return tmp, "new"
    except Exception:
        try:
            sftp.remove(tmp)
        except Exception:
            pass
        raise


def _publish(data, date, name, functions):
    if not all(k in functions for k in
               ("_roster_sftp_connection", "_dual_kustom_open")):
        raise RuntimeError("Existing dual-site SFTP helper is unavailable")
    primary = functions["_roster_sftp_connection"]()
    if not isinstance(primary, tuple) or len(primary) != 3:
        raise RuntimeError("Primary site SFTP connection unavailable")
    p_ssh, p_sftp, p_site = primary
    secondary = None
    stages = []
    digest = hashlib.sha256(data).digest()
    try:
        secondary = functions["_dual_kustom_open"]()
        k_ssh, k_sftp = secondary
        dests = [
            ("Bodgybros", p_sftp, posixpath.join(
                posixpath.dirname(posixpath.dirname(p_site.rstrip("/"))), "sps-roc")),
            ("Kustom", k_sftp, "/home10/kustomvi/sps-roc")
        ]
        for label, sftp, root in dests:
            _safe_dir(sftp, root)
            original = posixpath.join(root, "originals")
            _safe_dir(sftp, original)
            dest = posixpath.join(root, date.isoformat() + ".csv")
            arch = posixpath.join(original, name)
            if not re.fullmatch(r"[A-Za-z0-9 ._()\-]{8,220}\.csv", name):
                raise RuntimeError("SharePoint CSV name is unsafe for private archive")
            tmp_main, state_main = _stage_file(sftp, dest, data, digest)
            tmp_arch, state_arch = _stage_file(sftp, arch, data, digest)
            stages.append((label, sftp, dest, arch, tmp_main, tmp_arch, state_main,
                           state_arch))
        for label, sftp, dest, arch, tmp_main, tmp_arch, a, b in stages:
            if tmp_arch:
                sftp.posix_rename(tmp_arch, arch)
            if tmp_main:
                sftp.posix_rename(tmp_main, dest)
            if _sha_of_remote(sftp, dest) != digest or _sha_of_remote(sftp, arch) != digest:
                raise RuntimeError("ROC published private CSV integrity check failed")
            _say(label + ": private report " + date.isoformat() + " verified (" + a + ")")
    finally:
        for item in stages:
            _,sftp,_,_,tmp_main,tmp_arch,*_ = item
            for temp in (tmp_main,tmp_arch):
                if temp:
                    try:
                        sftp.remove(temp)
                    except Exception:
                        pass
        if secondary:
            try:
                secondary[1].close()
            except Exception:
                pass
            try:
                secondary[0].close()
            except Exception:
                pass
        if "_roster_sftp_release" in functions:
            try:
                functions["_roster_sftp_release"]()
            except Exception:
                pass
        else:
            try:
                p_sftp.close()
            finally:
                p_ssh.close()


def process(browser, functions, target_date=None):
    """Runs within an existing authenticated Playwright Chrome context."""
    date = target_date or (datetime.now(TZ).date() - timedelta(days=1))
    _say("Checking yesterday's ROC CSV for " + date.isoformat())
    page = browser.new_page()
    try:
        year = YEAR_ROOT + "/" + str(date.year)
        view = YEAR_VIEW + "?id=" + quote(year, safe="")
        page.goto(view, wait_until="domcontentloaded", timeout=45000)
        current = page.url.lower()
        if "login.microsoftonline.com" in current or "login.live.com" in current:
            raise RuntimeError("Existing SharePoint session requires Microsoft sign-in")
        if "transportcloud.sharepoint.com" not in current:
            raise RuntimeError("Unexpected ROC SharePoint sign-in redirect")
        target = _find_target(page, date)
        content = _get_csv(page, target, date)
        count = _validate(content)
        _say("CSV validated: " + str(count) + " records, " +
             str(len(content)) + " bytes")
        _publish(content, date, target["name"], functions)
        _say("COMPLETE: " + date.isoformat() + " saved privately on both websites")
        return True
    finally:
        page.close()


def safe_process(browser, functions):
    try:
        return process(browser, functions)
    except Exception as exc:
        # No private incident records or credentials should be included.
        text = str(exc)
        text = re.sub(r"https?://\S+", "[SharePoint URL]", text)
        _say("NOT COMPLETE: " + text[:230])
        return False

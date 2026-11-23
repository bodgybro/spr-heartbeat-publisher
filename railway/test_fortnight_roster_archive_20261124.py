import hashlib
import io
import os
from pathlib import Path
from datetime import date
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

from fortnight_roster_archive_20261124_patch import apply


def pdf(text):
    b = io.BytesIO()
    c = canvas.Canvas(b)
    c.drawString(30, 780, text)
    c.save()
    return b.getvalue()


BASE = '''# SPR_ROSTER_SFTP_CONNECTION_REUSE_20261101
import io,hashlib,posixpath
FILES={}
ROOT='/home11/bodgybro/public_html/sps'
SFTP=None
class Sftp:
    def __init__(self):self.data=FILES
    def stat(self,path):
        if path not in self.data:raise FileNotFoundError(path)
        return type('Stat',(),{'st_size':len(self.data[path]),'st_mode':0o100600})()
    def open(self,path,mode):
        if mode=='rb':return io.BytesIO(self.data[path])
        if mode=='wb':
            target=self.data
            class Writer(io.BytesIO):
                def close(self):target[path]=self.getvalue();super().close()
            return Writer()
        raise AssertionError(mode)
    def posix_rename(self,src,dst):self.data[dst]=self.data.pop(src)
    def chmod(self,path,mode):pass
    def close(self):pass
    def remove(self,path):del self.data[path]

def _roster_sftp_connection():return (type('Client',(),{'close':lambda s:None})(),SFTP,ROOT)
def _roster_sftp_dirs(sftp,site_root,parts,private=False):
    assert private
    return posixpath.join(site_root,*parts)
def _roster_sftp_digest(sftp,path):return hashlib.sha256(sftp.data[path]).hexdigest()
def _roster_valid_cache_path(path):
    parts=path.split('/')
    if len(parts)!=4 or parts[1] not in ('drivers','guards') or parts[2] not in ('daily','period','fortnight'):
        raise ValueError('bad path')
    return parts

def _roster_sftp_check_url(url):
    if not url.startswith('https://transportcloud.sharepoint.com/'):raise ValueError('bad url')
def upload_cached_roster_pdf(url,name,data,cache_path=''):
    FILES[posixpath.join(ROOT,'rosters',*_roster_valid_cache_path(cache_path))]=bytes(data)
    return {'ok':True, 'changed':True}
if __name__=="__main__":
    pass
'''


def get_module(tmp_path):
    path=tmp_path/'fake_updater.py'
    path.write_text(BASE)
    apply(path)
    import importlib.util
    spec=importlib.util.spec_from_file_location('fake_updater',path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SFTP=m.Sftp()
    return m


def test_14_day_roster_cycle(tmp_path):
    m=get_module(tmp_path)
    assert m._roster_archive_fortnight(date(2026,11,14))=='2026-11-01'
    assert m._roster_archive_fortnight(date(2026,11,15))=='2026-11-15'
    assert m._roster_archive_fortnight(date(2026,11,28))=='2026-11-15'
    assert m._roster_archive_fortnight(date(2026,11,29))=='2026-11-29'
    assert m._roster_archive_fortnight(date(2026,12,12))=='2026-11-29'
    assert m._roster_archive_fortnight(date(2026,12,13))=='2026-12-13'


def test_heading_overrides_print_date(tmp_path):
    m=get_module(tmp_path)
    doc=pdf('Fortnight commencing: 29/11/2026. Printed on 24/11/2026')
    assert m._roster_archive_effective_date(doc,'period')==date(2026,11,29)
    assert m._roster_archive_effective_date(pdf('Daily roster date: 21/11/2026'),'daily')==date(2026,11,21)
    assert m._roster_archive_effective_date(pdf('No dates printed'),'daily') is None
    assert m._roster_archive_effective_date(pdf('20/11/2026 29/11/2026'),'fortnight') is None


def test_preserves_old_and_new_versions_before_live_overwrite(tmp_path):
    m=get_module(tmp_path)
    cache_path='central/drivers/daily/D-DAY.pdf'
    target=m.ROOT+'/rosters/'+cache_path
    old=pdf('Daily roster date: 20/11/2026')
    new=pdf('Daily roster date: 21/11/2026')
    m.FILES[target]=old
    result=m.upload_cached_roster_pdf('https://transportcloud.sharepoint.com/sites/ST-SPS-SD/TCREW/ROSTERS/central.pdf','D-DAY.pdf',new,cache_path)
    assert result['ok'] and m.FILES[target]==new
    private='/home11/bodgybro/sps-private-assets/roster-archives-v1/fortnights/2026-11-15/central/drivers/daily'
    assert m.FILES[private+'/2026-11-20/'+hashlib.sha256(old).hexdigest()+'.pdf']==old
    assert m.FILES[private+'/2026-11-21/'+hashlib.sha256(new).hexdigest()+'.pdf']==new
    assert all('/public_html/' not in k for k in m.FILES if 'archives-v1' in k)


def test_unknown_date_kept_unclassified(tmp_path):
    m=get_module(tmp_path)
    data=pdf('No recognizable roster dates in this PDF')
    cache_path='central/guards/period/G-PER.pdf'
    m.upload_cached_roster_pdf('https://transportcloud.sharepoint.com/test','G-PER.pdf',data,cache_path)
    target='/home11/bodgybro/sps-private-assets/roster-archives-v1/unclassified/central/guards/period/'+hashlib.sha256(data).hexdigest()+'.pdf'
    assert m.FILES[target]==data


def test_archive_failure_preserves_live_file(tmp_path):
    m=get_module(tmp_path)
    cache_path='central/drivers/daily/D-DAY.pdf'
    target=m.ROOT+'/rosters/'+cache_path
    old=pdf('Daily roster date: 20/11/2026')
    new=pdf('Daily roster date: 21/11/2026')
    m.FILES[target]=old
    def bad_dirs(*args,**kw):raise PermissionError('private archive unavailable')
    m._roster_sftp_dirs=bad_dirs
    with pytest.raises(PermissionError):
        m.upload_cached_roster_pdf('https://transportcloud.sharepoint.com/test','D-DAY.pdf',new,cache_path)
    assert m.FILES[target]==old


def test_patch_idempotent(tmp_path):
    p=tmp_path/'stub.py'
    p.write_text(BASE)
    apply(p)
    before=p.read_bytes()
    apply(p)
    assert p.read_bytes()==before

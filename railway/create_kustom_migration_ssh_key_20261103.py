#!/usr/bin/env python3
"""Create private Railway-held SSH key for authorised Kustom Vinyls site migration.

Only the PUBLIC key is printed; private key never leaves the private persistent
Railway volume. No network access, DNS changes or website file edits.
"""
import os,hashlib,base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

folder=Path('/data/credentials/kustom-transfer')
folder.mkdir(mode=0o700,parents=True,exist_ok=True)
os.chmod(folder,0o700)
private=folder/'id_ed25519'
public=folder/'id_ed25519.pub'
if private.exists():
    key=serialization.load_ssh_private_key(private.read_bytes(),password=None)
    if not isinstance(key,ed25519.Ed25519PrivateKey):
        raise RuntimeError('Existing migration private key is not Ed25519; refusing overwrite')
    print('[KUSTOM TRANSFER SSH] Existing secure key reused',flush=True)
else:
    if public.exists():
        raise RuntimeError('Public key exists without private key; refusing overwrite')
    key=ed25519.Ed25519PrivateKey.generate()
    raw=key.private_bytes(encoding=serialization.Encoding.PEM,
          format=serialization.PrivateFormat.OpenSSH,
          encryption_algorithm=serialization.NoEncryption())
    descriptor=os.open(str(private),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as out:out.write(raw)
    print('[KUSTOM TRANSFER SSH] New dedicated private key stored securely on persistent Railway volume',flush=True)
os.chmod(private,0o600)
value=key.public_key().public_bytes(encoding=serialization.Encoding.OpenSSH,
                                 format=serialization.PublicFormat.OpenSSH).decode('ascii')
line=value+' spr-kustom-railway-20261103'
public.write_text(line+'\n',encoding='ascii')
os.chmod(public,0o644)
body=value.split()[1]
fingerprint=base64.b64encode(hashlib.sha256(base64.b64decode(body)).digest()).decode('ascii').rstrip('=')
print('[KUSTOM TRANSFER SSH PUBLIC KEY] '+line,flush=True)
print('[KUSTOM TRANSFER SSH FINGERPRINT] SHA256:'+fingerprint,flush=True)
print('[KUSTOM TRANSFER SSH] Private key not printed; no site files touched',flush=True)

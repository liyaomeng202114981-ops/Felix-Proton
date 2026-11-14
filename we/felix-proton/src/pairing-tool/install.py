#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Install only this small tool and its own menu entry; do not pair applications."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from backend import PairingError, PairingService


OWNER='Felix Pairing v1'
ICON_FILE='assets/felix-pairing-round-v5.svg'
ICON_NAME='felix-pairing-round-v5'
FILES=('app.py','backend.py','catalog.py','lib/desktop.py','LICENSE','COPYRIGHT','VERSION',ICON_FILE)
DESKTOP_ID='io.github.felixproton.Pairing.desktop'


def install():
    service=PairingService()
    desktop=service.desktop
    source=Path(__file__).resolve().parent
    data={name:(source/name).read_bytes() for name in FILES}
    digest=hashlib.sha256(b''.join(name.encode()+b'\0'+data[name] for name in FILES)).hexdigest()
    base=service.data_home/'felix-pairing-tool'
    version=base/('v1-'+digest[:16])
    apps=service.data_home/'applications'
    target=apps/DESKTOP_ID
    icon=service.data_home/'icons/hicolor/scalable/apps'/(ICON_NAME+Path(ICON_FILE).suffix)
    manifest=base/'installation.json'
    before=desktop._snapshot(target)
    if before and ('X-Felix-Pairing-Owner='+OWNER+'\n').encode() not in desktop._content(before).split(b'\0')[0]:
        raise RuntimeError('工具入口已有其他内容，已保留。')
    if os.path.lexists(manifest):
        if manifest.is_symlink() or not manifest.is_file():
            raise RuntimeError('工具安装记录类型不符，已保留。')
        previous=json.loads(manifest.read_text())
        if previous.get('owner')!=OWNER:raise RuntimeError('已有其他安装记录，已保留。')
    else:previous={}
    if os.path.lexists(icon):
        if icon.is_symlink() or not icon.is_file():raise RuntimeError('工具图标类型不符，已保留。')
        current=hashlib.sha256(icon.read_bytes()).hexdigest()
        previous_hash=previous.get('icon_sha256') if previous.get('icon')==str(icon) else None
        if current not in (previous_hash,hashlib.sha256(data[ICON_FILE]).hexdigest()):
            raise RuntimeError('工具图标已有其他内容，已保留。')
    base.mkdir(parents=True,exist_ok=True)
    if version.exists():
        if version.is_symlink() or any((version/name).read_bytes()!=value for name,value in data.items()):
            raise RuntimeError('工具版本目录已有其他内容，已保留。')
    else:
        with tempfile.TemporaryDirectory(prefix='.stage-',dir=base) as directory:
            stage=Path(directory)/'app';stage.mkdir()
            for name,value in data.items():
                (stage/name).parent.mkdir(parents=True,exist_ok=True)
                (stage/name).write_bytes(value)
            stage.rename(version)
    entry=('''[Desktop Entry]
Type=Application
Name=Felix 配对
Comment=将 Steam 与网易 UU 的原有入口配对
Exec=/usr/bin/python3 -B '''+desktop._quote(version/'app.py')+'''
Icon='''+ICON_NAME+'''
Terminal=false
Categories=Utility;Game;
StartupNotify=true
X-Felix-Pairing-Owner='''+OWNER+'\n').encode()
    apps.mkdir(parents=True,exist_ok=True)
    if not desktop._same(before,desktop._snapshot(target)):
        raise RuntimeError('安装期间工具入口已改变，请重试。')
    desktop._atomic(icon,data[ICON_FILE],mode=0o644)
    desktop._atomic(target,entry,mode=0o644)
    record={'owner':OWNER,'version':str(version),'desktop':str(target),'icon':str(icon),
            'icon_name':ICON_NAME,'icon_sha256':hashlib.sha256(data[ICON_FILE]).hexdigest(),
            'files':{name:hashlib.sha256(value).hexdigest() for name,value in data.items()}}
    try:
        record['pair_record_upgraded']=service.upgrade_record()
    except (PairingError, OSError, ValueError, KeyError, TypeError):
        # Installing the UI never authorizes accepting a changed connection.
        record['pair_record_upgraded']=False
        record['pair_record_needs_review']=True
    desktop._atomic(manifest,(json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode())
    command=shutil.which('gtk-update-icon-cache')
    if command:
        subprocess.run([command,'--force','--ignore-theme-index',str(service.data_home/'icons/hicolor')],
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    command=shutil.which('update-desktop-database')
    if command:subprocess.run([command,str(apps)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
    return record


if __name__=='__main__':
    print(json.dumps(install(),ensure_ascii=False))

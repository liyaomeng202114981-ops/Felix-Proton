#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Show only the tool's fixture UI; never change launchers or start a client."""
import argparse
import json
from pathlib import Path
import time
from unittest.mock import patch

import app
import gi
gi.require_version('Graphene','1.0')
from gi.repository import Gdk, Gio, GLib, Graphene, Gtk
from catalog import App


class FixtureService:
    def __init__(self):self.calls=[]
    def inspect(self):
        return {'connected':False,'managed':False,'adopted':False,'message':'配对会沿用两个应用原来的图标和入口。'}
    def pair(self,platform,accelerator):
        self.calls.append((platform,accelerator))
        return {'connected':True,'managed':True,'adopted':False,
                'message':'下次从原图标启动时生效。正在运行的应用会保持当前连接。'}
    def remove(self):
        self.calls.append('remove')
        return self.inspect()


def pump(predicate,timeout=5):
    end=time.monotonic()+timeout
    context=GLib.MainContext.default()
    while time.monotonic()<end:
        while context.pending():context.iteration(False)
        if predicate():return
        time.sleep(.01)
    raise AssertionError('UI did not reach expected state')


def snapshot(window,path):
    paintable=Gtk.WidgetPaintable.new(window.get_content())
    snap=Gtk.Snapshot()
    width,height=window.get_content().get_width(),window.get_content().get_height()
    found,color=window.get_style_context().lookup_color('window_bg_color')
    assert found
    snap.append_color(color,Graphene.Rect().init(0,0,width,height))
    paintable.snapshot(snap,width,height)
    node=snap.to_node()
    assert node is not None
    texture=window.get_renderer().render_texture(node,None)
    path.parent.mkdir(parents=True,exist_ok=True)
    assert texture.save_to_png(str(path))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-dir',type=Path,required=True)
    parser.add_argument('--unconfigured',action='store_true',help='Verify the real backend opens safely in an empty temporary HOME/XDG')
    args=parser.parse_args()
    application=app.PairingApplication()
    # Never join or activate the real tool's single-instance D-Bus application.
    application.set_application_id('io.github.felixproton.Pairing.Smoke')
    application.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    assert application.register(None)
    provider=Gtk.CssProvider();provider.load_from_data(app.CSS.encode())
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    items=[App('steam.desktop','Steam',Gio.ThemedIcon.new('steam'),'/fixture/steam.desktop','platform'),
           App('uu-accelerator.desktop','网易 UU 加速器',Gio.ThemedIcon.new('network-vpn'),
               '/fixture/uu-accelerator.desktop','accelerator')]
    service=app.PairingService() if args.unconfigured else FixtureService()
    if args.unconfigured:
        assert not service.active.exists(), 'Use an empty temporary HOME/XDG for this check'
    window=app.PairingWindow(application,service=service,apps=items)
    def resolve(value):
        key=Path(value).name if value.startswith('/') else value.removeprefix('felix-app:')
        return next(item for item in items if item.desktop_id==key)
    try:
        window.present()
        pump(lambda:not window.busy and window.get_mapped())
        pump(lambda:window.get_content().get_width()>100)
        pump_frame()
        if args.unconfigured:
            assert not window.result.get('ready')
            assert window.status_title.get_label()=='暂时无法配对'
            assert not service.ledger.exists()
            snapshot(window,args.snapshot_dir/'unconfigured.png')
            print(json.dumps({'unconfigured_ui':'passed','pair_or_client_operations':0}))
            return
        snapshot(window,args.snapshot_dir/'empty.png')
        with patch.object(app.catalog,'resolve_drop',side_effect=resolve):
            assert window.targets[0].emit('drop','felix-app:steam.desktop',0.,0.)
            assert len(window.selected)==1 and not service.calls
            assert not window.targets[1].emit('drop','felix-app:steam.desktop',0.,0.)
            assert window.targets[1].emit('drop','felix-app:uu-accelerator.desktop',0.,0.)
            pump(lambda:not window.busy)
            assert service.calls==[('steam.desktop','uu-accelerator.desktop')]
            assert window.status_title.get_label()=='入口已配对'
            assert window.remove_button.get_visible()
            pump_frame()
            snapshot(window,args.snapshot_dir/'paired.png')
            window.remove_pair();pump(lambda:not window.busy)
            assert not window.selected and service.calls[-1]=='remove'
            # Drop one application onto the other, rather than into the two slots.
            assert window.targets[3].emit('drop','felix-app:steam.desktop',0.,0.)
            pump(lambda:not window.busy)
            assert service.calls[-1]==('steam.desktop','uu-accelerator.desktop')
            assert len(window.selected)==2
            window._paired({'ready':False,'connected':True,'managed':True,'adopted':False,
                            'message':'上次配对尚未完成，请恢复入口。'})
            assert window.status_title.get_label()=='暂时无法配对'
            assert window.remove_button.get_label()=='恢复入口'
            window._paired({'ready':True,'connected':False,'managed':True,'adopted':True,
                            'message':'入口已被修改。'})
            assert window.status_title.get_label()=='暂时无法配对'
            assert window.remove_button.get_label()=='移除管理记录'
            file_list=Gdk.FileList.new_from_list([Gio.File.new_for_path('/fixture/steam.desktop')])
            assert window._receive(file_list,lambda value:window.accept_drop(value,kind='platform'))
            pump(lambda:not window.busy)
        print(json.dumps({'fixture_ui_checks':'passed','pair_calls':sum(isinstance(call,tuple) for call in service.calls),
                          'client_or_network_operations':0,
                          'snapshots':['empty.png','paired.png']}))
    finally:
        window.destroy()
        application.quit()


def pump_frame():
    done=[]
    GLib.timeout_add(150,lambda:done.append(True) or False)
    pump(lambda:bool(done))


if __name__=='__main__':main()

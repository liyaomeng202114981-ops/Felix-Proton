#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Felix Li, with OpenAI Codex assistance.
"""A small local UI for pairing the existing Steam and UU launchers."""
import argparse
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode=True
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

import catalog
from backend import PairingService


CSS='''
.pair-title { font-size: 27px; font-weight: 750; }
.pair-subtitle { font-size: 14px; }
.pair-slot { border: 2px dashed alpha(@window_fg_color,.17); border-radius: 20px; padding: 20px 12px; }
.pair-slot.filled { border-style: solid; border-color: alpha(@accent_color,.55); background: alpha(@accent_bg_color,.065); }
.pair-slot.drop-active { border-color: @accent_color; background: alpha(@accent_bg_color,.12); }
.pair-slot-title { font-size: 16px; font-weight: 700; }
.pair-link { color: @accent_color; background: alpha(@accent_bg_color,.1); border-radius: 32px; padding: 12px; }
.pair-app { border-radius: 14px; padding: 14px 18px; }
.pair-status { border-radius: 14px; padding: 14px; background: alpha(@accent_bg_color,.075); }
.pair-status.error { background: alpha(@error_bg_color,.09); }
.pair-footnote { font-size: 12px; }
'''


class PairingWindow(Adw.ApplicationWindow):
    def __init__(self,application,*,service=None,apps=None):
        super().__init__(application=application,title='Felix 配对',default_width=720,default_height=660)
        self.service=service or PairingService()
        self.apps=catalog.load_apps() if apps is None else apps
        self.selected={}
        self.busy=False
        self.result={}
        self.targets=[]
        self.set_icon_name('felix-pairing-round-v5')
        self.set_size_request(560,520)
        toolbar=Adw.ToolbarView()
        header=Adw.HeaderBar()
        title=Adw.WindowTitle(title='Felix 配对',subtitle='Steam × 网易 UU')
        header.set_title_widget(title)
        toolbar.add_top_bar(header)
        scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,vexpand=True)
        clamp=Adw.Clamp(maximum_size=650,tightening_threshold=560)
        body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=20)
        body.set_margin_start(26);body.set_margin_end(26)
        body.set_margin_top(22);body.set_margin_bottom(24)
        heading=Gtk.Label(label='把平台和加速器，连在一起。',xalign=0,wrap=True)
        heading.add_css_class('pair-title');body.append(heading)
        intro=Gtk.Label(label='只需配对一次。之后直接使用原图标，无需再打开本工具。',xalign=0,wrap=True)
        intro.add_css_class('dim-label');intro.add_css_class('pair-subtitle');body.append(intro)

        slots=Gtk.Box(spacing=14,homogeneous=False)
        self.slots={}
        for index,(kind,title_text,icon_name) in enumerate((
                ('platform','游戏平台','applications-games-symbolic'),
                ('accelerator','加速器','network-vpn-symbolic'))):
            if index:
                link=Gtk.Image.new_from_icon_name('insert-link-symbolic')
                link.add_css_class('pair-link');link.set_valign(Gtk.Align.CENTER);slots.append(link)
            card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,hexpand=True)
            card.add_css_class('pair-slot')
            image=Gtk.Image.new_from_icon_name(icon_name);image.set_pixel_size(56)
            name=Gtk.Label(label='拖入'+title_text,wrap=True);name.add_css_class('pair-slot-title')
            hint=Gtk.Label(label=title_text);hint.add_css_class('dim-label')
            card.append(image);card.append(name);card.append(hint)
            self._drop_target(card,lambda value,k=kind:self.accept_drop(value,kind=k))
            self.slots[kind]=(card,image,name,hint)
            slots.append(card)
        body.append(slots)
        row=Gtk.Box(spacing=8)
        section=Gtk.Label(label='已安装的应用',xalign=0,hexpand=True);section.add_css_class('heading');row.append(section)
        choose=Gtk.Button(label='选择快捷方式…');choose.add_css_class('flat')
        choose.connect('clicked',self.choose_file);row.append(choose);body.append(row)
        self.app_grid=Gtk.Box(spacing=12,homogeneous=True)
        for app in self.apps:self.app_grid.append(self.app_card(app))
        if not self.apps:
            empty=Gtk.Label(label='没有找到 Steam 或网易 UU 的应用入口。请先安装并完成原有配置。',wrap=True)
            empty.add_css_class('dim-label');self.app_grid.append(empty)
        body.append(self.app_grid)

        self.status_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=7)
        self.status_box.add_css_class('pair-status')
        self.status_title=Gtk.Label(label='准备好后，拖动两个图标即可。',xalign=0,wrap=True)
        self.status_title.add_css_class('heading')
        self.status_message=Gtk.Label(label='拖动下方两个图标，或点击选择。配对会保留原图标和入口。',xalign=0,wrap=True)
        self.status_message.add_css_class('dim-label')
        self.status_box.append(self.status_title);self.status_box.append(self.status_message)
        self.progress=Gtk.Spinner(halign=Gtk.Align.START);self.status_box.append(self.progress)
        self.remove_button=Gtk.Button(label='解除配对',halign=Gtk.Align.START,visible=False)
        self.remove_button.add_css_class('flat');self.remove_button.connect('clicked',self.remove_pair)
        self.status_box.append(self.remove_button);body.append(self.status_box)
        note=Gtk.Label(label='配对后仍从原图标启动。在网易 UU 中选择游戏、区服和节点，再从 Steam 开始游戏。',
                       xalign=0,wrap=True)
        note.add_css_class('dim-label');note.add_css_class('pair-footnote');body.append(note)
        clamp.set_child(body);scroll.set_child(clamp);toolbar.set_content(scroll);self.set_content(toolbar)
        self._run(self.service.inspect,self._inspected)

    def _drop_target(self,widget,callback):
        target=Gtk.DropTarget.new(GObject.TYPE_STRING,Gdk.DragAction.COPY)
        target.set_gtypes([GObject.TYPE_STRING,Gdk.FileList])
        target.connect('drop',lambda _target,value,_x,_y:self._receive(value,callback))
        target.connect('enter',lambda *_args:self._entered(widget))
        target.connect('leave',lambda *_args:widget.remove_css_class('drop-active'))
        widget.add_controller(target);self.targets.append(target)

    def _entered(self,widget):
        widget.add_css_class('drop-active')
        return Gdk.DragAction.COPY

    def _receive(self,value,callback):
        try:
            if isinstance(value,Gdk.FileList):
                files=value.get_files()
                if len(files)!=1 or not files[0].get_path():
                    raise ValueError('请一次拖入一个本机应用快捷方式。')
                value=files[0].get_path()
            return callback(value)
        except (OSError,ValueError) as error:
            self.show_error(str(error));return False
        finally:
            for card,*_ in self.slots.values():card.remove_css_class('drop-active')

    def app_card(self,app):
        button=Gtk.Button(hexpand=True);button.add_css_class('card');button.add_css_class('pair-app')
        content=Gtk.Box(spacing=12)
        image=Gtk.Image.new_from_gicon(app.icon) if app.icon else Gtk.Image.new_from_icon_name('application-x-executable')
        image.set_pixel_size(42);content.append(image)
        words=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4,hexpand=True)
        name=Gtk.Label(label=app.name,xalign=0,ellipsize=3);name.add_css_class('heading')
        hint=Gtk.Label(label='拖动配对 · 点击选择',xalign=0);hint.add_css_class('dim-label')
        words.append(name);words.append(hint);content.append(words);button.set_child(content)
        button.set_tooltip_text('拖入上方，或把另一个应用拖到这里')
        button.connect('clicked',lambda *_:self.select(app))
        drag=Gtk.DragSource.new();drag.set_actions(Gdk.DragAction.COPY)
        drag.connect('prepare',lambda *_:Gdk.ContentProvider.new_for_value('felix-app:'+app.desktop_id))
        drag.connect('drag-begin',lambda source,_drag:source.set_icon(Gtk.WidgetPaintable.new(image),0,0))
        button.add_controller(drag)
        self._drop_target(button,lambda value:self.accept_drop(value,target_app=app))
        return button

    def accept_drop(self,value,*,kind=None,target_app=None):
        if self.busy:return False
        app=catalog.resolve_drop(value)
        if kind and app.kind!=kind:
            self.show_error('请将这个图标放到'+('游戏平台' if app.kind=='platform' else '加速器')+'位置。')
            return False
        if target_app:
            if target_app.kind==app.kind:
                self.show_error('把 Steam 和网易 UU 的两个不同图标拖到一起。');return False
            self._set_selected(target_app)
        self.select(app)
        return True

    def _set_selected(self,app):
        self.selected[app.kind]=app
        card,image,name,hint=self.slots[app.kind]
        if app.icon:image.set_from_gicon(app.icon)
        name.set_label(app.name);hint.set_label('游戏平台' if app.kind=='platform' else '加速器')
        card.add_css_class('filled')

    def select(self,app):
        if self.busy:return
        self._set_selected(app)
        if len(self.selected)==2:
            self.status_title.set_label('正在配对…')
            self.status_message.set_label('正在检查现有配置并保存连接。')
            self._run(lambda:self.service.pair(self.selected['platform'].desktop_id,
                                               self.selected['accelerator'].desktop_id),self._paired)
        else:
            self.status_box.remove_css_class('error')
            self.status_title.set_label('再放入另一个应用。')
            self.status_message.set_label('两个图标放好后会自动完成配对。')

    def _run(self,action,callback):
        self.busy=True;self.progress.set_visible(True);self.progress.start()
        self.remove_button.set_sensitive(False)
        def work():
            try:result=action();error=None
            except Exception as exception:result=None;error=str(exception)
            GLib.idle_add(finish,result,error)
        def finish(result,error):
            self.busy=False;self.progress.stop();self.progress.set_visible(False)
            self.remove_button.set_sensitive(True)
            if error:self.show_error(error)
            else:callback(result)
            return GLib.SOURCE_REMOVE
        threading.Thread(target=work,daemon=True).start()

    def _inspected(self,result):
        self.result=result
        if not result.get('ready',True):
            self.show_error(result.get('message') or '已有配置需要检查。')
            self.remove_button.set_visible(bool(result.get('managed')))
            self.remove_button.set_label('移除管理记录' if result.get('adopted') else '恢复入口')
            return
        if result.get('managed'):
            for app in self.apps:self._set_selected(app)
            self._paired(result)
        elif result.get('connected'):
            self.status_title.set_label('检测到已有连接')
            self.status_message.set_label('Steam 和网易 UU 已经关联。拖入两个图标，即可在这里管理。')
        elif result.get('message'):
            self.status_message.set_label(result['message'])

    def _paired(self,result):
        self.result=result
        if not result.get('ready',True) or result.get('managed') and not result.get('connected'):
            self._inspected({**result,'ready':False})
            return
        self.status_box.remove_css_class('error')
        self.status_title.set_label('入口已配对' if result.get('connected') else '配对记录已移除')
        self.status_message.set_label(result.get('message') or '下次从原图标启动时生效。正在运行的应用会保持当前连接。')
        self.remove_button.set_visible(bool(result.get('managed')))
        self.remove_button.set_label('移除管理记录' if result.get('adopted') else '解除配对')

    def remove_pair(self,*_):
        if self.busy:return
        self._run(self.service.remove,self._removed)

    def _removed(self,result):
        self.selected.clear()
        for kind,(card,image,name,hint) in self.slots.items():
            card.remove_css_class('filled')
            image.set_from_icon_name('applications-games-symbolic' if kind=='platform' else 'network-vpn-symbolic')
            name.set_label('拖入'+('游戏平台' if kind=='platform' else '加速器'))
        self._paired(result)
        self.status_title.set_label('管理记录已移除' if result.get('connected') else '已解除配对')

    def show_error(self,message):
        self.status_box.add_css_class('error');self.status_title.set_label('暂时无法配对')
        self.status_message.set_label(message)

    def choose_file(self,*_):
        if self.busy:return
        dialog=Gtk.FileDialog(title='选择已安装应用的快捷方式')
        file_filter=Gtk.FileFilter();file_filter.set_name('应用快捷方式');file_filter.add_pattern('*.desktop')
        filters=Gio.ListStore.new(Gtk.FileFilter);filters.append(file_filter);dialog.set_filters(filters)
        def finished(source,result):
            try:
                file=source.open_finish(result)
                if file:self._receive(file.get_path(),self.accept_drop)
            except GLib.Error as error:
                if not error.matches(Gtk.DialogError.quark(),Gtk.DialogError.DISMISSED):self.show_error('无法读取所选快捷方式。')
        dialog.open(self,None,finished)


class PairingApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id='io.github.felixproton.Pairing',flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window=None
    def do_activate(self):
        if self.window is None:
            provider=Gtk.CssProvider();provider.load_from_data(CSS.encode())
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.window=PairingWindow(self)
        self.window.present()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    return PairingApplication().run([sys.argv[0]])


if __name__=='__main__':
    raise SystemExit(main())

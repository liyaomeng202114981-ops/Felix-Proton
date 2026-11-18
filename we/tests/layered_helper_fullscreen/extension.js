import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export default class FixtureObserver extends Extension {
    enable() {
        const path = GLib.getenv('FELIX_UI_BENCH_SNAPSHOT');
        if (!path)
            return;
        const rect = r => [r.x, r.y, r.width, r.height];
        let previous = '';
        let activated = null;
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 45, () => {
            const windows = global.get_window_actors()
                .map(actor => actor.meta_window)
                .filter(win => /^FelixEdgeFixture-(plain|fixed|broken|corrected|fixed-broken|broken-coords)$/.test(win.get_title() ?? ''));
            if (windows.length === 1 && windows[0] !== activated) {
                activated = windows[0];
                Main.overview.hide();
                activated.activate(global.get_current_time());
            }
            const state = JSON.stringify({
                windows: windows.map(win => ({
                    name: win.get_title(), maximized: win.is_maximized(), frame: rect(win.get_frame_rect()),
                    buffer: rect(win.get_buffer_rect()), client: win.get_client_type(),
                })),
                pointer: global.get_pointer().slice(0, 2),
            });
            if (state !== previous) {
                GLib.file_set_contents(path, state);
                previous = state;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._timer)
            GLib.Source.remove(this._timer);
    }
}

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from gi.repository import GObject
except ImportError:
    print("No GTK support for Python found, cannot run tray")

import subprocess
import distutils.spawn
import logging
import getpass


logging.root.setLevel(logging.INFO)

NOTIFY_SEND_BIN = distutils.spawn.find_executable("notify-send")
ST_BIN = distutils.spawn.find_executable("syncthing")

ST_STOPPED_ICON = "system-shutdown"
ST_RUNNING_ICON = "system-run"

USERNAME = getpass.getuser()


class SyncThingTray(object):
    """Tray app to control Syncthing"""

    # Various shell arguments for dealing with the Syncthing process
    CHECK_RUNNING_ARGS = ["pgrep", "-U", USERNAME, "syncthing"]
    START_ARGS = [ST_BIN, "-no-browser"]
    KILL_ARGS = ["pkill", "-U", USERNAME, "syncthing"]

    def __init__(self):
        self.tray = Gtk.StatusIcon()
        self.tray.connect('popup-menu', self.show_menu)
        self.tray.set_visible(True)
        self.tray.set_from_icon_name(ST_STOPPED_ICON)
        self.menu = None
        self.timer_callback()  # starts off refreshing

    def is_st_running(self):
        # XXX Do something if this fails
        p = subprocess.Popen(SyncThingTray.CHECK_RUNNING_ARGS,
                             stdout=subprocess.PIPE)
        out, _ = p.communicate()

        if out.strip() == "":
            return False
            logging.debug("Syncthing is not running")
        else:
            logging.debug("Syncthing is running")
            return True

    def start_syncthing_cb(self, widget):
        # XXX Do something if this fails
        logging.info("Starting Syncthing")
        subprocess.Popen(SyncThingTray.START_ARGS)
        self.set_icon(True)

    def stop_syncthing_cb(self, widget):
        # XXX Do something if this fails
        logging.info("Stopping Syncthing")
        subprocess.call(SyncThingTray.KILL_ARGS)
        self.set_icon(False)

    def set_timer(self, timeout):
        logging.debug("setting timer for %d seconds" % timeout)
        GObject.timeout_add_seconds(timeout, self.timer_callback)

    def set_icon(self, on):
        if on:
            self.tray.set_from_icon_name(ST_RUNNING_ICON)
        else:
            self.tray.set_from_icon_name(ST_STOPPED_ICON)

    def timer_callback(self):
        logging.debug("timer callback running")
        self.set_icon(self.is_st_running())
        self.set_timer(5)

    def show_menu(self, icon, button, time):
        logging.info("user enabled menu")
        self.menu = Gtk.Menu()

        # Start/stop syncthing
        if self.is_st_running():
            control = Gtk.MenuItem("Stop Syncthing")
            control.connect("activate", self.stop_syncthing_cb)
        else:
            control = Gtk.MenuItem("Start Syncthing")
            control.connect("activate", self.start_syncthing_cb)
        control.show()
        self.menu.append(control)

        # Exit
        exit = Gtk.MenuItem("Exit")
        exit.show()
        self.menu.append(exit)
        exit.connect("activate", self.exit_cb)

        self.menu.popup(None, None, None, None, button, time)

    def exit_cb(self, widget):
        logging.info("exit")
        Gtk.main_quit()


if __name__ == "__main__":
    logging.info("Starting up")
    SyncThingTray()
    Gtk.main()

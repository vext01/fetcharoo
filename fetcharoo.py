# Copyright (c) 2015, Edd Barrett <vext01@gmail.com>
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY
# SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION
# OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

from gi.repository import Gtk
from gi.repository import GObject
from gi.repository import GLib

import subprocess
import distutils.spawn
import logging
import mailbox

logging.root.setLevel(logging.DEBUG)

NOTIFY_SEND = distutils.spawn.find_executable("notify-send")


class MbsyncTray(object):
    """Main class, dealing with tray icon and menus"""

    FETCH_STATE_WAIT = 0
    FETCH_STATE_FETCHING = 1

    def __init__(self, fetch_interval=300):
        # Tray Icon itself
        self.tray = Gtk.StatusIcon()
        self.tray.set_from_stock(Gtk.STOCK_JUSTIFY_RIGHT)
        self.tray.connect('popup-menu', self.show_menu)
        self.tray.set_visible(True)

        self.enabled = True
        self.fetch_state = self.FETCH_STATE_WAIT
        self.fetch_interval = fetch_interval

        # XXX real command
        self.fetch_cmd = ["/bin/sleep", "5"]

        # XXX make configurable
        self.new_mail = {"test": 0}

        self.fetch_mail()  # fetch straight away

    def set_timer(self):
        logging.debug("setting timer for %d seconds" % self.fetch_interval)
        GObject.timeout_add_seconds(self.fetch_interval, self.timer_callback)

    def timer_callback(self):
        """Called by gobject timeout periodically to check for mail"""

        logging.debug("timer callback running")
        if self.fetch_state == self.FETCH_STATE_WAIT:
            if self.enabled:
                self.fetch_mail()
        else:
            assert False  # NOREACH

        return False

    def fetch_done_callback(self, pid, rv, data):
        if rv != 0:
            err_s = "'%s' failed! exit=%d" % (" ".join(self.fetch_cmd), rv)
            logging.error(err_s)
            self.notify(err_s)
        else:
            logging.debug("fetch process done, exit=%d" % rv)

        self.check_for_new_mail()

        self.fetch_state = self.FETCH_STATE_WAIT
        self.set_timer()

    def check_for_new_mail(self):
        for md_name, old_count in self.new_mail.iteritems():
            logging.info("checking maildir '%s' for new mail" % md_name)
            md = mailbox.Maildir(md_name, create=False)
            new_count = len(md)
            logging.debug("count for maildir %s: %d" % (md_name, new_count))

            if new_count > old_count:
                msg = "%d new messages in maildir %s" % \
                    (new_count, md_name)
                logging.info(msg)
                self.notify(msg)
                self.new_mail[md_name] = new_count

    def fetch_mail(self):
        """Shell out to a command to fetch email into a maildir"""
        logging.info("Calling: %s" % " ".join(self.fetch_cmd))
        try:
            pid, _in, out, err = GObject.spawn_async(
                self.fetch_cmd, flags=GObject.SPAWN_DO_NOT_REAP_CHILD)
        except GLib.Error as e:
            err_s = "spawn failed: %s" % e
            logging.error(err_s)
            self.notify(err_s)
            self.set_timer()  # try again
            return False

        self.fetch_state = self.FETCH_STATE_FETCHING
        GObject.child_watch_add(pid, self.fetch_done_callback, None)
        logging.debug("fetch process pid: %d" % pid)

        return False

    def notify(self, message):
        logging.debug("notify user: %s" % message)
        if NOTIFY_SEND:
            subprocess.check_call([NOTIFY_SEND, message])
        else:
            logging.warn("notify send not found, cannot notify")

    def toggle_enabled(self, x):
        self.enabled = not self.enabled
        on_off = "ON" if self.enabled else "OFF"
        logging.info("user toggled fetching, now %s" % on_off)
        if self.enabled:
            self.set_timer()

    def show_menu(self, icon, button, time):
        logging.debug("user enabled menu")
        self.menu = Gtk.Menu()

        # Enable/Disable
        option = "Disable" if self.enabled else "Enable"
        en_item = Gtk.MenuItem(option)
        en_item.connect('activate', self.toggle_enabled)
        en_item.show()
        self.menu.append(en_item)

        # Exit
        exit = Gtk.MenuItem("Exit")
        exit.show()
        self.menu.append(exit)
        exit.connect('activate', Gtk.main_quit)

        self.menu.popup(None, None, None, None, button, time)


if __name__ == "__main__":
    logging.info("starting up")
    MbsyncTray(fetch_interval=5)
    Gtk.main()

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


class WatchedMaildir(object):
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.last_count = 0


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
        self.watch_maildirs = [
            WatchedMaildir("Test:test", "test"),
            WatchedMaildir("Test:yay", "yay"),
            WatchedMaildir("Test:xxx", "xxx"),
        ]

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
        for watch in self.watch_maildirs:
            logging.info("checking maildir '%s' (%s) for new mail"
                         % (watch.name, watch.path))

            try:
                md = mailbox.Maildir(watch.path, create=False)
            except mailbox.NoSuchMailboxError:
                err_s = "No such mailbox: %s" % watch.path
                logging.error(err_s)
                self.notify(err_s)
                continue

            new_count = len(md)
            md.close()
            logging.debug("count = %d" % new_count)

            # XXX this logic is naive
            # Is the new count the same, but with different messages?
            # Suggest keeping a hash summary of the new messages in order
            # to know really whether to show the notification.
            if new_count > watch.last_count:
                msg = "%d new messages in maildir %s" % \
                    (new_count, watch.name)
                logging.info(msg)
                self.notify(msg)
                watch.last_count = new_count

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

        # Clickable maildir entries
        md_lens = [len(md.name) for md in self.watch_maildirs]
        md_name_size = max(md_lens)
        for md in self.watch_maildirs:
            pad_md_name = md.name.ljust(md_name_size)
            # XXX needs to be a monospace font
            label = "%s: %05d" % (pad_md_name, md.last_count)
            md_item = Gtk.MenuItem(label)
            #md_item.connect('activate', xxx)
            md_item.show()
            self.menu.append(md_item)

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

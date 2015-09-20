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
import json
import os

logging.root.setLevel(logging.DEBUG)

NOTIFY_SEND = distutils.spawn.find_executable("notify-send")
DEFAULT_CONFIG_PATH = os.path.join(os.environ["HOME"], ".fetcharoo.json")


class WatchedMaildir(object):
    def __init__(self, name, path):
        self.name = name
        self.path = str(path)
        self.new_msg_ids = frozenset([])


class MbsyncTray(object):
    """Main class, dealing with tray icon and menus"""

    FETCH_STATE_WAIT = 0
    FETCH_STATE_FETCHING = 1
    FETCH_STATE_DISABLED = 2

    def __init__(self, config):
        # Tray Icon itself

        self.tray = Gtk.StatusIcon()
        self.tray.connect('popup-menu', self.show_menu)
        self.tray.set_visible(True)

        self.fetch_interval = config["fetch_interval"]
        self.fetch_cmd = [str(x) for x in config["fetch_command"]]

        self.watch_maildirs = []
        for name, info in config["maildirs"].iteritems():
            self.watch_maildirs.append(WatchedMaildir(name, info["path"]))

        self.change_state(self.FETCH_STATE_WAIT)

        self.fetch_mail()  # fetch straight away

    def set_icon(self):
        if self.fetch_state == self.FETCH_STATE_WAIT:
            if self.is_new_mail():
                icon_name = "mail-unread"
            else:
                icon_name = "mail-read"
        elif self.fetch_state == self.FETCH_STATE_FETCHING:
            icon_name = "mail-send-receive"
        elif self.fetch_state == self.FETCH_STATE_DISABLED:
            icon_name = "stock_delete"
        else:
            assert False

        self.tray.set_from_icon_name(icon_name)

    def set_timer(self):
        logging.debug("setting timer for %d seconds" % self.fetch_interval)
        GObject.timeout_add_seconds(self.fetch_interval, self.timer_callback)

    def timer_callback(self):
        """Called by gobject timeout periodically to check for mail"""

        logging.debug("timer callback running")
        if self.fetch_state == self.FETCH_STATE_WAIT:
            self.fetch_mail()
        elif self.fetch_state == self.FETCH_STATE_DISABLED:
            pass
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

        self.change_state(self.FETCH_STATE_WAIT)
        self.set_timer()

    def is_new_mail(self):
        for watch in self.watch_maildirs:
            if watch.new_msg_ids:
                return True

    def check_for_new_mail(self):
        for watch in self.watch_maildirs:
            logging.info("checking maildir '%s' (%s) for new mail"
                         % (watch.name, watch.path))

            try:
                md = mailbox.Maildir(watch.path, create=False,
                                     factory=mailbox.MaildirMessage)
            except mailbox.NoSuchMailboxError:
                err_s = "No such mailbox: %s" % watch.path
                logging.error(err_s)
                self.notify(err_s)
                continue

            new_msgs = []
            for k in md.iterkeys():
                msg = md.get_message(k)
                flags = msg.get_flags()
                if 'S' not in flags:
                    new_msgs.append(k)
            md.close()

            new_msgs = frozenset(new_msgs)
            old_msgs = watch.new_msg_ids
            actually_new = old_msgs.symmetric_difference(new_msgs)

            if actually_new:
                msg = "%d new messages in maildir %s" % \
                    (len(actually_new), watch.name)
                logging.info(msg)
                self.notify(msg)
                watch.new_msg_ids = actually_new

    def change_state(self, which):
        self.fetch_state = which
        self.set_icon()

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

        self.change_state(self.FETCH_STATE_FETCHING)
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
        if self.fetch_state == self.FETCH_STATE_DISABLED:
            on_off = "ON"
            self.fetch_mail()  # wil set new state
        else:
            on_off = "OFF"
            self.change_state(self.FETCH_STATE_DISABLED)

        logging.info("user toggled fetching, now %s" % on_off)

    def show_menu(self, icon, button, time):
        logging.debug("user enabled menu")
        self.menu = Gtk.Menu()

        # Clickable maildir entries
        md_lens = [len(md.name) for md in self.watch_maildirs]
        md_name_size = max(md_lens)
        for md in self.watch_maildirs:
            pad_md_name = md.name.ljust(md_name_size)
            # XXX needs to be a monospace font
            label = "%s: %05d" % (pad_md_name, len(md.new_msg_ids))
            md_item = Gtk.MenuItem(label)
            #md_item.connect('activate', xxx)
            md_item.show()
            self.menu.append(md_item)

        # Enable/Disable
        if self.fetch_state == self.FETCH_STATE_DISABLED:
            option = "Enable"
        else:
            option = "Disable"
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


def read_config(path):
    logging.info("reading config file from '%s'" % path)
    with open(path, "r") as fh:
        config = json.load(fh)
    return config

if __name__ == "__main__":
    logging.info("starting up")
    config = read_config(DEFAULT_CONFIG_PATH)
    MbsyncTray(config)
    Gtk.main()

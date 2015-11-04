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
import json
import os
import sys
import signal

logging.root.setLevel(logging.DEBUG)

NOTIFY_SEND = distutils.spawn.find_executable("notify-send")
DEFAULT_CONFIG_PATH = os.path.join(os.environ["HOME"], ".fetcharoo.json")


def fatal(msg):
    logging.fatal(msg)
    sys.exit(1)


def sanitise_config_type(d, typ, name):
    if not isinstance(d, typ):
        fatal("%s in config should be a %s" % (name, typ))


class WatchedMaildir(object):
    def __init__(self, name, path, click_command):
        self.name = name
        self.path = path
        self.click_command = click_command
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

        # Sanitise config file input
        try:
            self.fetch_interval = config["fetch_interval"]
        except KeyError:
            fatal("config is missing a 'fetch_interval'")
        sanitise_config_type(self.fetch_interval, int, "fetch_interval")

        try:
            self.fetch_timeout = config["fetch_timeout"]
        except KeyError:
            fatal("config is missing a 'fetch_timeout'")
        sanitise_config_type(self.fetch_timeout, int, "fetch_timeout")

        try:
            self.fetch_cmd = config["fetch_command"]
        except KeyError:
            fatal("config is missing a 'fetch_command'")
        sanitise_config_type(self.fetch_cmd, list, "fetch_command")
        self.fetch_cmd = [str(x) for x in self.fetch_cmd]

        try:
            md_config = config["maildirs"]
        except KeyError:
            md_config = {}  # ok to have no maildirs
        sanitise_config_type(md_config, dict, "maildirs")

        self.watch_maildirs = []
        for name, info in md_config.iteritems():
            try:
                md_path = info["path"]
            except KeyError:
                fatal("maildir '%s' in config file is missing a 'path'" % name)
            md_path = str(md_path)
            sanitise_config_type(md_path, str,
                                 "path for maildir '%s'" % name)
            try:
                md_click_cmd = info["click_command"]
            except KeyError:
                md_click_cmd = None  # OK to have no command

            if md_click_cmd is not None:
                sanitise_config_type(md_click_cmd, list,
                                     "click_command for maildir '%s'" % name)
                md_click_cmd = [str(x) for x in md_click_cmd]

            self.watch_maildirs.append(WatchedMaildir(
                name, md_path, md_click_cmd))

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

    def set_timer(self, timeout):
        logging.debug("setting timer for %d seconds" % timeout)
        GObject.timeout_add_seconds(timeout, self.timer_callback)

    def kill_fetch_subprocess(self):
        os.kill(self.fetch_subprocess_pid, signal.SIGKILL)
        self.fetch_subprocess_pid = None  # used to indicate it was killed

    def timer_callback(self):
        """Called by gobject timeout periodically to check for mail"""

        logging.debug("timer callback running")
        if self.fetch_state == self.FETCH_STATE_WAIT:
            self.fetch_mail()
        elif self.fetch_state == self.FETCH_STATE_DISABLED:
            pass
        elif self.fetch_state == self.FETCH_STATE_FETCHING:
            # this is taking too long
            err_s = "'%s' timed out!" % " ".join(self.fetch_cmd)
            logging.error(err_s)
            self.notify(err_s)
            self.kill_fetch_subprocess()
        else:
            assert False  # NOREACH

        return False

    def fetch_done_callback(self, pid, rv, data):
        if self.fetch_subprocess_pid is not None:
            # process was NOT killed due to timeout
            if rv != 0:
                err_s = "'%s' failed! exit=%d" % \
                    (" ".join(self.fetch_cmd), rv)
                logging.error(err_s)
                self.notify(err_s)
            else:
                logging.debug("fetch process done, exit=%d" % rv)

        self.check_for_new_mail()

        self.change_state(self.FETCH_STATE_WAIT)
        self.set_timer(self.fetch_interval)

    def is_new_mail(self):
        for watch in self.watch_maildirs:
            if watch.new_msg_ids:
                return True

    def check_for_new_mail(self):
        for watch in self.watch_maildirs:
            logging.info("checking maildir '%s' (%s) for new mail"
                         % (watch.name, watch.path))

            # Sadly it's way to slow to use the mailbox module in the
            # standard library, so we fall back on filesystem ops.
            new_subdir = os.path.join(watch.path, "new")
            new_msgs = [x for x in os.listdir(new_subdir)
                        if not os.path.isdir(os.path.join(new_subdir, x))]

            new_msgs = frozenset(new_msgs)
            old_msgs = watch.new_msg_ids
            actually_new = new_msgs - old_msgs

            if actually_new:
                msg = "%d new messages in maildir %s" % \
                    (len(actually_new), watch.name)
                logging.info(msg)
                self.notify(msg)
            watch.new_msg_ids = new_msgs

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
            self.set_timer(self.fetch_interval)  # try again in a while
            return False

        self.fetch_subprocess_pid = pid
        self.change_state(self.FETCH_STATE_FETCHING)
        GObject.child_watch_add(pid, self.fetch_done_callback, None)
        self.set_timer(self.fetch_timeout)  # ensure it doesn't take forever

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

    def mk_maildir_click_cb(self, cmd):
        def wrap(nouse):
            logging.info("spawning mailbox click_command: %s" % cmd)
            pid, _in, out, err = GObject.spawn_async(cmd)
        return wrap

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
            md_item.connect('activate',
                            self.mk_maildir_click_cb(md.click_command))
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
        try:
            config = json.load(fh)
        except Exception as e:
            fatal("problem with config file: %s" % str(e))
    return config

if __name__ == "__main__":
    logging.info("starting up")
    config = read_config(DEFAULT_CONFIG_PATH)
    MbsyncTray(config)
    Gtk.main()

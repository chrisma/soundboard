# encoding: utf-8
import csv
import fcntl
import math
import optparse
import os
import subprocess
import string
import struct
import sys
import termios
import tty
try:
    from urllib.parse import quote_plus
except ImportError:
    from urllib import quote_plus


CONFIG_FILE = 'videos.cfg'
SOUND_SUFFIXES = ['wav', 'mp3', 'ogg']
KEYS = string.ascii_lowercase + string.digits + string.ascii_uppercase
CACHE_DIR = 'cache'
YOUTUBE = 'http://www.youtube.com/watch?v=%s'
HERE = os.path.dirname(os.path.abspath(__file__))


def read(path):
    with open(path) as f:
        config = csv.DictReader(f,
                 fieldnames='key,loc,title,start,length,format'.split(','))
        for video in config:
            key = video['key']
            if key.startswith('#') and key != '#':
                continue
            loc = video['loc']
            video['uri'] = uri = loc if '.' in loc else YOUTUBE % loc
            video['title'] = video['title'].decode('utf-8')
            video['linenum'] = config.line_num
            # By happy coincidence, quote_plus cannot contain any of quvi's
            # --exec specifiers (%u, %t, %e, and %h.  Instead of %eX it uses
            # %EX.)  Let's hope `HERE` does not contain any as well.
            video['path'] = os.path.join(HERE, CACHE_DIR, quote_plus(uri))
            yield video

def read_many(paths, resolve, keys=KEYS):
    videos = {}
    conflicts = []
    keys = list(KEYS)

    for path in paths:
        for video in read(path):
            key = video['key']
            if key in videos:
                if resolve:
                    conflicts.append(video)
                else:
                    raise ValueError(
                            "duplicate hotkey `%s' in line %d, file `%s'" %
                            (key, video['linenum'], path))
            else:
                if key in keys:
                    keys.remove(key)
                videos[key] = video

    for key, video in zip(keys, conflicts):
        video['key'] = key
        videos[key] = video

    return videos


def setup(videos):
    try:
        os.makedirs(os.path.join(HERE, CACHE_DIR))
    except OSError:
        pass

    for video in videos.values():
        if os.path.exists(video['path']):
            continue
        cmd = ['quvi', '--feature', '-verify', video['uri'],
               '--exec', 'wget %%u -O %s' % video['path']]
        if video['format']:
            cmd.extend(['--format', video['format']])
        ret = subprocess.call(cmd)
        if ret == 0x41:  # QUVI_NOSUPPORT, libquvi does not support the host
            # Maybe we can just download the bare resource.
            subprocess.call(['wget', video['uri'], '-O', video['path']])


def loop(videos):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)

    try:
        while 1:
            ch = sys.stdin.read(1)
            if ch == '\x03':  # Ctrl-C
                break
            if ch in videos:
                video = videos[ch]
                play(video)
    finally:
        tty.setcbreak(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def play(video):
    cmd = ['mplayer', '-fs', '-af', 'volnorm=2:0.75', video['path']]
    if video['start']:
        cmd.extend(['-ss', video['start']])
    if video['length']:
        cmd.extend(['-endpos', video['length']])
    subprocess.call(cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def usage(videos):
    """
    ┏━━━┱──────────────┐
    ┃ x ┃ First title  │
    ┃ y ┃ Second title │
    ┗━━━┹──────────────┘

    """
    # $COLUMNS
    width, = struct.unpack('xxh', fcntl.ioctl(0, termios.TIOCGWINSZ, '0000'))

    # Sort by title length so subsequent columns are guaranteed to have the
    # longest item at their very top.
    out = videos.values()
    out.sort(key=lambda v: len(v['title']), reverse=True)
    total = len(out)

    # Responsive design for terminals, fuckyeah
    for cols in range(total, 0, -1):
        # First, and longest, item of the `i`th column.
        column = lambda i: int(math.ceil(float(i) * total / cols))
        rows = column(1)
        pads = [len(out[column(i)]['title']) for i in xrange(cols)]

        # The number of columns is too damn high.
        # Some columns are empty and can still be removed.
        if rows * cols - total >= rows:
            continue

        realw = sum(pads) + len(u"┏━━━┱──┐ ") * cols
        if realw < width:
            break

    # Header
    for j in xrange(cols):
        print u"┏━━━┱─" + u"─"*pads[j] + u"─┐",
    print

    # Body
    for i in xrange(rows):
        for j in xrange(cols):
            try:
                video = out[j * rows + i]
            except IndexError:
                video = dict(key=' ', title='', loc='')
            is_sound = any(video['loc'].endswith('.' + suf)
                           for suf in SOUND_SUFFIXES)
            print u"┃ %s ┃%s%-*s │" % (
                    video['key'], ' ~'[is_sound], pads[j], video['title']),
        print

    # Footer
    for j in xrange(cols):
        print u"┗━━━┹─" + u"─"*pads[j] + u"─┘",
    print


def main(argv):
    parser = optparse.OptionParser()
    parser.add_option('-s', '--setup',
            action='store_true', default=False,
            help="download all video files")
    parser.add_option('-a', '--auto-resolve',
            action='store_true', default=False,
            help="automatically resolve keybinding conflicts")
    parser.add_option('-k', '--key',
            help="only play a single video")
    options, args = parser.parse_args(argv)

    videos = read_many(args or [os.path.join(HERE, CONFIG_FILE)],
                       options.auto_resolve)

    if options.key:
        play(videos[options.key])
    elif options.setup:
        setup(videos)
    else:
        usage(videos)
        loop(videos)


if __name__ == '__main__':
    main(sys.argv[1:])

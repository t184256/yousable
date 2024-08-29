# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import math
import multiprocessing
import random
import sys
import time

import setproctitle

_proctitlebase = None
_sleeptimer = None
_sleepreason = None
_status = None
_children = []


def proctitle(status=None):
    global _status
    _status = status
    _proctitle_update()


def _proctitle_update():
    global _proctitlebase, _sleeptimer, _sleepreason, _status

    TRANSLIT = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'c', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': "'", 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    TRANSLIT.update({k.upper(): v.title() for k, v in TRANSLIT.items()})
    TRANSLIT = {ord(k): v for k, v in TRANSLIT.items()}

    def clean_str(s):
        s = s.translate(TRANSLIT)
        return ''.join(c for c in s if c.isprintable() and ord(c) < 128)

    s = ['yousable']
    if _proctitlebase:
        s.append(_proctitlebase)
    if _sleepreason:
        s.append(_sleepreason)
    if _sleeptimer:
        s.append(f'{_sleeptimer}s')
    if _status:
        s.append(_status)
    setproctitle.setproctitle(clean_str(': '.join(s)))


def sleep(sleepreason, config=None, base_sec=None, variance_sec=None):
    base_sec = (
        base_sec if base_sec is not None else
        config['limits']['throttle_seconds']
    )
    variance_sec = (
        variance_sec if variance_sec is not None else
        config['limits']['throttle_variance_seconds']
    )
    _sleep(base_sec, variance_sec, sleepreason)


def _sleep(base, variance, sleepreason):
    global _sleeptimer, _sleepreason
    _sleepreason = sleepreason
    total = int(math.ceil(base + random.random() * variance))
    print(f'sleeping for {total}s: {sleepreason}...', file=sys.stderr)
    for i in range(total):
        #print(f'sleeping for {total - i}s/{total}s: {sleepreason}...',
        #      file=sys.stderr)
        time.sleep(1)  # TODO: something less dynamic
        _sleeptimer = total - i
        _proctitle_update()
    _sleeptimer = _sleepreason = None


def start_process(name, target, *args):
    def target_(*a):
        global _proctitlebase, _children
        _children = []
        _proctitlebase = name
        proctitle('starting...')
        return target(*a)
    p = multiprocessing.Process(target=target_, args=args)
    p.start()
    _children.append(p)
    return p


def reap():
    global _children
    new_children = []
    for p in _children:
        if p.exitcode is None:
            new_children.append(p)
    _children = new_children

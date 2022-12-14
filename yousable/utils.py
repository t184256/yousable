# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import multiprocessing

import setproctitle


_proctitlebase = None
_children = []


def proctitle(status=None):
    global _proctitlebase

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
    if status:
        s.append(status)
    setproctitle.setproctitle(clean_str(': '.join(s)))


def start_process(name, target, *args):
    def target_(*a):
        global _proctitlebase, _children
        _children = []
        _proctitlebase = name
        proctitle(f'starting...')
        return target(*a)
    p = multiprocessing.Process(target=target_, args=args)
    p.start()
    _children.append(p)
    return p


def reap():
    global _children
    new_children = []
    for p in _children:
        if p.exitcode == None:
            new_children.append(p)
    _children = new_children

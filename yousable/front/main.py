# SPDX-FileCopyrightText: 2022 Alexander Sosedkin <monk@unboiled.info>
# SPDX-License-Identifier: AGPL-3.0-or-later

import functools
import os
import re
import subprocess
import sys
import urllib

import flask
from flask_httpauth import HTTPBasicAuth
import werkzeug.security

import yousable


def create_app(config=None):
    app = flask.Flask(__name__)
    auth = HTTPBasicAuth()

    config = config or yousable.main.load_config()
    app.config.update(config)


    @app.route('/')
    def root():
        return "query /feed/CHANNEL_NAME to get the RSS feed you're after"


    def separate_extra_opts_from_user(user):
        if user is None:
            return None, {}
        user, *extra = user.split(';', 1)
        extra = dict([x.split('=') for x in extra if '=' in x])
        return user, extra


    def hash_password(plain):
        return werkzeug.security.generate_password_hash(plain)


    @auth.verify_password
    def verify_password(user, password):
        user, _ = separate_extra_opts_from_user(user)
        if user in app.config['secrets']:
            return werkzeug.security.check_password_hash(
                app.config['secrets'][user], password
            )
        return False


    def login_required(func):
        @functools.wraps(func)
        def f(*a, **kwa):
            if app.config['secrets'] is not None:
                return auth.login_required(func)(*a, **kwa)
            else:
                return func(*a, **kwa)
        return f


    def url_maker(*components, **kwargs):
        baseurl = flask.url_for('root', _external=True).rstrip('/')
        return ('/'.join([baseurl, *components]) +
                ('?' + '&'.join(f'{k}={v}' for k, v in kwargs.items())
                 if kwargs else ''))


    @app.route('/feed/<feed_name>')
    @login_required
    def feed(feed_name):
        user, extra_opts = separate_extra_opts_from_user(auth.current_user())
        extra_opts = {**flask.request.args, **extra_opts}
        if feed_name not in app.config['feeds']:
            return f'`{feed_name}` not in config.feeds', 400
        if 'url' not in app.config['feeds'][feed_name]:
            return f'`url not specified for `{feed_name}`', 500
        profile = (extra_opts['profile'] if 'profile' in extra_opts
                   else 'default')
        if profile not in app.config['profiles']:
            return f'`profile `{profile}` not specified in configuration', 500
        return yousable.front.feed.feed(app.config, profile, feed_name,
                                        extra_opts, url_maker)

    @app.route('/download/<feed_name>/<entry_id_profile_container>')
    @login_required
    def _download(feed_name, entry_id_profile_container):
        assert entry_id_profile_container.count('.') == 2
        return download(feed_name, *entry_id_profile_container.split('.'))


    @app.route('/download/<feed_name>/<entry_id>/<profile>/<container>')
    @login_required
    def download(feed_name, entry_id, profile, container):
        if feed_name not in app.config['feeds']:
            return f'`{feed_name}` not in config.feeds', 400
        if profile not in app.config['profiles']:
            return f'`profile `{profile}` not specified in configuration', 500

        out_path = os.path.join(feed_name, entry_id, f'{profile}.{container}')
        server_path = os.path.join(app.config['paths']['x_accel'], out_path)
        file_path = os.path.join(app.config['paths']['out'], out_path)
        if not os.path.exists(file_path):
            return (f'`{feed_name}/{entry_id}.{profile}.{container}` '
                    'not present', 404)

        profile_config = app.config['profiles'][profile]
        audio_video = 'video' if profile_config['video'] else 'audio'
        mime = f'{audio_video}/{container}'
        name = f'{entry_id}.{profile}.{container}'

        if app.config['paths']['x_accel'] is not None:
            response = flask.make_response()
            response.headers['Content-Description'] = 'File Transfer'
            response.headers['Cache-Control'] = 'no-cache'
            response.headers['Content-Type'] = mime
            response.headers['Content-Disposition'] = \
                    f'attachment; filename={name}'
            response.headers['Content-Length'] = os.path.getsize(file_path)
            response.headers['X-Accel-Redirect'] = \
                    urllib.parse.quote(server_path)
            return response
        else:
            return flask.send_file(file_path, mimetype=mime,
                                   as_attachment=True, download_name=name)

    return app


def main(config=None):
    app = create_app(config=None)
    app.run(host='0.0.0.0', port=8080)  # debugging server for development


if __name__ == '__main__':
    main()

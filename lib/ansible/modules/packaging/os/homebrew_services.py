#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2013, Andrew Dunham <andrew@du.nham.ca>
# (c) 2013, Daniel Jaouen <dcj24@cornell.edu>
# (c) 2015, Indrajit Raychaudhuri <irc+code@indrajit.com>
#
# Based on macports (Jimmy Tang <jcftang@gmail.com>)
#
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: homebrew_services
author:
    - "Indrajit Raychaudhuri (@indrajitr)"
    - "Daniel Jaouen (@danieljaouen)"
    - "Andrew Dunham (@andrew-d)"
requirements:
   - "python >= 2.6"
short_description: Services manager for homebrew
description:
    - Manages homebrew services
version_added: "2.5.0"
options:
    name:
        description:
            - list of names of packages to start/stop/restart
        required: false
        default: None
        aliases: ['pkg', 'package', 'formula']
    path:
        description:
            - "A ':' separated list of paths to search for 'brew'
              executable. Since a package (I(formula) in homebrew
              parlance) location is prefixed relative to the actual path
              of I(brew) command, providing an alternative I(brew) path
              enables managing different set of packages in an
              alternative location in the system."
        required: false
        default: '/usr/local/bin'
    state:
        description:
            - state of the package
        choices: [ 'started', 'stopped', 'restarted' ]
        required: true
        default: started
    service_options:
        description:
            - options flags
        required: false
        default: null
        aliases: ['options']
        version_added: "1.4"
'''
EXAMPLES = '''
# Start formula foo with 'brew' in default path (C(/usr/local/bin))
- homebrew_services:
    name: foo
    state: started

# Start formula foo with 'brew' in alternate path C(/my/other/location/bin)
- homebrew_services:
    name: foo
    path: /my/other/location/bin
    state: started

# Stop formula foo with 'brew' in default path (C(/usr/local/bin))
- homebrew_services:
    name: foo
    state: stopped

# Restart formula foo with 'brew' in default path
- homebrew_services:
    name: foo
    state: restarted
'''

import os.path
import re

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.six import iteritems, string_types


# exceptions -------------------------------------------------------------- {{{
class HomebrewServiceException(Exception):
    pass
# /exceptions ------------------------------------------------------------- }}}


# utils ------------------------------------------------------------------- {{{
def _create_regex_group(s):
    lines = (line.strip() for line in s.split('\n') if line.strip())
    chars = filter(None, (line.split('#')[0].strip() for line in lines))
    group = r'[^' + r''.join(chars) + r']'
    return re.compile(group)
# /utils ------------------------------------------------------------------ }}}


class HomebrewService(object):
    '''A class to manage HomebrewService packages.'''

    # class regexes ------------------------------------------------ {{{
    VALID_PATH_CHARS = r'''
        \w                  # alphanumeric characters (i.e., [a-zA-Z0-9_])
        \s                  # spaces
        :                   # colons
        {sep}               # the OS-specific path separator
        .                   # dots
        -                   # dashes
    '''.format(sep=os.path.sep)

    VALID_BREW_PATH_CHARS = r'''
        \w                  # alphanumeric characters (i.e., [a-zA-Z0-9_])
        \s                  # spaces
        {sep}               # the OS-specific path separator
        .                   # dots
        -                   # dashes
    '''.format(sep=os.path.sep)

    VALID_PACKAGE_CHARS = r'''
        \w                  # alphanumeric characters (i.e., [a-zA-Z0-9_])
        .                   # dots
        /                   # slash (for taps)
        \+                  # plusses
        -                   # dashes
        :                   # colons (for URLs)
        @                   # at-sign
    '''

    INVALID_PATH_REGEX = _create_regex_group(VALID_PATH_CHARS)
    INVALID_BREW_PATH_REGEX = _create_regex_group(VALID_BREW_PATH_CHARS)
    INVALID_PACKAGE_REGEX = _create_regex_group(VALID_PACKAGE_CHARS)
    # /class regexes ----------------------------------------------- }}}

    # class validations -------------------------------------------- {{{
    @classmethod
    def valid_path(cls, path):
        '''
        `path` must be one of:
         - list of paths
         - a string containing only:
             - alphanumeric characters
             - dashes
             - dots
             - spaces
             - colons
             - os.path.sep
        '''

        if isinstance(path, string_types):
            return not cls.INVALID_PATH_REGEX.search(path)

        try:
            iter(path)
        except TypeError:
            return False
        else:
            paths = path
            return all(cls.valid_brew_path(path_) for path_ in paths)

    @classmethod
    def valid_brew_path(cls, brew_path):
        '''
        `brew_path` must be one of:
         - None
         - a string containing only:
             - alphanumeric characters
             - dashes
             - dots
             - spaces
             - os.path.sep
        '''

        if brew_path is None:
            return True

        return (
            isinstance(brew_path, string_types)
            and not cls.INVALID_BREW_PATH_REGEX.search(brew_path)
        )

    @classmethod
    def valid_package(cls, package):
        '''A valid package is either None or alphanumeric.'''

        if package is None:
            return True

        return (
            isinstance(package, string_types)
            and not cls.INVALID_PACKAGE_REGEX.search(package)
        )

    @classmethod
    def valid_state(cls, state):
        '''
        A valid state is one of:
            - None
            - installed
            - upgraded
            - head
            - linked
            - unlinked
            - absent
        '''

        if state is None:
            return True
        else:
            return (
                isinstance(state, string_types)
                and state.lower() in (
                    'started',
                    'stopped',
                    'restarted',
                )
            )

    @classmethod
    def valid_module(cls, module):
        '''A valid module is an instance of AnsibleModule.'''

        return isinstance(module, AnsibleModule)
    # /class validations ------------------------------------------- }}}

    # class properties --------------------------------------------- {{{
    @property
    def module(self):
        return self._module

    @module.setter
    def module(self, module):
        if not self.valid_module(module):
            self._module = None
            self.failed = True
            self.message = 'Invalid module: {0}.'.format(module)
            raise HomebrewServiceException(self.message)

        else:
            self._module = module
            return module

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path):
        if not self.valid_path(path):
            self._path = []
            self.failed = True
            self.message = 'Invalid path: {0}.'.format(path)
            raise HomebrewServiceException(self.message)

        else:
            if isinstance(path, string_types):
                self._path = path.split(':')
            else:
                self._path = path

            return path

    @property
    def brew_path(self):
        return self._brew_path

    @brew_path.setter
    def brew_path(self, brew_path):
        if not self.valid_brew_path(brew_path):
            self._brew_path = None
            self.failed = True
            self.message = 'Invalid brew_path: {0}.'.format(brew_path)
            raise HomebrewServiceException(self.message)

        else:
            self._brew_path = brew_path
            return brew_path

    @property
    def params(self):
        return self._params

    @params.setter
    def params(self, params):
        self._params = self.module.params
        return self._params

    @property
    def current_package(self):
        return self._current_package

    @current_package.setter
    def current_package(self, package):
        if not self.valid_package(package):
            self._current_package = None
            self.failed = True
            self.message = 'Invalid package: {0}.'.format(package)
            raise HomebrewServiceException(self.message)

        else:
            self._current_package = package
            return package
    # /class properties -------------------------------------------- }}}

    def __init__(self, module, path, packages=None, state=None,
                 service_options=None):
        if not service_options:
            service_options = list()
        self._setup_status_vars()
        self._setup_instance_vars(module=module, path=path, packages=packages,
                                  state=state, service_options=service_options, )

        self._prep()

    # prep --------------------------------------------------------- {{{
    def _setup_status_vars(self):
        self.failed = False
        self.changed = False
        self.changed_count = 0
        self.unchanged_count = 0
        self.message = ''

    def _setup_instance_vars(self, **kwargs):
        for key, val in iteritems(kwargs):
            setattr(self, key, val)

    def _prep(self):
        self._prep_brew_path()

    def _prep_brew_path(self):
        if not self.module:
            self.brew_path = None
            self.failed = True
            self.message = 'AnsibleModule not set.'
            raise HomebrewServiceException(self.message)

        self.brew_path = self.module.get_bin_path(
            'brew',
            required=True,
            opt_dirs=self.path,
        )
        if not self.brew_path:
            self.brew_path = None
            self.failed = True
            self.message = 'Unable to locate homebrew executable.'
            raise HomebrewServiceException('Unable to locate homebrew executable.')

        return self.brew_path

    def _status(self):
        return (self.failed, self.changed, self.message)
    # /prep -------------------------------------------------------- }}}

    def run(self):
        try:
            self._run()
        except HomebrewServiceException:
            pass

        if not self.failed and (self.changed_count + self.unchanged_count > 1):
            self.message = "Changed: %d, Unchanged: %d" % (
                self.changed_count,
                self.unchanged_count,
            )
        (failed, changed, message) = self._status()

        return (failed, changed, message)

    # checks ------------------------------------------------------- {{{
    def _current_package_is_started(self):
        if not self.valid_package(self.current_package):
            self.failed = True
            self.message = 'Invalid package: {0}.'.format(self.current_package)
            raise HomebrewServiceException(self.message)

        cmd = [
            "{brew_path}".format(brew_path=self.brew_path),
            "services"
            "list",
        ]
        rc, out, err = self.module.run_command(cmd, use_unsafe_shell=True)

        for line in out.split('\n'):
            if (
                re.search(r'^' + r"{0}".format(self.current_package) + r'.*started', line)
            ):
                return True

        return False
    # /checks ------------------------------------------------------ }}}

    # commands ----------------------------------------------------- {{{
    def _run(self):
        if self.packages:
            if self.state == 'started':
                return self._start_packages()
            elif self.state == 'stopped':
                return self._stop_packages()
            elif self.state == 'restarted':
                return self._restart_packages()

    # started ------------------------------- {{{
    def _start_current_package(self):
        if not self.valid_package(self.current_package):
            self.failed = True
            self.message = 'Invalid package: {0}.'.format(self.current_package)
            raise HomebrewServiceException(self.message)

        if self.module.check_mode:
            self.changed = True
            self.message = 'Package would be started: {0}'.format(
                self.current_package
            )
            raise HomebrewServiceException(self.message)

        opts = (
            [self.brew_path, 'services', 'start']
            + self.service_options
            + [self.current_package, ]
        )
        cmd = [opt for opt in opts if opt]
        rc, out, err = self.module.run_command(cmd)

        if err == "":
            self.changed_count += 1
            self.message = 'Package started: {0}'.format(
                self.current_package,
            )
            return True
        else:
            self.failed = True
            self.message = err.strip()
            raise HomebrewServiceException(self.message)

    def _start_packages(self):
        for package in self.packages:
            self.current_package = package
            self._start_current_package()

        return True
    # /started ------------------------------ }}}

    # stopped ------------------------------- {{{
    def _stop_current_package(self):
        if not self.valid_package(self.current_package):
            self.failed = True
            self.message = 'Invalid package: {0}.'.format(self.current_package)
            raise HomebrewServiceException(self.message)

        if self.module.check_mode:
            self.changed = True
            self.message = 'Package would be stopped: {0}'.format(
                self.current_package
            )
            raise HomebrewServiceException(self.message)

        opts = (
            [self.brew_path, 'services', 'stop']
            + self.service_options
            + [self.current_package, ]
        )
        cmd = [opt for opt in opts if opt]
        rc, out, err = self.module.run_command(cmd)

        match = (
            r"^Error: Service `"
            + r"{0}".format(self.current_package)
            + r"` is not started."
        )

        if err == "":
            self.changed_count += 1
            self.changed = True
            self.message = 'Package stopped: {0}'.format(self.current_package)
            return True
        elif re.match(match, err):
            self.unchanged_count += 1
            self.changed = False
            self.message = 'Package already stopped: {0}'.format(self.current_package)
            return True
        else:
            self.failed = True
            self.message = err.strip()
            raise HomebrewServiceException(self.message)

    def _stop_packages(self):
        for package in self.packages:
            self.current_package = package
            self._stop_current_package()

        return True
    # /stopped ------------------------------- }}}

    # restarted ------------------------------ {{{
    def _restart_current_package(self):
        if not self.valid_package(self.current_package):
            self.failed = True
            self.message = 'Invalid package: {0}.'.format(self.current_package)
            raise HomebrewServiceException(self.message)

        if self.module.check_mode:
            self.changed = True
            self.message = 'Package would be restarted: {0}'.format(
                self.current_package
            )
            raise HomebrewServiceException(self.message)

        opts = (
            [self.brew_path, 'services', 'restart']
            + self.service_options
            + [self.current_package, ]
        )
        cmd = [opt for opt in opts if opt]
        rc, out, err = self.module.run_command(cmd)

        if err == "":
            self.changed_count += 1
            self.changed = True
            self.message = 'Package restarted: {0}'.format(self.current_package)
            return True
        else:
            self.failed = True
            self.message = err.strip()
            raise HomebrewServiceException(self.message)

    def _restart_packages(self):
        for package in self.packages:
            self.current_package = package
            self._restart_current_package()

        return True
    # /restarted ----------------------------- }}}
    # /commands ---------------------------------------------------- }}}


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(
                aliases=["pkg", "package", "formula"],
                required=True,
                type='list',
            ),
            path=dict(
                default="/usr/local/bin",
                required=False,
                type='path',
            ),
            state=dict(
                default="started",
                choices=[
                    "started",
                    "stopped",
                    "restarted",
                ],
            ),
            service_options=dict(
                default=None,
                aliases=['options'],
                type='list',
            )
        ),
        supports_check_mode=True,
    )

    module.run_command_environ_update = dict(LANG='C', LC_ALL='C', LC_MESSAGES='C', LC_CTYPE='C')

    p = module.params

    if p['name']:
        packages = p['name']
    else:
        packages = None

    path = p['path']
    if path:
        path = path.split(':')

    state = p['state']

    p['service_options'] = p['service_options'] or []
    service_options = ['--{0}'.format(install_option)
                       for install_option in p['service_options']]

    homebrew_service = HomebrewService(module=module, path=path, packages=packages,
                                       state=state,
                                       service_options=service_options)
    (failed, changed, message) = homebrew_service.run()
    if failed:
        module.fail_json(msg=message)
    else:
        module.exit_json(changed=changed, msg=message)


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
# coding: UTF-8
#
# Copyright 2010-2014 The pygit2 contributors
#
# This file is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License, version 2,
# as published by the Free Software Foundation.
#
# In addition to the permissions in the GNU General Public License,
# the authors give you unlimited permission to link the compiled
# version of this file into combinations with other programs,
# and to distribute those combinations without any restriction
# coming from the use of this file.  (The General Public License
# restrictions do apply in other respects; for example, they cover
# modification of the file, and distribution when not linked into
# a combined executable.)
#
# This file is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; see the file COPYING.  If not, write to
# the Free Software Foundation, 51 Franklin Street, Fifth Floor,
# Boston, MA 02110-1301, USA.

"""Setup file for pygit2."""

from __future__ import print_function

import codecs
from distutils.core import setup, Extension, Command
from distutils.command.build import build
from distutils.command.build_ext import build_ext
from distutils.command.sdist import sdist
import distutils.spawn as ds
import distutils.dir_util as dd
from distutils import log
import os
import shlex
import hashlib
import platform
from subprocess import Popen, PIPE
import sys
import unittest
import fileinput

# Read version from local pygit2/version.py without pulling in
# pygit2/__init__.py
sys.path.insert(0, 'pygit2')
from version import __version__, __sha__

# Python 2 support
# See https://github.com/libgit2/pygit2/pull/180 for a discussion about this.
if sys.version_info[0] == 2:
    u = lambda s: unicode(s, 'utf-8')
else:
    u = str

pygit2_exts = [os.path.join('src', name) for name in os.listdir('src')
               if name.endswith('.c')]

platform_name = platform.system()
shared_ext = '.so'
if 'Windows' in platform_name:
    shared_ext = '.dll'
elif 'Darwin' in platform_name:
    shared_ext = '.dylib'

class TestCommand(Command):
    """Command for running unittests without install."""

    user_options = [("args=", None, '''The command args string passed to
                                    unittest framework, such as
                                     --args="-v -f"''')]

    def initialize_options(self):
        self.args = ''
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.run_command('build')
        bld = self.distribution.get_command_obj('build')
        # Add build_lib in to sys.path so that unittest can found DLLs and libs
        sys.path = [os.path.abspath(bld.build_lib)] + sys.path

        test_argv0 = [sys.argv[0] + ' test --args=']
        # For transfering args to unittest, we have to split args by ourself,
        # so that command like:
        #
        #   python setup.py test --args="-v -f"
        #
        # can be executed, and the parameter '-v -f' can be transfering to
        # unittest properly.
        test_argv = test_argv0 + shlex.split(self.args)
        unittest.main(None, defaultTest='test.test_suite', argv=test_argv)


#################
# CMake function
#################
def run_cmd(cmd="cmake", cmd_args=[]):
    """
    Runs CMake to determine configuration for this build
    """
    if ds.find_executable(cmd) is None:
        log.error("%s is required to build libgit2" % cmd)
        log.error("Please install %s and re-run setup" % cmd)
        sys.exit(-1)

    # construct argument string
    try:
        ds.spawn([cmd] + cmd_args)
    except ds.DistutilsExecError:
        log.error("Error while running %s" % cmd)
        log.error("run 'setup.py build --help' for build options"
                  "You may also try editing the settings in "
                  "CMakeLists.txt file and re-running setup")
        sys.exit(-1)


class build_ext_subclass(build_ext):
    def build_extensions(self):
        # download and build libgit2
        ver = __version__
        # apparently, we use an old enough libgit2 that isn't hosted
        if '0.20' in ver:
            ver = '0.20.0'
        fn = 'v%s.zip' % ver
        url = 'https://github.com/libgit2/libgit2/archive/%s' % fn
        cwd = os.getcwd()
        install_path = os.path.abspath(os.path.join('build', 'libgit2'))

        # only build libgit2 once
        if not (os.path.isdir(os.path.join(install_path, 'lib')) and
                os.path.isdir(os.path.join(install_path, 'include'))):

            dd.mkpath(self.build_temp)
            os.chdir(self.build_temp)

            # download and save zip file, only if checksum doesn't match
            sha = None
            try:
                sha = hashlib.sha256(open(fn, 'rb').read()).hexdigest()
            except IOError:
                pass
            if sha != __sha__:
                # TODO: replace with pure python
                run_cmd('curl', ['-LO', url])

            # TODO: replace with pure python
            run_cmd('unzip', ['-o', fn])

            dd.mkpath('build')
            os.chdir('build')

            cmake_args = [
                '-DCMAKE_INSTALL_PREFIX:PATH=%s' % install_path,
                '-DCMAKE_C_COMPILER:PATH=%s' % self.compiler.compiler[0],
                '-DCMAKE_INSTALL_RPATH:PATH=@loader_path',
                '-DCMAKE_INSTALL_NAME_DIR:PATH=@loader_path',
                '-DCMAKE_INSTALL_RPATH_USE_LINK_PATH:BOOL=TRUE',
                '-DBUILD_CLAR:BOOL=OFF',
                '../libgit2-%s' % ver,
            ]

            run_cmd('cmake', cmake_args)

            # bug in libgit2 that is fixed with newer versions
            for line in fileinput.input('CMakeFiles/git2.dir/flags.make',
                                        inplace=True):
                print(line.replace('-DGIT_USE_ICONV', ''), end='')

            run_cmd('make', '-j8 all install'.split())

            os.chdir(cwd)

            # post-install: move to same location as _pygit2.so
            libs = ['libgit2.0.20.0', 'libgit2.0', 'libgit2']
            lib_path = os.path.join(install_path, 'lib')
            for l in libs:
                self.copy_file(os.path.join(lib_path, l + shared_ext),
                               os.path.abspath(self.build_lib))

        # make sure we search our header path first
        self.compiler.compiler_so.insert(1, '-Ibuild/libgit2/include')
        build_ext.build_extensions(self)


class sdist_files_from_git(sdist):
    def get_file_list(self):
        popen = Popen(['git', 'ls-files'], stdout=PIPE, stderr=PIPE)
        stdoutdata, stderrdata = popen.communicate()
        if popen.returncode != 0:
            print(stderrdata)
            sys.exit()

        for line in stdoutdata.splitlines():
            # Skip hidden files at the root
            if line[0] == '.':
                continue
            self.filelist.append(line)

        # Ok
        self.filelist.sort()
        self.filelist.remove_duplicates()
        self.write_manifest()


cmdclass = {
    'test': TestCommand,
    'sdist': sdist_files_from_git}

# always bundle libgit2 shared libraries with pygit2
cmdclass['build_ext'] = build_ext_subclass

classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Topic :: Software Development :: Version Control"]


with codecs.open('README.rst', 'r', 'utf-8') as readme:
    long_description = readme.read()

setup(name='pygit2',
      description='Python bindings for libgit2.',
      keywords='git',
      version=__version__,
      url='http://github.com/libgit2/pygit2',
      classifiers=classifiers,
      license='GPLv2',
      maintainer=u('J. David Ibáñez'),
      maintainer_email='jdavid.ibp@gmail.com',
      long_description=long_description,
      packages=['pygit2'],
      ext_modules=[
          Extension('_pygit2', pygit2_exts,
                    extra_link_args=['build/libgit2/lib/libgit2' + shared_ext]),
      ],
      cmdclass=cmdclass)

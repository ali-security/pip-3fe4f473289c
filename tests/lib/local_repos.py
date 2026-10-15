from __future__ import absolute_import

import os
import shutil
import subprocess
import tarfile
import tempfile

from pip.vcs import subversion, git, bazaar, mercurial
from tests.lib import DATA_DIR, path_to_url


if hasattr(subprocess, "check_call"):
    subprocess_call = subprocess.check_call
else:
    subprocess_call = subprocess.call


def _create_initools_repository(directory):
    subprocess_call('svnadmin create INITools'.split(), cwd=directory)


def _dump_initools_repository(directory):
    # The INITools svn dump this used to load
    # (bitbucket.org/hltbra/pip-initools-dump) no longer exists, and the
    # original repository (svn.colorstudy.com) is long gone. Build an
    # equivalent repository locally: trunk/ holds the INITools 0.2 source
    # shipped in tests/data, padded to more than 10 revisions because some
    # tests check out trunk@10.
    initools_url = path_to_url(os.path.join(directory, 'INITools'))
    tmp = tempfile.mkdtemp()
    try:
        sdist = tarfile.open(
            os.path.join(DATA_DIR, 'packages', 'INITools-0.2.tar.gz')
        )
        sdist.extractall(tmp)
        sdist.close()
        source = os.path.join(tmp, 'INITools-0.2')
        shutil.rmtree(os.path.join(source, 'INITools.egg-info'))
        os.remove(os.path.join(source, 'PKG-INFO'))
        subprocess_call([
            'svn', 'import', '-q', '-m', 'Import INITools 0.2',
            source, initools_url + '/trunk',
        ])
        for rev in range(10):
            subprocess_call([
                'svn', 'mkdir', '-q', '--parents', '-m', 'Pad history',
                '%s/tags/padding-%d' % (initools_url, rev),
            ])
    finally:
        shutil.rmtree(tmp)


def _create_svn_repository_for_initools(directory):
    if not os.path.exists(os.path.join(directory, 'INITools')):
        _create_initools_repository(directory)
        _dump_initools_repository(directory)


def _get_vcs_and_checkout_url(remote_repository, directory):
    vcs_classes = {'svn': subversion.Subversion,
                   'git': git.Git,
                   'bzr': bazaar.Bazaar,
                   'hg': mercurial.Mercurial}
    default_vcs = 'svn'
    if '+' not in remote_repository:
        remote_repository = '%s+%s' % (default_vcs, remote_repository)
    vcs, repository_path = remote_repository.split('+', 1)
    vcs_class = vcs_classes[vcs]
    branch = ''
    if vcs == 'svn':
        branch = os.path.basename(remote_repository)
        # remove the slash
        repository_name = os.path.basename(
            remote_repository[:-len(branch) - 1]
        )
    else:
        repository_name = os.path.basename(remote_repository)

    destination_path = os.path.join(directory, repository_name)
    if not os.path.exists(destination_path):
        vcs_class(remote_repository).obtain(destination_path)
    return '%s+%s' % (
        vcs,
        path_to_url('/'.join([directory, repository_name, branch])),
    )


def local_checkout(remote_repo, directory):
    if not os.path.exists(directory):
        os.mkdir(directory)
        # os.makedirs(directory)

    if remote_repo.startswith('svn'):
        _create_svn_repository_for_initools(directory)
    return _get_vcs_and_checkout_url(remote_repo, directory)


def local_repo(remote_repo, directory):
    return local_checkout(remote_repo, directory).split('+', 1)[1]

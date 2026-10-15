import logging

import pretend
import pytest

import pip.basecommand
from pip.basecommand import Command
from pip.commands import commands_dict
from pip.commands.install import InstallCommand
from pip.status_codes import SUCCESS, UNKNOWN_ERROR
from pip.utils import outdated


class FakeCommand(Command):
    name = 'fake'
    summary = name

    def __init__(self, error=False):
        self.error = error
        super(FakeCommand, self).__init__()

    def main(self, args):
        args.append("--disable-pip-version-check")
        return super(FakeCommand, self).main(args)

    def run(self, options, args):
        logging.getLogger("pip.tests").info("fake")
        if self.error:
            raise SystemExit(1)


class FakeCommandWithUnicode(FakeCommand):
    name = 'fake_unicode'
    summary = name

    def run(self, options, args):
        logging.getLogger("pip.tests").info(b"bytes here \xE9")
        logging.getLogger("pip.tests").info(
            b"unicode here \xC3\xA9".decode("utf-8")
        )


class FakeCommandWithVersionCheck(Command):
    """
    A command that does *not* disable the pip self version check.

    It is isolated so that PIP_DISABLE_PIP_VERSION_CHECK, which the test
    suite exports, does not turn the self version check off.
    """
    name = 'fake_version_check'
    summary = name

    def __init__(self, body=None):
        self.body = body
        super(FakeCommandWithVersionCheck, self).__init__(isolated=True)

    def run(self, options, args):
        if self.body is not None:
            self.body()


class FakeSession(object):
    def __init__(self, events=None, resp=None):
        self.events = events if events is not None else []
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def get(self, url, headers=None):
        self.events.append("network")
        return self.resp


class Test_basecommand_logging(object):
    """
    Test `pip.basecommand.Command` setting up logging consumers based on
    options
    """

    def test_log_command_success(self, tmpdir):
        """
        Test the --log option logs when command succeeds
        """
        cmd = FakeCommand()
        log_path = tmpdir.join('log')
        cmd.main(['fake', '--log', log_path])
        assert 'fake' == open(log_path).read().strip()[:4]

    def test_log_command_error(self, tmpdir):
        """
        Test the --log option logs when command fails
        """
        cmd = FakeCommand(error=True)
        log_path = tmpdir.join('log')
        cmd.main(['fake', '--log', log_path])
        assert 'fake' == open(log_path).read().strip()[:4]

    def test_log_file_command_error(self, tmpdir):
        """
        Test the --log-file option logs (when there's an error).
        """
        cmd = FakeCommand(error=True)
        log_file_path = tmpdir.join('log_file')
        cmd.main(['fake', '--log-file', log_file_path])
        assert 'fake' == open(log_file_path).read().strip()[:4]

    def test_unicode_messages(self, tmpdir):
        """
        Tests that logging bytestrings and unicode objects don't break logging
        """
        cmd = FakeCommandWithUnicode()
        log_path = tmpdir.join('log')
        cmd.main(['fake_unicode', '--log', log_path])


def test_pip_version_check_not_hijacked_by_command_body(monkeypatch):
    """
    The command body (e.g. ``pip install``) may install a malicious
    distribution that shadows the modules and the network machinery the
    self version check uses. Nothing of the check may run once the body is
    done: it is all done beforehand, and only the upgrade prompt computed
    then is displayed afterwards.
    """
    events = []
    resp = pretend.stub(
        raise_for_status=lambda: None,
        json=lambda: {"releases": {"1.0": {}, "2.0": {}}},
    )
    session = FakeSession(events, resp)

    def build_session(options, retries=None, timeout=None):
        events.append("build_session")
        return session

    def get_installed_version(name):
        events.append("get_installed_version")
        return "1.0"

    fake_state = pretend.stub(
        state={},
        save=lambda pypi_version, current_time: events.append("save_state"),
    )

    def load_selfcheck_statefile():
        events.append("load_state")
        return fake_state

    monkeypatch.setattr(outdated, "get_installed_version",
                        get_installed_version)
    monkeypatch.setattr(outdated, "load_selfcheck_statefile",
                        load_selfcheck_statefile)
    warning = pretend.call_recorder(lambda *a, **kw: None)
    monkeypatch.setattr(outdated.logger, "warning", warning)

    hijacked_calls = []

    def hijacked(*args, **kwargs):
        hijacked_calls.append(args)
        raise AssertionError("code installed by the command body ran")

    def malicious_install():
        events.append("run")
        # Everything the self version check could use from now on comes
        # from the freshly installed (malicious) distribution.
        monkeypatch.setattr(cmd, "_build_session", hijacked)
        monkeypatch.setattr(session, "get", hijacked)
        monkeypatch.setattr(outdated, "get_installed_version", hijacked)
        monkeypatch.setattr(outdated, "load_selfcheck_statefile", hijacked)
        monkeypatch.setattr(outdated, "packaging_version",
                            pretend.stub(parse=hijacked))

    cmd = FakeCommandWithVersionCheck(body=malicious_install)
    monkeypatch.setattr(cmd, "_build_session", build_session)

    assert cmd.main([]) == SUCCESS

    assert hijacked_calls == []
    assert events == [
        "build_session",
        "get_installed_version",
        "load_state",
        "network",
        "save_state",
        "run",
    ]
    # The upgrade prompt computed before the body is still displayed.
    assert len(warning.calls) == 1
    message = warning.calls[0].args[0] % warning.calls[0].args[1:]
    assert "You are using pip version 1.0" in message
    assert "version 2.0 is available" in message


def test_pip_version_check_fetch_before_and_emit_after_body(monkeypatch):
    events = []

    def fetch(session):
        events.append("fetch")
        return "upgrade prompt"

    def emit(upgrade_prompt):
        events.append(("emit", upgrade_prompt))

    monkeypatch.setattr(pip.basecommand, "pip_version_check_fetch", fetch)
    monkeypatch.setattr(pip.basecommand, "pip_version_check_emit", emit)

    cmd = FakeCommandWithVersionCheck(body=lambda: events.append("run"))
    monkeypatch.setattr(cmd, "_build_session",
                        lambda *args, **kwargs: FakeSession())

    assert cmd.main([]) == SUCCESS
    assert events == ["fetch", "run", ("emit", "upgrade prompt")]


def test_pip_version_check_emitted_when_body_fails(monkeypatch):
    events = []
    monkeypatch.setattr(pip.basecommand, "pip_version_check_fetch",
                        lambda session: "upgrade prompt")
    monkeypatch.setattr(pip.basecommand, "pip_version_check_emit",
                        lambda prompt: events.append(("emit", prompt)))

    def failing_body():
        events.append("run")
        raise RuntimeError("command failed")

    cmd = FakeCommandWithVersionCheck(body=failing_body)
    monkeypatch.setattr(cmd, "_build_session",
                        lambda *args, **kwargs: FakeSession())

    assert cmd.main([]) == UNKNOWN_ERROR
    assert events == ["run", ("emit", "upgrade prompt")]


def test_pip_version_check_errors_do_not_break_command(monkeypatch):
    def failing(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(pip.basecommand, "pip_version_check_emit", failing)

    ran = []
    cmd = FakeCommandWithVersionCheck(body=lambda: ran.append(True))
    # Neither a failure to fetch nor to emit fails the command.
    monkeypatch.setattr(cmd, "_build_session", failing)
    assert cmd.main([]) == SUCCESS

    monkeypatch.setattr(pip.basecommand, "pip_version_check_fetch",
                        lambda session: "upgrade prompt")
    monkeypatch.setattr(cmd, "_build_session",
                        lambda *args, **kwargs: FakeSession())
    assert cmd.main([]) == SUCCESS

    assert ran == [True, True]


@pytest.mark.parametrize('command_name', sorted(commands_dict))
@pytest.mark.parametrize(
    "disable_pip_version_check, no_index, expected_called",
    [
        # The fetch phase only runs when both disable_pip_version_check
        # and no_index are False.
        (False, False, True),
        (False, True, False),
        (True, False, False),
        (True, True, False),
    ],
)
def test_pip_version_check_gating(monkeypatch, command_name,
                                  disable_pip_version_check, no_index,
                                  expected_called):
    """
    Test whether the pre-body fetch runs when ``pip_version_check()`` is
    entered, for each of the commands.
    """
    fetch = pretend.call_recorder(lambda session: None)
    monkeypatch.setattr(pip.basecommand, "pip_version_check_fetch", fetch)

    command = commands_dict[command_name]()
    monkeypatch.setattr(command, "_build_session",
                        lambda *args, **kwargs: FakeSession())
    options = command.parser.get_default_values()
    options.disable_pip_version_check = disable_pip_version_check
    options.no_index = no_index

    with command.pip_version_check(options, []):
        pass

    if expected_called:
        assert len(fetch.calls) == 1
    else:
        assert fetch.calls == []


def test_install_pip_version_check_skipped_when_pip_is_a_requirement(
        monkeypatch):
    """
    ``pip install pip`` must skip the self version check: the running pip
    may be replaced before emit.
    """
    fetch = pretend.call_recorder(lambda session: None)
    monkeypatch.setattr(pip.basecommand, "pip_version_check_fetch", fetch)

    command = InstallCommand(isolated=True)
    monkeypatch.setattr(command, "_build_session",
                        lambda *args, **kwargs: FakeSession())
    options = command.parser.get_default_values()
    options.disable_pip_version_check = False
    options.no_index = False

    for args in (["pip"], ["pip==9.0.1"], ["PIP>=9"], ["requests", "Pip"]):
        with command.pip_version_check(options, args):
            pass
    assert fetch.calls == []

    with command.pip_version_check(options, ["some-other-pkg"]):
        pass
    assert len(fetch.calls) == 1

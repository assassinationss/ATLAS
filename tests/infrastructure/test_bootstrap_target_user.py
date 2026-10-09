"""Every step that runs code from the checkout runs as the target user.

With ``sudo bash`` the bootstrap used to run ``run_doctor`` and the
steering-vector check as root: root can leave files in the checkout that
the user cannot change, and root's PATH does not see the user's
``~/.local/bin``, so an existing good vector failed its check and was
rebuilt. This test reads the script and holds every step that runs code
from the checkout to ``run_as_target`` — the same de-escalation the
clone, the CLI install, the model download and the TUI build already use.
"""
import re
import shutil
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "atlas-bootstrap.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="the bootstrap script is a bash script")

# A step that runs code from the checkout: the CLI's own modules, a script
# shipped in the ASA folder, a run from the install dir, an editable pip
# install of the checkout, the Go TUI, a repo script, or the atlas CLI
# itself.
CODE_FROM_CHECKOUT = re.compile(
    r"""(?x)
        python3\s+-m\s+atlas\.            # the CLI's own Python modules
      | python3\s+"\$asa_dir/             # a script shipped in the checkout
      | python3\s+"\$install_dir          # a run from the install dir
      | \bpip\s+install[^\n]*\s-e\s       # an editable install of the checkout
      | \bgo\s+(?:mod\s+download|build)\b # the Go TUI
      | \./scripts/[\w.-]+\.sh\b          # a repo script
      | \batlas\s+asa\s+check\b           # the steering-vector check
    """
)


def function(name):
    found = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", TEXT, re.M | re.S)
    assert found, f"{name}() is not in scripts/atlas-bootstrap.sh"
    return found.group(0)


def is_talk(line):
    """A line that only talks about a step: a comment, a [[ ]] probe or a message."""
    stripped = line.strip()
    return (
        stripped.startswith("#")
        or "[[" in line
        or "die " in line
        or stripped.startswith("echo ")
        or re.match(r"log_(?:step|info|ok|warn|err|skip)\b", stripped) is not None
    )


def code_lines():
    return [
        (number, line)
        for number, line in enumerate(TEXT.splitlines(), 1)
        if CODE_FROM_CHECKOUT.search(line) and not is_talk(line)
    ]


def test_every_code_from_the_checkout_runs_as_the_target_user():
    offenders = [
        f"line {number}: {line.strip()}"
        for number, line in code_lines()
        if "run_as_target" not in line
    ]
    assert not offenders, (
        "steps that run code from the checkout miss run_as_target "
        "(with sudo bash they run as root):\n" + "\n".join(offenders)
    )


def test_run_doctor_goes_through_the_target_user():
    body = function("run_doctor")
    found = re.search(r"doctor_out=\$\((.+)\)", body)
    assert found, "run_doctor no longer captures doctor output in doctor_out"
    assert "run_as_target" in found.group(1), (
        "run_doctor runs the checkout's doctor module without run_as_target; "
        'use the TUI-build shape: run_as_target sh -c "cd ... && python3 -m atlas.commands.doctor ..."'
    )


def test_the_vector_check_sees_the_target_users_path():
    body = function("build_asa_steering_vector")
    probes = [line for line in body.splitlines() if "command -v atlas" in line]
    assert probes, "build_asa_steering_vector no longer probes for the atlas CLI"
    for line in probes:
        assert "run_as_target" in line, (
            f"the atlas probe `{line.strip()}` runs as the invoking user; "
            "under sudo bash root's PATH will not see ~/.local/bin and the "
            "vector is rebuilt every time — probe through run_as_target"
        )

"""secrets.py --set: the value is prompted for, never passed on the command line."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import secrets as engine_secrets  # noqa: E402


class SetCommand(unittest.TestCase):
    def test_value_is_prompted_for_not_passed(self):
        cmd = engine_secrets.set_command("TWITTERAPI_IO_API_KEY")
        # -w last with no argument is what makes `security` prompt for it.
        self.assertEqual(cmd[-1], "-w")
        self.assertEqual(cmd[cmd.index("-a") + 1], "TWITTERAPI_IO_API_KEY")
        self.assertEqual(cmd[cmd.index("-s") + 1], engine_secrets.KEYCHAIN_SERVICE)

    def test_security_is_on_the_acl(self):
        # Without it the unattended launchd run stalls on an "allow access?" prompt.
        cmd = engine_secrets.set_command("APIFY_TOKEN")
        self.assertEqual(cmd[cmd.index("-T") + 1], "/usr/bin/security")

    def test_set_needs_exactly_one_name(self):
        self.assertEqual(engine_secrets.main(["secrets.py", "--set"]), 2)
        self.assertEqual(engine_secrets.main(["secrets.py", "--set", "A", "B"]), 2)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""
paths.py finds the instance by its fixed order: COMMS_ENGINE_INSTANCE, then
CLAUDE_PROJECT_DIR when it holds a brand.json, then the nearest parent of the
working directory with a brand.json, then the development layout.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import paths  # noqa: E402


class InstanceOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="paths-")
        self.a = os.path.join(self.tmp, "a")
        self.b = os.path.join(self.tmp, "b")
        self.deep = os.path.join(self.b, "Content", "Calendar")
        os.makedirs(self.a)
        os.makedirs(self.deep)
        for d in (self.a, self.b):
            with open(os.path.join(d, "brand.json"), "w") as f:
                f.write("{}")
        self.bare = os.path.join(self.tmp, "bare")
        os.makedirs(self.bare)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_variable_wins(self):
        env = {paths.ENV: self.a, "CLAUDE_PROJECT_DIR": self.b}
        self.assertEqual(paths.instance(env, cwd=self.deep), self.a)

    def test_the_variable_is_taken_as_written(self):
        """An explicit instance is trusted even before brand.json exists (new-instance writes it)."""
        self.assertEqual(paths.instance({paths.ENV: self.bare}, cwd=self.deep), self.bare)

    def test_the_project_dir_next(self):
        self.assertEqual(paths.instance({"CLAUDE_PROJECT_DIR": self.a}, cwd=self.deep), self.a)

    def test_a_project_dir_without_a_brand_file_is_passed_over(self):
        self.assertEqual(paths.instance({"CLAUDE_PROJECT_DIR": self.bare}, cwd=self.deep), self.b)

    def test_the_nearest_parent_with_a_brand_file(self):
        self.assertEqual(paths.instance({}, cwd=self.deep), self.b)

    def test_the_development_layout_last(self):
        expected = os.path.dirname(os.path.dirname(paths.ENGINE_HOME))
        self.assertEqual(paths.instance({}, cwd=self.bare), expected)


class Scripts(unittest.TestCase):
    def test_a_script_by_name_and_with_a_dash(self):
        self.assertEqual(paths.script("config"), os.path.join(paths.ENGINE_HOME, "scripts", "config.py"))
        self.assertEqual(paths.script("jobs-status"), os.path.join(paths.ENGINE_HOME, "scripts", "jobs_status.py"))
        self.assertTrue(paths.script("runjob").endswith(os.path.join("schedule", "runjob.py")))
        self.assertIsNone(paths.script("doctor"))

    def test_the_answers(self):
        self.assertEqual(paths.engine_home(), paths.ENGINE_HOME)
        self.assertTrue(paths.state().endswith("state"))
        self.assertTrue(paths.local_json().endswith("engine.local.json"))


if __name__ == "__main__":
    unittest.main()

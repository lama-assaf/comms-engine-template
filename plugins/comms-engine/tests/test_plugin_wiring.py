"""
The flows call the plugins; they do not only name them.

2026-11-13: atelier and salon were enabled in settings.json but installed for other
checkouts, the console said "installed", and the flows mentioned them in prose alone
("as the salon campaign-strategist"), so no plugin agent or skill ever ran. The Motion
plugin was not referenced at all. These checks read the tracked files a clone arrives
with, and spawn nothing:

- settings.json enables every plugin engine.json names, and denies salon's look-alikes
  of the project's own agents and skills, motion:post and motion:generate
- theme-writer preloads its two salon skills through its `skills:` line
- the chain (scripts/workflow.py, engine.json params.workflows) calls the three plugin
  agents by their full names, gives the voice keeper its limits, and invokes the retro skill
- /motion --film writes a missing brand kit from the genome (`motion.py kit --write`),
  drives motion:video and holds the page to `motion.py film`
- the corpus script passes `--settings` from `engine.py plugins --headless-settings` and the
  runner passes the same on every model call; the chain allows the one skill it invokes and
  honours cycle.voice_pass
- the agents that must not obey atelier's copy check are told so
- every role is data (engine.json params.plugins.roles): a plugin at a pinned version, a brief
  that carries this repository's rules, a fallback; doctor fails on a version mismatch only
- each role the plan adds is called where its work is done, with its brief named there
"""
import json
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(ENGINE, "..", ".."))
CLAUDE = ENGINE


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def frontmatter(text):
    return text.split("---", 2)[1]


class Settings(unittest.TestCase):
    def setUp(self):
        self.settings = json.loads(read(REPO, ".claude", "settings.json"))
        self.plugins = json.loads(read(ENGINE, "engine.json"))["params"]["plugins"]

    def test_every_named_plugin_is_enabled(self):
        self.assertEqual(self.plugins["names"], ["atelier@atelier", "salon@atelier", "motion@atelier"])
        for name in self.plugins["names"]:
            self.assertIs(self.settings["enabledPlugins"].get(name), True, name)

    def test_the_schedule_switches_off_only_plugins_it_names(self):
        self.assertEqual(self.plugins["interactive_only"], ["motion@atelier"])
        self.assertLessEqual(set(self.plugins["interactive_only"]), set(self.plugins["names"]))

    def test_look_alikes_and_sending_skills_are_denied(self):
        deny = set(self.settings["permissions"]["deny"])
        for rule in ("Agent(salon:theme-desk)", "Agent(salon:theme-listener)",
                     "Skill(salon:claim-gate)", "Skill(salon:theme-post)",
                     "Skill(salon:theme-listening)", "Skill(salon:linkedin-post)",
                     "Skill(salon:social-listening)", "Skill(salon:publisher-gates)", "Skill(salon:website-publish)",
                     "Skill(salon:engine-dashboard)", "Skill(salon:telegram-broadcast)", "Skill(salon:discord-announcement)",
                     "Skill(motion:post)"):
            self.assertIn(rule, deny)
        # motion:generate is not denied outright any more: the Skill hook refuses it unless a person
        # recorded a cost sign-off (tests/test_media.py pins the hook)
        self.assertNotIn("Skill(motion:generate)", deny)
        # the hooks are the engine plugin's, and the project enables it
        self.assertIs(self.settings["enabledPlugins"].get("comms-engine@comms-engine"), True)
        self.assertNotIn("hooks", self.settings, "the hooks ship with the plugin, not in the project's settings")
        hooks = json.loads(read(ENGINE, "hooks", "hooks.json"))["hooks"]
        matchers = {h["matcher"]: h["hooks"][0]["command"] for h in hooks["PreToolUse"]}
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard_skills.py", matchers["Skill"])
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/guard_posting.py", matchers["Bash"])
        # every look-alike denied is one the project really has its own of
        for skill in ("claim-gate", "theme-post", "theme-listening", "linkedin-post"):
            self.assertTrue(os.path.isfile(os.path.join(CLAUDE, "skills", skill, "SKILL.md")), skill)

    def test_nothing_the_flows_call_is_denied(self):
        deny = " ".join(self.settings["permissions"]["deny"])
        for name in ("atelier:brand-voice-keeper", "salon:campaign-strategist", "salon:engagement-manager",
                     "salon:campaign-retro", "salon:trend-to-content", "salon:hook-writing",
                     "motion:video", "motion:render"):
            self.assertNotIn(f"({name})", deny)
        for role in json.loads(read(ENGINE, "engine.json"))["params"]["plugins"]["roles"].values():
            self.assertNotIn(f"({role['use']})", deny, role["use"])


class Flows(unittest.TestCase):
    def test_theme_writer_preloads_the_salon_skills(self):
        fm = frontmatter(read(CLAUDE, "agents", "theme-writer.md"))
        m = re.search(r"^skills:\s*\[(.*)\]\s*$", fm, re.M)
        self.assertIsNotNone(m, "theme-writer needs a `skills:` line: naming a skill in prose loads nothing")
        self.assertEqual([s.strip() for s in m.group(1).split(",")],
                         ["salon:trend-to-content", "salon:hook-writing", "salon:post-audit", "salon:x-thread",
                          "atelier:ab-test-design"])

    def test_the_chain_calls_the_plugin_agents(self):
        """The cycle is run by scripts/workflow.py: each plugin agent is the `agent` of one model
        call, by its full name, and the runner logs it because the agent holds no Bash."""
        flows = json.loads(read(ENGINE, "engine.json"))["params"]["workflows"]
        for name, agent in (("voice", "atelier:brand-voice-keeper"), ("slots", "salon:campaign-strategist"),
                            ("engage", "salon:engagement-manager")):
            model = next(s["model"] for s in flows[name]["steps"] if "model" in s)
            self.assertEqual(model["agent"], agent, f"{name} calls {agent}")
            self.assertEqual(model["runlog"], name, f"{name}: the agent holds no Bash, the runner logs the step")
        retro = next(s["model"] for s in flows["readout"]["steps"] if "model" in s)
        self.assertIn("Skill(salon:campaign-retro)", retro["tools"])
        self.assertRegex(read(CLAUDE, "briefs", "workflows", "readout.md"), r"invoke the `salon:campaign-retro` skill")
        for name in os.listdir(os.path.join(CLAUDE, "briefs", "workflows")):
            self.assertNotRegex(read(CLAUDE, "briefs", "workflows", name), r"As the salon [a-z-]+:", "a role played is an agent not called")
        self.assertIn("--no-voice", frontmatter(read(CLAUDE, "commands", "social-cycle.md")))

    def test_the_voice_pass_runs_before_the_gate_and_holds_the_meaning(self):
        doc = json.loads(read(ENGINE, "engine.json"))["params"]
        chain = doc["chains"]["weekday"]
        self.assertLess(chain.index("draft"), chain.index("voice"))
        self.assertLess(chain.index("voice"), chain.index("gate"))
        block = read(CLAUDE, "briefs", "workflows", "voice.md")
        for must in ("voice.md", "`title`, `post`, `teaser_x` and `teaser_linkedin`", "no new fact", "`cites`"):
            self.assertIn(must, block)
        steps = doc["workflows"]["voice"]["steps"]
        self.assertEqual(steps[1]["run"], ["engine", "state_check"],
                         "code checks the queue still reads after the voice keeper wrote to it")

    def test_the_engagement_brief_keeps_handles_out(self):
        block = read(CLAUDE, "briefs", "workflows", "engage.md")
        self.assertIn("no handle and no person's name", block)
        self.assertIn("Nothing is sent", block)

    def test_motion_film_goes_through_the_plugin_and_the_film_check(self):
        text = read(CLAUDE, "commands", "motion.md")
        fm = frontmatter(text)
        self.assertIn("--film", fm)
        self.assertIn("Skill", [t.strip() for t in re.search(r"^allowed-tools:(.*)$", fm, re.M).group(1).split(",")])
        for must in ("`motion:video`", "`motion:render`", "engine motion film <id>", "engine motion kit --write",
                     "`data-says`", "`data-says-aloud`",
                     "videos/projects/<id>/", "videos/finals/<id>-v<N>.mp4", "brand/motion-kit/Motion.md"):
            self.assertIn(must, text)
        self.assertLess(text.index("**The check, before any render.**"), text.index("**The render.**"))

    def test_agents_do_not_obey_the_copy_check_on_text_that_is_not_theirs(self):
        note = "atelier rules flagged the"
        # the gatekeeper is not in this list any more: it returns findings and holds no Edit or Write,
        # so the copy check has nothing of its to flag (tests/test_review.py pins that)
        for agent, must in (("theme-writer.md", "Never change a cited line"),
                            ("motion-designer.md", "A lifted line stays as the post has it")):
            text = read(CLAUDE, "agents", agent)
            self.assertIn(note, text, agent)
            self.assertIn(must, text, agent)


class Roles(unittest.TestCase):
    """Which plugin plays which role is data (engine.json params.plugins.roles, scripts/roles.py):
    every role resolves to an enabled plugin at a pinned version with a brief, or falls back."""

    def setUp(self):
        import sys
        sys.path.insert(0, os.path.join(ENGINE, "scripts"))
        import roles
        self.roles = roles
        self.shipped = json.loads(read(ENGINE, "engine.json"))["params"]["plugins"]["roles"]

    def rows(self, **versions):
        return [{"id": f"{name}@atelier", "version": v, "enabled": True, "projectPath": None, "errors": None}
                for name, v in versions.items()]

    def test_every_role_resolves_or_has_a_fallback(self):
        self.assertEqual(self.roles.problems(self.shipped), [])
        for name, r in self.shipped.items():
            self.assertTrue(os.path.isfile(os.path.join(CLAUDE, r["brief"])), f"{name}: no brief at {r['brief']}")
            self.assertTrue(r["fallback"].strip(), name)
            self.assertRegex(r["version"], r"^\d+\.\d+\.\d+$", name)
        self.assertEqual(self.roles.pinned(self.shipped), {"atelier": "0.3.0", "salon": "0.3.0", "motion": "0.1.5"})

    def test_the_roles_the_plan_adds_are_there(self):
        uses = {r["use"]: (name, r["kind"]) for name, r in self.shipped.items()}
        for use, kind in (("salon:adversarial-refinement", "skill"), ("salon:post-audit", "skill"), ("salon:x-thread", "skill"),
                          ("salon:comment-strategy", "skill"), ("salon:reply-playbook", "skill"), ("salon:launch-window", "skill"),
                          ("salon:community-manager", "agent"), ("atelier:copywriter", "agent"),
                          ("atelier:narrative-architect", "agent"), ("atelier:ab-test-design", "skill"),
                          ("atelier:release-narrator", "agent"), ("atelier:motion-direction", "skill")):
            self.assertIn(use, uses)
            self.assertEqual(uses[use][1], kind, use)
        self.assertIn("Telegram or Discord", self.shipped["community"]["when"])

    def test_every_brief_carries_this_repositorys_rules(self):
        for name in [n for n in os.listdir(os.path.join(CLAUDE, "briefs")) if n.endswith(".md")]:
            text = " ".join(read(CLAUDE, "briefs", name).split())
            if name == "README.md":
                self.assertIn("A send is `channels.send()`'s alone", text)
                continue
            self.assertRegex(text, r"(Nothing is (posted|sent|scheduled)|You write no file|nothing is sent)", name)
            self.assertNotRegex(text, r"As the (salon|atelier) [a-z-]+:", name)
        used = {r["brief"] for r in self.shipped.values() if r["brief"].startswith("briefs/") and r["brief"].count("/") == 1}
        have = {f"briefs/{n}" for n in os.listdir(os.path.join(CLAUDE, "briefs")) if n.endswith(".md") and n != "README.md"}
        self.assertEqual(used, have, "every brief is some role's, and every role's brief is there")

    def test_a_role_that_does_not_resolve_is_a_problem(self):
        bad = json.loads(json.dumps(self.shipped))
        bad["voice-pass"]["brief"] = "briefs/nowhere.md"
        bad["hooks"]["use"] = "hook writing"
        bad["retro"]["fallback"] = ""
        bad["film"]["version"] = "latest"
        bad["blog-slots"]["use"] = "salon:theme-desk"
        bad["candidates"]["use"] = "unknownplugin:copywriter"
        bad["narrative"]["version"] = "0.2.0"
        text = "\n".join(self.roles.problems(bad))
        for must in ("plugins.roles.voice-pass.brief", "plugins.roles.hooks.use", "plugins.roles.retro.fallback",
                     "plugins.roles.film.version", "salon:theme-desk is denied in .claude/settings.json",
                     "the plugin unknownplugin is not one of plugins.names", "atelier is pinned to more than one version"):
            self.assertIn(must, text)

    def test_doctor_fails_on_a_version_mismatch_and_only_on_that(self):
        ok = self.roles.doctor_lines(self.rows(atelier="0.3.0", salon="0.3.0", motion="0.1.5"), self.shipped)
        self.assertTrue(all(ln["ok"] for ln in ok), ok)
        self.assertEqual(ok[0]["check"], "plugin roles")
        moved = {ln["check"]: ln for ln in self.roles.doctor_lines(self.rows(atelier="0.3.0", salon="0.4.0", motion="0.1.5"), self.shipped)}
        self.assertFalse(moved["plugin salon (pinned 0.3.0)"]["ok"])
        self.assertIn("installed 0.4.0, roles pinned to 0.3.0", moved["plugin salon (pinned 0.3.0)"]["tail"])
        self.assertTrue(moved["plugin atelier (pinned 0.3.0)"]["ok"])
        fresh = {ln["check"]: ln for ln in self.roles.doctor_lines([], self.shipped)}
        self.assertTrue(all(ln["ok"] for ln in fresh.values()), "a fresh clone has no plugin installed and still passes")
        self.assertIn("fall back", fresh["plugin salon (pinned 0.3.0)"]["tail"])
        self.assertTrue(all(ln["ok"] for ln in self.roles.doctor_lines(None, self.shipped)), "no claude on PATH is not a failure")
        elsewhere = [{"id": "salon@atelier", "version": "9.9.9", "enabled": True, "projectPath": "/somewhere/else", "errors": None}]
        self.assertTrue(all(ln["ok"] for ln in self.roles.doctor_lines(elsewhere, self.shipped)),
                        "a plugin installed for another checkout is not this checkout's")

    def test_a_brand_changes_a_role_in_the_setup_file(self):
        import sys
        import tempfile
        sys.path.insert(0, os.path.join(ENGINE, "scripts"))
        import config
        d = tempfile.mkdtemp()
        base = os.path.join(d, "engine.json")
        with open(base, "w", encoding="utf-8") as f:
            json.dump({"params": {"plugins": {"names": ["salon@atelier"], "roles": {"hooks": self.shipped["hooks"]}}}}, f)
        with open(os.path.join(d, "brand.json"), "w", encoding="utf-8") as f:
            json.dump({"brand": {"slug": "acme"}, "streams": {"acme": {}},
                       "plugins": {"roles": {"hooks": {"version": "0.4.0"}}}}, f)
        got = config.cfg("plugins.roles.hooks", base=base, local=os.path.join(d, "none.json"), env={})
        self.assertEqual((got["version"], got["use"]), ("0.4.0", "salon:hook-writing"), "one key changes; the rest of the role stays")
        self.assertEqual(config.validate(base, os.path.join(d, "none.json")), [])


class Wiring(unittest.TestCase):
    """Each new role is called where its work is done, with its brief named there."""

    def flows(self):
        return json.loads(read(ENGINE, "engine.json"))["params"]["workflows"]

    def tools(self, name):
        """What any model step of the workflow may use."""
        return [t for s in self.flows()[name]["steps"] if "model" in s for t in s["model"]["tools"]]

    def test_the_writer_ranks_states_and_may_hand_an_alternative_on(self):
        text = " ".join(read(CLAUDE, "agents", "theme-writer.md").split())
        for must in ("briefs/", "`candidate-ranking.md` for `salon:post-audit`", "`hypothesis.md` for `atelier:ab-test-design`",
                     "`thread-format.md` for `salon:x-thread`", "`atelier:copywriter`", "`atelier:narrative-architect`",
                     "`candidates.md` in full", "You spawn no other agent"):
            self.assertIn(must, text)
        self.assertIn("Agent", json.loads(re.search(r"^tools:\s*(\[.*\])\s*$", read(CLAUDE, "agents", "theme-writer.md"), re.M).group(1)))
        tools = self.tools("draft")
        self.assertIn("Agent(atelier:copywriter)", tools)
        self.assertIn("Agent(atelier:narrative-architect)", tools)
        self.assertNotIn("Agent", tools, "never the bare tool: only the two agents named")

    def test_the_engagement_drafts_use_the_two_playbooks_under_the_brief(self):
        self.assertIn("Skill(salon:comment-strategy)", self.tools("engage"))
        self.assertIn("Skill(salon:reply-playbook)", self.tools("engage"))
        for brief in ("engage.md", "engage-craft.md"):
            self.assertIn("briefs/engagement-drafts.md", " ".join(read(CLAUDE, "briefs", "workflows", brief).split()), brief)
        self.assertIn("the brief wins", " ".join(read(CLAUDE, "briefs", "workflows", "engage-craft.md").split()))

    def test_send_timing_motion_direction_and_release_staging(self):
        self.assertIn("Skill(salon:launch-window)", self.tools("slots"))
        self.assertIn("briefs/send-timing.md", read(CLAUDE, "briefs", "workflows", "send-timing.md"))
        self.assertIn("Skill(atelier:motion-direction)", self.tools("motion"))
        self.assertIn("briefs/motion-direction.md", read(CLAUDE, "briefs", "workflows", "motion.md"))
        self.assertRegex(frontmatter(read(CLAUDE, "agents", "motion-designer.md")), r"(?m)^skills:\s*\[atelier:motion-direction\]\s*$")
        announce = read(CLAUDE, "commands", "announce.md")
        self.assertIn("Agent", [t.strip() for t in re.search(r"^allowed-tools:(.*)$", frontmatter(announce), re.M).group(1).split(",")])
        flat = " ".join(announce.split())
        for must in ("`atelier:release-narrator`", "briefs/release-staging.md", "changes no word of the copy", "writes no file"):
            self.assertIn(must, flat)

    def test_the_community_manager_is_asked_only_where_a_stream_lists_those_channels(self):
        flow = self.flows()["community"]
        self.assertEqual(flow["when"], {"channels": ["telegram", "discord"]})
        self.assertTrue(flow["optional"])
        model = next(s["model"] for s in flow["steps"] if "model" in s)
        self.assertEqual((model["agent"], model["runlog"]), ("salon:community-manager", "community"))
        self.assertFalse([t for t in model["tools"] if t.startswith(("Bash", "Skill", "Agent"))])
        self.assertIn("briefs/community.md", read(CLAUDE, "briefs", "workflows", "community.md"))


class HeadlessRuns(unittest.TestCase):
    CORPUS = os.path.join(REPO, "plugins", "comms-engine", "skills", "deck-reader", "scripts", "corpus_cycle_daily.sh")

    def workflow(self):
        import sys
        sys.path.insert(0, os.path.join(ENGINE, "scripts"))
        import workflow
        return workflow

    def test_both_runs_switch_off_the_interactive_plugins(self):
        text = read(self.CORPUS)
        var = re.search(r"^(\w+)=\"\$\(python3 \"\$ENGINE/scripts/engine\.py\" plugins --headless-settings "
                        r"2>/dev/null \|\| echo '\{\}'\)\"$", text, re.M)
        self.assertIsNotNone(var, "the settings come from engine.py, with {} when it cannot run")
        # the call itself, not the comments that mention it
        call = re.search(r"^\s*(?:env\s[^\n]*?\s)?claude -p", text, re.M)
        self.assertIn(f'--settings "${var.group(1)}"', text[call.start():])
        self.assertLess(var.start(), call.start())
        # the chain's model calls: the runner passes the same settings on every one
        workflow = self.workflow()
        argv = workflow.claude_argv({"prompt": "gate.md", "tools": ["Read"]}, "x", 1)
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), {"enabledPlugins": {"motion@atelier": False}})

    def test_the_chain_allows_the_skill_it_invokes_and_no_other(self):
        flows = json.loads(read(ENGINE, "engine.json"))["params"]["workflows"]
        skills = [t for name, sp in flows.items() if isinstance(sp, dict)
                  for s in sp.get("steps", []) for t in (s.get("model") or {}).get("tools", []) if t.startswith("Skill")]
        self.assertEqual(sorted(skills), ["Skill(atelier:motion-direction)", "Skill(salon:adversarial-refinement)",
                                          "Skill(salon:campaign-retro)", "Skill(salon:comment-strategy)",
                                          "Skill(salon:launch-window)", "Skill(salon:reply-playbook)"])

    def test_the_chain_honours_the_voice_pass_switch(self):
        doc = json.loads(read(ENGINE, "engine.json"))["params"]
        self.assertEqual(doc["workflows"]["voice"]["when"]["config"], "cycle.voice_pass")
        self.assertIs(doc["cycle"]["voice_pass"], True)



class SkillsReachTheirStep(unittest.TestCase):
    """A step may allow a skill only where it can load: an agent loads one through its `skills:`
    line or a `Skill` in its own `tools`; a plugin agent's tools are the plugin's, and salon's hold
    no Skill, so its steps allow none (2026-11-14: launch-window was never reached)."""

    def test_no_step_allows_a_skill_its_agent_cannot_load(self):
        flows = json.loads(read(ENGINE, "engine.json"))["params"]["workflows"]
        problems = []
        for name, spec in flows.items():
            if name.startswith("_"):
                continue
            for step in spec["steps"]:
                model = step.get("model") or {}
                wanted = [t[len("Skill("):-1] for t in model.get("tools", []) if t.startswith("Skill(")]
                agent = model.get("agent")
                if not wanted or not agent:
                    continue
                if ":" in agent and not agent.startswith("comms-engine:"):
                    problems.append(f"{name}: {agent} is a plugin agent, yet the step allows {wanted}")
                    continue
                fm = frontmatter(read(CLAUDE, "agents", agent.split(":")[-1] + ".md"))
                tools = json.loads(re.search(r"^tools:\s*(\[.*\])\s*$", fm, re.M).group(1))
                m = re.search(r"^skills:\s*\[(.*)\]\s*$", fm, re.M)
                preloaded = [x.strip() for x in m.group(1).split(",")] if m else []
                problems += [f"{name}: {agent} cannot load {w}" for w in wanted if "Skill" not in tools and w not in preloaded]
        self.assertEqual(problems, [])

    def test_the_skill_steps_follow_their_agents(self):
        flows = json.loads(read(ENGINE, "engine.json"))["params"]["workflows"]
        for name, prompt, skills in (("slots", "send-timing.md", ["salon:launch-window"]),
                                     ("engage", "engage-craft.md", ["salon:comment-strategy", "salon:reply-playbook"])):
            models = [s["model"] for s in flows[name]["steps"] if "model" in s]
            self.assertEqual([m.get("agent") for m in models][0].split(":")[0], "salon", name)
            craft = next(m for m in models if m["prompt"] == prompt)
            self.assertNotIn("agent", craft)
            for skill in skills:
                self.assertIn(f"Skill({skill})", craft["tools"])
                self.assertIn(f"`{skill}`", read(CLAUDE, "briefs", "workflows", prompt).replace("salon's `", "`salon:"), skill)

if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lane_stats.py"
FIXTURES = Path(__file__).parent / "fixtures" / "lane_stats"
SENTINEL = "SYNTHETIC_PRIVATE_BODY_SENTINEL_52981"
spec = importlib.util.spec_from_file_location("lane_stats", SCRIPT)
lane_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lane_stats)

RECORD_KEYS = set("""
project session_id tool_use_id agent_id agent_type description model_param
prompt_chars spec_reasoning spec_model spec_budget mode is_async start_ts end_ts
duration_s notify_count notify_status result_found status verdict report_model lane_name lane_effort files_changed
insertions deletions sub_model sub_turns sub_input_tokens sub_output_tokens
sub_cache_read_tokens sub_cache_creation_tokens cc_version era
""".split())


def assistant(tool_id, agent="sol-implementer", start="2026-11-06T00:00:00Z", prompt="", name="Agent"):
    return {
        "type": "assistant", "timestamp": start, "sessionId": "synthetic",
        "version": "2.1.fake", "cwd": "/fictional/project", "gitBranch": "feat/example",
        "message": {"content": [{"type": "tool_use", "name": name, "id": tool_id,
                                  "input": {"subagent_type": agent, "description": "generic task",
                                            "prompt": prompt}}]},
    }


def result(tool_id, report, end="2026-11-06T00:01:00Z"):
    return {"type": "user", "timestamp": end, "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": report}]}}


def notification(tool_id, report=None, status="completed", end="2026-11-06T00:02:00Z"):
    body = f"<result>{report}</result>" if report is not None else ""
    return {"type": "user", "timestamp": end, "message": {"content": (
        f"<task-notification><tool-use-id>{tool_id}</tool-use-id>"
        f"<status>{status}</status>{body}</task-notification>")}}


def write_session(root, lines, project="fake-project", session="synthetic"):
    directory = root / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (session + ".jsonl")
    with path.open("w", encoding="utf-8") as stream:
        for line in lines:
            stream.write(json.dumps(line) + "\n")
    return path


class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.sessions, cls.stats = lane_stats.mine(FIXTURES)
        cls.by_id = {record["tool_use_id"]: record for record in cls.records}

    def test_sync_report_diffstat_and_spec(self):
        record = self.by_id["toolu_fake_sync"]
        self.assertEqual(record["status"], "complete")
        self.assertEqual((record["files_changed"], record["insertions"], record["deletions"]), (3, 10, 2))
        self.assertFalse(record["is_async"])
        self.assertTrue(record["result_found"])
        self.assertEqual(record["duration_s"], 60)
        self.assertEqual(record["spec_reasoning"], "medium")
        self.assertEqual(record["spec_model"], "gpt-6.1-sol")
        self.assertEqual(record["spec_budget"], "12")
        self.assertEqual(record["lane_name"], "sol-implementer")
        self.assertEqual(record["model_param"], "sonnet")
        self.assertEqual(record["cc_version"], "2.1.fake")
        self.assertEqual(record["agent_type"], "sol-implementer")

    def test_async_uses_last_of_two_notifications(self):
        record = self.by_id["toolu_fake_advisor"]
        self.assertEqual(record["notify_count"], 2)
        self.assertEqual(record["verdict"], "ship")
        self.assertEqual(record["end_ts"], "2026-10-11T12:03:00Z")
        self.assertEqual(record["duration_s"], 180)
        self.assertEqual(record["agent_id"], "fake-advisor")
        self.assertTrue(record["is_async"])
        self.assertTrue(record["result_found"])
        self.assertEqual(record["mode"], "review")
        self.assertEqual(record["report_model"], "opus")
        session = next(s for s in self.sessions if s["session_id"] == "session-a")
        self.assertEqual(session["verdict_sequence"], ["fix-first", "ship"])

    def test_copied_history_deduplicates_and_explore_is_ignored(self):
        self.assertEqual(len(self.records), 3)
        self.assertEqual(set(self.by_id), {"toolu_fake_sync", "toolu_fake_advisor", "toolu_fake_missing"})
        self.assertEqual(self.by_id["toolu_fake_sync"]["session_id"], "session-a")
        self.assertEqual(len(self.sessions), 3)

    def test_markers_only_count_assistant_text_blocks(self):
        session = next(s for s in self.sessions if s["session_id"] == "session-a")
        self.assertEqual(session["takeovers"], 1)
        self.assertEqual(session["direct_markers"], 1)
        self.assertEqual(sum(s["takeovers"] for s in self.sessions), 1)

    def test_subagent_usage_and_missing_files(self):
        record = self.by_id["toolu_fake_sync"]
        self.assertEqual(record["agent_id"], "fake-sync")
        self.assertEqual(record["sub_turns"], 2)
        self.assertEqual(record["sub_model"], "claude-sonnet-fake")
        self.assertEqual(record["sub_input_tokens"], 150)
        self.assertEqual(record["sub_output_tokens"], 30)
        self.assertEqual(record["sub_cache_read_tokens"], 35)
        self.assertEqual(record["sub_cache_creation_tokens"], 47)
        for tool_id in ("toolu_fake_advisor", "toolu_fake_missing"):
            for key in lane_stats.SUB_FIELDS:
                self.assertIsNone(self.by_id[tool_id][key], (tool_id, key))
        self.assertIsNone(self.by_id["toolu_fake_missing"]["agent_id"])
        self.assertFalse(self.by_id["toolu_fake_missing"]["result_found"])

    def test_era_boundaries(self):
        self.assertEqual(self.by_id["toolu_fake_sync"]["era"], "v7")
        self.assertEqual(self.by_id["toolu_fake_advisor"]["era"], "v8.0")
        self.assertEqual(self.by_id["toolu_fake_missing"]["era"], "v8.1")
        self.assertEqual(lane_stats.era("2026-10-11T00:30:00+01:00"), "v7")
        self.assertEqual(lane_stats.era("2026-11-06T00:30:00+01:00"), "v8.0")
        self.assertIsNone(lane_stats.era("bad-date"))

    def test_cli_outputs_schema_summary_and_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            process = subprocess.run(
                [sys.executable, str(SCRIPT), "--projects-root", str(FIXTURES), "--out", str(out)],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stderr, "")
            self.assertRegex(process.stdout, r"^files scanned=\d+ invocations=3 result_found=2\n$")
            self.assertEqual({p.name for p in out.iterdir()}, {"invocations.jsonl", "sessions.jsonl", "summary.md"})
            for path in out.iterdir():
                self.assertNotIn(SENTINEL, path.read_text(encoding="utf-8"))
            records = [json.loads(line) for line in (out / "invocations.jsonl").read_text().splitlines()]
            for record in records:
                self.assertEqual(set(record), RECORD_KEYS)
                for key, value in record.items():
                    if isinstance(value, str) and key not in lane_stats.UNCAPPED_FIELDS:
                        self.assertLessEqual(len(value), 120 if key == "description" else 32, key)
            sessions = [json.loads(line) for line in (out / "sessions.jsonl").read_text().splitlines()]
            for session in sessions:
                self.assertEqual(set(session), {"project", "session_id", "takeovers", "direct_markers", "verdict_sequence"})
            summary = (out / "summary.md").read_text(encoding="utf-8")
            self.assertEqual(len(re.findall(r"^## [1-5]\. ", summary, re.MULTILINE)), 5)
            for heading in re.findall(r"^### .*", summary, re.MULTILINE):
                self.assertRegex(heading, r"\(n=\d+\)$")
            self.assertIn("| sessions with fix-first followed by ship | 1 |", summary)
            self.assertIn("| -Users-demo-project | session-a | 1 | 1 |", summary)
            self.assertIn("| ≤20 | 1 | 100.0% |", summary)
            self.assertIn("| missing | 1 |", summary)
            self.assertIn("| opus | 1 |", summary)
            self.assertIn("262.0", summary)

    def test_project_filter_and_since(self):
        records, sessions, _ = lane_stats.mine(FIXTURES, re.compile("does-not-match"))
        self.assertEqual((records, sessions), ([], []))
        records, sessions, _ = lane_stats.mine(FIXTURES, re.compile("demo"), date(2026, 10, 11))
        self.assertEqual({r["tool_use_id"] for r in records}, {"toolu_fake_advisor", "toolu_fake_missing"})
        self.assertEqual({s["session_id"] for s in sessions}, {"session-a", "session-b"})
        with tempfile.TemporaryDirectory() as directory:
            process = subprocess.run(
                [sys.executable, str(SCRIPT), "--projects-root", str(FIXTURES),
                 "--since", "2026-11-06", "--project-filter", "demo", "--out", directory],
                capture_output=True, text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("invocations=1 result_found=0", process.stdout)


class EdgeCaseTests(unittest.TestCase):
    def mine_lines(self, lines):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_session(root, lines)
            return lane_stats.mine(root)

    def test_report_values_discard_annotations_and_markdown(self):
        cases = (
            ("VERDICT: revise - take option E; the deciding risk...", {"verdict": "revise"}),
            ("VERDICT: **ship**", {"verdict": "ship"}),
            ("VERDICT: A ship / B fix-first", {"verdict": "mixed"}),
            ("VERDICT: ship / ship", {"verdict": "ship"}),
            ("STATUS: complete (brief omitted...)", {"status": "complete"}),
            ("STATUS: `**PARTIAL**` - pending", {"status": "partial"}),
            ("MODEL: Opus 5.5 (the Fable pin was unavailable...)", {"report_model": "opus"}),
            ("MODEL: Claude SONNET 9", {"report_model": "sonnet"}),
            ("MODEL: GPT-6.1-sol", {"report_model": "gpt"}),
            ("MODEL: " + "x" * 40 + " Fable", {"report_model": "other"}),
            ("MODE: review (round 2)", {"mode": "review"}),
            ("LANE: sol-implementer (gpt-6.1-sol, effort: high)",
             {"lane_name": "sol-implementer", "lane_effort": "high"}),
            ("LANE: sol-implementer not invoked", {"lane_effort": "not-invoked"}),
            ("LANE: sol-implementer NOT USED (effort: high)", {"lane_effort": "not-invoked"}),
            ("LANE: sol (effort: unknown)", {"lane_effort": "other"}),
            ("LANE: " + "x" * 100, {"lane_name": "x" * 32, "lane_effort": "other"}),
        )
        for report, expected in cases:
            with self.subTest(report=report):
                parsed = lane_stats.report_fields(report)
                for key, value in expected.items():
                    self.assertEqual(parsed[key], value)
        for label, key in (("STATUS", "status"), ("VERDICT", "verdict"),
                           ("MODEL", "report_model"), ("MODE", "mode")):
            for value in ("", "unexpected value", "shipping"):
                self.assertEqual(lane_stats.report_fields(f"{label}: {value}")[key], "other")
            self.assertIsNone(lane_stats.report_fields("")[key])
        for status in lane_stats.STATUSES:
            self.assertEqual(lane_stats.report_fields(f"STATUS: {status} (note)")["status"], status)

    def test_prompt_normalization_and_report_mode_precedence(self):
        records, _, _ = self.mine_lines([
            assistant("normalized", prompt="MODE: review (round 2)\n"
                      "REASONING: max (security-sensitive ...)\n"
                      "MODEL: gpt-6.1-sol (pinned)\nBUDGET: 12 (minutes)"),
            result("normalized", "STATUS: complete"),
            assistant("override", prompt="MODE: review"),
            result("override", "MODE: CONSULT (round 2)"),
            assistant("unknown", prompt="MODE: unknown\nREASONING: unknown\nBUDGET: 12.5 minutes"),
            result("unknown", "MODE: unknown"),
        ])
        by_id = {r["tool_use_id"]: r for r in records}
        for key, value in {"mode": "review", "spec_reasoning": "max",
                           "spec_model": "gpt-6.1-sol", "spec_budget": "12"}.items():
            self.assertEqual(by_id["normalized"][key], value)
        self.assertEqual(by_id["override"]["mode"], "consult")
        for key in ("mode", "spec_reasoning", "spec_budget"):
            self.assertEqual(by_id["unknown"][key], "other")

    def test_notification_status_is_separate_from_report_status(self):
        for status in ("completed", "failed", "killed", "unexpected"):
            with self.subTest(status=status):
                records, _, _ = self.mine_lines([
                    assistant("notify"), notification("notify", "Notes only", status=status)])
                self.assertIsNone(records[0]["status"])
                self.assertEqual(records[0]["notify_status"], status if status != "unexpected" else "other")
        records, _, _ = self.mine_lines([assistant("sync"), result("sync", "STATUS: partial")])
        self.assertIsNone(records[0]["notify_status"])

    def test_central_caps_include_metadata_added_after_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            line = assistant("caps", prompt="MODEL: " + "m" * 100)
            line["version"] = "v" * 100
            args = line["message"]["content"][0]["input"]
            args.update(description="d" * 500, model="p" * 100)
            reply = result("caps", "STATUS: complete")
            reply["toolUseResult"] = {"agentId": "caps"}
            write_session(root, [line, reply])
            sub = root / "fake-project" / "synthetic" / "subagents"
            sub.mkdir(parents=True)
            (sub / "agent-caps.jsonl").write_text(json.dumps({
                "type": "assistant", "message": {"model": "s" * 100}}) + "\n")
            record = lane_stats.mine(root)[0][0]
            for key, letter in (("cc_version", "v"), ("model_param", "p"),
                                ("spec_model", "m"), ("sub_model", "s")):
                self.assertEqual(record[key], letter * 32)
            self.assertEqual(record["description"], "d" * 120)

    def test_long_report_prose_is_absent_from_every_cli_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            prose = "PRIVATE_REMAINDER_" + "z" * 500
            write_session(root, [
                assistant("prose", agent="fable-advisor"),
                result("prose", "VERDICT: **ship** - " + prose),
            ])
            out = Path(directory) / "out"
            process = subprocess.run([sys.executable, str(SCRIPT), "--projects-root", str(root),
                                      "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            for path in out.iterdir():
                self.assertNotIn(prose, path.read_text())
                self.assertNotIn("PRIVATE_REMAINDER", path.read_text())
            session = json.loads((out / "sessions.jsonl").read_text())
            self.assertEqual(session["verdict_sequence"], ["ship"])

    def test_advisor_verdict_null_rate_counts_only_found_results(self):
        records, sessions, _ = self.mine_lines([
            assistant("no-verdict", agent="fable-advisor"), result("no-verdict", "STATUS: complete"),
            assistant("verdict", agent="fable-advisor"), result("verdict", "VERDICT: ship"),
            assistant("no-result", agent="fable-advisor"),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            lane_stats.summary(path, records, sessions)
            output = path.read_text()
            self.assertIn("### Verdict null rate among advisor calls with results (n=2)", output)
            self.assertIn("| no verdict | 1 | 50.0% |", output)

    def test_earliest_timestamp_wins_over_filename_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_session(root, [assistant("toolu_dup", start="2026-11-06T00:00:00Z")], session="a-later")
            write_session(root, [assistant("toolu_dup", start="2026-10-10T00:00:00Z")], session="z-earlier")
            records, _, _ = lane_stats.mine(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["session_id"], "z-earlier")

    def test_async_launch_is_not_a_report(self):
        launch = result("toolu_async", "Async agent launched successfully: fake")
        launch["toolUseResult"] = {"isAsync": True, "agentId": "fake"}
        records, _, _ = self.mine_lines([assistant("toolu_async"), launch])
        record = records[0]
        self.assertTrue(record["is_async"])
        self.assertFalse(record["result_found"])
        self.assertIsNone(record["end_ts"])
        self.assertIsNone(record["duration_s"])
        self.assertEqual(record["notify_count"], 0)

    def test_failed_and_killed_notification_without_report(self):
        for status in ("failed", "killed"):
            with self.subTest(status=status):
                records, _, _ = self.mine_lines([
                    assistant("toolu_failed"), notification("toolu_failed", status=status)])
                self.assertIsNone(records[0]["status"])
                self.assertEqual(records[0]["notify_status"], status)
                self.assertFalse(records[0]["result_found"])
                self.assertEqual(records[0]["notify_count"], 1)
                self.assertEqual(records[0]["duration_s"], 120)

    def test_multiple_notifications_in_one_message(self):
        first = notification("toolu_multi", "VERDICT: fix-first")
        second = notification("toolu_multi", "VERDICT: ship")
        first["message"]["content"] = [
            {"type": "text", "text": first["message"]["content"]},
            {"type": "text", "text": second["message"]["content"]},
        ]
        records, sessions, _ = self.mine_lines([assistant("toolu_multi", agent="fable-advisor"), first])
        self.assertEqual(records[0]["notify_count"], 2)
        self.assertEqual(records[0]["verdict"], "ship")
        self.assertEqual(sessions[0]["verdict_sequence"], ["fix-first", "ship"])

    def test_since_uses_utc_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_session(root, [
                assistant("toolu_before", start="2026-11-06T00:30:00+01:00"),
                assistant("toolu_after", start="2026-11-05T23:30:00-01:00"),
            ])
            records, _, _ = lane_stats.mine(root, since=date(2026, 11, 6))
            self.assertEqual([r["tool_use_id"] for r in records], ["toolu_after"])

    def test_metadata_streams_pretty_json_and_ignores_description_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.meta.json"
            path.write_text(json.dumps({
                "description": 'generic text: "toolUseId": "wrong"',
                "nested": {"toolUseId": "also-wrong"}, "toolUseId": "toolu_right",
            }, indent=2), encoding="utf-8")
            stats = {"files_scanned": 0}
            self.assertEqual(lane_stats.meta_tool_id(path, stats), "toolu_right")
            self.assertEqual(stats["files_scanned"], 1)

    def test_final_notification_clears_previous_report_fields(self):
        records, sessions, _ = self.mine_lines([
            assistant("toolu_clear", agent="fable-advisor", prompt="MODE: consult"),
            notification("toolu_clear", "VERDICT: proceed\nMODEL: Fable 5.1\n2 files changed"),
            notification("toolu_clear", status="failed", end="2026-11-06T00:03:00Z"),
        ])
        record = records[0]
        self.assertIsNone(record["status"])
        self.assertEqual(record["notify_status"], "failed")
        self.assertIsNone(record["verdict"])
        self.assertIsNone(record["report_model"])
        self.assertIsNone(record["files_changed"])
        self.assertEqual(record["mode"], "consult")
        self.assertEqual(sessions[0]["verdict_sequence"], ["proceed"])

    def test_decorated_mixed_case_labels_parse_because_real_advisors_write_them(self):
        parsed = lane_stats.report_fields("Intro.\n\n**Verdict: revise.** The direction holds.\n"
                                          "**STATUS:** complete\n")
        self.assertEqual((parsed["verdict"], parsed["status"]), ("revise", "complete"))
        parsed = lane_stats.report_fields("**Verdict**: ship\n")
        self.assertEqual(parsed["verdict"], "ship")

    def test_nested_result_close_tag_does_not_truncate_report(self):
        body = ("<tool-use-id>t</tool-use-id><status>completed</status><result>```\n</result>\n```\n"
                "VERDICT: ship\n</result>")
        report = lane_stats.xml_field(body, "result")
        self.assertIn("VERDICT: ship", report)
        self.assertEqual(lane_stats.xml_field(body, "tool-use-id"), "t")

    def test_report_fields_are_first_match_and_line_start(self):
        parsed = lane_stats.report_fields(
            "prefix STATUS: wrong\n"
            "STATUS: partial  \nSTATUS: complete\nVERDICT: fix-first\nVERDICT: ship\n"
            "MODEL: Fable 5.1\nMODEL: Opus 5.5\nLANE: sol\nMODE: review\n"
            "1 file changed, 7 deletions(-)\n4 files changed, 99 insertions(+)\n")
        self.assertEqual(parsed, {"status": "partial", "verdict": "fix-first", "report_model": "fable",
                                  "lane_name": "sol", "lane_effort": "other", "mode": "review", "files_changed": 1,
                                  "insertions": 0, "deletions": 7})
        self.assertEqual(lane_stats.field("STATUS:\nVERDICT: ship", "STATUS"), "")
        for prompt, expected in (("prefix REVIEW", None), ("Notes\nrEvIeW task", "review"),
                                 ("mOdE: cOnSuLt", "consult"), ("MODE: preview", "other")):
            self.assertEqual(lane_stats.prompt_mode(prompt), expected)

    def test_all_supported_agents_and_sync_string_or_text_blocks(self):
        lines = []
        for index, agent in enumerate(("sol-implementer", "sonnet-implementer", "luna-implementer",
                                       "opus-implementer", "fable-advisor")):
            tool_id = f"toolu_{index}"
            lines.extend([assistant(tool_id, agent="fable-advisor:" + agent),
                          result(tool_id, [{"type": "text", "text": "STATUS: complete"}])])
        for agent in ("Explore", "other:sol-implementer", "fable-advisor:Explore", "sol-implementer-extra"):
            lines.append(assistant("ignored_" + agent, agent=agent))
        records, _, _ = self.mine_lines(lines)
        self.assertEqual(len(records), 5)
        self.assertTrue(all(r["result_found"] and r["status"] == "complete" for r in records))

    def test_subagent_most_frequent_model_and_sparse_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sync = result("toolu_usage", "STATUS: complete")
            sync["toolUseResult"] = {"agentId": "usage"}
            write_session(root, [assistant("toolu_usage"), sync])
            sub = root / "fake-project" / "synthetic" / "subagents"
            sub.mkdir(parents=True)
            lines = [
                {"type": "assistant", "message": {"model": "minority", "usage": {"input_tokens": 4}}},
                {"type": "user", "message": {"usage": {"output_tokens": 999}}},
                {"type": "assistant", "message": {"model": "majority", "usage": {"output_tokens": 5}}},
                {"type": "assistant", "message": {"model": "majority"}},
            ]
            with (sub / "agent-usage.jsonl").open("w") as stream:
                stream.write("malformed\n")
                for line in lines:
                    stream.write(json.dumps(line) + "\n")
            record = lane_stats.mine(root)[0][0]
            self.assertEqual((record["sub_model"], record["sub_turns"]), ("majority", 3))
            self.assertEqual((record["sub_input_tokens"], record["sub_output_tokens"]), (4, 5))
            self.assertEqual(record["sub_cache_creation_tokens"], 0)

    def test_summary_buckets_and_model_families(self):
        lines = []
        for index, size in enumerate((0, 20, 21, 100, 101)):
            tool_id = f"toolu_size_{index}"
            lines.extend([assistant(tool_id, prompt="REASONING: high"),
                          result(tool_id, f"STATUS: complete\n1 file changed, {size} insertions(+)")])
        lines.append(assistant("toolu_no_diff"))
        for index, (model, mode, verdict) in enumerate((
                ("Fable 9", "CONSULT", "proceed"), ("Claude Opus 8", "REVIEW", "ship"),
                ("Other model", "REVIEW", "fix-first"))):
            tool_id = f"toolu_model_{index}"
            lines.extend([assistant(tool_id, agent="fable-advisor", prompt=mode),
                          result(tool_id, f"MODEL: {model}\nVERDICT: {verdict}")])
        records, sessions, _ = self.mine_lines(lines)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            lane_stats.summary(path, records, sessions)
            output = path.read_text(encoding="utf-8")
            for text in ("| ≤20 | 2 | 40.0% |", "| 21–100 | 2 | 40.0% |", "| >100 | 1 | 20.0% |",
                         "| missing | 1 |", "| high | 5 |", "| fable | 1 |", "| opus | 1 |",
                         "| other | 1 |", "| consult | proceed | 1 |",
                         "| sessions with fix-first followed by ship | 0 |"):
                self.assertIn(text, output)
        self.assertEqual(lane_stats.percentile([0, 10], .5), 5)
        self.assertEqual(lane_stats.percentile([0, 10], .9), 9)
        self.assertIsNone(lane_stats.percentile([None], .5))

    def test_empty_input_cli_and_bad_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "empty"
            root.mkdir()
            command = [sys.executable, str(SCRIPT), "--projects-root", str(root), "--out", str(Path(directory) / "out")]
            process = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(process.stdout, "files scanned=0 invocations=0 result_found=0\n")
            for extra in (("--project-filter", "["), ("--since", "not-a-date"),
                          ("--projects-root", str(root / "missing"))):
                process = subprocess.run(command + list(extra), capture_output=True, text=True)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("error:", process.stderr)
                self.assertNotIn("Traceback", process.stderr)

    def test_malformed_main_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_session(root, [assistant("toolu_valid"), result("toolu_valid", "STATUS: complete")])
            with path.open("a") as stream:
                stream.write('{"unfinished":\nnot-json\nnull\n[]\n')
            records, _, _ = lane_stats.mine(root)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "complete")


if __name__ == "__main__":
    unittest.main()

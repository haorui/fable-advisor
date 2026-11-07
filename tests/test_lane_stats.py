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
PATCH = (f"diff --git a/{SENTINEL}.py b/{SENTINEL}.py\n"
         f"--- a/{SENTINEL}.py\n+++ b/{SENTINEL}.py\n"
         "@@ -1,2 +1,3 @@\n-old one\n-old two\n+new one\n+new two\n+new three\n"
         "diff --git a/second.py b/second.py\n"
         "--- /dev/null\n+++ b/second.py\n@@ -0,0 +1,2 @@\n+new four\n+new five\n")
spec = importlib.util.spec_from_file_location("lane_stats", SCRIPT)
lane_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lane_stats)

RECORD_KEYS = set("""
project session_id tool_use_id agent_id agent_type description model_param
prompt_chars spec_reasoning spec_model spec_budget mode is_async start_ts end_ts
duration_s notify_count notify_status result_found status verdict report_model lane_name lane_effort files_changed
insertions deletions sub_model sub_turns sub_input_tokens sub_output_tokens
sub_cache_read_tokens sub_cache_creation_tokens cc_version era
size_files size_insertions size_deletions size_new_untracked size_source
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


def sub_tool(tool_id, command="", name="Bash"):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": tool_id, "name": name, "input": {"command": command}}]}}


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
        self.assertEqual(record["size_source"], "delta")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (1, 15, 4, 2))

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
        missing = self.by_id["toolu_fake_missing"]
        self.assertEqual(missing["size_source"], "none")
        self.assertTrue(all(missing[key] is None for key in lane_stats.SIZE_FIELDS))

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
            for title in ("Size source by agent type (n=2)", "Transcript change sizes (n=1)",
                          "Lane overhead by size: sol-implementer (n=1)",
                          "Lane overhead by size: sol-implementer — upper-bound sizes included (n=1)",
                          "Spec reasoning × line bucket (n=1)", "Report-quoted diffstat (n=1)"):
                self.assertIn("### " + title, summary)
            for row in ("| sol-implementer | 1 | 0 | 0 | 0 | 0 |", "| sonnet-implementer | 0 | 0 | 0 | 0 | 1 |",
                        "| 1-20 | 1 | 0 | 0 | 0 |",
                        "| new untracked > 0 | 1 | 0 | 0 | 0 |",
                        "| 1-20 | 1 | 60.0 | 60.0 | 227.0 | 2.0 | complete: 1 |",
                        "| medium | 0 | 1 | 0 | 0 | 0 |"):
                self.assertIn(row, summary)

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

    def mine_subagent(self, lines, agent="sol-implementer"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reply = result("size", "STATUS: complete")
            reply["toolUseResult"] = {"agentId": "synthetic-size"}
            write_session(root, [assistant("size", agent=agent), reply])
            sub = root / "fake-project" / "synthetic" / "subagents"
            sub.mkdir(parents=True)
            with (sub / "agent-synthetic-size.jsonl").open("w", encoding="utf-8") as stream:
                for line in lines:
                    stream.write(json.dumps(line) + "\n")
            return lane_stats.mine(root)[0][0]

    def test_status_baselines_keep_after_totals_and_subtract_observed_untracked(self):
        for command, output, source, untracked in (
                ("git status --short", "", "delta-clean", 2),
                ("git status --porcelain", "?? baseline.txt\n", "delta-clean", 1),
                ("git status -sb", "## synthetic\n?? baseline.txt\n", "delta-clean", 1),
                ("git status --short", " M tracked.py\n?? baseline.txt\n", "after-dirty", 1),
                ("git status --short", "A  tracked.py\n", "after-dirty", 2),
                ("git status --short", "UU tracked.py\n", "after-dirty", 2),
                ("git status", "On branch synthetic\nChanges not staged for commit:\n"
                 "  modified: tracked.py\nno changes added to commit\n", "after-dirty", 2),
                ("git status", "On branch synthetic\nChanges to be committed:\n"
                 "  new file: tracked.py\n", "after-dirty", 2),
                ("git status", "On branch synthetic\nnothing to commit, working tree clean\n", "delta-clean", 2),
                ("git status", "On branch synthetic\nUntracked files:\n  baseline.txt\n"
                 "nothing added to commit but untracked files present\n", "delta-clean", 2)):
            with self.subTest(command=command, output=output):
                record = self.mine_subagent([
                    sub_tool("before", command), result("before", output),
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "git diff --stat; git status --short"),
                    result("after", "2 files changed, 5 insertions(+), 2 deletions(-)\n"
                           " M tracked.py\n?? baseline.txt\n?? new.txt\n"),
                ])
                self.assertEqual(record["size_source"], source)
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (2, 5, 2, untracked))

    def test_latest_status_determines_clean_baseline(self):
        for first, last, source in ((" M tracked.py\n", "?? baseline.txt\n", "delta-clean"),
                                    ("", " M tracked.py\n", "after-dirty")):
            with self.subTest(source=source):
                record = self.mine_subagent([
                    sub_tool("first", "git status --short"),
                    sub_tool("last", "git status --short"),
                    result("last", last), result("first", first),
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "git diff --shortstat"),
                    result("after", "2 files changed, 5 insertions(+), 2 deletions(-)"),
                ])
                self.assertEqual(record["size_source"], source)
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (2, 5, 2))

    def test_preflight_status_filters_ignore_interleaved_foreign_output(self):
        command = ("command -v codex && codex --version; cd /fictional/repo && "
                   "git status --short | head -20 && git branch --show-current && git log --oneline -1")
        for status, source in (("", "delta-clean"), (" M tracked.py\n", "after-dirty")):
            with self.subTest(source=source):
                record = self.mine_subagent([
                    sub_tool("before", command),
                    result("before", "/fictional/bin/codex\ncodex-cli synthetic\n" + status +
                           "## synthetic\nsynthetic-branch\n123abcd synthetic subject\n"),
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "git diff --shortstat"),
                    result("after", "2 files changed, 5 insertions(+), 2 deletions(-)"),
                ])
                self.assertEqual(record["size_source"], source)
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (2, 5, 2))

    def test_status_filter_limits_do_not_claim_complete_counts_or_clean_baseline(self):
        for filter_command, limit in (("head -2", 2), ("tail -n 2", 2),
                                      ("head --lines=2", 2), ("tail", 10), ("head", 10)):
            for tracked in (True, False):
                with self.subTest(filter_command=filter_command, tracked=tracked):
                    status = (" M tracked.py\n" if tracked else "?? first.txt\n")
                    status += "".join(f"?? new-{i}.txt\n" for i in range(limit - 1))
                    record = self.mine_subagent([
                        sub_tool("before", "git status --short | " + filter_command), result("before", status),
                        sub_tool("launch", "codex exec 'synthetic task'"),
                        sub_tool("after", "git diff --stat; git status --short | " + filter_command),
                        result("after", "1 file changed, 5 insertions(+)\n" + status),
                    ])
                    self.assertEqual(record["size_source"], "after-dirty")
                    self.assertIsNone(record["size_new_untracked"])
                    self.assertEqual(record["size_insertions"], 5)

    def test_launch_heredoc_preflight_is_before_even_with_quotes_in_body(self):
        command = ("git status --short && SPEC=$(mktemp /fictional/spec.XXXXXX)\n"
                   "cat > \"$SPEC\" << 'SPEC_EOF'\n"
                   "It's a synthetic task with an unmatched \" quote.\n"
                   "git diff --shortstat; codex exec 'body text is not a launch'\n"
                   "SPEC_EOF\nnohup codex exec - < \"$SPEC\" > /fictional/output 2>&1 & echo $!")
        record = self.mine_subagent([
            sub_tool("launch", command), result("launch", "?? baseline.txt\n12345\n/fictional/spec\n"),
            sub_tool("after", "git diff --stat; git status --short"),
            result("after", "1 file changed, 5 insertions(+)\n?? baseline.txt\n?? new.txt\n"),
        ])
        self.assertEqual(record["size_source"], "delta-clean")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (1, 5, 0, 1))

    def test_malformed_segment_does_not_drop_other_measurements(self):
        record = self.mine_subagent([
            sub_tool("launch", "git status --short; echo 'unterminated; nohup codex exec task &"),
            result("launch", "12345\n"),
            sub_tool("after", "echo 'unterminated; git diff --shortstat; echo done"),
            result("after", "1 file changed, 5 insertions(+)"),
        ])
        self.assertEqual(record["size_source"], "delta-clean")
        self.assertEqual(record["size_insertions"], 5)

    def test_launch_preflight_diff_subtracts_and_post_launch_segments_are_not_baselines(self):
        record = self.mine_subagent([
            sub_tool("launch", "git diff --shortstat; nohup codex exec task & git status --short"),
            result("launch", "1 file changed, 2 insertions(+)\n12345\n"),
            sub_tool("after", "git diff --shortstat"),
            result("after", "2 files changed, 5 insertions(+)"),
        ])
        self.assertEqual(record["size_source"], "delta")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (1, 3, 0, None))

    def test_diff_and_status_measurements_merge_independently_in_tool_order(self):
        record = self.mine_subagent([
            sub_tool("before-diff", "git diff --shortstat"),
            result("before-diff", "1 file changed, 3 insertions(+)"),
            sub_tool("before-status", "git status --short"),
            result("before-status", " M tracked.py\n?? baseline.txt\n"),
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after-diff", "git diff --shortstat"),
            sub_tool("after-status", "git status --short"),
            result("after-status", " M tracked.py\n?? baseline.txt\n?? new.txt\n"),
            result("after-diff", "2 files changed, 5 insertions(+), 2 deletions(-)"),
        ])
        self.assertEqual(record["size_source"], "delta")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (1, 2, 2, 1))

    def test_unobserved_before_untracked_uses_after_count(self):
        record = self.mine_subagent([
            sub_tool("before", "git diff --stat"), result("before", "1 file changed, 3 insertions(+)"),
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git diff --stat; git status --short"),
            result("after", "2 files changed, 5 insertions(+)\n?? new.txt\n"),
        ])
        self.assertEqual(record["size_source"], "delta")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (1, 2, 0, 1))

    def test_plain_patch_counts_complete_hunks_and_all_files(self):
        for command, output in (("git diff", PATCH), ("git diff|cat", PATCH),
                                ("git diff | tee /fictional/copy | cat", PATCH),
                                ("git diff", PATCH + "\\ No newline at end of file\n")):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", command), result("after", output),
                ])
                self.assertEqual(record["size_source"], "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (2, 5, 2))

    def test_patch_and_stat_totals_survive_adjacent_status_and_scoped_patch_output(self):
        for command, output in (
                ("git status --short; git diff", f" M {SENTINEL}.py\n" + PATCH),
                ("git diff; git status --short", PATCH + f" M {SENTINEL}.py\n"),
                ("git diff --check; git diff", PATCH),
                ("git diff --stat; git diff -- a.py", "2 files changed, 5 insertions(+), 2 deletions(-)\n" + PATCH),
                ("git diff --stat; git diff --check", "2 files changed, 5 insertions(+), 2 deletions(-)\n"),
                ("git diff --stat 2>/dev/null", "2 files changed, 5 insertions(+), 2 deletions(-)\n")):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", command), result("after", output),
                ])
                self.assertEqual(record["size_source"], "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (2, 5, 2))

    def test_non_size_diff_modes_do_not_turn_empty_output_into_zero_totals(self):
        for flag in ("--check", "--name-only", "--name-status", "--quiet", "--no-patch", "-s"):
            with self.subTest(flag=flag):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "git diff " + flag), result("after", ""),
                ])
                self.assertEqual(record["size_source"], "none")
                self.assertTrue(all(record[key] is None for key in lane_stats.SIZE_FIELDS))

    def test_patch_body_summary_text_cannot_replace_adjacent_stat(self):
        patch = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                 "@@ -1 +1,2 @@\n 99 files changed, 999 insertions(+)\n+added\n")
        record = self.mine_subagent([
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git diff --stat; git diff -- a.py"),
            result("after", "1 file changed, 1 insertion(+)\n" + patch),
        ])
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (1, 1, 0))

    def test_plain_patch_truncation_markers_and_incomplete_hunks_are_discarded(self):
        for output in (PATCH + "[... 100 lines omitted]\n", PATCH + "[output truncated]\n",
                       "Output too large\n" + PATCH, PATCH.rsplit("+new five", 1)[0],
                       PATCH + "diff --git a/unfinished.py b/unfinished.py\n",
                       PATCH.replace("@@ -1,2 +1,3 @@", "@@ -1,3 +1,3 @@")):
            with self.subTest(output=output):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "git diff"), result("after", output),
                ])
                self.assertEqual(record["size_source"], "none")
                self.assertTrue(all(record[key] is None for key in lane_stats.SIZE_FIELDS))

    def test_scoped_and_filtered_plain_patches_are_ignored(self):
        for command in ("git diff HEAD~1", "git diff origin/main...HEAD", "git diff -- a.py",
                        "git diff a.py", "git diff --cached", "git diff --staged",
                        "git diff|head -20", "git diff | tail -20", "git diff | sed -n '1,20p'",
                        "git diff | grep '^+'", "git diff | awk '{print}'", "git diff | cat | head -20"):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", command), result("after", PATCH),
                ])
                self.assertEqual(record["size_source"], "none")

    def test_patch_context_multiple_hunks_and_implicit_single_line_counts(self):
        output = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                  "@@ -1,2 +1,3 @@\n context\n-old\n+new\n+added\n"
                  "@@ -9 +10 @@\n-old\n+new\n")
        record = self.mine_subagent([
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git diff"), result("after", output),
        ])
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (1, 3, 2))

    def test_stat_pipes_use_summary_even_without_spaces_around_pipe(self):
        for command, output, expected in (
                ("git diff --stat | tail -3", " a.py | 7 +++++--\n2 files changed, 5 insertions(+), 2 deletions(-)\n", (2, 5, 2)),
                ("git diff --stat|tail -3", "2 files changed, 5 insertions(+), 2 deletions(-)\n", (2, 5, 2)),
                ("git diff --stat | head -2", " a.py | 5 +++++\n b.py | 2 --\n", None),
                ("git diff --stat | head -2", " a.py | 7 +++++--\n1 file changed, 5 insertions(+), 2 deletions(-)\n", (1, 5, 2)),
                ("git diff --stat|head -0", "", None)):
            with self.subTest(command=command, output=output):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", command), result("after", output),
                ])
                self.assertEqual(record["size_source"], "none" if expected is None else "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), expected or (None, None, None))
        self.assertEqual(lane_stats.stat_commands("git diff --stat|tail -3"), [("stat", False, True, None)])

    def test_cli_new_size_paths_keep_transcript_text_private(self):
        cases = (
            ("clean", "git status --short", f"?? {SENTINEL}.txt\n", "git diff", PATCH, "delta-clean"),
            ("dirty", "git status", f"On branch synthetic\nChanges not staged for commit:\n  modified: {SENTINEL}\n",
             "git diff --stat|tail -3", f" {SENTINEL}.py | 7 +++++--\n1 file changed, 5 insertions(+), 2 deletions(-)\n", "after-dirty"),
            ("patch", None, None, "git diff|cat", PATCH, "after-only"),
            ("truncated", None, None, "git diff", PATCH + f"[... {SENTINEL} truncated]\n", "none"),
            ("head", None, None, "git diff --stat|head -2", f" {SENTINEL}.py | 7 +++++--\n", "none"),
            ("preflight-clean", "command -v codex; git status --short | head -20; git branch --show-current",
             f"/fictional/{SENTINEL}\ncodex-cli synthetic\nsynthetic-branch\n",
             "git diff --shortstat", "1 file changed, 5 insertions(+)\n", "delta-clean"),
            ("preflight-dirty", "git status --short | tail -20; git log --oneline -1",
             f" M {SENTINEL}.py\n123abcd synthetic subject\n",
             "git diff --shortstat", "1 file changed, 5 insertions(+)\n", "after-dirty"),
            ("heredoc", "git status --short; cat << 'SYNTHETIC_EOF'\n"
             f"It's {SENTINEL} with an unmatched \" quote.\nSYNTHETIC_EOF\nnohup codex exec task &",
             f"?? {SENTINEL}.txt\n12345\n", "git diff --shortstat",
             "1 file changed, 5 insertions(+)\n", "delta-clean"),
            ("malformed", "git status --short; echo 'unterminated; nohup codex exec task &",
             f"/fictional/{SENTINEL}\n12345\n", "echo 'unterminated; git diff --shortstat",
             "1 file changed, 5 insertions(+)\n", "delta-clean"),
            ("mixed", None, None, f"git diff --stat; git diff -- {SENTINEL}.py",
             "2 files changed, 5 insertions(+), 2 deletions(-)\n" + PATCH, "after-only"),
            ("status-patch", None, None, "git status --short; git diff",
             f" M {SENTINEL}.py\n" + PATCH, "after-only"),
            ("redirect", None, None, "git diff --stat 2>/dev/null",
             f" {SENTINEL}.py | 5 +++++\n1 file changed, 5 insertions(+)\n", "after-only"),
            ("status-truncated", None, None, "git status --short | head -2",
             f" M {SENTINEL}.py\n?? {SENTINEL}.txt\n", "after-only"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            main = []
            for tool_id, before_cmd, before_text, after_cmd, after_text, _ in cases:
                reply = result(tool_id, "STATUS: complete")
                reply["toolUseResult"] = {"agentId": tool_id}
                main.extend([assistant(tool_id), reply])
                sub = root / "fake-project" / "synthetic" / "subagents"
                sub.mkdir(parents=True, exist_ok=True)
                lines = [sub_tool("before", before_cmd), result("before", before_text)] if before_cmd else []
                command = after_cmd.replace("git ", "git -C /fictional/" + SENTINEL + " ", 1)
                lines.extend([sub_tool("launch", "codex exec '" + SENTINEL + "'"),
                              sub_tool("after", command),
                              result("after", after_text)])
                (sub / ("agent-" + tool_id + ".jsonl")).write_text(
                    "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
            write_session(root, main)
            out = Path(directory) / "out"
            process = subprocess.run([sys.executable, str(SCRIPT), "--projects-root", str(root), "--out", str(out)],
                                     capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(process.returncode, 0, process.stderr)
            for path in out.iterdir():
                self.assertNotIn(SENTINEL, path.read_text(encoding="utf-8"))
            records = [json.loads(line) for line in (out / "invocations.jsonl").read_text().splitlines()]
            self.assertEqual({r["tool_use_id"]: r["size_source"] for r in records},
                             {case[0]: case[-1] for case in cases})
            for record in records:
                self.assertEqual(set(record), RECORD_KEYS)
                self.assertTrue(all(record[key] is None or type(record[key]) is int for key in lane_stats.SIZE_FIELDS))

    def test_after_only_shortstat_and_untracked_in_chained_output(self):
        for agent in ("sol-implementer", "luna-implementer"):
            with self.subTest(agent=agent):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "cd '/fictional/fake project' && git diff --shortstat; "
                             "git -C '/fictional/fake project' status --short"),
                    result("after", [{"type": "text", "text": "1 file changed, 3 insertions(+)\n"
                                      " M tracked.py\n?? first.txt\n?? second.txt\n"}]),
                ], agent=agent)
                self.assertEqual(record["size_source"], "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (1, 3, 0, 2))

    def test_scoped_commands_are_ignored(self):
        for command in ("git diff --stat origin/main...HEAD", "git diff HEAD~1..HEAD --stat",
                        "git diff --stat -- src/foo.py", "git diff --stat src/foo.py",
                        "git diff --cached --stat", "git diff --stat --staged",
                        "git diff --numstat HEAD~1", "git status --short -- src/foo.py",
                        "git diff --stat > /tmp/out.txt", "git diff >> /tmp/patch.diff",
                        "git diff --stat 1>/tmp/out.txt"):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"), sub_tool("scoped", command),
                    result("scoped", "1 file changed, 99 insertions(+)\n?? secret.txt"),
                ])
                self.assertEqual(record["size_source"], "none")
                self.assertTrue(all(record[key] is None for key in lane_stats.SIZE_FIELDS))

    def test_stdout_redirect_with_empty_output_is_not_a_zero_size_change(self):
        # Empty stdout from a redirected diff would otherwise land in the threshold-sensitive 0 bucket.
        for command in ("git diff > /tmp/patch.diff", "git diff --stat >/tmp/out.txt",
                        "git diff --stat &>/tmp/x", "git diff --stat 2>&1 >/tmp/x"):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"), sub_tool("after", command),
                    result("after", ""),
                ])
                self.assertEqual(record["size_source"], "none")

    def test_stderr_merge_keeps_status_pipe_truncation_visible(self):
        # `2>&1` is routine; it must not hide the `| head -3` that makes 3 rows a truncated read.
        record = self.mine_subagent([
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git status --short 2>&1 | head -3"),
            result("after", "?? a.py\n?? b.py\n?? c.py"),
        ])
        self.assertEqual(lane_stats.stat_commands("git status --short 2>&1 | head -3")[0][2:], (True, 3))
        self.assertIsNone(record["size_new_untracked"])
        self.assertEqual(lane_stats.stat_commands("git diff --stat 2>&1 && git status --short")[1][0], "status")

    def test_pager_idioms_and_bare_head_are_whole_tree_measurements(self):
        for command in ("git --no-pager diff --stat", "GIT_PAGER=cat git diff --stat",
                        "PAGER=cat git -C /fictional/repo --no-pager diff --stat", "git diff HEAD --stat",
                        "git diff --stat 2>/dev/null"):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"), sub_tool("after", command),
                    result("after", " a.py | 3 ++-\n 1 file changed, 2 insertions(+), 1 deletion(-)"),
                ])
                self.assertEqual(record["size_source"], "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (1, 2, 1))

    def test_numstat_counts_binary_file_without_adding_binary_lines(self):
        record = self.mine_subagent([
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git -C /fictional/repo diff --numstat"),
            result("after", "5\t2\ta.py\n-\t-\timg.png\n1\t0\tb.py\n"),
        ])
        self.assertEqual(record["size_source"], "after-only")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (3, 6, 2))

    def test_sonnet_splits_at_first_edit_write_or_notebook_edit(self):
        for name in ("Edit", "Write", "NotebookEdit"):
            with self.subTest(name=name):
                record = self.mine_subagent([
                    sub_tool("before", "git diff --stat"),
                    result("before", "2 files changed, 10 insertions(+)"),
                    sub_tool("edit", name=name),
                    sub_tool("after", "git diff --stat"),
                    result("after", "3 files changed, 25 insertions(+), 4 deletions(-)"),
                ], agent="sonnet-implementer")
                self.assertEqual(record["size_source"], "delta")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (1, 15, 4))

    def test_file_detail_counts_changed_paths_even_when_total_file_count_is_unchanged(self):
        record = self.mine_subagent([
            sub_tool("before", "git diff --stat"),
            result("before", " a.py | 5 +++++\n b.py | 5 +++++\n"
                   "2 files changed, 10 insertions(+)"),
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git diff --stat"),
            result("after", " a.py | 5 +++++\n b.py | 9 +++++----\n"
                   "2 files changed, 10 insertions(+), 4 deletions(-)"),
        ])
        self.assertEqual(record["size_source"], "delta")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (1, 0, 4))

    def test_last_measurements_use_tool_order_and_clamp_negative_deltas(self):
        record = self.mine_subagent([
            sub_tool("old", "git diff --stat; git status --porcelain"),
            sub_tool("before", "git diff --stat; git status --porcelain"),
            sub_tool("launch", "codex exec 'synthetic task'"),
            result("before", "2 files changed, 10 insertions(+), 8 deletions(-)\n?? a.txt\n?? b.txt"),
            result("old", "1 file changed, 1 insertion(+)"),
            sub_tool("after", "git diff --shortstat; git status --porcelain"),
            result("after", "1 file changed, 3 insertions(+)\n?? a.txt"),
        ])
        self.assertEqual(record["size_source"], "delta")
        self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS), (0, 0, 0, 0))

    def test_chained_diffs_take_last_unscoped_total(self):
        for command, output in (
                ("git diff --stat; git diff --shortstat",
                 " a.py | 2 ++\n1 file changed, 2 insertions(+)\n2 files changed, 7 deletions(-)"),
                ("git diff --stat; git diff --stat origin/main...HEAD",
                 "2 files changed, 7 deletions(-)\n9 files changed, 99 insertions(+)"),
                ("git diff --stat -- a.py && git diff --numstat",
                 "9 files changed, 99 insertions(+)\n0\t7\ta.py\n-\t-\tb.png")):
            with self.subTest(command=command):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", command), result("after", output),
                ])
                self.assertEqual(record["size_source"], "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS[:3]), (2, 0, 7))

    def test_no_split_or_no_after_produces_no_size(self):
        stat = [sub_tool("stat", "git diff --stat"), result("stat", "1 file changed, 3 insertions(+)")]
        for lines, agent in ((stat, "sol-implementer"),
                             (stat + [sub_tool("launch", "codex exec 'synthetic task'")], "sol-implementer"),
                             ([sub_tool("launch", "codex exec 'synthetic task'")] + stat, "sonnet-implementer")):
            with self.subTest(lines=lines, agent=agent):
                record = self.mine_subagent(lines, agent=agent)
                self.assertEqual(record["size_source"], "none")
                self.assertTrue(all(record[key] is None for key in lane_stats.SIZE_FIELDS))

    def test_ambiguous_chained_numstats_are_not_summed_as_one_diff(self):
        record = self.mine_subagent([
            sub_tool("launch", "codex exec 'synthetic task'"),
            sub_tool("after", "git diff --numstat; git diff --numstat"),
            result("after", "5\t2\ta.py\n1\t0\tb.py\n"),
        ])
        self.assertEqual(record["size_source"], "none")
        self.assertTrue(all(record[key] is None for key in lane_stats.SIZE_FIELDS))

    def test_known_agent_id_with_missing_subagent_file_has_no_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reply = result("missing-subagent", "STATUS: complete")
            reply["toolUseResult"] = {"agentId": "synthetic-missing"}
            write_session(root, [assistant("missing-subagent"), reply])
            record = lane_stats.mine(root)[0][0]
        self.assertEqual(record["size_source"], "none")
        self.assertTrue(all(record[key] is None for key in lane_stats.SIZE_FIELDS))

    def test_clean_diff_status_only_and_failed_tool_results(self):
        for command, output, expected in (
                ("git diff --stat", "", (0, 0, 0, None)),
                ("git status --short", "?? a.txt\n?? b.txt", (None, None, None, 2)),
                ("git diff --stat", "fatal: synthetic error", None)):
            with self.subTest(command=command, output=output):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", command), result("after", output),
                ])
                self.assertEqual(record["size_source"], "none" if expected is None else "after-only")
                self.assertEqual(tuple(record[key] for key in lane_stats.SIZE_FIELDS),
                                 expected or (None, None, None, None))
        failure = result("after", "1 file changed, 99 insertions(+)")
        failure["message"]["content"][0]["is_error"] = True
        record = self.mine_subagent([sub_tool("launch", "codex exec 'synthetic task'"),
                                     sub_tool("after", "git diff --stat"), failure])
        self.assertEqual(record["size_source"], "none")

    def test_summary_transcript_buckets_overhead_and_reasoning_counts(self):
        records = []
        for size in (0, 1, 20, 21, 100, 101, 500, 501):
            for source, duration, tokens, turns, status in (
                    ("delta", 10, 10, 2, "complete"), ("delta-clean", 10, 10, 2, "complete"),
                    ("after-dirty", 30, 30, 4, "partial"), ("after-only", 30, 30, 4, "partial")):
                record = self.mine_subagent([
                    sub_tool("launch", "codex exec 'synthetic task'"),
                    sub_tool("after", "git diff --shortstat"),
                    result("after", f"1 file changed, {size} insertions(+)"),
                ])
                record.update(size_source=source, duration_s=duration, sub_input_tokens=tokens,
                              sub_output_tokens=tokens, sub_cache_creation_tokens=tokens,
                              sub_cache_read_tokens=99999, sub_turns=turns, status=status,
                              spec_reasoning="high" if source in ("delta", "delta-clean") else "medium")
                records.append(record)
        self.assertEqual([lane_stats.line_bucket(r) for r in records[::4]],
                         ["0", "1-20", "1-20", "21-100", "21-100", "101-500", "101-500", ">500"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            lane_stats.summary(path, records, [])
            output = path.read_text()
        for title in ("Size source by agent type", "Transcript change sizes",
                      "Lane overhead by size: sol-implementer — upper-bound sizes included"):
            self.assertIn(f"### {title} (n=32)", output)
        for title in ("Lane overhead by size: sol-implementer", "Spec reasoning × line bucket"):
            self.assertIn(f"### {title} (n=16)", output)
        self.assertIn("| Agent type | delta | delta-clean | after-dirty | after-only | none |", output)
        self.assertIn("| Insertions + deletions | delta | delta-clean | after-dirty | after-only |", output)
        self.assertIn("| sol-implementer | 8 | 8 | 8 | 8 | 0 |", output)
        exact = output.split("### Lane overhead by size: sol-implementer (n=16)")[1].split("###", 1)[0]
        for label, count in zip(lane_stats.LINE_BUCKETS, (1, 2, 2, 2, 1)):
            self.assertIn(f"| {label} | {count} | {count} | {count} | {count} |", output)
            self.assertIn(f"| {label} | {count * 2} | 10.0 | 10.0 | 30.0 | 2.0 | complete: {count * 2} |", exact)
            self.assertIn(f"| {label} | {count * 4} | 20.0 | 30.0 | 60.0 | 3.0 | "
                          f"complete: {count * 2}; partial: {count * 2} |", output)
        self.assertIn("| high | 2 | 4 | 4 | 4 | 2 |", output)
        self.assertNotIn("| medium |", output.split("### Spec reasoning × line bucket")[1].split("###", 1)[0])

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

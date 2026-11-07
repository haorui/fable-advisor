#!/usr/bin/env python3
"""Mine plugin invocations without exporting transcript prompts or reports.

Only immediate project/*.jsonl files are main sessions. --since filters call
start dates in UTC. Copied calls belong to the earliest occurrence (ties use
the sorted file order); session statistics still describe each main file.
Token totals measure the Claude subagent wrapper, not external Codex usage.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import shlex


AGENT_RE = re.compile(
    r"^(?:fable-advisor:)?"
    r"(fable-advisor|sol-implementer|sonnet-implementer|luna-implementer|opus-implementer)$"
)
DIFF_RE = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?"
    r"(?:, (\d+) deletions?\(-\))?"
)
REPORT_FIELDS = {
    "status": "STATUS", "verdict": "VERDICT", "report_model": "MODEL",
    "lane": "LANE", "mode": "MODE",
}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
STATUSES = {"complete", "partial", "incomplete", "timeout", "unavailable",
            "blocked", "refused", "insufficient-brief"}
VERDICTS = r"(?<![\w-])(?:ship|fix-first|rethink|proceed|revise)(?![\w-])"
UNCAPPED_FIELDS = {"project", "session_id", "tool_use_id", "agent_id", "start_ts", "end_ts"}
SUB_FIELDS = (
    "sub_model", "sub_turns", "sub_input_tokens", "sub_output_tokens",
    "sub_cache_read_tokens", "sub_cache_creation_tokens",
)
TOKEN_FIELDS = {
    "sub_input_tokens": "input_tokens",
    "sub_output_tokens": "output_tokens",
    "sub_cache_read_tokens": "cache_read_input_tokens",
    "sub_cache_creation_tokens": "cache_creation_input_tokens",
}
SIZE_AGENTS = {"sol-implementer", "sonnet-implementer", "luna-implementer"}
SIZE_FIELDS = ("size_files", "size_insertions", "size_deletions", "size_new_untracked")
SIZE_SOURCES = ("delta", "delta-clean", "after-dirty", "after-only")
LINE_BUCKETS = ("0", "1-20", "21-100", "101-500", ">500")
TAKEOVER = "taking this over after two lane failures"
DIRECT = "→ direct ·"


def json_lines(path, stats):
    """Skip corrupt lines and non-object JSON; never buffer a transcript."""
    try:
        stream = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return
    stats["files_scanned"] += 1
    with stream:
        for line in stream:
            try:
                item = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(item, dict):
                yield item


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return None


def time_key(value):
    return timestamp(value) or datetime.max.replace(tzinfo=timezone.utc)


def era(start_ts):
    parsed = timestamp(start_ts)
    if parsed is None:
        return None
    if parsed.date() < date(2026, 10, 11):
        return "v7"
    if parsed.date() < date(2026, 11, 6):
        return "v8.0"
    return "v8.1"


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        )
    return ""


def field(text, name, flags=0):
    # Labels may carry markdown decoration and any case (`**Verdict: revise.**`);
    # the closed-vocabulary normalization downstream guards against false hits.
    match = re.search(r"^[*_#> \t]*" + name + r"[*_]*[ \t]*:[*_]*[ \t]*([^\r\n]*)", text,
                      re.MULTILINE | re.IGNORECASE | flags)
    return match.group(1).strip() if match else None


def leading_token(value, vocabulary=None):
    if value is None:
        return None
    value = value.translate(str.maketrans("", "", "*`")).strip()
    match = re.match(r"[\w-]+" if vocabulary is not None else r"\S+", value)
    token = match.group(0) if match else ""
    if vocabulary is not None:
        token = token.lower()
        return token if token in vocabulary else "other"
    return token[:32] or "other"


def prompt_mode(prompt):
    match = re.search(r"^(?:MODE:[ \t]*([^\r\n]*)|((?:REVIEW|CONSULT)\b[^\r\n]*))",
                      prompt, re.MULTILINE | re.I)
    return leading_token(next(g for g in match.groups() if g is not None),
                         {"review", "consult"}) if match else None


def report_fields(report):
    values = {key: field(report, label) for key, label in REPORT_FIELDS.items()}
    verdict = values["verdict"]
    matches = set(re.findall(VERDICTS, verdict.replace("*", "").replace("`", "").lower())) if verdict is not None else set()
    model = values["report_model"]
    family = re.search(r"fable|opus|sonnet|gpt", model[:40], re.I) if model is not None else None
    lane = values["lane"]
    effort = re.search(r"\beffort:[ \t]*([^\r\n]*)", lane, re.I) if lane is not None else None
    result = {
        "status": leading_token(values["status"], STATUSES),
        "verdict": ("mixed" if len(matches) > 1 else next(iter(matches), "other")) if verdict is not None else None,
        "report_model": (family.group().lower() if family else "other") if model is not None else None,
        "lane_name": leading_token(lane),
        "lane_effort": ("not-invoked" if re.search(r"\bnot (?:invoked|used)\b", lane, re.I)
                        else leading_token(effort.group(1), EFFORTS) if effort else "other") if lane is not None else None,
        "mode": leading_token(values["mode"], {"review", "consult"}),
    }
    diff = DIFF_RE.search(report)
    for index, key in enumerate(("files_changed", "insertions", "deletions"), 1):
        # An omitted insertion/deletion clause in a diffstat means zero.
        result[key] = int(diff.group(index) or 0) if diff else None
    return result


def new_call(project, session_id, line, block):
    args = block["input"]
    prompt = args.get("prompt")
    prompt = prompt if isinstance(prompt, str) else ""
    budget = field(prompt, "BUDGET", re.I)
    budget_token = budget.split()[0] if budget else ""
    record = {
        "project": project, "session_id": session_id, "tool_use_id": block["id"],
        "agent_id": None, "agent_type": AGENT_RE.fullmatch(args["subagent_type"]).group(1),
        "description": args.get("description"), "model_param": args.get("model"),
        "prompt_chars": len(prompt),
        "spec_reasoning": leading_token(field(prompt, "REASONING", re.I), EFFORTS),
        "spec_model": leading_token(field(prompt, "MODEL", re.I)),
        "spec_budget": (budget_token if re.fullmatch(r"[0-9]+", budget_token) else "other") if budget is not None else None,
        "is_async": False,
        "start_ts": line.get("timestamp"), "end_ts": None, "duration_s": None,
        "notify_count": 0, "notify_status": None, "result_found": False,
        "cc_version": line.get("version"), "era": era(line.get("timestamp")),
    }
    record.update(report_fields(""))
    record["mode"] = prompt_mode(prompt)
    record.update(dict.fromkeys(SUB_FIELDS))
    record.update(dict.fromkeys(SIZE_FIELDS))
    record["size_source"] = "none"
    return {"record": record, "prompt_mode": record["mode"], "verdicts": []}


def apply_report(call, report, end_ts, notification_status=None):
    record = call["record"]
    record.update(report_fields(report))
    record["mode"] = record["mode"] or call["prompt_mode"]
    if record["notify_count"]:
        record["notify_status"] = leading_token(notification_status or "", {"completed", "failed", "killed"})
    record["result_found"] = bool(report.strip())
    record["end_ts"] = end_ts
    if record["agent_type"] == "fable-advisor" and record["verdict"]:
        call["verdicts"].append((time_key(end_ts), record["verdict"]))


def xml_field(body, name):
    # <result> is the last element of a notification and may itself contain a
    # literal "</result>" (e.g. in a code block), so match it greedily.
    lazy = "" if name == "result" else "?"
    match = re.search(r"<" + name + r">(.*" + lazy + r")</" + name + r">", body, re.DOTALL)
    return match.group(1).strip() if match else None


def scan_session(path, project, since, stats):
    calls = {}
    takeovers = direct_markers = 0
    for line in json_lines(path, stats):
        message = line.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if line.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        takeovers += text.count(TAKEOVER)
                        direct_markers += text.count(DIRECT)
                args = block.get("input")
                if (block.get("type") != "tool_use" or block.get("name") not in ("Agent", "Task")
                        or not isinstance(args, dict)
                        or not isinstance(args.get("subagent_type"), str)
                        or not AGENT_RE.fullmatch(args["subagent_type"])
                        or not isinstance(block.get("id"), str)):
                    continue
                tool_id = block["id"]
                if tool_id not in calls:
                    calls[tool_id] = new_call(project, path.stem, line, block)
        elif line.get("type") == "user":
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    call = calls.get(block.get("tool_use_id"))
                    if call is None:
                        continue
                    report = text_content(block.get("content"))
                    launch = line.get("toolUseResult")
                    launch = launch if isinstance(launch, dict) else {}
                    agent_id = launch.get("agentId")
                    if isinstance(agent_id, str):
                        call["record"]["agent_id"] = agent_id
                    if report.startswith("Async agent launched successfully"):
                        call["record"]["is_async"] = True
                    elif not call["record"]["notify_count"]:
                        apply_report(call, report, line.get("timestamp"))
            for match in re.finditer(r"<task-notification>(.*?)</task-notification>",
                                     text_content(content), re.DOTALL):
                body = match.group(1)
                call = calls.get(xml_field(body, "tool-use-id"))
                if call is not None:
                    call["record"]["is_async"] = True
                    call["record"]["notify_count"] += 1
                    apply_report(call, xml_field(body, "result") or "", line.get("timestamp"),
                                 xml_field(body, "status"))

    selected = []
    verdicts = []
    for call in calls.values():
        record = call["record"]
        start = timestamp(record["start_ts"])
        if since and (start is None or start.date() < since):
            continue
        end = timestamp(record["end_ts"])
        if start and end:
            record["duration_s"] = (end - start).total_seconds()
        selected.append(record)
        verdicts.extend(call["verdicts"])
    session = {
        "project": project, "session_id": path.stem, "takeovers": takeovers,
        "direct_markers": direct_markers,
        "verdict_sequence": [value for _, value in sorted(verdicts, key=lambda item: item[0])],
    }
    return selected, session


def meta_tool_id(path, stats):
    """Read just a metadata object's string fields, including pretty JSON.

    Tokenizing each line avoids loading a whole file or retaining descriptions.
    JSON strings cannot contain literal newlines, so tokens stay within lines.
    """
    try:
        stream = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    stats["files_scanned"] += 1
    depth = 0
    previous = None
    key = None
    with stream:
        for line in stream:
            for token in re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\]:,]|[^\s{}\[\]:,"]+', line):
                if token in ("{", "["):
                    depth += 1
                elif token in ("}", "]"):
                    depth -= 1
                elif depth == 1 and token.startswith('"'):
                    try:
                        value = json.loads(token)
                    except ValueError:
                        return None
                    if previous in ("{", ","):
                        key = value
                    elif previous == ":" and key == "toolUseId":
                        return value
                previous = token
    return None


def strip_heredocs(command):
    """Keep shell headers, but never tokenize arbitrary heredoc bodies."""
    lines = []
    delimiters = []
    for line in command.splitlines(keepends=True):
        if delimiters:
            if line.strip() == delimiters[0]:
                delimiters.pop(0)
            continue
        lines.append(line)
        delimiters.extend(re.findall(r"(?<!<)<<[-~]?\s*['\"]?(\w+)['\"]?", line))
    return "".join(lines)


def shell_segments(command):
    command = strip_heredocs(command)
    # Keep ampersand redirects inside their segment: `2>&1` -> `2>`, `>&2` -> `>`,
    # `&>f` -> `>f`. Otherwise `&` lexes as a separator and hides redirects and pipes.
    command = re.sub(r"(\d?>>?|<)&(?=[\d-])", r"\1", command)
    command = re.sub(r"&>(>?)", r">\1", command)
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        # A broken quote in one segment must not hide independent Git commands.
        tokens = []
        for part in re.split(r"(&&|\|\||[;|\n])", command):
            if part in ("&&", "||", ";", "|", "\n"):
                tokens.append(part)
            else:
                try:
                    tokens.extend(shlex.split(part))
                except ValueError:
                    continue
    segments = [[]]
    separators = []
    for token in tokens:
        if token and all(char in ";&|()\n" for char in token):
            separators.append(token)
            segments.append([])
        else:
            segments[-1].append(token)
    return segments, separators


def stat_commands(command, before_launch=False):
    """Describe Git stat commands without retaining shell text in records."""
    segments, separators = shell_segments(command)
    commands = []
    for index, segment in enumerate(segments):
        if before_launch and any(token.rsplit("/", 1)[-1] == "codex" and following == "exec"
                                 for token, following in zip(segment, segment[1:])):
            break
        # Leading env assignments (GIT_PAGER=cat git ...) don't change what Git prints.
        while segment and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", segment[0]):
            segment = segment[1:]
        if not segment or segment[0] != "git":
            continue
        args = segment[1:]
        # Redirection destinations are shell syntax, not Git path scopes.
        redirect = next((i for i, arg in enumerate(args) if re.match(r"^\d*[<>]", arg)), len(args))
        # Stdout sent to a file leaves nothing to measure; an empty result must not read as zero.
        if any(re.match(r"^(?:1?>>?|>\|)", arg) for arg in args[redirect:]):
            continue
        args = args[:redirect]
        while args:
            if len(args) >= 2 and args[0] in ("-C", "-c", "--git-dir", "--work-tree"):
                args = args[2:]
            elif args[0] in ("--no-pager", "-P", "--paginate", "-p", "--no-optional-locks"):
                args = args[1:]
            else:
                break
        if not args or args[0] not in ("diff", "status"):
            continue
        operation, args = args[0], args[1:]
        if operation == "status":
            short = any(arg == "--short" or arg.startswith("--porcelain") or
                        (re.fullmatch(r"-[sb]+", arg) and "s" in arg) for arg in args)
            kind = "status" if short else "status-long"
        else:
            kind = next((flag[2:] for flag in ("--numstat", "--shortstat", "--stat")
                         if any(arg.split("=", 1)[0] == flag for arg in args)), "patch")
            if kind == "patch" and any(arg in ("--check", "--name-only", "--name-status",
                                               "--quiet", "--no-patch", "-s") for arg in args):
                continue
        # A bare HEAD compares the whole tree (worktree + index vs HEAD); ranges stay excluded.
        scoped = any(arg in ("--cached", "--staged", "--") or ".." in arg
                     or (not arg.startswith("-") and not (operation == "diff" and arg == "HEAD"))
                     for arg in args)
        piped = False
        limit = None
        consumer = index
        while consumer < len(separators) and separators[consumer] in ("|", "|&"):
            piped = True
            consumer += 1
            downstream = segments[consumer]
            program = downstream[0].rsplit("/", 1)[-1] if downstream else ""
            if kind.startswith("status") and program in ("head", "tail"):
                options = " ".join(downstream[1:])
                count = re.fullmatch(r"(?:-(\d+)|(?:-n\s*|--lines[= ])(\d+))?", options)
                if count:
                    length = int(next((n for n in count.groups() if n is not None), "10"))
                    limit = min(limit, length) if limit is not None else length
                else:
                    scoped = True
            elif kind in ("patch", "status", "status-long") and program not in ("cat", "tee"):
                scoped = True
        commands.append((kind, scoped, piped, limit))
    return commands


def patch_totals(output):
    """Reject marked truncation and hunks with missing old/new lines."""
    if re.search(r"\[\.\.\.\s|truncated|Output too large", output, re.I):
        return None
    totals = [0, 0, 0]
    old = new = 0
    complete = False
    for line in output.splitlines():
        if line.startswith("diff --git "):
            if old or new or (totals[0] and not complete):
                return None
            totals[0] += 1
            complete = False
        elif not totals[0]:
            continue
        elif line.startswith("@@"):
            hunk = re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
            if not hunk or old or new or not totals[0]:
                return None
            old, new = (int(count) if count is not None else 1 for count in hunk.groups())
            complete = True
        elif line.startswith("\\ No newline at end of file"):
            continue
        elif old or new:
            if line.startswith("+"):
                new -= 1
            elif line.startswith("-"):
                old -= 1
            elif line.startswith(" "):
                old -= 1
                new -= 1
            else:
                return None
            if old < 0 or new < 0:
                return None
        elif line.startswith(("rename to ", "copy to ", "Binary files ", "new mode ",
                              "new file mode ", "deleted file mode ")):
            complete = True
        elif line.startswith(("+", "-", " ")) and not line.startswith(("+++ ", "--- ")):
            # A body line after the declared end also indicates an invalid hunk.
            if not re.match(r"^[ MADRCUT?!]{2} \S", line):
                return None
        if line.startswith("+") and not line.startswith("+++ "):
            totals[1] += 1
        elif line.startswith("-") and not line.startswith("--- "):
            totals[2] += 1
    return totals if totals[0] and complete and not (old or new) else None


def size_measurement(commands, output):
    """Parse totals and transient per-file stats; ignore scoped Git output.

    Diff summaries and contiguous numstat rows delimit chained diff outputs.
    If scoped and unscoped outputs cannot be paired unambiguously, discard
    the diff rather than attributing a scoped total to the working tree.
    """
    diffs = [(kind, scoped, piped) for kind, scoped, piped, _ in commands if not kind.startswith("status")]
    statuses = [(kind, scoped, limit) for kind, scoped, _, limit in commands if kind.startswith("status")]
    summaries = [diff for diff in diffs if diff[0] != "patch"]
    events = []
    details = {}
    numstat = None
    old = new = 0
    for line in output.splitlines():
        # Summary-like text inside a patch hunk is file content, not a stat.
        hunk = re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if hunk:
            old, new = (int(count) if count is not None else 1 for count in hunk.groups())
            continue
        if old or new:
            if line.startswith(("-", " ")):
                old = max(0, old - 1)
            if line.startswith(("+", " ")):
                new = max(0, new - 1)
            continue
        row = re.fullmatch(r"(\d+|-)\t(\d+|-)\t(.+)", line)
        if row:
            if numstat is None:
                numstat = [0, 0, 0]
            numstat[0] += 1
            if row[1] != "-" and row[2] != "-":
                numstat[1] += int(row[1])
                numstat[2] += int(row[2])
            continue
        if numstat is not None:
            events.append(("numstat", numstat, None))
            numstat = None
        match = DIFF_RE.fullmatch(line.strip())
        if match:
            events.append(("stat", [int(value or 0) for value in match.groups()], details or None))
            details = {}
        else:
            row = re.fullmatch(r"\s*(.+?)\s+\|\s+(\d+)(?:\s+([+-]+))?\s*", line)
            if row:
                details[row[1]] = (int(row[2]), row[3] or "")
    if numstat is not None:
        events.append(("numstat", numstat, None))

    selected = None
    if len(events) == len(summaries):
        for (kind, scoped, _), event in zip(summaries, events):
            if not scoped and (kind == "numstat") == (event[0] == "numstat"):
                selected = event
    elif summaries and all(not scoped for _, scoped, _ in summaries) and events:
        # Adjacent numstat outputs can merge into one run of rows. A final
        # summary is self-delimiting, but merged numstats cannot be separated.
        if events[-1][0] != "numstat" or sum(kind == "numstat" for kind, _, _ in summaries) <= sum(
                event[0] == "numstat" for event in events):
            selected = events[-1]
    if selected is None and len(diffs) == 1 and diffs[0][0] == "patch" and not diffs[0][1]:
        totals = patch_totals(output)
        if totals is not None:
            selected = ("patch", totals, None)
    if selected is None and diffs and all(not scoped and not piped for _, scoped, piped in diffs) and not output.strip():
        selected = ("stat", [0, 0, 0], None)
    has_status = statuses and not any(scoped for _, scoped, _ in statuses)
    if selected is None and not has_status:
        return None
    values = dict.fromkeys(SIZE_FIELDS)
    if selected is not None:
        values.update(zip(SIZE_FIELDS[:3], selected[1]))
    clean = None
    if has_status:
        short = all(kind == "status" for kind, _, _ in statuses)
        rows = [line for line in output.splitlines() if re.match(r"^[ MADRCUT?!]{2} \S", line)]
        truncated = any(limit is not None and len(rows) >= limit for _, _, limit in statuses)
        tracked = any(any(char not in " ?" for char in line[:2]) for line in rows)
        long_dirty = re.search(r"^(?:Changes (?:not staged for commit|to be committed):|Unmerged paths:)",
                               output, re.M)
        if tracked or long_dirty or truncated:
            clean = 0
        elif (short or
              re.search(r"nothing to commit|nothing added to commit but untracked files present", output)):
            clean = 1
        if short and not truncated:
            values["size_new_untracked"] = sum(line.startswith("?? ") for line in rows)
        elif not truncated and "nothing to commit, working tree clean" in output:
            values["size_new_untracked"] = 0
    if selected is None and clean is None:
        return None
    return values, selected[2] if selected else None, clean


def merge_size_measurement(previous, measurement, orders, position):
    """Keep the latest diff and status independently, in tool invocation order."""
    values, details, clean = previous or (dict.fromkeys(SIZE_FIELDS), None, None)
    current, current_details, current_clean = measurement
    if current["size_files"] is not None and position > orders[0]:
        values.update((key, current[key]) for key in SIZE_FIELDS[:3])
        details = current_details
        orders[0] = position
    if (current_clean is not None or current["size_new_untracked"] is not None) and position > orders[1]:
        values["size_new_untracked"] = current["size_new_untracked"]
        clean = current_clean
        orders[1] = position
    return values, details, clean


def size_result(before, after, split):
    result = dict.fromkeys(SIZE_FIELDS)
    result["size_source"] = "none"
    if not split or after is None:
        return result
    result.update(after[0])
    result["size_source"] = ("after-only" if before is None else
                             "delta" if before[0]["size_files"] is not None else
                             "delta-clean" if before[2] == 1 else "after-dirty")
    if before is not None:
        for key in SIZE_FIELDS:
            old, new = before[0][key], after[0][key]
            result[key] = max(0, new - old) if old is not None and new is not None else new
        if before[1] is not None and after[1] is not None:
            result["size_files"] = sum(before[1].get(path) != stat for path, stat in after[1].items())
    return result


def scan_subagent(path, agent_type, stats):
    usage = None
    models = Counter()
    pending = {}
    before = after = None
    split = False
    order = 0
    before_orders = [-1, -1]
    after_orders = [-1, -1]
    for line in json_lines(path, stats):
        if usage is None:
            usage = {key: 0 for key in SUB_FIELDS if key != "sub_model"}
        message = line.get("message")
        if line.get("type") == "assistant":
            usage["sub_turns"] += 1
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("model"), str):
                models[message["model"]] += 1
            tokens = message.get("usage")
            if isinstance(tokens, dict):
                for output, source in TOKEN_FIELDS.items():
                    value = tokens.get(source)
                    if isinstance(value, int) and not isinstance(value, bool):
                        usage[output] += value
        if agent_type not in SIZE_AGENTS or not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if line.get("type") == "assistant" and block.get("type") == "tool_use":
                order += 1
                args = block.get("input")
                command = args.get("command") if isinstance(args, dict) else None
                launch = (block.get("name") == "Bash" and isinstance(command, str)
                          and re.search(r"\bcodex\s+exec\b", command))
                edit = block.get("name") in ("Edit", "Write", "NotebookEdit")
                first_split = not split and (edit if agent_type == "sonnet-implementer" else launch)
                if first_split:
                    split = True
                if block.get("name") == "Bash" and isinstance(command, str):
                    commands = stat_commands(command, before_launch=bool(first_split))
                    if commands and isinstance(block.get("id"), str):
                        pending[block["id"]] = (order, split and not first_split, commands)
            elif line.get("type") == "user" and block.get("type") == "tool_result":
                invocation = pending.pop(block.get("tool_use_id"), None)
                if invocation is None or block.get("is_error"):
                    continue
                position, is_after, commands = invocation
                measurement = size_measurement(commands, text_content(block.get("content")))
                if measurement is not None:
                    if is_after:
                        after = merge_size_measurement(after, measurement, after_orders, position)
                    else:
                        before = merge_size_measurement(before, measurement, before_orders, position)
    if usage is not None:
        usage["sub_model"] = models.most_common(1)[0][0] if models else None
        if agent_type in SIZE_AGENTS:
            usage.update(size_result(before, after, split))
    return usage


def add_subagent_usage(records, root, stats):
    by_session = defaultdict(list)
    for record in records:
        by_session[(record["project"], record["session_id"])].append(record)
    for (project, session_id), calls in by_session.items():
        directory = root / project / session_id / "subagents"
        missing_ids = {record["tool_use_id"]: record for record in calls if record["agent_id"] is None}
        if missing_ids:
            for path in sorted(directory.glob("agent-*.meta.json")):
                tool_id = meta_tool_id(path, stats)
                if tool_id in missing_ids:
                    missing_ids[tool_id]["agent_id"] = path.name[len("agent-"):-len(".meta.json")]
        usage_cache = {}
        for record in calls:
            agent_id = record["agent_id"]
            if not agent_id or Path(agent_id).name != agent_id or "\\" in agent_id:
                continue
            cache_key = (agent_id, record["agent_type"])
            if cache_key not in usage_cache:
                usage_cache[cache_key] = scan_subagent(
                    directory / ("agent-" + agent_id + ".jsonl"), record["agent_type"], stats)
            if usage_cache[cache_key] is not None:
                record.update(usage_cache[cache_key])


def percentile(values, fraction):
    """Linearly interpolate between sorted samples; absent samples stay null."""
    values = sorted(value for value in values if value is not None)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def display(value):
    if value is None:
        return "missing"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def table(stream, title, n, headers, rows):
    stream.write(f"### {title} (n={n})\n\n")
    stream.write("| " + " | ".join(headers) + " |\n")
    stream.write("| " + " | ".join("---" for _ in headers) + " |\n")
    for row in rows:
        stream.write("| " + " | ".join(display(cell) for cell in row) + " |\n")
    stream.write("\n")


def line_bucket(record):
    insertions, deletions = record["size_insertions"], record["size_deletions"]
    if insertions is None or deletions is None:
        return None
    size = insertions + deletions
    return next(label for limit, label in zip((0, 20, 100, 500, float("inf")), LINE_BUCKETS)
                if size <= limit)


def summary(path, records, sessions):
    with path.open("w", encoding="utf-8") as stream:
        stream.write("# Lane statistics\n\n")
        stream.write("Calls are deduplicated by tool-use ID; session totals describe main files. "
                     "Missing values are shown explicitly. Percentiles use linear interpolation. "
                     "Token totals include input, output, cache read and cache creation in the "
                     "Claude wrapper; external Codex usage is unavailable.\n\n")
        stream.write("## 1. Invocations by project and agent\n\n")
        counts = Counter((r["project"], r["agent_type"]) for r in records)
        table(stream, "Project × agent type", len(records), ["Project", "Agent type", "Count"],
              [(project, agent, count) for (project, agent), count in sorted(counts.items())])

        stream.write("## 2. Invocations by era and agent\n\n")
        groups = defaultdict(list)
        for record in records:
            groups[(record["era"] or "missing", record["agent_type"])].append(record)
        rows = []
        for (period, agent), group in sorted(groups.items()):
            statuses = Counter(r["status"] or "missing" for r in group)
            tokens = [sum(r[key] for key in TOKEN_FIELDS) for r in group
                      if all(r[key] is not None for key in TOKEN_FIELDS)]
            durations = [r["duration_s"] for r in group if r["duration_s"] is not None]
            rows.append((period, agent, len(group),
                         f"{sum(r['result_found'] for r in group) / len(group):.1%}",
                         "; ".join(f"{key}: {value}" for key, value in sorted(statuses.items())),
                         len(durations), percentile(durations, .5), percentile(durations, .9),
                         len(tokens), percentile(tokens, .5)))
        table(stream, "Era × agent type", len(records),
              ["Era", "Agent type", "Count", "Result found", "Statuses", "Duration n",
               "Duration p50 (s)", "Duration p90 (s)", "Token n", "Sub tokens p50"], rows)

        stream.write("## 3. Implementer calls\n\n")
        implementers = [r for r in records if r["agent_type"] != "fable-advisor"]
        reasoning = Counter(r["spec_reasoning"] or "missing" for r in implementers)
        table(stream, "Spec reasoning", len(implementers), ["Reasoning", "Count"], sorted(reasoning.items()))
        measured_agents = [r for r in implementers if r["agent_type"] in SIZE_AGENTS]
        sources = Counter((r["agent_type"], r["size_source"]) for r in measured_agents)
        table(stream, "Size source by agent type", len(measured_agents),
              ["Agent type", *SIZE_SOURCES, "none"],
              [(agent, *(sources[agent, source] for source in (*SIZE_SOURCES, "none")))
               for agent in sorted({r["agent_type"] for r in measured_agents})])
        measured = [r for r in measured_agents if r["size_source"] != "none"]
        buckets = Counter((line_bucket(r), r["size_source"]) for r in measured)
        rows = [(label, *(buckets[label, source] for source in SIZE_SOURCES))
                for label in LINE_BUCKETS]
        # Status-only measurements have no tracked-line total.
        rows.append(("missing", *(buckets[None, source] for source in SIZE_SOURCES)))
        rows.append(("new untracked > 0",
                     *(sum(r["size_source"] == source and (r["size_new_untracked"] or 0) > 0 for r in measured)
                       for source in SIZE_SOURCES)))
        table(stream, "Transcript change sizes", len(measured),
              ["Insertions + deletions", *SIZE_SOURCES], rows)
        stream.write("The untracked row overlaps the line buckets and counts only ?? output lines. "
                     "Missing fields were not observed. Delta subtracts observed totals; delta-clean "
                     "uses a clean tracked baseline as zero. After-dirty and after-only sizes are upper bounds.\n\n")
        sol = [r for r in measured if r["agent_type"] == "sol-implementer" and line_bucket(r) is not None]
        fresh_fields = ("sub_input_tokens", "sub_output_tokens", "sub_cache_creation_tokens")
        for upper_bounds in (False, True):
            included = sol if upper_bounds else [r for r in sol if r["size_source"] in ("delta", "delta-clean")]
            rows = []
            for label in LINE_BUCKETS:
                group = [r for r in included if line_bucket(r) == label]
                durations = [r["duration_s"] for r in group]
                tokens = [sum(r[key] for key in fresh_fields) for r in group
                          if all(r[key] is not None for key in fresh_fields)]
                statuses = Counter(r["status"] or "missing" for r in group)
                rows.append((label, len(group), percentile(durations, .5), percentile(durations, .9),
                             percentile(tokens, .5), percentile([r["sub_turns"] for r in group], .5),
                             "; ".join(f"{key}: {value}" for key, value in sorted(statuses.items()))))
            title = "Lane overhead by size: sol-implementer" + (" — upper-bound sizes included" if upper_bounds else "")
            table(stream, title, len(included),
                  ["Insertions + deletions", "n", "Duration p50 (s)", "Duration p90 (s)",
                   "Wrapper fresh tokens p50", "Wrapper turns p50", "Statuses"], rows)
        stream.write("Default overhead and reasoning tables use only delta and delta-clean sizes. Fresh tokens "
                     "sum input, output and cache creation; cache reads are excluded.\n\n")
        sized = [r for r in measured if r["size_source"] in ("delta", "delta-clean") and line_bucket(r) is not None]
        cross = Counter((r["spec_reasoning"] or "missing", line_bucket(r)) for r in sized)
        table(stream, "Spec reasoning × line bucket", len(sized), ["Reasoning", *LINE_BUCKETS],
              [(effort, *(cross[effort, label] for label in LINE_BUCKETS))
               for effort in sorted({r["spec_reasoning"] or "missing" for r in sized})])
        diffs = [r["insertions"] + r["deletions"] for r in implementers if r["files_changed"] is not None]
        sizes = [("≤20", sum(size <= 20 for size in diffs)),
                 ("21–100", sum(20 < size <= 100 for size in diffs)),
                 (">100", sum(size > 100 for size in diffs))]
        table(stream, "Report-quoted diffstat", len(diffs),
              ["Insertions + deletions", "Count", "Share"],
              [(label, count, f"{count / len(diffs):.1%}" if diffs else None) for label, count in sizes])
        table(stream, "Diffstat coverage", len(implementers), ["Diffstat", "Count"],
              [("present", len(diffs)), ("missing", len(implementers) - len(diffs))])

        stream.write("## 4. Advisor calls\n\n")
        advisors = [r for r in records if r["agent_type"] == "fable-advisor"]
        verdicts = Counter((r["mode"] or "missing", r["verdict"] or "missing") for r in advisors)
        table(stream, "Mode × final verdict", len(advisors), ["Mode", "Verdict", "Count"],
              [(mode, verdict, count) for (mode, verdict), count in sorted(verdicts.items())])
        models = Counter(r["report_model"] or "other" for r in advisors)
        table(stream, "Reported model family (missing included in other)", len(advisors),
              ["Model family", "Count"], [(model, models[model]) for model in ("fable", "opus", "sonnet", "gpt", "other")])
        found = [r for r in advisors if r["result_found"]]
        missing = sum(r["verdict"] is None for r in found)
        table(stream, "Verdict null rate among advisor calls with results", len(found),
              ["Metric", "Count", "Rate"],
              [("no verdict", missing, f"{missing / len(found):.1%}" if found else None)])

        stream.write("## 5. Per-session totals\n\n")
        table(stream, "Markers by session", len(sessions),
              ["Project", "Session", "Takeovers", "Direct markers"],
              [(s["project"], s["session_id"], s["takeovers"], s["direct_markers"]) for s in sessions])
        recovered = sum("ship" in s["verdict_sequence"][s["verdict_sequence"].index("fix-first") + 1:]
                        for s in sessions if "fix-first" in s["verdict_sequence"])
        table(stream, "Session markers and review recovery", len(sessions), ["Metric", "Count"],
              [("takeovers", sum(s["takeovers"] for s in sessions)),
               ("direct markers", sum(s["direct_markers"] for s in sessions)),
               ("sessions with fix-first followed by ship", recovered)])


def mine(projects_root, project_filter=None, since=None):
    stats = {"files_scanned": 0}
    calls = {}
    sessions = []
    for project in sorted(projects_root.iterdir()):
        if not project.is_dir() or (project_filter and not project_filter.search(project.name)):
            continue
        for path in sorted(project.glob("*.jsonl")):
            records, session = scan_session(path, project.name, since, stats)
            if records:
                sessions.append(session)
            for record in records:
                tool_id = record["tool_use_id"]
                if tool_id not in calls or time_key(record["start_ts"]) < time_key(calls[tool_id]["start_ts"]):
                    calls[tool_id] = record
    records = sorted(calls.values(), key=lambda r: (time_key(r["start_ts"]), r["tool_use_id"]))
    add_subagent_usage(records, projects_root, stats)
    for record in records:
        for key, value in record.items():
            if isinstance(value, str) and key not in UNCAPPED_FIELDS:
                record[key] = value[:120 if key == "description" else 32]
    return records, sessions, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", type=Path, default=Path("~/.claude/projects").expanduser())
    parser.add_argument("--project-filter", help="regular expression matched against project directory names")
    parser.add_argument("--since", type=date.fromisoformat, help="inclusive UTC call start date (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        project_filter = re.compile(args.project_filter) if args.project_filter else None
    except re.error as error:
        parser.error(f"invalid --project-filter: {error}")
    if not args.projects_root.is_dir():
        parser.error("--projects-root must be an existing directory")
    records, sessions, stats = mine(args.projects_root, project_filter, args.since)
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, items in (("invocations.jsonl", records), ("sessions.jsonl", sessions)):
        with (args.out / filename).open("w", encoding="utf-8") as stream:
            for item in items:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    summary(args.out / "summary.md", records, sessions)
    print(f"files scanned={stats['files_scanned']} invocations={len(records)} "
          f"result_found={sum(record['result_found'] for record in records)}")


if __name__ == "__main__":
    main()

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
            if agent_id not in usage_cache:
                usage = None
                models = Counter()
                for line in json_lines(directory / ("agent-" + agent_id + ".jsonl"), stats):
                    if usage is None:
                        usage = {key: 0 for key in SUB_FIELDS if key != "sub_model"}
                    if line.get("type") != "assistant":
                        continue
                    usage["sub_turns"] += 1
                    message = line.get("message")
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
                if usage is not None:
                    usage["sub_model"] = models.most_common(1)[0][0] if models else None
                usage_cache[agent_id] = usage
            if usage_cache[agent_id] is not None:
                record.update(usage_cache[agent_id])


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
        diffs = [r["insertions"] + r["deletions"] for r in implementers if r["files_changed"] is not None]
        sizes = [("≤20", sum(size <= 20 for size in diffs)),
                 ("21–100", sum(20 < size <= 100 for size in diffs)),
                 (">100", sum(size > 100 for size in diffs))]
        table(stream, "Change sizes among calls with a diffstat", len(diffs),
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

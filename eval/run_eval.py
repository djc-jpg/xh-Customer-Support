import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "eval" / "customer_support_v1_eval_dataset.json"
RESULTS_DIR = ROOT / "eval" / "results"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run auto-evaluation against the live /chat SSE endpoint.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL of the running agent service")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="Path to the evaluation dataset JSON")
    parser.add_argument("--category", action="append", help="Filter by category, can be passed multiple times")
    parser.add_argument("--limit", type=int, default=0, help="Only run the first N matching cases")
    parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    parser.add_argument("--output", default="", help="Optional output path for the report JSON")
    return parser.parse_args()


def load_dataset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or "").lower())
    return compact


def split_alt_values(value: str) -> list[str]:
    if "_or_" not in value:
        return [value]
    return [part for part in value.split("_or_") if part]


def stringify(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


def extract_tool_names(tool_calls: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in tool_calls:
        if isinstance(item, dict):
            name = item.get("name") or item.get("tool_name")
            if name:
                names.append(str(name))
    return names


def collect_retrieval_text(meta: dict[str, Any], trace: dict[str, Any]) -> str:
    texts: list[str] = []
    knowledge = meta.get("knowledge", {})
    for item in knowledge.get("retrieval_docs", []):
        if isinstance(item, dict):
            texts.append(str(item.get("text", "")))

    retrieval = trace.get("retrieval", {})
    for hit in retrieval.get("hits", []):
        if isinstance(hit, dict):
            texts.append(str(hit.get("snippet", "")))

    return "\n".join(texts)


def check_literal_violations(answer: str, must_not_contain: list[str]) -> list[str]:
    answer_norm = normalize_text(answer)
    violations: list[str] = []
    for item in must_not_contain:
        token = normalize_text(item)
        if token and token in answer_norm:
            violations.append(item)
    return violations


def evaluate_case(case: dict[str, Any], meta: dict[str, Any], answer: str, request_error: str | None) -> dict[str, Any]:
    trace = meta.get("trace", {}) if isinstance(meta, dict) else {}
    analysis = trace.get("analysis", {}) or meta.get("analysis", {}) or {}
    tool_calls = trace.get("tool_calls", []) or meta.get("tool_outputs", []) or []
    tool_names = extract_tool_names(tool_calls)
    retrieval_text = collect_retrieval_text(meta, trace)

    checks: dict[str, dict[str, Any]] = {}

    def add_check(name: str, passed: bool | None, expected: Any, actual: Any, note: str = "") -> None:
        checks[name] = {
            "passed": passed,
            "expected": expected,
            "actual": actual,
            "note": note,
        }

    expected_intents = split_alt_values(case["expected_intent"])
    actual_intent = str(analysis.get("intent", ""))
    add_check("intent", actual_intent in expected_intents, expected_intents, actual_intent)

    expected_sentiments = split_alt_values(case["expected_sentiment"])
    actual_sentiment = str(analysis.get("sentiment", ""))
    add_check("sentiment", actual_sentiment in expected_sentiments, expected_sentiments, actual_sentiment)

    expected_urgencies = split_alt_values(case["expected_urgency"])
    actual_urgency = str(analysis.get("urgency", ""))
    add_check("urgency", actual_urgency in expected_urgencies, expected_urgencies, actual_urgency)

    actual_need_tool = bool(analysis.get("need_tool", False))
    expected_need_tool = case["expected_need_tool"]
    if expected_need_tool == "required":
        add_check("need_tool", actual_need_tool is True, expected_need_tool, actual_need_tool)
    elif expected_need_tool == "forbidden":
        add_check("need_tool", actual_need_tool is False, expected_need_tool, actual_need_tool)
    else:
        add_check("need_tool", None, expected_need_tool, actual_need_tool, note="Optional case; manual review recommended")

    expected_tools = case.get("expected_tools", [])
    if expected_tools:
        missing = [tool for tool in expected_tools if tool not in tool_names]
        add_check("tools", not missing, expected_tools, tool_names, note="" if not missing else f"Missing tools: {missing}")
    elif expected_need_tool == "forbidden":
        add_check("tools", len(tool_names) == 0, expected_tools, tool_names)
    else:
        add_check("tools", None, expected_tools, tool_names, note="No strict tool expectation for this case")

    expected_topics = case.get("expected_retrieval_topics", [])
    if expected_topics:
        retrieval_norm = normalize_text(retrieval_text)
        matched_topics = [topic for topic in expected_topics if normalize_text(topic) in retrieval_norm]
        passed = len(matched_topics) >= 1
        add_check("retrieval_topics", passed, expected_topics, matched_topics, note="" if passed else "No expected topic found in retrieved text")
    else:
        add_check("retrieval_topics", None, expected_topics, [], note="No strict retrieval topic expectation")

    violations = check_literal_violations(answer, case.get("must_not_contain", []))
    add_check("literal_safety", len(violations) == 0, case.get("must_not_contain", []), violations)

    if request_error:
        add_check("request_error", False, "no error", request_error)
    else:
        add_check("request_error", True, "no error", "")

    auto_checks = [check for check in checks.values() if isinstance(check["passed"], bool)]
    auto_pass = all(check["passed"] for check in auto_checks) if auto_checks else False
    manual_review_required = bool(case.get("expected_answer_points")) or any(check["passed"] is None for check in checks.values())
    failed_checks = [name for name, check in checks.items() if check["passed"] is False]
    error_analysis = analyze_error(case, trace, checks, request_error, answer)

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "user_input": case["user_input"],
        "trace_id": trace.get("trace_id", meta.get("trace_id", "")),
        "latency_ms": trace.get("latency_ms"),
        "status": trace.get("status", "unknown"),
        "analysis": analysis,
        "tool_names": tool_names,
        "answer": answer,
        "checks": checks,
        "failed_checks": failed_checks,
        "auto_pass": auto_pass,
        "manual_review_required": manual_review_required,
        "manual_review_points": case.get("expected_answer_points", []),
        "error_analysis": error_analysis,
    }


def analyze_error(
    case: dict[str, Any],
    trace: dict[str, Any],
    checks: dict[str, dict[str, Any]],
    request_error: str | None,
    answer: str,
) -> dict[str, Any]:
    failed_checks = [name for name, check in checks.items() if check["passed"] is False]
    trace_error_type = str(trace.get("error", {}).get("type", "")).strip()

    if request_error:
        error_layer = trace_error_type or "unknown_error"
    elif "intent" in failed_checks or "sentiment" in failed_checks or "urgency" in failed_checks:
        error_layer = "intent_error"
    elif "need_tool" in failed_checks or "tools" in failed_checks:
        error_layer = "tool_decision_error"
    elif "retrieval_topics" in failed_checks:
        error_layer = "retrieval_error"
    elif "literal_safety" in failed_checks:
        error_layer = "response_grounding_error"
    else:
        error_layer = ""

    root_cause = infer_root_cause(error_layer, checks, trace, request_error)
    fix_direction = suggest_fix_direction(error_layer, case)

    return {
        "error_layer": error_layer,
        "failed_checks": failed_checks,
        "root_cause": root_cause,
        "fix_direction": fix_direction,
        "trace_error_type": trace_error_type,
        "answer_preview": clip_preview(answer),
    }


def infer_root_cause(
    error_layer: str,
    checks: dict[str, dict[str, Any]],
    trace: dict[str, Any],
    request_error: str | None,
) -> str:
    if request_error:
        return f"Request failed before a complete trace was produced: {request_error}"

    if error_layer == "intent_error":
        for key in ("intent", "sentiment", "urgency"):
            check = checks.get(key, {})
            if check.get("passed") is False:
                return f"{key} mismatch: expected {check.get('expected')} but got {check.get('actual')}"
        return "Analysis stage produced an unexpected classification."

    if error_layer == "tool_decision_error":
        need_tool_check = checks.get("need_tool", {})
        tools_check = checks.get("tools", {})
        if need_tool_check.get("passed") is False:
            return f"need_tool mismatch: expected {need_tool_check.get('expected')} but got {need_tool_check.get('actual')}"
        if tools_check.get("passed") is False:
            return tools_check.get("note") or f"Tool mismatch: expected {tools_check.get('expected')} but got {tools_check.get('actual')}"
        return "Tool decision did not match the expected execution path."

    if error_layer == "retrieval_error":
        retrieval = trace.get("retrieval", {})
        return f"Retrieved topics did not match expectations. Query was: {retrieval.get('query', '')}"

    if error_layer == "response_grounding_error":
        literal_check = checks.get("literal_safety", {})
        return f"Forbidden content detected in final answer: {literal_check.get('actual')}"

    if error_layer:
        return f"Trace reported error type: {error_layer}"

    return ""


def suggest_fix_direction(error_layer: str, case: dict[str, Any]) -> str:
    if error_layer == "intent_error":
        return "Refine intent/sentiment/urgency prompts or add more examples for this input pattern."
    if error_layer == "tool_decision_error":
        return "Tighten tool decision rules and missing-parameter follow-up logic for this scenario."
    if error_layer == "retrieval_error":
        return "Improve retrieval query rewrite, metadata, or ranking for the expected FAQ topic."
    if error_layer == "response_grounding_error":
        return "Strengthen grounding constraints so the final answer stays aligned with retrieved/tool facts."
    if error_layer == "unknown_error":
        return "Inspect service logs and trace output to isolate the failure before adjusting prompts or code."
    if error_layer:
        return f"Investigate the {error_layer} path and add a dedicated regression case."
    if case.get("expected_answer_points"):
        return "Manual review recommended to verify answer quality, tone, and completeness."
    return ""


def clip_preview(text: str, limit: int = 180) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip("，。；;,. ") + "..."


def stream_chat(base_url: str, message: str, timeout: int, session_id: str) -> tuple[dict[str, Any], str, str | None]:
    payload = {
        "session_id": session_id,
        "message": message,
        "top_k": 3,
        "use_tools": True,
        "show_debug": True,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    meta: dict[str, Any] = {}
    answer_parts: list[str] = []
    request_error: str | None = None

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                payload_text = line[6:]
                if payload_text == "[DONE]":
                    break
                try:
                    obj = json.loads(payload_text)
                except json.JSONDecodeError:
                    continue
                event_type = obj.get("type")
                content = obj.get("content")
                if event_type == "answer" and isinstance(content, str):
                    answer_parts.append(content)
                elif event_type == "meta" and isinstance(content, dict):
                    meta = content
                elif event_type == "error":
                    request_error = stringify(content)
    except urllib.error.HTTPError as exc:
        request_error = f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        request_error = f"URL Error: {exc.reason}"
    except TimeoutError:
        request_error = "Timeout"
    except Exception as exc:  # noqa: BLE001
        request_error = f"{type(exc).__name__}: {exc}"

    answer = "".join(answer_parts).replace("[FINAL_ANSWER]", "").strip()
    trace_answer = meta.get("trace", {}).get("final_answer", "")
    if trace_answer:
        answer = str(trace_answer).strip()

    return meta, answer, request_error


def summarize_results(results: list[dict[str, Any]], started_at: str, base_url: str, dataset_path: Path) -> dict[str, Any]:
    metrics = {
        "intent_accuracy": [],
        "sentiment_accuracy": [],
        "urgency_accuracy": [],
        "need_tool_accuracy": [],
        "tool_match_rate": [],
        "retrieval_topic_hit_rate": [],
        "literal_safety_rate": [],
        "request_success_rate": [],
    }

    auto_pass_count = 0
    manual_review_count = 0
    bad_cases: list[dict[str, Any]] = []
    error_layer_counts: dict[str, int] = {}

    for result in results:
        if result["auto_pass"]:
            auto_pass_count += 1
        if result["manual_review_required"]:
            manual_review_count += 1
        if not result["auto_pass"]:
            analysis = result.get("error_analysis", {})
            error_layer = analysis.get("error_layer") or "unclassified"
            error_layer_counts[error_layer] = error_layer_counts.get(error_layer, 0) + 1
            bad_cases.append(
                {
                    "case_id": result["case_id"],
                    "category": result["category"],
                    "trace_id": result.get("trace_id", ""),
                    "error_layer": error_layer,
                    "failed_checks": result.get("failed_checks", []),
                    "root_cause": analysis.get("root_cause", ""),
                    "fix_direction": analysis.get("fix_direction", ""),
                    "answer_preview": analysis.get("answer_preview", ""),
                }
            )

        for key, metric_name in [
            ("intent", "intent_accuracy"),
            ("sentiment", "sentiment_accuracy"),
            ("urgency", "urgency_accuracy"),
            ("need_tool", "need_tool_accuracy"),
            ("tools", "tool_match_rate"),
            ("retrieval_topics", "retrieval_topic_hit_rate"),
            ("literal_safety", "literal_safety_rate"),
            ("request_error", "request_success_rate"),
        ]:
            passed = result["checks"][key]["passed"]
            if isinstance(passed, bool):
                metrics[metric_name].append(1 if passed else 0)

    summary_metrics = {
        name: round(sum(values) / len(values), 4) if values else None for name, values in metrics.items()
    }

    return {
        "generated_at": started_at,
        "base_url": base_url,
        "dataset": str(dataset_path),
        "cases_total": len(results),
        "auto_pass_rate": round(auto_pass_count / len(results), 4) if results else 0.0,
        "manual_review_rate": round(manual_review_count / len(results), 4) if results else 0.0,
        "bad_case_count": len(bad_cases),
        "bad_case_error_layers": error_layer_counts,
        "metrics": summary_metrics,
        "bad_cases": bad_cases,
        "results": results,
    }


def filter_cases(cases: list[dict[str, Any]], categories: list[str] | None, limit: int) -> list[dict[str, Any]]:
    filtered = cases
    if categories:
        wanted = {item.strip() for item in categories if item.strip()}
        filtered = [case for case in filtered if case["category"] in wanted]
    if limit > 0:
        filtered = filtered[:limit]
    return filtered


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def build_prelude_messages(case: dict[str, Any]) -> list[str]:
    explicit = case.get("prelude_messages", [])
    if isinstance(explicit, list):
        messages = [str(item).strip() for item in explicit if str(item).strip()]
        if messages:
            return messages

    context = str(case.get("context", "")).strip()
    if not context or context == "单轮":
        return []

    if "上一轮已经查到 O1001" in context:
        return ["我的订单 O1001 到哪了？"]
    if "上一轮提到登录失败" in context:
        return ["登录不了，一直提示密码错误怎么办？"]
    if "上一轮刚创建工单" in context:
        return ["给我转人工客服"]

    return []


def main() -> int:
    args = parse_args()
    dataset_path = Path(args.dataset)
    dataset = load_dataset(dataset_path)
    cases = filter_cases(dataset["cases"], args.category, args.limit)

    if not cases:
        print("No cases selected.")
        return 1

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        session_id = f"eval-{case['case_id']}-{uuid4().hex[:8]}"
        print(f"[{index}/{len(cases)}] Running {case['case_id']} ({case['category']})")
        for prelude in build_prelude_messages(case):
            _, _, _ = stream_chat(args.base_url, prelude, args.timeout, session_id)
        meta, answer, request_error = stream_chat(args.base_url, case["user_input"], args.timeout, session_id)
        result = evaluate_case(case, meta, answer, request_error)
        results.append(result)
        print(
            f"  auto_pass={result['auto_pass']} "
            f"trace_id={result.get('trace_id') or '-'} "
            f"latency_ms={result.get('latency_ms') or '-'}"
        )

    report = summarize_results(results, started_at, args.base_url, dataset_path)

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = RESULTS_DIR / f"eval-report-{timestamp}.json"

    write_report(report, output_path)

    print("\nSummary")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
    print(f"\nReport written to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

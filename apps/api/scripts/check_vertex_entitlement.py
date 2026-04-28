from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict, List, Tuple

import google.auth
import requests
from google.auth.transport.requests import Request


def _build_headers(token: str, project: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "x-goog-user-project": project,
    }


def _vertex_host(region: str) -> str:
    if region == "global":
        return "aiplatform.googleapis.com"
    return f"{region}-aiplatform.googleapis.com"


def _get_token() -> str:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


def list_gemini_31_models(project: str, region: str, token: str) -> Dict[str, Any]:
    headers = _build_headers(token, project)
    host = _vertex_host(region)
    url = f"https://{host}/v1beta1/publishers/google/models"

    page_token = ""
    rows: List[str] = []
    status_code = 0

    while True:
        params = {"pageSize": 200}
        if page_token:
            params["pageToken"] = page_token

        response = requests.get(url, headers=headers, params=params, timeout=30)
        status_code = response.status_code

        if response.status_code != 200:
            return {
                "ok": False,
                "status_code": response.status_code,
                "error": (response.text or "")[:600],
                "models": [],
            }

        data = response.json()
        for model in data.get("publisherModels", []):
            name = model.get("name", "")
            if "gemini-3.1" in name.lower():
                rows.append(name)

        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    return {
        "ok": True,
        "status_code": status_code,
        "models": sorted(set(rows)),
    }


def runtime_generate_content(
    project: str,
    region: str,
    model_id: str,
    token: str,
    prompt: str,
) -> Dict[str, Any]:
    headers = {
        **_build_headers(token, project),
        "Content-Type": "application/json",
    }
    host = _vertex_host(region)
    url = (
        f"https://{host}/v1/projects/{project}/locations/{region}"
        f"/publishers/google/models/{model_id}:generateContent"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }

    started = time.perf_counter()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=40)
        elapsed = time.perf_counter() - started
        return {
            "model": model_id,
            "status_code": response.status_code,
            "ok": response.status_code == 200,
            "elapsed_sec": round(elapsed, 2),
            "snippet": (response.text or "")[:600],
        }
    except requests.exceptions.RequestException as exc:
        elapsed = time.perf_counter() - started
        return {
            "model": model_id,
            "status_code": None,
            "ok": False,
            "elapsed_sec": round(elapsed, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def stability_test(
    project: str,
    region: str,
    model_id: str,
    token: str,
    rounds: int,
) -> Dict[str, Any]:
    headers = {
        **_build_headers(token, project),
        "Content-Type": "application/json",
    }
    host = _vertex_host(region)
    url = (
        f"https://{host}/v1/projects/{project}/locations/{region}"
        f"/publishers/google/models/{model_id}:generateContent"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Return ONLY strict JSON: {\"sv\":\"domain.v1\",\"ok\":true}"}],
            }
        ]
    }

    counts: Dict[int, int] = {}
    timeout_count = 0
    cut_json_like = 0
    ok_count = 0
    fail_count = 0
    elapsed: List[float] = []

    for _ in range(rounds):
        started = time.perf_counter()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            elapsed.append(time.perf_counter() - started)
            counts[response.status_code] = counts.get(response.status_code, 0) + 1

            if response.status_code != 200:
                fail_count += 1
                continue

            text = ""
            try:
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0].get("text", "")
            except Exception:
                pass

            text = (text or "").strip()
            if not text:
                fail_count += 1
                continue

            try:
                json.loads(text)
                ok_count += 1
            except Exception:
                if text.startswith("{") and not text.endswith("}"):
                    cut_json_like += 1
                fail_count += 1
        except requests.exceptions.Timeout:
            timeout_count += 1
            fail_count += 1
        except requests.exceptions.RequestException:
            fail_count += 1
        except Exception:
            fail_count += 1

    avg = round(sum(elapsed) / len(elapsed), 2) if elapsed else 0.0
    p95 = round(sorted(elapsed)[int(0.95 * (len(elapsed) - 1))], 2) if elapsed else 0.0

    return {
        "model": model_id,
        "rounds": rounds,
        "ok": ok_count,
        "fail": fail_count,
        "timeout": timeout_count,
        "cut_json_like": cut_json_like,
        "status_counts": counts,
        "avg_sec": avg,
        "p95_sec": p95,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Vertex Gemini 3.1 entitlement and runtime stability.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--models", nargs="+", default=["gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview"])
    parser.add_argument("--stability-rounds", type=int, default=5)
    args = parser.parse_args()

    token = _get_token()

    report: Dict[str, Any] = {
        "project": args.project,
        "region": args.region,
    }

    report["publisher_list"] = list_gemini_31_models(args.project, args.region, token)

    runtime_checks = []
    stability_checks = []
    for model_id in args.models:
        runtime_checks.append(runtime_generate_content(args.project, args.region, model_id, token, "hello"))
        stability_checks.append(stability_test(args.project, args.region, model_id, token, args.stability_rounds))

    report["runtime"] = runtime_checks
    report["stability"] = stability_checks

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

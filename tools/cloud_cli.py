"""Automated GitHub CLI & Batch Factory Orchestrator for AEGIS Cloud Video Studio."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from export_secrets_bundle import DEFAULT_OUT, DEFAULT_VAULT, export_keys_bundle

STUDIO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = STUDIO_ROOT / "queue" / "jobs.json"
DOWNLOADS_DIR = STUDIO_ROOT / "output" / "downloaded"


def find_gh_exe() -> str | None:
    """Locate official GitHub CLI binary even when newly installed before PATH refresh."""
    hit = shutil.which("gh")
    if hit:
        return hit
    candidates = [
        Path(r"C:\Program Files\GitHub CLI\gh.exe"),
        Path(r"C:\Program Files (x86)\GitHub CLI\gh.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "bin" / "gh.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "GitHub CLI" / "gh.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _run(cmd: list[str], cwd: Path = STUDIO_ROOT, check: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=check, input=input_text, encoding="utf-8", errors="replace")


def get_status() -> dict[str, Any]:
    """Return gh installation status, authentication state, remote origin, and key bundle info."""
    gh = find_gh_exe()
    logged_in = False
    gh_user = ""
    auth_detail = ""
    if gh:
        p = _run([gh, "auth", "status"], check=False)
        auth_detail = (p.stdout + "\n" + p.stderr).strip()
        logged_in = p.returncode == 0
        for line in auth_detail.splitlines():
            if "Logged in to" in line and "account" in line:
                gh_user = line.split("account")[-1].strip().split()[0].strip("()")
                break

    remote_url = ""
    r = _run(["git", "remote", "get-url", "origin"], check=False)
    if r.returncode == 0:
        remote_url = r.stdout.strip()

    repo_slug = ""
    if gh and logged_in and remote_url:
        rv = _run([gh, "repo", "view", "--json", "nameWithOwner,isPrivate,url"], check=False)
        if rv.returncode == 0:
            try:
                repo_slug = json.loads(rv.stdout).get("nameWithOwner", "")
            except Exception:
                pass

    vault_keys = 0
    if DEFAULT_VAULT.exists():
        try:
            raw = json.loads(DEFAULT_VAULT.read_text(encoding="utf-8"))
            vault_keys = sum(1 for k in raw if k.get("apiKey") and k.get("enabled", True) and k.get("status") != "invalid")
        except Exception:
            pass

    return {
        "gh_installed": bool(gh),
        "gh_path": gh,
        "gh_logged_in": logged_in,
        "gh_user": gh_user,
        "remote_url": remote_url,
        "repo_slug": repo_slug,
        "vault_keys_ready": vault_keys,
        "bundle_exists": DEFAULT_OUT.exists(),
    }


def setup_and_push_private_repo(repo_name: str = "ci-worker-7c4e") -> dict[str, Any]:
    """Create private GitHub repo if needed, push clean commits, and sync AISTUDIO_KEYS_JSON Secret."""
    gh = find_gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI (gh) is not installed yet.")
    st = get_status()
    if not st["gh_logged_in"]:
        raise RuntimeError("GitHub CLI is not authenticated. Run 'gh auth login --web' or authorize via dashboard first.")

    bundle_info = export_keys_bundle(DEFAULT_VAULT, DEFAULT_OUT, copy_clipboard=False)
    _run(["git", "add", "."], check=True)
    diff_chk = _run(["git", "diff", "--cached", "--quiet"], check=False)
    if diff_chk.returncode != 0:
        _run(["git", "commit", "-m", "Update AEGIS Cloud Video Studio automation"], check=True)

    if not st["remote_url"]:
        res = _run([gh, "repo", "create", repo_name, "--private", "--source", ".", "--remote", "origin", "--push"], check=True)
        create_msg = res.stdout.strip() or "Created private repo and pushed main."
    else:
        _run([gh, "auth", "setup-git"], check=False)
        res = _run(["git", "push", "-u", "origin", "main"], check=True)
        create_msg = res.stdout.strip() or "Pushed main branch."

    secret_val = DEFAULT_OUT.read_text(encoding="utf-8")
    _run([gh, "secret", "set", "AISTUDIO_KEYS_JSON"], check=True, input_text=secret_val)
    return {
        "success": True,
        "message": create_msg,
        "secret_synced_keys": bundle_info["exported_count"],
        "status": get_status(),
    }


def sync_secrets() -> dict[str, Any]:
    gh = find_gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI (gh) is not installed.")
    bundle_info = export_keys_bundle(DEFAULT_VAULT, DEFAULT_OUT, copy_clipboard=False)
    secret_val = DEFAULT_OUT.read_text(encoding="utf-8")
    _run([gh, "secret", "set", "AISTUDIO_KEYS_JSON"], check=True, input_text=secret_val)
    return {"success": True, "synced_keys": bundle_info["exported_count"]}


def trigger_single_workflow(
    mode: str = "motion",
    topic_or_prompt: str = "",
    language: str = "العربية",
    scenes: int = 4,
    story_style: str = "storytelling",
    resolution: str = "1920x1080",
    fps: int = 30,
    video_url: str = "",
    subtitle_preset: str = "cinema",
    enable_dubbing: bool = False,
    voice: str = "Charon",
) -> dict[str, Any]:
    gh = find_gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI (gh) is not installed.")
    args = [
        gh, "workflow", "run", "cloud-video-studio.yml",
        "-f", f"mode={mode}",
        "-f", f"language={language}",
        "-f", f"voice={voice}",
    ]
    if mode == "motion":
        args.extend([
            "-f", f"topic_or_prompt={topic_or_prompt}",
            "-f", f"scenes={scenes}",
            "-f", f"story_style={story_style}",
            "-f", f"resolution={resolution}",
            "-f", f"fps={fps}",
        ])
    else:
        args.extend([
            "-f", f"video_url={video_url}",
            "-f", f"subtitle_preset={subtitle_preset}",
            "-f", f"enable_dubbing={'true' if enable_dubbing else 'false'}",
        ])
    _run(args, check=True)
    return {"success": True, "triggered": "cloud-video-studio.yml", "mode": mode}


def update_queue_and_trigger_batch(queue_patch: dict[str, Any], trigger_now: bool = True) -> dict[str, Any]:
    """Persist queue/jobs.json cleanly, push to GitHub, and launch parallel batch workflow."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue_patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    st = get_status()
    if st["remote_url"] and st["gh_logged_in"]:
        gh = find_gh_exe()
        if gh:
            _run([gh, "auth", "setup-git"], check=False)
        _run(["git", "add", "queue/jobs.json"], check=True)
        diff_chk = _run(["git", "diff", "--cached", "--quiet"], check=False)
        if diff_chk.returncode != 0:
            _run(["git", "commit", "-m", "Update automated video queue"], check=True)
            _run(["git", "push", "origin", "main"], check=True)
        if trigger_now and gh:
            _run([gh, "workflow", "run", "batch-factory.yml"], check=True)
    return {"success": True, "jobs_count": len(queue_patch.get("jobs") or []), "triggered_cloud": bool(st["remote_url"] and trigger_now)}


def list_runs(limit: int = 12) -> list[dict[str, Any]]:
    gh = find_gh_exe()
    if not gh:
        return []
    st = get_status()
    if not (st["gh_logged_in"] and st["remote_url"]):
        return []
    p = _run(
        [gh, "run", "list", "--limit", str(limit), "--json", "databaseId,workflowName,displayTitle,status,conclusion,createdAt,url"],
        check=False,
    )
    if p.returncode != 0:
        return []
    try:
        return json.loads(p.stdout)
    except Exception:
        return []


def download_run(run_id: str | int) -> dict[str, Any]:
    gh = find_gh_exe()
    if not gh:
        raise RuntimeError("GitHub CLI (gh) is not installed.")
    target_dir = DOWNLOADS_DIR / str(run_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    _run([gh, "run", "download", str(run_id), "-D", str(target_dir)], check=True)
    files = [str(p.relative_to(target_dir)) for p in target_dir.rglob("*") if p.is_file()]
    return {"success": True, "run_id": str(run_id), "folder": str(target_dir), "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS Cloud Studio GitHub Automation CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sp = sub.add_parser("setup")
    sp.add_argument("--repo-name", default="ci-worker-7c4e")
    sub.add_parser("sync-secrets")
    sub.add_parser("runs")
    dl = sub.add_parser("download")
    dl.add_argument("--run-id", required=True)
    args = parser.parse_args()

    if args.cmd == "status":
        print(json.dumps(get_status(), ensure_ascii=False, indent=2))
    elif args.cmd == "setup":
        print(json.dumps(setup_and_push_private_repo(args.repo_name), ensure_ascii=False, indent=2))
    elif args.cmd == "sync-secrets":
        print(json.dumps(sync_secrets(), ensure_ascii=False, indent=2))
    elif args.cmd == "runs":
        print(json.dumps(list_runs(), ensure_ascii=False, indent=2))
    elif args.cmd == "download":
        print(json.dumps(download_run(args.run_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

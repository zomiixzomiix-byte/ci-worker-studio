"""Zero-credential, TLS-encrypted uploader for @lokmane-cloud & Direct Google Drive Resumable Sessions.

Designed for stateless CI workers (GitHub Actions):
- Holds ZERO Google OAuth credentials (no client_id, client_secret, refresh_token).
- Authenticates only with a scoped @lokmane-cloud ingest account (ideally `write_only=True`
  locked to a single destination folder via `allowed_folders`).
- Requests a single-file Google Drive resumable upload `session_uri` via
  `POST /api/files/delegated-upload-init`, masks every token/URI via `::add-mask::`, and
  streams 16 MiB chunks directly to Google Drive over TLS — bypassing both user home internet
  and Cloudflare 100 MB request limits.
- Falls back transparently to `/api/files/upload-init` + `/api/files/upload-chunk` (16 MiB slices)
  if the server has not yet enabled `/delegated-upload-init` or uses local server storage.
"""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CHUNK_SIZE_BYTES = 16 * 1024 * 1024  # 16 MiB (exact 64 * 256 KiB multiple for Google Drive)

_SERIES_DIR_RULES: tuple[tuple[str, str], ...] = (
    (r"^A1_1_", "Core_01_A1_1"),
    (r"^A1_2_", "Core_02_A1_2"),
    (r"^A2_1_", "Core_03_A2_1"),
    (r"^A2_2_", "Core_04_A2_2"),
    (r"^B1_1_", "Core_05_B1_1"),
    (r"^B1_2_", "Core_06_B1_2"),
    (r"^BEW_", "Beruf_01_Bewerbungstraining"),
    (r"^TOUR_A1_", "Beruf_02_Tourismus_A1"),
    (r"^TOUR_A2_", "Beruf_03_Tourismus_A2"),
    (r"^PFL_A2_", "Beruf_04_Pflege_A2"),
    (r"^PFL_B1_", "Beruf_05_Pflege_B1"),
    (r"^TEL_", "Beruf_06_Telefontraining"),
    (r"^MED_", "Beruf_07_Medizin_B2_C1"),
    (r"^BT_", "Trainer_01_Berufstrainer"),
    (r"^IT_", "Trainer_02_Intensivtrainer"),
    (r"^TT_", "Trainer_03_Testtrainer"),
    (r"^VOK_", "Trainer_04_Vokabeltaschenbuch"),
)


def _mask(secret: str) -> None:
    """Emit GitHub Actions secret mask for dynamic tokens and session URIs."""
    if os.environ.get("GITHUB_ACTIONS") == "true" and secret and len(secret.strip()) >= 4:
        for line in secret.strip().splitlines():
            if len(line) >= 4:
                print(f"::add-mask::{line}", flush=True)


def _sanitize_text(text: str) -> str:
    """Strip query tokens or upload session IDs before logging any diagnostic."""
    redacted = re.sub(r"(upload_id|access_token|token)=[^&\s\"']+", r"\1=[REDACTED]", str(text))
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", "Bearer [REDACTED]", redacted, flags=re.IGNORECASE)
    return redacted


def enforce_secure_url(base_url: str) -> str:
    """Require HTTPS for any non-loopback endpoint to guarantee transport security."""
    clean = (base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme == "https" and parsed.netloc:
        return clean
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host in ("127.0.0.1", "localhost", "::1"):
        return clean
    raise ValueError("LC_BASE_URL must use https:// (plaintext http:// is rejected)")


def unit_from_release_tag(tag_name: str) -> str:
    """Recover canonical unit ID (e.g. A2_1_L07) from `pkg-<slug>-<runid>-<hex>` tags."""
    t = tag_name.strip()
    m = re.match(r"^pkg-([a-z0-9-]+?)-(\d{7,})-[0-9a-f]{6,}$", t, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper().replace("-", "_")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", t)


def unit_folder_parts(unit_id: str, root_folder: str = "") -> list[str]:
    """Return clean folder hierarchy parts inside Drive for a unit."""
    uid = unit_id.strip()
    parts: list[str] = []
    for seg in re.split(r"[\\/]+", (root_folder or "").strip()):
        if seg and seg not in (".", ".."):
            parts.append(seg)
    series_dir = "Other_Courses"
    for pat, label in _SERIES_DIR_RULES:
        if re.match(pat, uid, flags=re.IGNORECASE):
            series_dir = label
            break
    parts.append(series_dir)
    parts.append(uid)
    return parts


def _guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    overrides = {
        ".mp4": "video/mp4",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".pdf": "application/pdf",
        ".zip": "application/zip",
        ".ass": "text/plain",
        ".srt": "text/plain",
        ".txt": "text/plain",
    }
    return overrides.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


class LokmaneCloudClient:
    """Stdlib HTTPS client for @lokmane-cloud delegated and fallback chunked uploads."""

    def __init__(self, base_url: str, username: str, password: str, drive_id: int | None = None) -> None:
        self.base_url = enforce_secure_url(base_url)
        self.username = username.strip()
        self.password = password
        self.requested_drive_id = drive_id
        self.token = ""
        self.ssl_ctx = ssl.create_default_context()
        self._folder_cache: dict[tuple[int, str, str], str] = {}
        _mask(password)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> tuple[int, dict[str, Any]]:
        url = f"{self.base_url}{path}"
        hdrs = {"Accept": "application/json", "User-Agent": "AegisCloudUploader/1.0"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        if headers:
            hdrs.update(headers)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            hdrs["Content-Type"] = "application/json; charset=utf-8"

        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_ctx) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"detail": _sanitize_text(raw[:400])}
            return err.code, parsed

    def login(self) -> None:
        last_err = ""
        for attempt in range(4):
            try:
                status, data = self._request_json(
                    "POST",
                    "/api/auth/login",
                    {"username": self.username, "password": self.password},
                    timeout=30,
                )
                if status == 200 and data.get("token"):
                    self.token = str(data["token"])
                    _mask(self.token)
                    return
                last_err = f"HTTP {status}: {_sanitize_text(data.get('detail', data))}"
                if status in (401, 403):
                    break
            except Exception as exc:
                last_err = _sanitize_text(str(exc))
            time.sleep(min(10, 2**attempt))
        raise RuntimeError(f"Lokmane Cloud login failed ({last_err})")

    def select_drive(self) -> dict[str, Any]:
        status, data = self._request_json("GET", "/api/drives", timeout=30)
        if status != 200:
            raise RuntimeError(f"Drive discovery failed (HTTP {status})")
        drives = data.get("drives") or []
        if not drives:
            raise RuntimeError("No accessible drives configured for this account")
        if self.requested_drive_id is not None:
            for d in drives:
                if int(d["id"]) == int(self.requested_drive_id):
                    return d
            raise RuntimeError(f"Requested drive ID {self.requested_drive_id} is not accessible")
        for d in drives:
            if d.get("provider") == "gdrive":
                return d
        return drives[0]

    def ensure_folder_path(self, drive_id: int, parts: list[str]) -> str:
        parent_id = "root"
        for part in parts:
            key = (drive_id, parent_id, part)
            if key in self._folder_cache:
                parent_id = self._folder_cache[key]
                continue

            status, data = self._request_json(
                "POST",
                "/api/files/ensure-folder",
                {"account_id": drive_id, "parent_id": parent_id, "name": part},
                timeout=45,
            )
            if status == 404:
                # Backward-compatible fallback for servers without /ensure-folder
                st_l, list_data = self._request_json(
                    "GET",
                    f"/api/files/list?account_id={drive_id}&folder_id={urllib.parse.quote(parent_id, safe='')}",
                    timeout=45,
                )
                matched_id = ""
                if st_l == 200:
                    for it in list_data.get("files") or []:
                        if it.get("is_folder") and it.get("name") == part:
                            matched_id = str(it["id"])
                            break
                if matched_id:
                    folder_id = matched_id
                else:
                    st_m, mk_data = self._request_json(
                        "POST",
                        "/api/files/mkdir",
                        {"account_id": drive_id, "parent_id": parent_id, "name": part},
                        timeout=45,
                    )
                    if st_m not in (200, 201) or not mk_data.get("item"):
                        raise RuntimeError(f"Folder create failed for {part} (HTTP {st_m})")
                    folder_id = str(mk_data["item"]["id"])
            elif status not in (200, 201) or not data.get("item"):
                raise RuntimeError(f"Ensure folder failed for {part} (HTTP {status}: {_sanitize_text(data)})")
            else:
                folder_id = str(data["item"]["id"])

            self._folder_cache[key] = folder_id
            parent_id = folder_id
        return parent_id

    def _open_direct_connection(self, parsed: urllib.parse.ParseResult) -> http.client.HTTPConnection:
        host = parsed.hostname or ""
        port = parsed.port
        if parsed.scheme == "https":
            return http.client.HTTPSConnection(host, port or 443, timeout=180, context=self.ssl_ctx)
        if host in ("127.0.0.1", "localhost", "::1"):
            return http.client.HTTPConnection(host, port or 80, timeout=180)
        raise ValueError("Refusing insecure non-HTTPS upload session URI")

    def _query_gdrive_offset(self, session_uri: str, total_size: int) -> tuple[int, dict[str, Any] | None]:
        parsed = urllib.parse.urlparse(session_uri)
        req_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        conn = self._open_direct_connection(parsed)
        try:
            conn.request(
                "PUT",
                req_path,
                body=b"",
                headers={"Content-Length": "0", "Content-Range": f"bytes */{total_size}"},
            )
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status in (200, 201):
                meta = json.loads(body) if body.strip() else {"size": total_size}
                return total_size, meta
            rng = resp.getheader("Range", "")
            m = re.match(r"bytes=0-(\d+)", rng)
            return (int(m.group(1)) + 1 if m else 0), None
        finally:
            conn.close()

    def _put_direct_gdrive(self, session_uri: str, file_path: Path, total_size: int) -> dict[str, Any]:
        _mask(session_uri)
        parsed = urllib.parse.urlparse(session_uri)
        req_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        if total_size == 0:
            conn = self._open_direct_connection(parsed)
            try:
                conn.request(
                    "PUT",
                    req_path,
                    body=b"",
                    headers={"Content-Length": "0", "Content-Range": "bytes */0"},
                )
                resp = conn.getresponse()
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status not in (200, 201):
                    raise RuntimeError(f"Empty upload failed (HTTP {resp.status})")
                return json.loads(body) if body.strip() else {"name": file_path.name, "size": 0}
            finally:
                conn.close()

        offset = 0
        result: dict[str, Any] | None = None
        with file_path.open("rb") as fh:
            while offset < total_size:
                fh.seek(offset)
                chunk = fh.read(CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                end_byte = offset + len(chunk) - 1
                hdrs = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end_byte}/{total_size}",
                }
                sent_ok = False
                for attempt in range(5):
                    conn = self._open_direct_connection(parsed)
                    try:
                        conn.request("PUT", req_path, body=chunk, headers=hdrs)
                        resp = conn.getresponse()
                        body = resp.read().decode("utf-8", errors="replace")
                        if resp.status in (200, 201):
                            result = json.loads(body) if body.strip() else {"name": file_path.name, "size": total_size}
                            offset = total_size
                            sent_ok = True
                            break
                        if resp.status == 308:
                            rng = resp.getheader("Range", "")
                            m = re.match(r"bytes=0-(\d+)", rng)
                            offset = int(m.group(1)) + 1 if m else (offset + len(chunk))
                            sent_ok = True
                            break
                        if resp.status in (429, 500, 502, 503, 504):
                            raise RuntimeError(f"Transient Drive HTTP {resp.status}")
                        raise RuntimeError(f"Direct Drive upload HTTP {resp.status}: {_sanitize_text(body[:300])}")
                    except (http.client.HTTPException, OSError, TimeoutError, RuntimeError) as exc:
                        if "Direct Drive upload HTTP" in str(exc):
                            raise
                        if attempt >= 4:
                            raise
                        time.sleep(min(20, 2**attempt))
                        try:
                            synced_off, meta = self._query_gdrive_offset(session_uri, total_size)
                            if meta is not None:
                                result = meta
                                offset = total_size
                                sent_ok = True
                                break
                            if synced_off > offset:
                                offset = synced_off
                                sent_ok = True
                                break
                        except Exception:
                            pass
                    finally:
                        conn.close()
                if not sent_ok:
                    raise RuntimeError(f"Failed direct chunk at offset {offset} for {file_path.name}")

        if not result:
            raise RuntimeError(f"Direct Drive upload finished without metadata for {file_path.name}")
        return result

    def _post_chunk_multipart(
        self,
        upload_id: str,
        offset: int,
        is_final: bool,
        filename: str,
        chunk: bytes,
    ) -> dict[str, Any]:
        boundary = f"----AegisBoundary{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for name, val in (("upload_id", upload_id), ("offset", str(offset)), ("is_final", "1" if is_final else "0")):
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{val}\r\n"
                ).encode("utf-8")
            )
        safe_fn = filename.replace('"', "_")
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chunk"; filename="{safe_fn}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode("utf-8")
        )
        parts.append(chunk)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)

        url = f"{self.base_url}/api/files/upload-chunk"
        hdrs = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }
        last_err = ""
        for attempt in range(4):
            req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=180, context=self.ssl_ctx) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    return json.loads(raw)
            except urllib.error.HTTPError as err:
                raw = err.read().decode("utf-8", errors="replace")
                last_err = f"HTTP {err.code}: {_sanitize_text(raw[:300])}"
                if err.code not in (429, 500, 502, 503, 504):
                    break
            except Exception as exc:
                last_err = _sanitize_text(str(exc))
            time.sleep(min(20, 2**attempt))
        raise RuntimeError(f"Chunk upload failed at offset {offset} ({last_err})")

    def _upload_via_server_chunks(
        self,
        drive_id: int,
        parent_id: str,
        file_path: Path,
        mime_type: str,
        total_size: int,
        existing_upload_id: str = "",
    ) -> dict[str, Any]:
        upload_id = existing_upload_id
        if not upload_id:
            status, data = self._request_json(
                "POST",
                "/api/files/upload-init",
                {
                    "account_id": drive_id,
                    "parent_id": parent_id,
                    "filename": file_path.name,
                    "mime_type": mime_type,
                    "total_size": total_size,
                },
                timeout=45,
            )
            if status != 200 or not data.get("upload_id"):
                raise RuntimeError(f"Chunk upload init failed (HTTP {status}: {_sanitize_text(data)})")
            upload_id = str(data["upload_id"])

        if total_size == 0:
            res = self._post_chunk_multipart(upload_id, 0, True, file_path.name, b"")
            if not res.get("done") or not res.get("item"):
                raise RuntimeError(f"Empty chunk upload did not complete for {file_path.name}")
            return dict(res["item"])

        offset = 0
        last_res: dict[str, Any] = {}
        with file_path.open("rb") as fh:
            while offset < total_size:
                chunk = fh.read(CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                is_final = (offset + len(chunk)) >= total_size
                last_res = self._post_chunk_multipart(upload_id, offset, is_final, file_path.name, chunk)
                offset += len(chunk)

        if not last_res.get("done") or not last_res.get("item"):
            raise RuntimeError(f"Server chunk upload incomplete for {file_path.name}")
        return dict(last_res["item"])

    def upload_file(self, drive_id: int, parent_id: str, file_path: Path) -> tuple[dict[str, Any], str]:
        """Upload one local file using delegated direct Google Drive session with safe fallback."""
        total_size = file_path.stat().st_size
        mime_type = _guess_mime(file_path)

        status, data = self._request_json(
            "POST",
            "/api/files/delegated-upload-init",
            {
                "account_id": drive_id,
                "parent_id": parent_id,
                "filename": file_path.name,
                "mime_type": mime_type,
                "total_size": total_size,
            },
            timeout=45,
        )
        if status == 200 and data.get("mode") == "direct_gdrive" and data.get("session_uri"):
            item = self._put_direct_gdrive(str(data["session_uri"]), file_path, total_size)
            mode = "direct_gdrive"
        elif status == 200 and data.get("mode") == "local_chunked" and data.get("upload_id"):
            item = self._upload_via_server_chunks(
                drive_id, parent_id, file_path, mime_type, total_size, existing_upload_id=str(data["upload_id"])
            )
            mode = "local_chunked"
        elif status == 404:
            item = self._upload_via_server_chunks(drive_id, parent_id, file_path, mime_type, total_size)
            mode = "server_chunked_fallback"
        else:
            raise RuntimeError(f"Delegated upload init failed (HTTP {status}: {_sanitize_text(data)})")

        reported_size = item.get("size")
        if reported_size is not None and int(reported_size) != total_size:
            raise RuntimeError(
                f"Byte verification failed for {file_path.name}: expected={total_size} got={reported_size}"
            )
        return {
            "name": file_path.name,
            "size": total_size,
            "id": str(item.get("id", "")),
            "mode": mode,
        }, mode


def upload_directory(
    client: LokmaneCloudClient,
    unit_id: str,
    src_dir: Path,
    root_folder: str = "",
    summary_out: Path | None = None,
) -> dict[str, Any]:
    files = sorted(p for p in src_dir.iterdir() if p.is_file())
    if not files:
        raise RuntimeError(f"No output files found in {src_dir}")

    client.login()
    drive = client.select_drive()
    drive_id = int(drive["id"])
    folder_parts = unit_folder_parts(unit_id, root_folder=root_folder)
    target_parent_id = client.ensure_folder_path(drive_id, folder_parts)

    uploaded: list[dict[str, Any]] = []
    modes: set[str] = set()
    total_bytes = 0
    for fpath in files:
        t0 = time.monotonic()
        meta, mode = client.upload_file(drive_id, target_parent_id, fpath)
        dt = max(0.01, time.monotonic() - t0)
        mbps = (meta["size"] / (1024 * 1024)) / dt
        uploaded.append(meta)
        modes.add(mode)
        total_bytes += meta["size"]
        print(f"LC_FILE_OK: unit={unit_id} file={meta['name']} bytes={meta['size']} mode={mode} speed={mbps:.2f}MiB/s", flush=True)

    summary = {
        "unit_id": unit_id,
        "folder": "/".join(folder_parts),
        "file_count": len(uploaded),
        "total_bytes": total_bytes,
        "modes": sorted(modes),
        "files": uploaded,
    }
    if summary_out is not None:
        summary_out.parent.mkdir(parents=True, exist_ok=True)
        summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(
        f"LC_UPLOAD_OK: unit={unit_id} files={len(uploaded)} bytes={total_bytes} modes={','.join(sorted(modes))}",
        flush=True,
    )
    return summary


def _gh_json(args: list[str]) -> Any:
    res = subprocess.run(
        ["gh", *args],
        text=True,
        capture_output=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(res.stdout) if res.stdout.strip() else []


def migrate_releases(
    client: LokmaneCloudClient,
    repo: str,
    tag_prefix: str = "pkg-",
    root_folder: str = "",
    delete_after_verify: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    client.login()
    drive = client.select_drive()
    drive_id = int(drive["id"])

    releases = _gh_json(["api", f"repos/{repo}/releases?per_page=100", "--paginate"])
    candidates = [
        r for r in releases
        if isinstance(r, dict) and str(r.get("tag_name", "")).startswith(tag_prefix) and not r.get("draft")
    ]
    candidates.sort(key=lambda r: str(r.get("tag_name", "")))
    if limit > 0:
        candidates = candidates[:limit]

    migrated: list[dict[str, Any]] = []
    for rel in candidates:
        tag = str(rel["tag_name"])
        assets = rel.get("assets") or []
        if not assets:
            continue
        unit_id = unit_from_release_tag(tag)
        folder_parts = unit_folder_parts(unit_id, root_folder=root_folder)
        target_parent_id = client.ensure_folder_path(drive_id, folder_parts)

        tmp_dir = Path(tempfile.mkdtemp(prefix=f"lc_mig_{unit_id}_"))
        try:
            subprocess.run(
                ["gh", "release", "download", tag, "--repo", repo, "--dir", str(tmp_dir)],
                check=True,
                text=True,
                capture_output=True,
            )
            verified_count = 0
            rel_bytes = 0
            for asset in assets:
                name = str(asset["name"])
                exp_size = int(asset["size"])
                local_file = tmp_dir / name
                if not local_file.exists() or local_file.stat().st_size != exp_size:
                    raise RuntimeError(f"Asset verification failed locally for {tag}/{name}")
                meta, mode = client.upload_file(drive_id, target_parent_id, local_file)
                if meta["size"] != exp_size:
                    raise RuntimeError(f"Remote byte mismatch for {tag}/{name}")
                verified_count += 1
                rel_bytes += exp_size

            if verified_count != len(assets):
                raise RuntimeError(f"Count mismatch on {tag}: {verified_count} != {len(assets)}")

            deleted = False
            if delete_after_verify:
                subprocess.run(
                    ["gh", "release", "delete", tag, "--repo", repo, "--cleanup-tag", "--yes"],
                    check=True,
                    text=True,
                    capture_output=True,
                )
                deleted = True

            migrated.append(
                {"tag": tag, "unit_id": unit_id, "files": verified_count, "bytes": rel_bytes, "deleted": deleted}
            )
            print(f"LC_MIGRATE_OK: tag={tag} unit={unit_id} files={verified_count} bytes={rel_bytes} deleted={deleted}", flush=True)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"migrated_count": len(migrated), "migrated": migrated}


def _client_from_env(drive_id: int | None) -> LokmaneCloudClient:
    base_url = os.environ.get("LC_BASE_URL", "").strip()
    username = os.environ.get("LC_USERNAME", "").strip()
    password = os.environ.get("LC_PASSWORD", "")
    if not base_url or not username or not password:
        raise SystemExit("Missing LC_BASE_URL, LC_USERNAME, or LC_PASSWORD environment variables")
    env_drive = os.environ.get("LC_DRIVE_ID", "").strip()
    eff_drive = drive_id if drive_id is not None else (int(env_drive) if env_drive else None)
    return LokmaneCloudClient(base_url=base_url, username=username, password=password, drive_id=eff_drive)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Secure Zero-Credential @lokmane-cloud Direct Uploader")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upload-dir", help="Upload all deliverables in a directory to @lokmane-cloud")
    p_up.add_argument("--unit", required=True)
    p_up.add_argument("--dir", required=True, type=Path)
    p_up.add_argument("--drive-id", type=int, default=None)
    p_up.add_argument("--root-folder", default=os.environ.get("LC_ROOT_FOLDER", ""))
    p_up.add_argument("--summary-out", type=Path, default=None)

    p_mig = sub.add_parser("migrate-releases", help="Transfer public GitHub Releases into Drive via @lokmane-cloud")
    p_mig.add_argument("--repo", required=True)
    p_mig.add_argument("--prefix", default="pkg-")
    p_mig.add_argument("--drive-id", type=int, default=None)
    p_mig.add_argument("--root-folder", default=os.environ.get("LC_ROOT_FOLDER", ""))
    p_mig.add_argument("--delete-after-verify", action="store_true")
    p_mig.add_argument("--limit", type=int, default=0)
    p_mig.add_argument("--summary-out", type=Path, default=None)

    args = parser.parse_args(argv)
    client = _client_from_env(args.drive_id)

    if args.cmd == "upload-dir":
        upload_directory(client, args.unit, args.dir, root_folder=args.root_folder, summary_out=args.summary_out)
        return 0

    if args.cmd == "migrate-releases":
        res = migrate_releases(
            client,
            repo=args.repo,
            tag_prefix=args.prefix,
            root_folder=args.root_folder,
            delete_after_verify=args.delete_after_verify,
            limit=args.limit,
        )
        if args.summary_out:
            args.summary_out.parent.mkdir(parents=True, exist_ok=True)
            args.summary_out.write_text(json.dumps(res, indent=2), encoding="utf-8")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Read desktop application code into reclaimable page cache once per login boot."""
import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import time


def application_files():
    home = Path.home()
    names = [
        "/usr/lib/libnvidia-eglcore.so.*", "/usr/lib/libnvidia-glcore.so.*",
        "/usr/lib/libnvidia-glsi.so.*", "/usr/lib/libnvidia-gpucomp.so.*",
        "/usr/lib/libEGL_nvidia.so.*", "/usr/lib/libGLX_nvidia.so.*",
        "/opt/chromium.org/thorium/thorium", "/opt/chromium.org/thorium/icudtl.dat",
        "/opt/chromium.org/thorium/resources.pak", "/opt/chromium.org/thorium/v8_context_snapshot.bin",
        str(home / ".local/bin/AyuGram"),
    ]
    for command in ("AyuGram", "ayugram-desktop", "thorium-browser"):
        binary = shutil.which(command)
        if binary:
            names.append(binary)
    paths = []
    seen = set()
    for name in names:
        for value in sorted(glob.glob(name)):
            path = Path(value).resolve()
            if path.is_file() and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, action="append", help="Use just the specified test files")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-mib", type=int, default=1024)
    parser.add_argument("--state-file", type=Path, default=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "hyprstack/app-cache.json")
    args = parser.parse_args()
    if not 1 <= args.max_mib <= 2048:
        parser.error("--max-mib must be between 1 and 2048")
    paths = [p.resolve() for p in args.file] if args.file else application_files()
    files = [{"path": str(p), "size": p.stat().st_size, "mtimeNs": p.stat().st_mtime_ns} for p in paths]
    if args.list:
        print(json.dumps({"files": files, "totalMiB": round(sum(f["size"] for f in files) / 2**20, 1)}))
        return
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    try:
        previous = json.loads(args.state_file.read_text())
    except (OSError, ValueError):
        previous = {}
    if not args.force and previous.get("boot") == boot and previous.get("fingerprint") == fingerprint:
        print("Application code is already warmed for this boot")
        return
    start = time.monotonic()
    remaining = args.max_mib * 2**20
    results = []
    for item in files:
        if remaining <= 0:
            break
        size = min(item["size"], remaining)
        read = 0
        try:
            with open(item["path"], "rb", buffering=0) as source:
                os.posix_fadvise(source.fileno(), 0, size, os.POSIX_FADV_SEQUENTIAL)
                while read < size:
                    data = source.read(min(2**20, size - read))
                    if not data:
                        break
                    read += len(data)
                    time.sleep(.001)
                os.posix_fadvise(source.fileno(), 0, size, os.POSIX_FADV_NORMAL)
            results.append({"path": item["path"], "bytes": read})
        except OSError as error:
            results.append({"path": item["path"], "error": str(error)})
        remaining -= read
    report = {"boot": boot, "fingerprint": fingerprint, "seconds": round(time.monotonic() - start, 3),
              "readMiB": round(sum(r.get("bytes", 0) for r in results) / 2**20, 1), "files": results}
    args.state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.state_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(args.state_file)
    print(json.dumps(report))


if __name__ == "__main__":
    main()

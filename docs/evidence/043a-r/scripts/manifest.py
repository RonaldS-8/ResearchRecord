"""Manifest of raw result files: whole-file hash, result digest, recorded commit and flags."""
from hashlib import sha256
import json, os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
print("| 文件 | 字节 | 写入时间 | 记录的提交 | 工作区干净 | result 校验值 | 整个文件 SHA-256 前 16 位 |")
print("| --- | ---: | --- | --- | --- | --- | --- |")
for path in sorted(root.rglob("*.json")):
    raw = path.read_bytes()
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
    name = path.relative_to(root).as_posix()
    if not raw.strip():
        print(f"| `{name}` | 0 | {stamp} | 空文件 | – | – | – |")
        continue
    doc = json.loads(raw.decode("utf-8"))
    digest = sha256(json.dumps(doc["result"], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    commit = doc.get("commit", "")[:7] or "–"
    clean = {False: "是", True: "否"}.get(doc.get("uncommitted_changes"), "–")
    print(f"| `{name}` | {len(raw)} | {stamp} | `{commit}` | {clean} | `{digest}` | `{sha256(raw).hexdigest()[:16]}` |")

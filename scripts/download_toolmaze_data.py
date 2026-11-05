
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import HfApi, hf_hub_download

REPO = "dongsheng/ToolMaze"
MIRROR = "https://hf-mirror.com"
DEST = "./benchmarks/ToolMaze/data"

api = HfApi(endpoint=MIRROR)
info = api.dataset_info(REPO)
files = [f.rfilename for f in info.siblings]

print(f"发现 {len(files)} 个文件", flush=True)


def download(filename: str) -> str:
    return hf_hub_download(
        repo_id=REPO,
        repo_type="dataset",
        filename=filename,
        endpoint=MIRROR,
        local_dir=DEST,
        etag_timeout=30,
    )


failed = []
with ThreadPoolExecutor(max_workers=2) as pool:
    jobs = {pool.submit(download, f): f for f in files}

    for i, job in enumerate(as_completed(jobs), 1):
        try:
            job.result()
        except Exception as exc:
            failed.append((jobs[job], str(exc)))

        if i % 100 == 0:
            print(f"已处理 {i}/{len(files)}", flush=True)

print(f"完成，失败 {len(failed)} 个文件")
for filename, error in failed[:10]:
    print(filename, error)

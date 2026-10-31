"""Observed KV budgets from prior local launches; no inference or network requests."""
from pathlib import Path
import re

def observed_cache(repo,files,context,dtype,source_path=None):
    directory=Path.home()/'.unsloth/studio/logs/llama-server'
    if not directory.is_dir() or not repo or not files: return None
    for path in sorted(directory.glob('*.log'),key=lambda p:p.stat().st_mtime,reverse=True)[:12]:
        with path.open(errors='replace') as stream: text=stream.read(256*1024)
        if 'models--'+repo.replace('/','--') not in text or Path(files[0]).name not in text: continue
        if source_path and source_path not in text: continue
        if not re.search(r'\bn_ctx\s*=\s*'+str(int(context))+r'\b',text): continue
        types=re.findall(r'K \(([^)]+)\).*V \(([^)]+)\)',text)
        if not types or any(k!=dtype or v!=dtype for k,v in types): continue
        buffers=re.findall(r'KV buffer size\s*=\s*([0-9.]+) MiB',text)
        if buffers: return sum(map(float,buffers))/1024
    return None

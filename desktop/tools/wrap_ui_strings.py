"""Idempotent mechanical migration of Russian QML literals to runtime translation bindings."""
from pathlib import Path
import re

directory=Path(__file__).parents[1]/'spark_link/qml'
for filename,owner in [('Main.qml','window'),('ClusterScene.qml','scene'),('MemoryPage.qml','memory')]:
    path=directory/filename
    text=path.read_text()
    def replace(match):
        value=match.group()
        if not re.search('[А-Яа-яЁё]',value): return value
        if re.search(r'\bt\(\s*$',text[max(0,match.start()-30):match.start()]): return value
        return owner+'.t('+value+')'
    result=re.sub(r'"(?:\\.|[^"\\])*"',replace,text)
    if result!=text: path.write_text(result)

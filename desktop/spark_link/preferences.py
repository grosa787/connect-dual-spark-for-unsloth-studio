"""View-only preferences, deliberately independent of networking and model settings."""
from .state import CONFIG, read_json, write_json

LANGUAGES=('ru','en','de','es')
NODE_IDS=('head','worker2','worker3')

def port_anchor(port, vertical):
    if type(port) is not int or port not in (0,1): raise ValueError('Unknown physical port')
    return (11,49.75+28+port*24,92) if vertical else (28+port*24,-11,92)

class ViewPreferences:
    def __init__(self,path=None):
        self.path=path or CONFIG/'preferences.json'
        raw=read_json(self.path,{})
        if not isinstance(raw,dict): raw={}
        self.language=raw.get('language') if raw.get('language') in LANGUAGES else 'ru'
        self.startup=raw.get('startup',True) is True
        orientations=raw.get('orientations',{})
        self.orientations={node: orientations.get(node) is True for node in NODE_IDS} if isinstance(orientations,dict) else {}
    def vertical(self,node): return self.orientations.get(node,False)
    def save(self): write_json(self.path,{'language':self.language,'orientations':self.orientations,'startup':self.startup})
    def set_startup(self,enabled):
        from pathlib import Path
        import re
        self.startup=bool(enabled)
        target=CONFIG.parent/'autostart/spark-link.desktop'
        menu=Path.home()/'.local/share/applications/spark-link.desktop'
        if enabled and menu.is_file():
            target.parent.mkdir(parents=True,exist_ok=True)
            text=re.sub(r'^Exec=(.*)$',r'Exec=\1 --background',menu.read_text(),flags=re.MULTILINE)
            target.write_text(text+'X-GNOME-Autostart-enabled=true\n')
        elif not enabled and target.is_file(): target.unlink()
        self.save()
    def set_language(self,language):
        if language not in LANGUAGES: raise ValueError('Unsupported language')
        self.language=language
        self.save()
    def set_orientation(self,node,vertical):
        if node not in NODE_IDS or type(vertical) is not bool: raise ValueError('Unknown device orientation')
        self.orientations[node]=vertical
        self.save()

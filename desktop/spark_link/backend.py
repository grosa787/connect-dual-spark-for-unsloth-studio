import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from .inventory import scan, discover_worker
from .state import CONFIG, STATE, read_json, write_json
from .topology import default_topology, validate_topology, select_port, resize_topology, physical_links_ready
from .preferences import ViewPreferences, LANGUAGES, port_anchor
from .translations import translate
from . import __version__


class Backend(QObject):
    changed = Signal()
    busyChanged = Signal()
    logChanged = Signal()
    messageChanged = Signal()
    languageChanged = Signal()
    viewChanged = Signal()
    delivered = Signal(object)

    def __init__(self):
        super().__init__()
        self.preferences = ViewPreferences()
        self._topology = read_json(CONFIG / 'topology.json', default_topology())
        try: validate_topology(self._topology, require_targets=False)
        except ValueError: self._topology = default_topology()
        self._nodes = [{**n, 'online': False, 'error': 'Проверяем доступность…'} for n in self._topology['nodes']]
        self._busy = False
        self._scanning = False
        self._revision = 0
        self._infer_ports = not (CONFIG / 'topology.json').exists()
        self._logs = ''
        self._message = ''
        self._user_draft=bool(read_json(CONFIG/'draft-marker.json',False))
        from .planner_backend import ModelPlanner
        from .device_backend import DeviceManager
        self.planner=ModelPlanner(self)
        self.devices=DeviceManager(self)
        self.delivered.connect(self._receive)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(15000)
        QTimer.singleShot(150, self.refresh)

    @Property('QVariantList', notify=changed)
    def nodes(self): return [{**node,'name':self.translate(node['name'])} for node in self._nodes]

    @Property('QVariantMap', notify=changed)
    def topology(self):
        result=copy.deepcopy(self._topology)
        for node in result['nodes']: node['name']=self.translate(node['name'])
        return result

    @Property(str, notify=languageChanged)
    def language(self): return self.preferences.language

    @Property('QVariantList', constant=True)
    def languageNames(self): return ['Русский','English','Deutsch','Español']

    @Property(str, constant=True)
    def version(self): return __version__
    @Property(bool,notify=viewChanged)
    def startupEnabled(self): return self.preferences.startup
    @Slot(bool)
    def setStartup(self,enabled):
        self.preferences.set_startup(enabled)
        self.viewChanged.emit()

    @Property('QVariantList', notify=viewChanged)
    def orientations(self): return [self.preferences.vertical(node['id']) for node in self._topology['nodes']]

    @Slot(str, result=str)
    def translate(self, source): return translate(source,self.preferences.language)

    @Slot(str)
    def setLanguage(self, language):
        if language not in LANGUAGES or language==self.preferences.language: return
        self.preferences.set_language(language)
        self.languageChanged.emit()
        self.changed.emit()
        self.messageChanged.emit()

    @Slot(int,bool)
    def setOrientation(self,index,vertical):
        if not 0 <= index < len(self._topology['nodes']): return
        node=self._topology['nodes'][index]['id']
        if self.preferences.vertical(node)==vertical: return
        self.preferences.set_orientation(node,vertical)
        self.viewChanged.emit()

    @Slot(int,bool,result='QVariantList')
    def portAnchor(self,port,vertical): return list(port_anchor(port,vertical))

    @Property(bool, notify=busyChanged)
    def busy(self): return self._busy or self.devices._auth_busy

    @Property(str, notify=logChanged)
    def logs(self): return self._logs

    @Property(str, notify=messageChanged)
    def message(self): return self.translate(self._message)

    @Property(str, notify=changed)
    def clusterText(self):
        online = sum(n.get('online', False) for n in self._nodes)
        try:
            from .jobs import plan_matches
            from .topology import compile_topology
            plans = compile_topology(self._topology)
            if online==len(self._nodes) and not physical_links_ready(self._topology,self._nodes):
                return self.translate('Не все кабели подключены')
            if online == len(self._nodes) and all(plan_matches(n, plans[n['id']]) for n in self._nodes):
                return self.translate('Spark соединены')
            if online == len(self._nodes): return self.translate('Схема требует применения')
        except ValueError:
            pass
        return self.translate('Доступно {online} из {total} Spark').format(online=online,total=len(self._nodes))

    @Slot(object)
    def _receive(self, value):
        if 'nodes' in value:
            if value.get('revision', self._revision) != self._revision:
                self._scanning = False
                self.refresh()
                return
            self._nodes = value['nodes']
            self._scanning = False
            self._infer_ports = False
            if 'topology' in value:
                self._topology = value['topology']
                write_json(CONFIG / 'topology.json', self._topology)
            self.changed.emit()
            self.planner.update_nodes()
            self.devices.applyPending()
        if 'log' in value:
            self._logs = value['log']
            self.logChanged.emit()
        if 'message' in value:
            self._message = value['message']
            self.messageChanged.emit()
        if 'finished' in value:
            self._busy = False
            self.busyChanged.emit()
            self.refresh()
            self.devices.operation_finished(value.get('success',False),value.get('action',''))
            if value.get('success') and value.get('action')=='topology':
                self._user_draft=False
                write_json(CONFIG/'draft-marker.json',False)
        if value.get('open_studio'):
            QDesktopServices.openUrl(QUrl('http://127.0.0.1:8888'))

    @Slot()
    def refresh(self):
        if self._scanning or self._busy: return
        self._scanning = True
        topology = copy.deepcopy(self._topology)
        revision = self._revision
        def work():
            try:
                if not topology['nodes'][1].get('ssh'):
                    found = discover_worker()
                    if found: topology['nodes'][1] = found
                nodes = scan(topology)
                for node,data in zip(topology['nodes'],nodes):
                    if data.get('online'):
                        for key in ('machine_id','user','home','hostname','management_ip'):
                            if data.get(key): node[key]=data[key]
                # Infer initial selected ports from real stable IPs rather than a visual default.
                if self._infer_ports and len(nodes) == 2:
                    for side, index in [('a', 0), ('b', 1)]:
                        for iface, data in nodes[index].get('interfaces', {}).items():
                            if any(a.startswith('10.100.32.') for a in data.get('addresses', [])):
                                topology['cables'][0][side + '_port'] = 1 if 'f1np1' in iface else 0
                self.delivered.emit({'nodes': nodes, 'topology': topology, 'revision': revision})
            except Exception as exc:
                self.delivered.emit({'nodes': self._nodes, 'message': str(exc)})
        threading.Thread(target=work, daemon=True).start()

    @Slot(int)
    def setCount(self, count):
        if self._busy or count not in (2, 3) or count == len(self._topology['nodes']): return
        self._revision += 1
        self._infer_ports = False
        self._user_draft=True
        write_json(CONFIG/'draft-marker.json',True)
        value = resize_topology(self._topology,count)
        self._topology = value
        previous = {n['id']:n for n in self._nodes}
        self._nodes = [{**previous.get(n['id'], {'online': False, 'error': 'Устройство ещё не подключено.'}), **n} for n in value['nodes']]
        self.changed.emit()
        self.viewChanged.emit()

    @Slot(int, str)
    def setTarget(self, index, target):
        if index <= 0 or index >= len(self._topology['nodes']) or self._busy: return
        if self._topology['nodes'][index]['ssh'] == target.strip(): return
        self._topology['nodes'][index].pop('identity', None)
        self._topology['nodes'][index]['ssh'] = target.strip()
        self._user_draft=True
        write_json(CONFIG/'draft-marker.json',True)
        self._revision += 1
        self.changed.emit()

    @Slot(int, str, int)
    def setPort(self, cable, side, port):
        if self._busy: return
        try: updated=select_port(self._topology,cable,side,port)
        except ValueError: return
        if updated==self._topology: return
        self._topology=updated
        self._user_draft=True
        write_json(CONFIG/'draft-marker.json',True)
        self._revision += 1
        self._infer_ports = False
        self.changed.emit()

    @Slot()
    def saveDraft(self):
        try:
            validate_topology(self._topology, require_targets=False)
            write_json(CONFIG / 'topology.json', self._topology)
            self._message = 'Схема сохранена. Для изменения сети нажмите «Применить подключение».'
        except ValueError as exc:
            self._message = str(exc)
        self.messageChanged.emit()

    @Slot(str)
    def action(self, action):
        if self.busy or action not in ('install', 'update', 'update-app', 'refresh', 'check', 'rpc-logs', 'start-rpc', 'topology', 'start-studio','recover','recover-auto'): return
        try:
            if action == 'topology': validate_topology(self._topology)
            if action in ('update', 'refresh', 'topology', 'install', 'start-rpc') and any(n.get('model_active') for n in self._nodes):
                raise ValueError('Выгрузите модель в Studio перед установкой, обновлением или изменением кабелей.')
        except ValueError as exc:
            self._message = str(exc)
            self.messageChanged.emit()
            return
        self._busy = True
        self._logs = 'Подготовка операции…\n'
        self._message = 'Операция выполняется. Подробности во вкладке «Журнал».'
        self.busyChanged.emit()
        self.logChanged.emit()
        self.messageChanged.emit()
        STATE.mkdir(parents=True, exist_ok=True)
        stamp = str(time.time_ns())
        log = STATE / (stamp + '.log')
        result = STATE / (stamp + '.result.json')
        command = [sys.executable, '-u', '-m', 'spark_link.runner', action, '--log', str(log), '--result', str(result)]
        if action == 'topology':
            plan = STATE / (stamp + '.topology.json')
            write_json(plan, self._topology)
            command += ['--plan', str(plan)]
        def work():
            try:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                while process.poll() is None:
                    if log.is_file(): self.delivered.emit({'log': log.read_text(errors='replace')[-100000:]})
                    time.sleep(0.35)
                output = log.read_text(errors='replace')[-100000:] if log.exists() else process.stderr.read()
                record = read_json(result, {'returncode': process.returncode or 1})
                message = 'Готово. Операция завершена успешно.' if record['returncode'] == 0 else 'Операция не завершена. Причина указана в журнале.'
                self.delivered.emit({'log': output, 'message': message, 'finished': True,'success':record['returncode']==0,'action':action, 'open_studio': record['returncode']==0 and action=='start-studio'})
            except Exception as exc:
                self.delivered.emit({'message': str(exc), 'finished': True})
        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def open(self, target):
        if target == 'studio':
            if self._nodes and self._nodes[0].get('studio_service')=='active':
                QDesktopServices.openUrl(QUrl('http://127.0.0.1:8888'))
            else:
                self.action('start-studio')
        elif target == 'logs': QDesktopServices.openUrl(QUrl.fromLocalFile(str(STATE)))
        elif target == 'github': QDesktopServices.openUrl(QUrl('https://github.com/grosa787/connect-dual-spark-for-unsloth-studio'))

    @Slot(bool)
    def setVisible(self,visible):
        self.timer.setInterval(15000 if visible else 60000)
        if visible: self.refresh()

    @Slot(result=str)
    def chooseModelFile(self):
        from PySide6.QtWidgets import QFileDialog
        filename,_=QFileDialog.getOpenFileName(None,self.translate('Выберите GGUF-файл'),str(Path.home()/'.cache/huggingface/hub'),'GGUF (*.gguf)')
        return filename

import copy
import os
from pathlib import Path
import socket
import struct
import threading
from PySide6.QtCore import QObject,Signal,Slot,Property,QTimer
from .discovery import scan_new_devices,warm_neighbors,infer_topology
from .inventory import scan
from .onboarding import pair_device,trusted_node
from .state import CONFIG,read_json,write_json
from .topology import INTERFACES,default_topology


class DeviceManager(QObject):
    changed=Signal()
    delivered=Signal(object)
    found=Signal()
    def __init__(self,manager):
        super().__init__(manager)
        self.manager=manager
        self._candidates=[]; self._scanning=False; self._auth_busy=False; self._message=''
        self._pending=read_json(CONFIG/'pending-setup.json')
        self.delivered.connect(self._receive)
        self.manager.languageChanged.connect(self.changed)
        self.timer=QTimer(self); self.timer.timeout.connect(self.search); self.timer.start(60000)
        QTimer.singleShot(7000,self.search)
        self._link_event=threading.Event()
        if hasattr(socket,'AF_NETLINK'):
            def watch():
                try:
                    connection=socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,socket.NETLINK_ROUTE)
                    connection.bind((0,1))
                    while True:
                        data=connection.recv(65536)
                        offset=0
                        while offset+32<=len(data):
                            length,kind,_,_,_=struct.unpack_from('IHHII',data,offset)
                            if length<16: break
                            if kind==16:
                                index=struct.unpack_from('i',data,offset+20)[0]
                                try: interface=socket.if_indextoname(index)
                                except OSError: interface=''
                                if interface in INTERFACES: self._link_event.set()
                            offset+=(length+3)&~3
                except OSError: pass
            threading.Thread(target=watch,daemon=True).start()
        self.link_timer=QTimer(self); self.link_timer.timeout.connect(self._consume_link); self.link_timer.start(2000)

    @Property('QVariantList',notify=changed)
    def candidates(self): return self._candidates
    @Property(bool,notify=changed)
    def busy(self): return self._scanning or self._auth_busy
    @Property(str,notify=changed)
    def message(self): return self.manager.translate(self._message)
    @Property(bool,notify=changed)
    def pending(self): return bool(self._pending)

    def _consume_link(self):
        if self._link_event.is_set():
            self._link_event.clear()
            self.search()

    @Slot()
    def search(self):
        if self.manager._busy or self._scanning or self._auth_busy: return
        self._scanning=True; self._message='Ищем устройства на ConnectX-7…'; self.changed.emit()
        topology=copy.deepcopy(self.manager._topology)
        known=copy.deepcopy(self.manager._nodes)
        def work():
            try:
                for node in known:
                    if node.get('online'): warm_neighbors(node)
                refreshed=scan(topology)
                candidates=scan_new_devices(topology,refreshed)
                graph=infer_topology(refreshed) if all(n.get('online') for n in refreshed) else None
                self.delivered.emit({'candidates':candidates,'graph':graph,'nodes':refreshed})
            except Exception as exc: self.delivered.emit({'error':str(exc)})
        threading.Thread(target=work,daemon=True).start()

    @Slot(int,str,str)
    def authorize(self,index,username,password):
        if self._auth_busy or self.manager._busy or not 0<=index<len(self._candidates): return
        candidate=copy.deepcopy(self._candidates[index])
        self._auth_busy=True; self._message='Проверяем доступ к новому Spark…'; self.changed.emit(); self.manager.busyChanged.emit()
        def work():
            try:
                node=pair_device(candidate,username,password)
                self.delivered.emit({'paired':node,'candidate_id':candidate['id']})
            except Exception as exc: self.delivered.emit({'error':str(exc)})
        threading.Thread(target=work,daemon=True).start()

    @Slot(int)
    def addTrusted(self,index):
        if not 0<=index<len(self._candidates) or not self._candidates[index].get('authorized'): return
        candidate=copy.deepcopy(self._candidates[index])
        self._auth_busy=True; self.changed.emit(); self.manager.busyChanged.emit()
        def work():
            try: self.delivered.emit({'paired':trusted_node(candidate),'candidate_id':candidate['id']})
            except Exception as exc: self.delivered.emit({'error':str(exc)})
        threading.Thread(target=work,daemon=True).start()

    @Slot(object)
    def _receive(self,value):
        self._scanning=False; self._auth_busy=False
        self.manager.busyChanged.emit()
        if 'error' in value:
            self._message='Не удалось подключить устройство: '+value['error']
        elif 'paired' in value:
            node=value['paired']
            if any(n.get('machine_id')==node.get('machine_id') for n in self.manager._topology['nodes'] if n.get('machine_id')):
                self._message='Этот Spark уже добавлен.'; self.changed.emit(); return
            topology=copy.deepcopy(self.manager._topology)
            slot=next((i for i,n in enumerate(topology['nodes'][1:],1) if not n.get('ssh')),len(topology['nodes']))
            if slot>=3:
                self._message='Поддерживается не больше трёх Spark.'; self.changed.emit(); return
            node.update({'id':'worker'+str(slot+1),'name':'Второй Spark' if slot==1 else 'Третий Spark','local':False})
            if slot<len(topology['nodes']): topology['nodes'][slot]=node
            else: topology['nodes'].append(node)
            if len(topology['nodes'])==3 and len(topology['cables'])==1:
                first=topology['cables'][0]
                topology['cables'] += [{'a':'head','a_port':1-first['a_port'],'b':'worker3','b_port':0},
                                      {'a':'worker2','a_port':1-first['b_port'],'b':'worker3','b_port':1}]
            # Authentication is complete; cable discovery now runs with the enrolled identity.
            self.manager._topology=topology
            self.manager._revision+=1
            write_json(CONFIG/'topology.json',topology)
            self.manager._nodes=[*self.manager._nodes[:slot],node]
            self._candidates=[c for c in self._candidates if c['id']!=value.get('candidate_id')]
            self._pending={'version':1,'await_graph':True}
            write_json(CONFIG/'pending-setup.json',self._pending)
            self._message='Spark добавлен. Определяем кабели и готовим настройку.'
            self.manager.changed.emit(); self.manager.viewChanged.emit()
            QTimer.singleShot(500,self.search)
        else:
            previous={c['id'] for c in self._candidates}
            results=value.get('candidates',[])
            self._candidates=[c for c in results if not c.get('existing_id')]
            for recovered in (c for c in results if c.get('existing_id')):
                for node in self.manager._topology['nodes']:
                    if node['id']==recovered['existing_id']:
                        for key in ('ssh','identity','machine_id','management_ip','host_key_alias','host_key_id'):
                            if recovered['device'].get(key): node[key]=recovered['device'][key]
                write_json(CONFIG/'topology.json',self.manager._topology)
                self.manager._revision+=1
                self.manager.refresh()
            if any(c['id'] not in previous for c in self._candidates): self.found.emit()
            self._message='Найден новый Spark. Добавьте его для настройки.' if self._candidates else 'Поиск завершён. Новых устройств нет.'
            graph=value.get('graph')
            if graph and not self._pending and not self.manager._user_draft and graph['cables']!=self.manager._topology['cables']:
                self._pending={'version':1,'await_graph':False}
            if self._pending and graph:
                self.manager._topology=graph
                self.manager._nodes=value['nodes']
                self.manager._revision+=1
                self.manager._infer_ports=False
                write_json(CONFIG/'topology.json',graph)
                self._pending={'version':1,'await_graph':False,'paused':self._pending.get('paused',False)}
                write_json(CONFIG/'pending-setup.json',self._pending)
                self.manager.changed.emit(); self.manager.viewChanged.emit()
                self.applyPending()
            elif self._pending:
                self._message='Не все кабели или устройства обнаружены. Проверьте соединения и повторите поиск.'
        self.changed.emit()

    @Slot()
    def applyPending(self):
        if not self._pending or self._pending.get('await_graph') or self._pending.get('paused') or self.manager._busy: return
        if any(n.get('model_active') for n in self.manager._nodes):
            self._message='Настройка ждёт выгрузки активных моделей.'; self.changed.emit(); return
        self.manager.action('topology')

    def operation_finished(self,success,action):
        if success and action=='topology':
            self._pending=None
            write_json(CONFIG/'pending-setup.json',None)
            self._message='Spark настроен и готов к следующему запуску модели.'
            self.changed.emit()
        elif not success and action=='topology' and self._pending:
            self._pending['paused']=True
            write_json(CONFIG/'pending-setup.json',self._pending)
            self._message='Настройка приостановлена. Проверьте журнал и повторите её.'
            self.changed.emit()

    @Slot()
    def retrySetup(self):
        if self._pending:
            self._pending['paused']=False
            if self._pending.get('await_graph'): self.search()
            else: self.applyPending()

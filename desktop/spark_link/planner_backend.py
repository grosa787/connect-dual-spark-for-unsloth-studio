import copy
import re
from pathlib import Path
import threading
from PySide6.QtCore import QObject,Signal,Slot,Property
from .memory_planner import analyze_model,estimate_kv,allocate,parse_hf_reference,GIB
from .gguf_metadata import parse_header
from .state import CONFIG,read_json,write_json
from .model_policy import POLICIES,save_policy,remove_policy
from .runtime_stats import observed_cache


class ModelPlanner(QObject):
    changed=Signal()
    delivered=Signal(object)
    def __init__(self,manager):
        super().__init__(manager)
        self.manager=manager
        self._form={'reference':'','manual':False,'weights_gib':0.0,'context':1048576,'dtype':'f16',
                    'manual_kv':False,'cache_gib':0.0,'head_reserve':24.0,'worker_reserve':8.0,'units':'percent','variant_index':0}
        saved=read_json(CONFIG/'planner-form.json',{})
        self._form.update({k:v for k,v in saved.items() if k in self._form})
        self._analysis={}; self._result={}; self._percentages=[]; self._message=''; self._busy=False
        self._cache_quality='unknown'; self._cache_known=False
        self.delivered.connect(self._receive)
        self.manager.languageChanged.connect(self.changed)

    @Property('QVariantMap',notify=changed)
    def form(self): return self._form
    @Property('QVariantMap',notify=changed)
    def analysis(self): return self._analysis
    @Property('QVariantMap',notify=changed)
    def result(self): return self._result
    @Property('QVariantList',notify=changed)
    def percentages(self): return self._percentages
    @Property(bool,notify=changed)
    def busy(self): return self._busy
    @Property(str,notify=changed)
    def message(self): return self.manager.translate(self._message)
    @Property(str,notify=changed)
    def cacheQuality(self): return self._cache_quality
    @Property(bool,notify=changed)
    def cacheKnown(self): return self._cache_known
    @Property('QVariantList',notify=changed)
    def savedPlans(self): return [p.get('id','') for p in read_json(POLICIES,{'models':[]}).get('models',[])]
    @Property(bool,notify=changed)
    def hasSavedPlan(self):
        variant=self.selected() or {}
        key=self._analysis.get('repo','')+':'+variant.get('label','') if self._analysis.get('repo') and not self._form['manual'] else str(Path(self._form['reference']).resolve()) if self._form['reference'].startswith('/') else ''
        return any(p.get('id')==key for p in read_json(POLICIES,{'models':[]}).get('models',[]))

    def selected(self):
        variants=self._analysis.get('variants',[])
        index=int(self._form['variant_index'])
        return variants[index] if 0<=index<len(variants) else None

    def update_nodes(self):
        self.recalculate()

    @Slot(str,str)
    def setField(self,key,value):
        if key not in self._form: return
        try:
            if key in ('manual','manual_kv'): parsed=value=='true'
            elif key in ('weights_gib','cache_gib','head_reserve','worker_reserve'): parsed=float(value.replace(',','.'))
            elif key in ('context','variant_index'): parsed=int(value.replace('_','').replace(' ',''))
            elif key=='dtype':
                if value not in ('f16','q8_0','q4_0'): raise ValueError()
                parsed=value
            elif key=='units':
                if value not in ('percent','gib'): raise ValueError()
                parsed=value
            else: parsed=value.strip()
            self._form[key]=parsed
            if key=='manual' and parsed: self._form['manual_kv']=True
            write_json(CONFIG/'planner-form.json',self._form)
            self.recalculate()
        except (ValueError,OverflowError):
            self._message='Проверьте числовые значения.'; self.changed.emit()

    @Slot(str)
    def analyze(self,reference):
        if self._busy: return
        self._busy=True; self._message='Читаем метаданные модели…'; self.changed.emit()
        def work():
            try:
                if reference.startswith('/'):
                    path=Path(reference).expanduser()
                    with path.open('rb') as stream: meta=parse_header(stream.read(8*1024*1024))
                    files=list(path.parent.glob(path.name.split('-00001-of-')[0]+'*.gguf')) if '-00001-of-' in path.name else [path]
                    arch=meta.get('general.architecture','unknown')
                    data={'repo':'','local_path':str(path.resolve()),'source_path':str(path),'metadata':meta,'max_context':meta.get(arch+'.context_length'),
                          'variants':[{'label':path.name,'files':[p.name for p in files],'size_bytes':sum(p.stat().st_size for p in files),'kind':'gguf','complete':True}],'selected':0}
                else: data=analyze_model(reference)
                self.delivered.emit({'analysis':data,'reference':reference})
            except Exception as exc:
                self.delivered.emit({'error':str(exc)})
        threading.Thread(target=work,daemon=True).start()

    @Slot(object)
    def _receive(self,value):
        self._busy=False
        if 'analysis' in value:
            self._analysis=value['analysis']; self._form['reference']=value['reference']; self._form['variant_index']=self._analysis.get('selected',0)
            self._form['manual']=False; self._form['manual_kv']=False
            maximum=self._analysis.get('max_context')
            if maximum: self._form['context']=min(int(self._form['context']),int(maximum))
            self._percentages=[]
            self._message='Метаданные загружены из локального кеша.' if self._analysis.get('cached') else 'Метаданные модели прочитаны.'
            self.recalculate(auto=True)
        else:
            self._message='Не удалось прочитать модель: '+value.get('error','')
        self.changed.emit()

    @Slot(int,str)
    def setPercentage(self,index,value):
        try:
            number=float(value.replace(',','.'))
            if self._form['units']=='gib':
                # A partial edit can temporarily make the sum invalid and clear
                # _result. The next field must still use the selected model size.
                weights=float(self._form['weights_gib']) if self._form['manual'] else (self.selected() or {}).get('size_bytes',0)/GIB
                if weights<=0: raise ValueError()
                number=number/weights*100
            count=len(self.manager._nodes)
            if len(self._percentages)!=count: self._percentages=[100/count]*count
            self._percentages[index]=number
            self.recalculate()
        except (ValueError,ZeroDivisionError,IndexError):
            self._message='Проверьте доли устройств.'; self.changed.emit()

    @Slot()
    def autoAllocate(self): self.recalculate(auto=True)

    def recalculate(self,auto=False):
        variant=self.selected()
        weights=float(self._form['weights_gib']) if self._form['manual'] else (variant or {}).get('size_bytes',0)/GIB
        try:
            context=int(self._form['context'])
            if weights<=0: raise ValueError('missing_model')
            if context<=0 or (self._analysis.get('max_context') and not self._form['manual'] and context>self._analysis['max_context']): raise ValueError('context')
            if self._form['manual_kv']:
                cache=float(self._form['cache_gib']); self._cache_quality='manual'
            else:
                estimate=estimate_kv(self._analysis.get('metadata',{}),context,self._form['dtype'])
                cache=estimate['gib']; self._cache_quality=estimate['quality']
                if cache is None and variant:
                    cache=observed_cache(self._analysis.get('repo'),variant['files'],context,self._form['dtype'])
                    if cache is not None: self._cache_quality='observed'
            self._cache_known=cache is not None
            nodes=self.manager._nodes
            available=[(n.get('memory_total',0) if n.get('model_active') else n.get('memory_available',0))/1048576 if n.get('online') else 0 for n in nodes]
            shares=None if auto or len(self._percentages)!=len(nodes) else self._percentages
            self._result=allocate(weights,cache,available,shares,float(self._form['head_reserve']),float(self._form['worker_reserve']))
            self._percentages=[a['percent'] for a in self._result['allocations']]
            self._result['cache_quality']=self._cache_quality
            self._result['assumes_unloaded']=any(n.get('model_active') for n in nodes)
            self._result['can_save']=self._result['fits'] and (self._form['manual'] and self._form['reference'].startswith('/') or variant and variant['kind']=='gguf' and variant['complete'])
            self._message='План помещается с резервом памяти.' if self._result['fits'] else 'Не хватает запаса памяти. Измените доли или контекст.'
        except (ValueError,TypeError,OverflowError) as exc:
            self._result={}; self._cache_known=False if 'unknown' in str(exc) else self._cache_known
            if str(exc)=='missing_model': self._message='Вставьте ссылку на модель или задайте размер вручную.'
            elif 'unknown' in str(exc): self._message='Для этой архитектуры задайте KV-кеш вручную или выберите проверенный контекст.'
            elif 'percentages' in str(exc): self._message='Сумма долей должна быть равна 100%.'
            elif str(exc)=='context': self._message='Контекст превышает заявленный максимум модели.'
            else: self._message='Укажите размер модели, контекст и бюджет KV-кеша.'
        self.changed.emit()

    @Slot()
    def savePlan(self):
        self.recalculate()
        if not self._result.get('can_save'): return
        variant=self.selected() or {}
        policy={'repo':self._analysis.get('repo','') if not self._form['manual'] else '', 'variant':variant.get('label','manual'),
                'files':variant.get('files',[]),'weights_gib':self._result['weights_gib'],'kv_gib':self._result['kv_gib'],
                'context':int(self._form['context']),'dtype':self._form['dtype'],'head_reserve':self._form['head_reserve'],'worker_reserve':self._form['worker_reserve'],
                'percents':{n['id']:p for n,p in zip(self.manager._nodes,self._percentages) if n.get('online')},'auto_topology':True}
        if self._form['manual']:
            path=Path(self._form['reference'])
            if not path.is_file(): self._message='Выберите существующий GGUF-файл.'; self.changed.emit(); return
            policy['local_path']=str(path.resolve()); policy['source_path']=str(path)
        elif self._analysis.get('local_path'):
            policy['local_path']=self._analysis['local_path']; policy['source_path']=self._analysis['source_path']
        try:
            save_policy(policy,len(self.manager._nodes))
            write_json(CONFIG/'planner-form.json',self._form)
            self._message='План сохранён. Он применяется только при следующем запуске этой модели.'
        except Exception as exc:
            self._message='Не удалось сохранить план: '+str(exc)
        self.changed.emit()

    @Slot(int)
    def loadPlan(self,index):
        policies=read_json(POLICIES,{'models':[]}).get('models',[])
        if not 0<=index<len(policies): return
        policy=policies[index]
        self._analysis={'repo':policy.get('repo',''),'local_path':policy.get('local_path'),'source_path':policy.get('source_path'),
            'variants':[{'label':policy.get('variant','manual'),'files':policy.get('files',[]),'size_bytes':int(policy['weights_gib']*GIB),'kind':'gguf','complete':True}], 'cached':True}
        self._form.update({'reference':policy.get('repo') or policy.get('source_path') or policy.get('local_path',''),'manual':not bool(policy.get('repo')),
            'weights_gib':policy['weights_gib'],'manual_kv':True,'cache_gib':policy['kv_gib'],'context':policy['context'],'dtype':policy['dtype'],'variant_index':0,
            'head_reserve':policy.get('head_reserve',24),'worker_reserve':policy.get('worker_reserve',8)})
        self._percentages=[policy['percents'].get(n['id'],0) for n in self.manager._nodes]
        self.recalculate()

    @Slot()
    def removePlan(self):
        variant=self.selected() or {}
        key=self._analysis.get('repo','')+':'+variant.get('label','') if self._analysis.get('repo') and not self._form['manual'] else str(Path(self._form['reference']).resolve()) if self._form['reference'].startswith('/') else ''
        if key:
            remove_policy(key)
            self._message='План удалён. Будут использоваться обычные настройки запуска.'
            self.changed.emit()

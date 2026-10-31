"""Native credential dialog and stdin-only sudo execution for user-authorized setup jobs."""
import os
from pathlib import Path
import shlex
import subprocess
from .credentials import Vault,VaultUnavailable,credential_id
from .inventory import node_ssh
from .preferences import ViewPreferences
from .translations import translate

_application=None

def password_dialog(node):
    global _application
    from PySide6.QtWidgets import QApplication,QDialog,QVBoxLayout,QLabel,QLineEdit,QCheckBox,QDialogButtonBox
    _application=QApplication.instance() or QApplication([])
    language=ViewPreferences().language
    tr=lambda text:translate(text,language)
    dialog=QDialog(); dialog.setWindowTitle('Spark Link'); dialog.setMinimumWidth(460)
    dialog.setStyleSheet('QDialog{background:#f2f5ee;} QLabel,QCheckBox{color:#203024;font-size:14px;} QLineEdit{padding:10px;border:1px solid #bdcdb4;border-radius:8px;background:white;color:#203024;} QPushButton{padding:10px 18px;background:#b5e866;border:1px solid #9cbe73;border-radius:8px;color:#203024;min-width:100px;}')
    layout=QVBoxLayout(dialog); layout.setContentsMargins(24,24,24,24); layout.setSpacing(14)
    title=QLabel(tr('Доступ администратора')); title.setStyleSheet('font-size:21px;font-weight:600;'); layout.addWidget(title)
    description=QLabel(tr('Введите пароль учётной записи для настройки этого Spark.')+'\n'+(node.get('ssh') or node.get('name','This Spark')))
    description.setWordWrap(True); layout.addWidget(description)
    field=QLineEdit(); field.setEchoMode(QLineEdit.EchoMode.Password); field.setMaxLength(4096); layout.addWidget(field)
    store=QCheckBox(tr('Сохранить в зашифрованном хранилище GNOME')); store.setChecked(True); layout.addWidget(store)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('Продолжить'))
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('Отмена'))
    buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
    if dialog.exec()!=QDialog.DialogCode.Accepted: raise RuntimeError('Authentication was cancelled')
    password=field.text(); field.clear()
    if not password: raise ValueError('Password is empty')
    return password,store.isChecked()

def privileged(node,argv,*,capture=False):
    identity=credential_id(node)
    try: password=Vault().get(identity)
    except VaultUnavailable: password=None
    store=False
    if password is None: password,store=password_dialog(node)
    if store: Vault().set(identity,password)
    # Read the secret once, expose it only to sudo's validation pipe, then give
    # the actual administrator command /dev/null. A cached sudo timestamp must
    # never cause the password line to become a package/helper's stdin.
    script="set -e; IFS= read -r SPARK_LINK_ADMIN_INPUT; printf '%s\\n' \"$SPARK_LINK_ADMIN_INPUT\" | sudo -S -p '' -v || exit 77; unset SPARK_LINK_ADMIN_INPUT; sudo -n -- "+shlex.join([str(x) for x in argv])+" </dev/null; SPARK_LINK_ADMIN_STATUS=$?; exit \"$SPARK_LINK_ADMIN_STATUS\""
    shell=['bash','-c',script]
    command=shell if node.get('local') else node_ssh(node)+[shlex.join(shell)]
    # Never print argv containing passwords or pass them through an environment variable.
    result=subprocess.run(command,input=password+'\n',text=True,stdout=subprocess.PIPE if capture else None,stderr=None)
    if result.returncode:
        if result.returncode==77:
            try: Vault().delete(identity)
            except VaultUnavailable: pass
        raise RuntimeError('Administrator authentication or command failed; no password was logged')
    password=None
    return result

def gui_runner(node=None):
    from dual_spark.system import Runner
    class NativeRunner(Runner):
        def run_interactive(self,argv,*,label=None,**kwargs):
            if argv and argv[0]=='sudo':
                local={'local':True,'name':'Первый Spark','machine_id':Path('/etc/machine-id').read_text().strip()}
                return privileged(local,argv[1:])
            if argv and argv[0]=='ssh' and 'sudo ' in argv[-1] and node:
                parts=shlex.split(argv[-1])
                if parts and parts[0]=='sudo': return privileged(node,parts[1:])
            return super().run_interactive(argv,label=label,**kwargs)
    return NativeRunner(verbose=True)

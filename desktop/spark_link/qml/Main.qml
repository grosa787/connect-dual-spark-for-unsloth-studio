import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1240; height: 820
    minimumWidth: 1000; minimumHeight: 700
    visible: true
    title: "Spark Link"
    color: "#f2f5ee"
    font.family: "Ubuntu Sans"
    property int page: initialPage
    property int selectedNode: 0
    property int activeCable: 0
    property bool allowExit: false
    property int candidateIndex: -1
    property var selectedCandidate: ({})
    property string noticeText: devices.pending || devices.candidates.length>0 ? devices.message : manager.message
    function t(source) { let language=manager.language; return manager.translate(source) }
    property var titles: [window.t("Ваши Spark, вместе."), window.t("Соедините так, как в жизни."), window.t("Всё для первого запуска."), window.t("Актуальная и согласованная пара."), window.t("Что происходит сейчас."),window.t("Память под вашим контролем.")]
    property var captions: [window.t("Состояние устройств и быстрый доступ к Unsloth Studio"), window.t("Выберите разъёмы, проверьте кабели и примените сетевую схему"), window.t("Unsloth, CUDA-инструменты и RPC — с проверкой каждого шага"), window.t("Обновляйте Studio и RPC из одного места"), window.t("Полный вывод операций, сохранённый на этом Spark"),window.t("Модель, контекст и доли весов для каждого Spark")]
    function nodeName(id) { for(let n of manager.topology.nodes) if(n.id===id) return n.name; return id }
    function memory(n) { return n && n.memory_available ? (n.memory_available/1048576).toFixed(1)+window.t(" ГиБ доступно") : window.t("Ожидаем данные") }
    function portLabel(port) { return port===0 ? window.t("Порт 0 · ближе к Ethernet") : window.t("Порт 1 · крайний") }
    onClosing: function(close) { if(!allowExit) { close.accepted=false; window.hide(); manager.setVisible(false) } }
    function openOnboard(index) {
        window.candidateIndex=index
        window.selectedCandidate=devices.candidates[index]
        loginField.text=selectedCandidate.authorized && selectedCandidate.device ? selectedCandidate.device.user : ''
        passwordField.clear()
        showPassword.checked=false
        onboard.open()
    }

    Rectangle {
        id: sidebar
        width: 220; anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        color: "#f9fbf6"
        Rectangle { width: 1; color: "#dfe6d9"; anchors { right: parent.right; top: parent.top; bottom: parent.bottom } }
        ColumnLayout {
            anchors { fill: parent; margins: 20 }
            spacing: 8
            RowLayout {
                Layout.topMargin: 10; Layout.bottomMargin: 24; spacing: 10
                Image { source: "../assets/spark-link.svg"; sourceSize.width: 38; sourceSize.height: 38; Layout.preferredWidth: 38; Layout.preferredHeight: 38 }
                Text { text: "Spark Link"; color: "#203024"; font.pixelSize: 21; font.weight: Font.DemiBold }
            }
            Repeater {
                model: [window.t("Обзор"), window.t("Кабели и Spark"), window.t("Установка"), window.t("Обновления"), window.t("Журнал"),window.t("Память и модели")]
                Button {
                    id: nav
                    objectName: "nav_"+index
                    required property int index
                    required property string modelData
                    Layout.fillWidth: true; implicitHeight: 44
                    text: modelData; Accessible.name: modelData
                    onClicked: window.page=index
                    contentItem: RowLayout {
                        spacing: 12
                        Canvas {
                            Layout.leftMargin: 12; Layout.preferredWidth: 20; Layout.preferredHeight: 20
                            property color ink: window.page===nav.index ? "#355b30" : "#7b8977"
                            onInkChanged: requestPaint()
                            onPaint: {
                                let c=getContext("2d"); c.reset(); c.strokeStyle=ink; c.lineWidth=1.7; c.lineCap="round"
                                if(nav.index===0) { for(let x of [2,12]) for(let y of [2,12]) c.strokeRect(x,y,6,6) }
                                else if(nav.index===1) { c.strokeRect(1,4,7,11); c.strokeRect(12,4,7,11); c.beginPath(); c.moveTo(8,10); c.lineTo(12,10); c.stroke() }
                                else if(nav.index===2) { c.beginPath(); c.moveTo(10,1); c.lineTo(10,13); c.moveTo(5,9); c.lineTo(10,14); c.lineTo(15,9); c.moveTo(2,15); c.lineTo(2,19); c.lineTo(18,19); c.lineTo(18,15); c.stroke() }
                                else if(nav.index===3) { c.beginPath(); c.arc(10,10,7,0.1,5.6); c.moveTo(17,2); c.lineTo(17,8); c.lineTo(11,8); c.stroke() }
                                else if(nav.index===4) { c.strokeRect(3,1,14,18); for(let y of [6,10,14]) { c.beginPath(); c.moveTo(6,y); c.lineTo(14,y); c.stroke() } }
                                else { c.strokeRect(4,4,12,12); for(let v of [6,10,14]) { c.beginPath(); c.moveTo(v,0); c.lineTo(v,4); c.moveTo(v,16); c.lineTo(v,20); c.stroke() } }
                            }
                        }
                        Text { text: nav.text; elide:Text.ElideRight; color: window.page===nav.index ? "#294b2b" : "#64735f"; font.pixelSize: 14; font.weight: window.page===nav.index ? Font.DemiBold : Font.Normal; Layout.fillWidth: true; Layout.minimumWidth:0 }
                    }
                    background: Rectangle { radius: 9; color: window.page===nav.index ? "#e5f1d5" : nav.hovered ? "#f0f4ea" : "transparent"; border.width: nav.activeFocus ? 2 : 0; border.color: "#628543" }
                    ToolTip.visible:nav.hovered
                    ToolTip.text:nav.text
                }
            }
            Item { Layout.fillHeight: true }
            Rectangle { Layout.fillWidth: true; height: 1; color: "#e0e7da" }
            Text { text: window.t("Нативное приложение"); color: "#53634f"; font.pixelSize: 12; Layout.topMargin: 12 }
            Text { text: "Ubuntu ARM64  ·  v"+manager.version; color: "#6a7865"; font.pixelSize: 11 }
            Text { text:window.t("Язык приложения"); color:"#53634f"; font.pixelSize:12; Layout.topMargin:10 }
            ComboBox {
                objectName:"languageSelector"
                Layout.fillWidth:true; implicitHeight:40
                model:manager.languageNames
                currentIndex:['ru','en','de','es'].indexOf(manager.language)
                onActivated: manager.setLanguage(['ru','en','de','es'][currentIndex])
                Accessible.name:window.t("Язык приложения")
            }
            Button { text: window.t("Проект на GitHub"); flat: true; font.pixelSize: 12; onClicked: manager.open('github'); Accessible.name: text }
        }
    }

    ColumnLayout {
        anchors { left: sidebar.right; right: parent.right; top: parent.top; bottom: parent.bottom; margins: 24 }
        spacing: 16
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 8
                Text { Layout.fillWidth: true; elide: Text.ElideRight; text: window.titles[window.page]; font.pixelSize: 29; font.weight: Font.DemiBold; color: "#203024" }
                Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; text: window.captions[window.page]; font.pixelSize: 13; color: "#63725d" }
            }
            Rectangle {
                Layout.preferredWidth: statusLabel.implicitWidth+34; Layout.preferredHeight: 34
                radius: 17; color: "#e5efdc"; border.color: "#cfddc5"
                Text { id: statusLabel; anchors.centerIn: parent; text: manager.clusterText; color: "#3b5b30"; font.pixelSize: 12; font.weight: Font.DemiBold }
            }
        }
        Rectangle {
            visible: window.noticeText.length>0
            Layout.fillWidth: true; implicitHeight: notification.implicitHeight+24
            radius: 9; color: "#eaf1e1"; border.color: "#d1dfc5"
            Text { id: notification; anchors { left: parent.left; right: parent.right; margins: 14; verticalCenter: parent.verticalCenter } text: window.noticeText; wrapMode: Text.WordWrap; color: "#3d5734"; font.pixelSize: 13 }
        }
        ProgressBar { visible: manager.busy; indeterminate: true; Layout.fillWidth: true; implicitHeight: 4 }

        StackLayout {
            currentIndex: window.page
            Layout.fillWidth: true; Layout.fillHeight: true
            // Overview
            ColumnLayout {
                spacing: 16
                Repeater {
                    model:devices.candidates
                    Rectangle {
                        required property var modelData
                        required property int index
                        Layout.fillWidth:true; implicitHeight:70; radius:12; color:"#e1efcf"; border.color:"#bdd599"
                        RowLayout { anchors { fill:parent; margins:12 } spacing:14
                            ColumnLayout { Layout.fillWidth:true; Layout.minimumWidth:0; spacing:5
                                Text { text:window.t("Найден новый Spark"); font.pixelSize:15; font.weight:Font.DemiBold; color:"#2e4b27" }
                                Text { Layout.fillWidth:true; textFormat:Text.PlainText; text:modelData.address; elide:Text.ElideMiddle; font.pixelSize:12; color:"#536e45" }
                            }
                            ActionButton { text:window.t("Добавить и настроить"); primary:true; enabled:!manager.busy; onClicked:window.openOnboard(index) }
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: devices.candidates.length>0 ? 200 : 280
                    radius: 18; color: "#e7edde"; clip: true
                    ClusterScene { anchors.fill: parent; nodes: manager.nodes; topology: manager.topology; orientations:manager.orientations; selectedNode: window.selectedNode; onSelected: function(node,port) { window.selectedNode=node } }
                    RowLayout {
                        anchors { right: parent.right; top: parent.top; margins: 16 }
                        ActionButton { text: window.t("Проверить"); enabled: !manager.busy; onClicked: manager.refresh() }
                        ActionButton { text: window.t("Открыть Studio"); primary: true; onClicked: manager.open('studio') }
                    }
                }
                RowLayout {
                    spacing: 12; Layout.fillWidth: true
                    Repeater {
                        model: manager.nodes
                        Rectangle {
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true; Layout.preferredHeight: 144
                            radius: 12; color: "#ffffff"; border.color: "#dfe6d8"
                            ColumnLayout {
                                anchors { fill: parent; margins: 16 } spacing: 8
                                RowLayout { Layout.fillWidth: true; Text { text: modelData.name; color: "#263928"; font.pixelSize: 16; font.weight: Font.DemiBold } Item { Layout.fillWidth: true } Rectangle { width: 8; height: 8; radius: 4; color: modelData.online ? "#719c43" : "#b48745" } }
                                Text { text: modelData.online ? modelData.hostname : window.t("Не подключён"); color: "#64735f"; font.pixelSize: 12 }
                                Text { text: modelData.online ? window.memory(modelData) : (index===2 ? window.t("Можно подключить третий Spark") : window.t("Проверьте SSH и кабель")); color: "#365631"; font.pixelSize: 14 }
                                Text { text: modelData.model_active ? window.t("Модель запущена") : !modelData.online ? window.t("Ожидаем устройство") : (modelData.local ? modelData.studio_service : modelData.rpc_service) === "active" ? window.t("Готов к работе") : window.t("Требуется проверка служб"); font.pixelSize: 12; color: "#6a7964" }
                            }
                        }
                    }
                }
                RowLayout { Layout.fillWidth:true; spacing:10
                    ActionButton { text:window.t("Найти Spark"); enabled:!devices.busy && !manager.busy; onClicked:devices.search() }
                    ActionButton { text:window.t("Проверить и восстановить"); enabled:!manager.busy; onClicked:manager.action('recover') }
                    Item { Layout.fillWidth:true }
                    ActionButton { text:window.t("Проверить RPC"); enabled:!manager.busy; onClicked:manager.action('check') }
                }
            }
            // Cabling
            RowLayout {
                spacing: 18
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 200; radius: 16; color: "#e7edde"; clip: true
                        ClusterScene {
                            objectName: "cableScene"
                            anchors.fill: parent; nodes: manager.nodes; topology: manager.topology; selectedNode: window.selectedNode; editing: true
                            orientations:manager.orientations
                            onSelected: function(node,port) {
                                window.selectedNode=node
                                if(port<0) return
                                let cable=manager.topology.cables[window.activeCable]
                                let id=manager.topology.nodes[node].id
                                if(cable.a===id) manager.setPort(window.activeCable,'a',port)
                                else if(cable.b===id) manager.setPort(window.activeCable,'b',port)
                            }
                        }
                        RowLayout { anchors { top: parent.top; left: parent.left; margins: 14 } ActionButton { objectName: "twoNodes"; text: "2 Spark"; primary: manager.topology.nodes.length===2; enabled: !manager.busy; onClicked: { window.selectedNode=0; window.activeCable=0; manager.setCount(2) } } ActionButton { objectName: "threeNodes"; text: "3 Spark"; primary: manager.topology.nodes.length===3; enabled: !manager.busy; onClicked: { window.selectedNode=0; manager.setCount(3) } } }
                    }
                    Text { Layout.fillWidth: true; text: window.t("Порт 0 ближе к обычному Ethernet, порт 1 — крайний. Если корпус повёрнут, они могут выглядеть верхним и нижним."); wrapMode: Text.WordWrap; font.pixelSize: 12; color: "#5f7059" }
                    Repeater {
                        model: manager.topology.cables
                        Rectangle {
                            id: cableRow
                            required property var modelData
                            required property int index
                            Layout.fillWidth: true; implicitHeight: window.activeCable===index ? 98 : 48; radius: 10; color: window.activeCable===index ? "#edf4e3" : "#ffffff"; border.color: window.activeCable===index ? "#9ebf7a" : "#dce4d6"
                            ColumnLayout {
                                anchors { fill: parent; margins: 9 } spacing: 5
                                RowLayout { Layout.fillWidth: true; RadioButton { text: window.nodeName(cableRow.modelData.a)+"  ↔  "+window.nodeName(cableRow.modelData.b); checked: window.activeCable===cableRow.index; onClicked: window.activeCable=cableRow.index; font.pixelSize: 12 } }
                                RowLayout {
                                    visible: window.activeCable===cableRow.index
                                    spacing: 8; Layout.fillWidth: true
                                    ComboBox { Layout.fillWidth: true; model: [window.t("Порт 0 · ближе к Ethernet"), window.t("Порт 1 · крайний")]; currentIndex: cableRow.modelData.a_port; enabled: !manager.busy; font.pixelSize: 12; onActivated: manager.setPort(cableRow.index,'a',currentIndex); Accessible.name: window.t("Порт первого конца кабеля") }
                                    Text { text: "↔"; color: "#62765a" }
                                    ComboBox { objectName: "cableB_"+cableRow.index; Layout.fillWidth: true; model: [window.t("Порт 0 · ближе к Ethernet"), window.t("Порт 1 · крайний")]; currentIndex: cableRow.modelData.b_port; enabled: !manager.busy; font.pixelSize: 12; onActivated: manager.setPort(cableRow.index,'b',currentIndex); Accessible.name: window.t("Порт второго конца кабеля") }
                                }
                            }
                        }
                    }
                }
                Rectangle {
                    Layout.preferredWidth: 280; Layout.fillHeight: true; radius: 14; color: "#ffffff"; border.color: "#dce4d6"
                    ScrollView {
                        id: inspectorScroll
                        anchors { left:parent.left; right:parent.right; top:parent.top; bottom:applyTopology.top; margins:18; bottomMargin:12 }
                        clip:true; contentWidth:availableWidth
                    ColumnLayout {
                        width:inspectorScroll.availableWidth; height:Math.max(implicitHeight,inspectorScroll.availableHeight); spacing: 14
                        Text { text: window.t("Устройства"); font.pixelSize: 18; font.weight: Font.DemiBold; color: "#263b29" }
                        Repeater {
                            model: manager.topology.nodes
                            ColumnLayout {
                                id:deviceEditor
                                required property var modelData
                                required property int index
                                Layout.fillWidth: true; spacing: 6
                                Text { text: modelData.name; color: "#3c5335"; font.pixelSize: 13; font.weight: Font.DemiBold }
                                TextField { visible: index>0; Layout.fillWidth: true; text: modelData.ssh; placeholderText: "user@spark-xxxx.local"; enabled: !manager.busy; font.pixelSize: 12; onEditingFinished: manager.setTarget(index,text); Accessible.name: modelData.name+" SSH" }
                                Text { visible: index===0; text: window.t("Этот компьютер"); color: "#76836f"; font.pixelSize: 12 }
                                Text { text:window.t("Положение корпуса"); font.pixelSize:12; color:"#63725d"; Layout.topMargin:4 }
                                ComboBox {
                                    objectName:"orientation_"+deviceEditor.index
                                    Layout.fillWidth:true; implicitHeight:38
                                    model:[window.t("Лёжа"),window.t("Вертикально")]
                                    currentIndex:manager.orientations[deviceEditor.index] ? 1 : 0
                                    onActivated:manager.setOrientation(deviceEditor.index,currentIndex===1)
                                    Accessible.name:modelData.name+" · "+window.t("Положение корпуса")
                                }
                            }
                        }
                        Text { Layout.fillWidth:true; text:window.t("Только вид в 3D. Сеть и разъёмы не меняются."); wrapMode:Text.WordWrap; color:"#63725d"; font.pixelSize:12 }
                        Rectangle { Layout.fillWidth: true; height: 1; color: "#e3e9de" }
                        Text { text: window.t("Как переключить порт"); font.pixelSize: 14; font.weight: Font.DemiBold; color: "#36532f" }
                        Text { Layout.fillWidth: true; text: window.t("Выгрузите модели. Переставьте кабель. Выберите разъёмы на схеме и примените подключение. Следующий запуск использует новую сеть."); wrapMode: Text.WordWrap; font.pixelSize: 13; color: "#63755c"; lineHeight: 1.25 }
                        Text { Layout.fillWidth: true; text: manager.topology.nodes.length===3 ? window.t("SSH третьего Spark настраивается через NVIDIA Sync. Режим трёх устройств экспериментальный до аппаратной проверки.") : window.t("Адреса кластера сохраняются при переносе кабеля на другой порт."); wrapMode: Text.WordWrap; font.pixelSize: 12; color: "#71816a" }
                        Item { Layout.fillHeight: true }
                        ActionButton { Layout.fillWidth: true; text: window.t("Проверить устройства"); enabled: !manager.busy; onClicked: { manager.refresh(); devices.search() } }
                        ActionButton { visible:devices.pending; Layout.fillWidth:true; text:window.t("Повторить настройку"); enabled:!manager.busy; onClicked:devices.retrySetup() }
                        ActionButton { Layout.fillWidth: true; text: window.t("Сохранить схему"); enabled: !manager.busy; onClicked: manager.saveDraft() }
                    }
                    }
                    ActionButton { id:applyTopology; anchors { left:parent.left; right:parent.right; bottom:parent.bottom; margins:18 } text:window.t("Применить подключение"); primary:true; enabled:!manager.busy; onClicked:manager.action('topology') }
                }
            }
            // Installation
            ScrollView {
                id: installScroll
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: installScroll.availableWidth; spacing: 16
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: 150; radius: 16; color: "#e4efd8"
                        RowLayout { anchors { fill: parent; margins: 24 } spacing: 24
                            ColumnLayout { Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 10; Text { text: window.t("Готовим Spark к работе"); font.pixelSize: 23; color: "#2d4d2c"; font.weight: Font.DemiBold } Text { Layout.fillWidth: true; text: window.t("Приложение установит недостающие инструменты, Unsloth Studio и согласованный RPC на втором Spark. Журнал показывает каждый этап."); wrapMode: Text.WordWrap; font.pixelSize: 14; color: "#55714b" } }
                            ActionButton { text: window.t("Установить и настроить"); primary: true; enabled: !manager.busy; onClicked: { manager.action('install'); window.page=4 } }
                        }
                    }
                    Repeater {
                        model: [{title:"Unsloth Studio",body:window.t("Модели, чат и OpenAI-совместимый API на первом Spark"),action:window.t("Открыть Studio"),key:"open"},{title:window.t("RPC на втором Spark"),body:window.t("Автозапуск службы и передача вычислений через ConnectX-7"),action:window.t("Проверить RPC"),key:"check"},{title:window.t("Системные инструменты"),body:window.t("SSH, rsync, CMake, компилятор CUDA и библиотеки RDMA"),action:window.t("Проверить установку"),key:"check"}]
                        Rectangle { required property var modelData; Layout.fillWidth: true; implicitHeight: 100; radius: 12; color: "#ffffff"; border.color: "#dce5d5"
                            RowLayout { anchors { fill: parent; margins: 20 } ColumnLayout { Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 8; Text { text:modelData.title; font.pixelSize: 17; font.weight: Font.DemiBold; color: "#2d432d" } Text { Layout.fillWidth: true; text:modelData.body; wrapMode: Text.WordWrap; font.pixelSize:13; color:"#6b7a62" } } ActionButton { text:modelData.action; enabled: !manager.busy; onClicked: modelData.key==='open' ? manager.open('studio') : manager.action(modelData.key) } }
                        }
                    }
                    Text { Layout.fillWidth: true; text: window.t("Для системных пакетов и изменения сети откроется терминал с запросом пароля администратора. Уже установленная пользовательская настройка запуска моделей сохраняется."); wrapMode: Text.WordWrap; color: "#687a60"; font.pixelSize: 13 }
                }
            }
            // Updates
            ColumnLayout {
                spacing: 18
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 205; radius: 16; color: "#ffffff"; border.color: "#dce5d5"
                    ColumnLayout { anchors { fill: parent; margins: 26 } spacing: 12
                        Text { text: "Unsloth Studio"; font.pixelSize: 23; color: "#2b412b"; font.weight: Font.DemiBold }
                        Text { text: manager.nodes.length && manager.nodes[0].version ? manager.nodes[0].version : window.t("Версия появится после проверки"); color:"#66805a"; font.pixelSize:14 }
                        Text { Layout.fillWidth: true; text: window.t("Официальное обновление Studio, затем согласование host и RPC. Во время обновления модели должны быть выгружены."); wrapMode:Text.WordWrap; color:"#62745a"; font.pixelSize:14 }
                        ActionButton { text: window.t("Обновить Studio и RPC"); primary: true; enabled: !manager.busy; onClicked: { manager.action('update'); window.page=4 } }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 180; radius: 16; color: "#e8efdf"
                    ColumnLayout { anchors { fill: parent; margins: 26 } spacing: 12
                        Text { text: window.t("Восстановление после обновления"); font.pixelSize:20; font.weight:Font.DemiBold; color:"#355331" }
                        Text { Layout.fillWidth:true; text:window.t("Если llama.cpp обновилась отдельно, согласуйте сборки перед следующим запуском модели. Это может занять несколько минут."); wrapMode:Text.WordWrap; color:"#63775a"; font.pixelSize:14 }
                        RowLayout { spacing:12; ActionButton { text:window.t("Согласовать сборки"); enabled:!manager.busy; onClicked:{ manager.action('refresh'); window.page=4 } } ActionButton { text:window.t("Запустить службу RPC"); enabled:!manager.busy; onClicked:manager.action('start-rpc') } }
                    }
                }
                Item { Layout.fillHeight: true }
                CheckBox { Layout.fillWidth:true; text:window.t("Запускать приложение в фоне при входе"); checked:manager.startupEnabled; onToggled:manager.setStartup(checked) }
                RowLayout {
                    ActionButton { text: window.t("Обновить Spark Link"); enabled: !manager.busy; onClicked: { manager.action('update-app'); window.page=4 } }
                    ActionButton { text: window.t("Запустить Studio"); enabled: !manager.busy; onClicked: manager.action('start-studio') }
                }
            }
            // Journal
            ColumnLayout {
                spacing: 12
                RowLayout { Layout.fillWidth: true; Text { text: window.t("Вывод последней операции"); font.pixelSize:15; color:"#506448" } Item { Layout.fillWidth: true } ActionButton { text:window.t("Логи Studio и RPC"); enabled:!manager.busy; onClicked:manager.action('rpc-logs') } ActionButton { text: window.t("Папка журналов"); onClicked: manager.open('logs') } }
                ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    TextArea { text: manager.logs.length ? manager.logs : window.t("Операций пока нет. Выберите проверку, установку или обновление — здесь появится полный журнал."); textFormat:TextEdit.PlainText; readOnly:true; selectByMouse:true; wrapMode:TextEdit.Wrap; font.family:"monospace"; font.pixelSize:12; color:"#d8e8c8"; padding:20; background: Rectangle { color:"#253325"; radius:12 } }
                }
            }
            MemoryPage {}
        }
        RowLayout { Layout.fillWidth:true; Text { text: manager.busy ? window.t("Выполняется операция…") : window.t("RPC продолжает работать при скрытом окне"); color:"#63725d"; font.pixelSize:11 } Item { Layout.fillWidth:true } Text { text: window.t("Данные обновляются каждые 15 секунд"); color:"#63725d"; font.pixelSize:11 } }
    }
    Dialog {
        id:onboard; objectName:"onboardDialog"
        anchors.centerIn:Overlay.overlay
        width:Math.min(560,window.width-48)
        modal:true; focus:true; padding:24
        title:window.t("Добавить новый Spark")
        onClosed:passwordField.clear()
        background:Rectangle { radius:16; color:"#f8fbf4"; border.color:"#b4c6a4" }
        contentItem:ColumnLayout {
            spacing:14
            Text { Layout.fillWidth:true; text:window.t("Адрес определён по кабелю ConnectX-7. Введите учётную запись нового Spark."); wrapMode:Text.WordWrap; color:"#4e6743"; font.pixelSize:14 }
            Rectangle { Layout.fillWidth:true; implicitHeight:connectionIdentity.implicitHeight+24; radius:9; color:"#e8f0de"
                ColumnLayout { id:connectionIdentity; anchors { left:parent.left; right:parent.right; top:parent.top; margins:12 } spacing:8
                    Text { Layout.fillWidth:true; textFormat:Text.PlainText; text:window.selectedCandidate.address || ''; wrapMode:Text.WrapAnywhere; font.family:"monospace"; font.pixelSize:13; color:"#36562c" }
                    Text { Layout.fillWidth:true; textFormat:Text.PlainText; text:window.selectedCandidate.fingerprint || ''; wrapMode:Text.WrapAnywhere; font.family:"monospace"; font.pixelSize:11; color:"#5f7355" }
                }
            }
            Text { visible:window.selectedCandidate.authorized===true; Layout.fillWidth:true; text:window.t("Доверенный SSH-доступ уже настроен. Логин и пароль не требуются."); wrapMode:Text.WordWrap; font.pixelSize:13; color:"#3f6331" }
            Text { visible:window.selectedCandidate.authorized!==true; text:window.t("Логин нового Spark"); font.pixelSize:13; color:"#415c36" }
            TextField { id:loginField; objectName:"newSparkLogin"; visible:window.selectedCandidate.authorized!==true; Layout.fillWidth:true; implicitHeight:42; placeholderText:"username"; selectByMouse:true; Accessible.name:window.t("Логин нового Spark") }
            Text { visible:window.selectedCandidate.authorized!==true; text:window.t("Пароль"); font.pixelSize:13; color:"#415c36" }
            TextField { id:passwordField; objectName:"newSparkPassword"; visible:window.selectedCandidate.authorized!==true; Layout.fillWidth:true; implicitHeight:42; echoMode:showPassword.checked ? TextInput.Normal : TextInput.Password; maximumLength:4096; Accessible.name:window.t("Пароль") }
            CheckBox { id:showPassword; visible:window.selectedCandidate.authorized!==true; text:window.t("Показать пароль"); checked:false }
            Text { Layout.fillWidth:true; text:window.t("Пароль сохраняется только в защищённом хранилище GNOME. Приложение проверит GPU и настроит дальнейший доступ по SSH-ключу."); wrapMode:Text.WordWrap; color:"#607456"; font.pixelSize:12 }
            RowLayout { Layout.fillWidth:true; spacing:12
                ActionButton { text:window.t("Отмена"); onClicked:onboard.close() }
                Item { Layout.fillWidth:true }
                ActionButton { text:window.t("Добавить и настроить"); primary:true; enabled:window.selectedCandidate.authorized===true || (/^[a-z_][a-z0-9_-]*[$]?$/.test(loginField.text) && passwordField.text.length>0); onClicked:{ if(window.selectedCandidate.authorized) devices.addTrusted(window.candidateIndex); else devices.authorize(window.candidateIndex,loginField.text,passwordField.text); passwordField.clear(); onboard.close() } }
            }
        }
    }
}

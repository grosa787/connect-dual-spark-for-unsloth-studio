import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: memory
    clip:true; contentWidth:availableWidth
    function t(source) { let language=manager.language; return manager.translate(source) }
    property var variants:planner.analysis.variants || []
    property var variant:variants[Number(planner.form.variant_index)] || ({})
    property real modelSize:planner.form.manual ? Number(planner.form.weights_gib) : (variant.size_bytes || 0)/1073741824
    property real totalPercent:planner.percentages.reduce((a,b)=>a+Number(b),0)
    ColumnLayout {
        width:memory.availableWidth; spacing:16
        RowLayout {
            Layout.fillWidth:true; spacing:12
            ComboBox {
                objectName:"modelSourceSelector"; Layout.fillWidth:true; implicitHeight:42
                model:[memory.t("Ссылка Hugging Face / GGUF"),memory.t("Ручной расчёт")]
                currentIndex:planner.form.manual ? 1 : 0
                onActivated:planner.setField('manual',currentIndex===1 ? 'true' : 'false')
                Accessible.name:memory.t("Источник модели")
            }
            ComboBox {
                Layout.fillWidth:true; implicitHeight:42
                model:planner.savedPlans
                displayText:memory.t("Сохранённые планы")
                onActivated:planner.loadPlan(currentIndex)
                Accessible.name:memory.t("Сохранённые планы")
            }
        }
        Rectangle {
            Layout.fillWidth:true; implicitHeight:planMessage.implicitHeight+28; radius:10
            color:planner.result.fits ? "#e4efd9" : memory.modelSize>0 ? "#f1eadb" : "#eaf0e4"; border.color:planner.result.fits ? "#c4d8b0" : "#d4decb"
            Text { id:planMessage; anchors { left:parent.left; right:parent.right; margins:14; verticalCenter:parent.verticalCenter } text:planner.message; wrapMode:Text.WordWrap; font.pixelSize:13; color:"#46583a" }
        }
        RowLayout {
            Layout.fillWidth:true; spacing:16
            ColumnLayout {
                Layout.preferredWidth:340; Layout.minimumWidth:300; Layout.alignment:Qt.AlignTop; spacing:16
                Rectangle {
                    Layout.fillWidth:true; implicitHeight:sourceFields.implicitHeight+40; radius:12; color:"white"; border.color:"#dce5d5"
                    ColumnLayout {
                        id:sourceFields; anchors { left:parent.left; right:parent.right; top:parent.top; margins:20 } spacing:12
                        Text { text:memory.t("Модель и размер весов"); font.pixelSize:17; font.weight:Font.DemiBold; color:"#2d432d" }
                        ValueField {
                            Layout.fillWidth:true; label:planner.form.manual ? memory.t("Путь к GGUF для сохранения плана") : memory.t("ID или HTTPS-ссылка Hugging Face")
                            value:planner.form.reference; placeholder:"owner/model-GGUF"
                            onCommitted:planner.setField('reference',text)
                        }
                        RowLayout {
                            Layout.fillWidth:true; spacing:8
                            ActionButton { Layout.fillWidth:true; text:memory.t("Выбрать GGUF"); enabled:!planner.busy; onClicked:{ let p=manager.chooseModelFile(); if(p.length) { planner.setField('reference',p); if(!planner.form.manual) planner.analyze(p) } } }
                            ActionButton { visible:!planner.form.manual; Layout.fillWidth:true; text:memory.t("Распознать"); primary:true; enabled:!planner.busy; onClicked:planner.analyze(planner.form.reference) }
                        }
                        ProgressBar { visible:planner.busy; indeterminate:true; Layout.fillWidth:true }
                        ComboBox {
                            visible:!planner.form.manual && memory.variants.length>0
                            Layout.fillWidth:true; implicitHeight:40
                            model:memory.variants.map(v=>v.label+" · "+(v.size_bytes/1073741824).toFixed(2)+" GiB")
                            currentIndex:Number(planner.form.variant_index)
                            onActivated:planner.setField('variant_index',String(currentIndex))
                            Accessible.name:memory.t("Вариант квантования")
                        }
                        ValueField { Layout.fillWidth:true; label:memory.t("Общий размер весов, GiB"); value:memory.modelSize>0 ? memory.modelSize.toFixed(3) : ''; numeric:true; editable:planner.form.manual; onCommitted:planner.setField('weights_gib',text) }
                        Text { Layout.fillWidth:true; textFormat:Text.PlainText; text:memory.t("Максимум контекста")+": "+(planner.analysis.max_context || memory.t("неизвестен")); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#5c7053" }
                        Text { visible:planner.analysis.cached===true; Layout.fillWidth:true; text:memory.t("Используются сохранённые метаданные. Интернет сейчас не требуется."); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#526c43" }
                        Text { visible:planner.form.manual; Layout.fillWidth:true; text:memory.t("Для расчёта путь не нужен. Для применения выберите конкретный GGUF-файл."); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#62765a" }
                    }
                }
                Rectangle {
                    Layout.fillWidth:true; implicitHeight:cacheFields.implicitHeight+40; radius:12; color:"white"; border.color:"#dce5d5"
                    ColumnLayout {
                        id:cacheFields; anchors { left:parent.left; right:parent.right; top:parent.top; margins:20 } spacing:12
                        Text { text:memory.t("Контекст и KV-кеш"); font.pixelSize:17; font.weight:Font.DemiBold; color:"#2d432d" }
                        ValueField { Layout.fillWidth:true; label:memory.t("Контекст следующего запуска, токенов"); value:String(planner.form.context); numeric:true; onCommitted:planner.setField('context',text) }
                        ComboBox { Layout.fillWidth:true; implicitHeight:40; model:['KV: f16','KV: q8_0','KV: q4_0']; currentIndex:['f16','q8_0','q4_0'].indexOf(planner.form.dtype); onActivated:planner.setField('dtype',['f16','q8_0','q4_0'][currentIndex]); Accessible.name:memory.t("Тип KV-кеша") }
                        CheckBox { Layout.fillWidth:true; text:memory.t("Задать KV-кеш вручную"); checked:planner.form.manual_kv; onToggled:planner.setField('manual_kv',checked ? 'true' : 'false') }
                        ValueField { Layout.fillWidth:true; visible:planner.form.manual_kv; label:memory.t("Общий бюджет KV-кеша, GiB"); numeric:true; value:String(planner.form.cache_gib); onCommitted:planner.setField('cache_gib',text) }
                        Text { Layout.fillWidth:true; text:memory.t("KV-кеш всего")+": "+(planner.cacheKnown && planner.result.kv_gib!==undefined ? planner.result.kv_gib.toFixed(2)+" GiB" : memory.t("нужен ручной бюджет")); wrapMode:Text.WordWrap; font.pixelSize:13; color:"#355331" }
                        Text { Layout.fillWidth:true; text:planner.cacheQuality==='observed' ? memory.t("По журналу прежнего запуска с тем же контекстом и типом кеша.") : planner.cacheQuality==='manual' ? memory.t("Используется введённый вами бюджет кеша.") : memory.t("Расчёт приблизительный. Сжатые и гибридные архитектуры требуют отдельных данных."); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#62765a" }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth:true; Layout.minimumWidth:330; Layout.alignment:Qt.AlignTop
                implicitHeight:allocationFields.implicitHeight+40; radius:12; color:"white"; border.color:"#dce5d5"
                ColumnLayout {
                    id:allocationFields; anchors { left:parent.left; right:parent.right; top:parent.top; margins:20 } spacing:14
                    Text { text:memory.t("Распределение по Spark"); font.pixelSize:18; font.weight:Font.DemiBold; color:"#2d432d" }
                    Text { Layout.fillWidth:true; text:memory.t("Первому Spark оставляем больше памяти под Studio и служебный кеш."); wrapMode:Text.WordWrap; font.pixelSize:13; color:"#617458" }
                    RowLayout {
                        Layout.fillWidth:true; spacing:10
                        ValueField { Layout.fillWidth:true; label:memory.t("Резерв первого, GiB"); value:String(planner.form.head_reserve); numeric:true; onCommitted:planner.setField('head_reserve',text) }
                        ValueField { Layout.fillWidth:true; label:memory.t("Резерв остальных, GiB"); value:String(planner.form.worker_reserve); numeric:true; onCommitted:planner.setField('worker_reserve',text) }
                    }
                    ComboBox { Layout.fillWidth:true; implicitHeight:40; model:[memory.t("Доли весов в процентах"),memory.t("Объём весов в GiB")]; currentIndex:planner.form.units==='gib' ? 1 : 0; onActivated:planner.setField('units',currentIndex===1 ? 'gib' : 'percent'); Accessible.name:memory.t("Единицы распределения") }
                    Repeater {
                        model:manager.nodes
                        ColumnLayout {
                            required property var modelData
                            required property int index
                            property var allocation:planner.result.allocations ? planner.result.allocations[index] : ({})
                            Layout.fillWidth:true; spacing:8
                            Rectangle { Layout.fillWidth:true; height:1; color:"#e1e8dc" }
                            RowLayout {
                                Layout.fillWidth:true; spacing:12
                                ColumnLayout { Layout.fillWidth:true; Layout.minimumWidth:0; spacing:5
                                    Text { text:modelData.name; font.pixelSize:14; font.weight:Font.DemiBold; color:"#2e472c" }
                                    Text { Layout.fillWidth:true; text:modelData.online ? memory.t("Доступно")+": "+((modelData.model_active ? modelData.memory_total : modelData.memory_available)/1048576).toFixed(1)+" GiB" : memory.t("Не подключён"); font.pixelSize:12; color:"#65785e"; wrapMode:Text.WordWrap }
                                }
                                ValueField {
                                    Layout.preferredWidth:100; label:planner.form.units==='gib' ? memory.t("Веса, GiB") : memory.t("Доля, %")
                                    value:planner.percentages[index]!==undefined ? (planner.form.units==='gib' ? planner.percentages[index]*memory.modelSize/100 : planner.percentages[index]).toFixed(2) : '0'
                                    numeric:true; editable:modelData.online; onCommitted:planner.setPercentage(index,text)
                                }
                            }
                            Text { Layout.fillWidth:true; text:memory.t("Веса")+": "+((planner.percentages[index] || 0)*memory.modelSize/100).toFixed(2)+" GiB  ·  KV: "+(allocation.kv_gib!==undefined ? allocation.kv_gib.toFixed(2)+" GiB" : "—"); font.pixelSize:12; color:"#52694a"; wrapMode:Text.WordWrap }
                            Text { Layout.fillWidth:true; text:memory.t("Останется")+": "+(allocation.remaining_gib!==undefined ? allocation.remaining_gib.toFixed(2)+" GiB" : "—"); font.pixelSize:12; color:allocation.fits===false ? "#8b4a25" : "#426f31"; wrapMode:Text.WordWrap }
                        }
                    }
                    Text { visible:memory.modelSize>0; text:memory.t("Сумма долей")+": "+memory.totalPercent.toFixed(2)+"%"; font.pixelSize:14; font.weight:Font.DemiBold; color:Math.abs(memory.totalPercent-100)<0.05 ? "#426f31" : "#8b4a25" }
                    Text { visible:planner.result.assumes_unloaded===true; Layout.fillWidth:true; text:memory.t("Расчёт предполагает выгрузку уже работающих моделей перед новым запуском."); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#886033" }
                    Text { Layout.fillWidth:true; text:memory.t("Доли применяются по слоям и могут немного округляться. При изменении числа доступных Spark план пересчитывается автоматически."); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#62765a" }
                    Text { Layout.fillWidth:true; text:memory.t("В расчёте также заложены 4 GiB на вычислительные буферы каждого активного узла."); wrapMode:Text.WordWrap; font.pixelSize:12; color:"#62765a" }
                    ActionButton { Layout.fillWidth:true; text:memory.t("Распределить автоматически"); enabled:!planner.busy && memory.modelSize>0 && planner.cacheKnown; onClicked:planner.autoAllocate() }
                    ActionButton { objectName:"saveMemoryPlan"; Layout.fillWidth:true; text:memory.t("Сохранить для следующего запуска"); primary:true; enabled:!planner.busy && !manager.busy && planner.result.can_save===true; onClicked:planner.savePlan() }
                }
            }
        }
    }
}

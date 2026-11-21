# ESP32 Xiaomi Sensor Manager

Специализированная интеграция Home Assistant для ESP32-шлюзов с BLE-датчиками Xiaomi LYWSD03MMC.

> Статус: архитектура, в которой интеграция Xiaomi управляет устройствами и измерительными сущностями датчиков, реализована. Сквозная проверка требует Home Assistant, MQTT-брокера и ESP32 firmware.

## Установка через HACS

1. Откройте **HACS → Integrations**.
2. Откройте меню в правом верхнем углу и выберите **Custom repositories**.
3. Добавьте репозиторий `lavrenovalexsandr-cmyk/esp32-integration-xiaomi-sensor-manager` с категорией **Integration**.
4. Найдите **ESP32 Xiaomi Sensor Manager** и установите интеграцию.
5. Установите и настройте **ESP32 Manager** до добавления Xiaomi-интеграции.
6. Перезапустите Home Assistant.
7. В **Settings → Devices & services → Add integration** найдите **ESP32 Xiaomi Sensor Manager** и добавьте её.

Отдельно настройте штатную интеграцию **MQTT** в Home Assistant и убедитесь, что брокер подключён к ESP32. Xiaomi-интеграция использует уже настроенное MQTT-подключение и не требует адреса брокера или учётных данных в своей конфигурации.

Для установки через Custom repository GitHub Release не обязателен: если релизов нет, HACS использует короткий hash последнего commit как версию. Для обычных версионированных обновлений рекомендуется публиковать GitHub Release с тегом версии, согласованным с `manifest.json`. До установки через HACS можно также скопировать каталог `custom_components/esp32_xiaomi_lywsd03` в `config/custom_components/` вручную.

## Сущности Home Assistant и панель управления

Интеграция самостоятельно создаёт для каждого сохранённого Xiaomi LYWSD03MMC отдельное HA-устройство с тремя измерительными сущностями: температурой, влажностью и зарядом батареи. Устройство датчика связывается с родительским ESP32-шлюзом через `via_device`.

Панель **Xiaomi Sensor Manager** входит в этот же репозиторий и появляется в боковом меню Home Assistant после настройки интеграции. Она предназначена для администраторов. Отдельная Lovelace-карточка или второй HACS-репозиторий не требуются.

## Назначение и границы ответственности

Интеграция обслуживает Xiaomi-специфичные операции и координацию нескольких ESP32-шлюзов. Общие функции управления ESP32 (OTA, Restart, Factory Reset) остаются в универсальной интеграции `esp32_ota`; базовая идентификация шлюза относится к Platform Core и общему MQTT-контракту.

Распределение ответственности:

- **Firmware:** BLE-обнаружение, хранение bind-key в NVS, реестр, команды и результаты команд, retained snapshots и retained измерения по MQTT v1.
- **Platform Core:** общая идентичность и доступность ESP32, MQTT и Discovery только для общих сущностей шлюза. Xiaomi-сущности через Platform Core Discovery не создаются.
- **ESP32 Manager (`esp32_ota`):** единственный источник общих сведений о шлюзах; обнаружение, identity, profile, availability, общая запись Device Registry, публичный API и события жизненного цикла; OTA и общие системные команды.
- **Platform Core:** стабильная аппаратная идентичность, общие MQTT-контракты и платформенные механизмы прошивки.
- **Эта Xiaomi-интеграция:** только Xiaomi snapshots и measurements, доменное состояние по каждому шлюзу, правило «один MAC — один шлюз», сервисы add/remove, безопасная передача bind-key, создание/удаление дочерних Xiaomi-устройств и сенсоров, панель управления.
- **Панель Xiaomi Sensor Manager:** выбор шлюза и датчика, отображение `New`/`Save`, добавление и удаление через сервисы интеграции. Панель не публикует MQTT напрямую и не сохраняет bind-key.

## Общая идентификация ESP32-шлюза

Xiaomi Sensor Manager объявляет `esp32_ota` обязательной зависимостью в `manifest.json`. ESP32 Manager создаёт общую запись физического устройства с identifier:

```python
identifiers={("esp32", device_id)}
```

Xiaomi-интеграция не подписывается на общие MQTT-топики identity, profile и availability, не создаёт запись шлюза в Device Registry и не хранит собственную копию общих метаданных. При запуске она получает snapshot устройств через публичный API `hass.data["esp32_ota"]["api"]`, затем обновляет свой runtime-проекционный статус по событиям `esp32_ota_device_added` и `esp32_ota_device_updated`.

Из API используются `get_devices()` и `get_device(device_id)`. Для каскадного удаления Xiaomi Sensor Manager регистрирует собственный async cleanup handler через `register_remove_handler`. Интеграция продолжает самостоятельно обрабатывать только продуктовые топики Xiaomi: discovered, registry, command/result и sensor measurements.

## Возможности

- Работа с несколькими ESP32-шлюзами.
- Получение отдельно для каждого шлюза retained-списков `discovered` и `registry`.
- Сервисы добавления и удаления датчиков.
- Проверка, что MAC не сохранён и не добавляется одновременно на другом известном шлюзе.
- Корреляция результата команды по паре gateway device ID + `request_id`.
- Обработка offline/reconnect и повторная синхронизация по retained snapshots.
- Безопасная передача bind-key без сохранения его в Home Assistant.

## Идентификаторы и сервисы

Домен интеграции и сервисов: `esp32_xiaomi_lywsd03`.

Сервисы:

- `esp32_xiaomi_lywsd03.add_sensor`
- `esp32_xiaomi_lywsd03.remove_sensor`

Поля `add_sensor`:

- `device_id` — стабильный ID выбранного ESP32-шлюза из MQTT identity;
- `mac` — MAC датчика в формате `AA:BB:CC:DD:EE:FF`;
- `bind_key` — ровно 32 шестнадцатеричных символа (16 байт).

Поля `remove_sensor`:

- `device_id` — стабильный ID выбранного ESP32-шлюза;
- `mac` — MAC датчика.

Используем стабильный `device_id` из MQTT identity. Он совпадает с ID, используемым сервисами `esp32_ota`, но Xiaomi-интеграция не зависит от наличия этой интеграции. Идентификатор шлюза не является MAC датчика.

## Состояние датчиков

Для выбранного шлюза UI объединяет два независимых retained snapshot:

- **New** — MAC присутствует в `discovered`, но отсутствует в `registry`;
- **Save** — MAC присутствует в `registry`.

После успешного удаления датчик исключается из `registry`. Если шлюз продолжает получать его BLE-рекламу, датчик снова присутствует в `discovered` и отображается как **New**. Удалённые элементы не должны искусственно скрываться из списка обнаруженных.

Snapshots всегда хранятся раздельно по gateway device ID. Один MAC может быть обнаружен несколькими шлюзами, но может быть сохранён только на одном шлюзе одновременно.

## Home Assistant устройства и Areas

ESP32 Manager создаёт общую запись физического шлюза. Xiaomi Sensor Manager создаёт дочернее HA-устройство для каждого MAC из retained `registry` и три сущности: температуру, влажность и батарею. В `device_info` дочернего устройства указывается `via_device` с общим идентификатором ESP32 `("esp32", device_id)`. При исключении MAC из registry интеграция удаляет соответствующие сенсоры и устройство. Неизвестные измерения остаются `unknown`, пока датчик не передаст соответствующие данные.

Интеграция подписывается на `esp32/+/xiaomi/sensor/+/state`. Обработка продуктовых сообщений разрешается только для шлюзов, уже известных ESP32 Manager. Общие identity/profile/availability обрабатывает Manager. Доступность сенсоров зависит от центрального availability и валидности профиля.

Комнаты не передаются по MQTT и не хранятся в firmware. Пользователь назначает Area штатными средствами Home Assistant.

## Безопасность

- Bind-key передаётся только в MQTT-команде add.
- Ключ не сохраняется в config entry, options, реестре, diagnostics, событиях или состояниях Home Assistant.
- Ключ не включается в логи, ошибки и подтверждения сервисов.
- Перед отправкой проверяются MAC и формат ключа.
- Команда адресуется только выбранному шлюзу.
- MQTT-команды публикуются с `retain=false`.
- После отправки ключ не должен оставаться в долгоживущем состоянии интеграции или панели.

## MQTT-контракт

MQTT v1 согласован и реализован на стороне firmware. Спецификация:

- [MQTT protocol v1 — RU](docs/MQTT_PROTOCOL_RU.md)
- [MQTT protocol v1 — EN](docs/MQTT_PROTOCOL_EN.md)

Она определяет топики, payload, retained snapshots, команды add/remove, результаты, измерения, reconnect и безопасность. Создание Xiaomi-сущностей выполняет HA integration, а не MQTT Discovery firmware. Реализация интеграции должна соответствовать спецификации и фактическому поведению firmware.

## Панель Xiaomi Sensor Manager

Панель входит в этот репозиторий интеграции, регистрируется как custom panel Home Assistant и доступна администраторам. Она должна:

1. позволять выбрать ESP32-шлюз, известный Xiaomi-интеграции по MQTT identity, независимо от установки `esp32_ota`;
2. показывать обнаруженные и сохранённые датчики выбранного шлюза;
3. помечать сохранённые датчики как **Save**, новые — как **New**;
4. предоставлять поле bind-key только для добавления;
5. позволять удалить сохранённый датчик в той же панели;
6. вызывать `esp32_xiaomi_lywsd03.add_sensor` и `esp32_xiaomi_lywsd03.remove_sensor`.

Панель получает состояние через WebSocket API интеграции и вызывает её сервисы. Она не обращается к MQTT-брокеру напрямую.

После удаления датчик остаётся в общем списке, если он продолжает обнаруживаться; меняется только его статус с **Save** на **New**.

## Этапы реализации

1. Основа HA-интеграции, config flow и подписки на MQTT v1 — реализованы.
2. Раздельное состояние snapshots по шлюзам и восстановление из retained snapshots — реализованы.
3. Add/remove services, проверка MAC между шлюзами и корреляция command/result — реализованы.
4. WebSocket API состояния и события для ESP32 Xiaomi Sensor Manager — реализованы.
5. Создание HA sensor entities и дочерних устройств по retained registry — реализовано; проверка в работающем HA ожидается.
6. Панель Xiaomi Sensor Manager в составе интеграции — реализована; проверка в работающем HA ожидается.
7. Требуется эксплуатационная проверка нескольких шлюзов, offline/reconnect, повторной доставки QoS 1, динамического удаления сущностей и Areas.

## Связанные проекты

- [Firmware](https://github.com/lavrenovalexsandr-cmyk/esp32-firmware-xiaomi-lywsd03)
- [Универсальная ESP32-интеграция](https://github.com/lavrenovalexsandr-cmyk/esp32-integration-manager)
- [ESP32 Platform Core](https://github.com/lavrenovalexsandr-cmyk/esp32-platform-core)
- [ESP32 Platform BLE](https://github.com/lavrenovalexsandr-cmyk/esp32-component-ble)
- [Xiaomi LYWSD03MMC driver](https://github.com/lavrenovalexsandr-cmyk/esp32-component-xiaomi-lywsd03)

Основная документация — README.md на русском языке; английская версия — README_EN.md.

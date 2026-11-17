# ESP32 Home Assistant Integration — Xiaomi LYWSD03MMC

Специализированная интеграция Home Assistant для ESP32-шлюзов с BLE-датчиками Xiaomi LYWSD03MMC.

> Статус: первая версия Python-интеграции реализована в `custom_components/esp32_xiaomi_lywsd03` и подготовлена для установки через HACS. Требуется проверка в реальном Home Assistant с MQTT-брокером и ESP32 firmware.

## Установка через HACS

1. Откройте **HACS → Integrations**.
2. Откройте меню в правом верхнем углу и выберите **Custom repositories**.
3. Добавьте репозиторий `lavrenovalexsandr-cmyk/esp32-integration-xiaomi-lywsd03` с категорией **Integration**.
4. Найдите **ESP32 Xiaomi LYWSD03MMC** и установите интеграцию.
5. Перезапустите Home Assistant.
6. В **Settings → Devices & services → Add integration** найдите **ESP32 Xiaomi LYWSD03MMC** и добавьте её.

Отдельно настройте штатную интеграцию **MQTT** в Home Assistant и убедитесь, что брокер подключён к ESP32. Xiaomi-интеграция использует уже настроенное MQTT-подключение и не требует адреса брокера или учётных данных в своей конфигурации.

Для установки через HACS нужен опубликованный GitHub Release с тегом, совпадающим с версией в `manifest.json`. До первого стабильного релиза репозиторий можно проверять вручную, скопировав каталог `custom_components/esp32_xiaomi_lywsd03` в `config/custom_components/`.

## Сущность шлюза и данные для карточки

Для каждого обнаруженного ESP32 создаётся одна служебная сущность `sensor.<gateway>_xiaomi_sensors` в общей записи устройства ESP32. Она не является сущностью измерений Xiaomi. Атрибуты:

- `device_id` — стабильный ID шлюза;
- `available` — последнее состояние availability;
- `discovered` — список обнаруженных MAC;
- `registry` — список сохранённых MAC;
- `pending` — ожидающие команды;
- `last_result` — результат последней завершившейся команды.

Измерения температуры, влажности и батареи по-прежнему создаются firmware через MQTT Discovery.

## Назначение и границы ответственности

Интеграция обслуживает Xiaomi-специфичные операции и координацию нескольких ESP32-шлюзов. Общие функции управления ESP32 (OTA, Restart, Factory Reset) остаются в универсальной интеграции `esp32_ota`; базовая идентификация шлюза относится к Platform Core и общему MQTT-контракту.

Распределение ответственности:

- **Firmware / Platform Core:** BLE-обнаружение, хранение bind-key в NVS, MQTT v1, публикация retained snapshots и измерений, Home Assistant MQTT Discovery датчиков.
- **Универсальная интеграция `esp32_ota`:** OTA и общие команды управления; она также использует общую запись шлюза в HA, но не является обязательной для Xiaomi-интеграции.
- **Общий MQTT-контракт / Platform Core:** стабильная идентичность шлюза и его базовые данные.
- **Эта Xiaomi-интеграция:** получение MQTT snapshots, поддержка состояния по каждому шлюзу, глобальная проверка правила «один MAC — один шлюз», сервисы add/remove и безопасная передача bind-key.
- **Lovelace card:** выбор шлюза/датчика и вызов сервисов этой интеграции. Карточка не публикует MQTT напрямую и не сохраняет bind-key.

Xiaomi-интеграция не создаёт собственные устройства датчиков и не дублирует их измерительные сущности: три сущности каждого датчика создаются штатным MQTT Discovery firmware через Platform Core. Для интерфейса управления интеграция предоставляет WebSocket API состояния и события обновления.

## Общая идентификация ESP32-шлюза

Xiaomi-интеграция независима от `esp32_ota`: она не должна импортировать её код или требовать её установки.

Для объединения сведений разных ESP32-интеграций в одну запись Home Assistant Device Registry используется общий идентификатор шлюза:

```python
identifiers={("esp32", device_id)}
```

Здесь `esp32` — общий namespace платформы, а `device_id` — стабильный ID из MQTT identity. Имя и модель шлюза берутся из тех же полей MQTT identity (`name` и `model`), чтобы интеграции показывали согласованные данные.

**Реализация:** интеграция самостоятельно получает MQTT identity шлюзов и использует `("esp32", device_id)` при регистрации/обогащении gateway device. Она не использует `("esp32_ota", device_id)` и не зависит от наличия `esp32_ota`. Сервисы Xiaomi принимают стабильный `device_id`.

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

Xiaomi-интеграция самостоятельно получает MQTT identity шлюзов и использует общий Device Registry identifier `("esp32", device_id)`. Если `esp32_ota` установлена, обе интеграции дополняют одну запись шлюза, а не создают две. Firmware через Platform Core MQTT Discovery создаёт самостоятельное HA-устройство для каждого Xiaomi-датчика и три сущности: температуру, влажность и батарею. Неизвестные измерения остаются `unknown`, пока датчик не передаст соответствующие данные.

Текущая реализация Platform Core не формирует `via_device`, поэтому связь дочернего датчика с устройством шлюза через device registry пока не создаётся. Не дублировать эту связь собственными механизмами в Xiaomi-интеграции.

Комнаты не передаются по MQTT и не хранятся в firmware. Пользователь назначает Area штатными средствами Home Assistant.

## Безопасность

- Bind-key передаётся только в MQTT-команде add.
- Ключ не сохраняется в config entry, options, реестре, diagnostics, событиях или состояниях Home Assistant.
- Ключ не включается в логи, ошибки и подтверждения сервисов.
- Перед отправкой проверяются MAC и формат ключа.
- Команда адресуется только выбранному шлюзу.
- MQTT-команды публикуются с `retain=false`.
- После отправки ключ не должен оставаться в долгоживущем состоянии интеграции или карточки.

## MQTT-контракт

MQTT v1 согласован и реализован на стороне firmware. Спецификация:

- [MQTT protocol v1 — RU](docs/MQTT_PROTOCOL_RU.md)
- [MQTT protocol v1 — EN](docs/MQTT_PROTOCOL_EN.md)

Она определяет топики, payload, retained snapshots, команды add/remove, результаты, измерения, reconnect, безопасность и ограничение HA entity registry в Platform Core. Реализация интеграции должна соответствовать спецификации и фактическому поведению firmware.

## Карточка

UI находится в репозитории [esp32-card](https://github.com/lavrenovalexsandr-cmyk/esp32-card). Xiaomi Sensor Manager должна:

1. позволять выбрать ESP32-шлюз, известный Xiaomi-интеграции по MQTT identity, независимо от установки `esp32_ota`;
2. показывать обнаруженные и сохранённые датчики выбранного шлюза;
3. помечать сохранённые датчики как **Save**, новые — как **New**;
4. предоставлять поле bind-key только для добавления;
5. позволять удалить сохранённый датчик в той же карточке;
6. вызывать `esp32_xiaomi_lywsd03.add_sensor` и `esp32_xiaomi_lywsd03.remove_sensor`.

После удаления датчик остаётся в общем списке, если он продолжает обнаруживаться; меняется только его статус с **Save** на **New**.

## Этапы реализации

1. Основа HA-интеграции, config flow и подписки на MQTT v1 — реализованы.
2. Раздельное состояние snapshots по шлюзам и восстановление из retained snapshots — реализованы.
3. Add/remove services, проверка MAC между шлюзами и корреляция command/result — реализованы.
4. WebSocket API состояния и события для Xiaomi Sensor Manager — реализованы.
5. Xiaomi Sensor Manager card — отдельная задача в репозитории esp32-card.
6. Требуется эксплуатационная проверка нескольких шлюзов, offline/reconnect, повторной доставки QoS 1 и Areas.

## Связанные проекты

- [Firmware](https://github.com/lavrenovalexsandr-cmyk/esp32-firmware-xiaomi-lywsd03)
- [Универсальная ESP32-интеграция](https://github.com/lavrenovalexsandr-cmyk/esp32-integration-core)
- [ESP32 Platform Core](https://github.com/lavrenovalexsandr-cmyk/esp32-platform-core)
- [ESP32 Platform BLE](https://github.com/lavrenovalexsandr-cmyk/esp32-component-ble)
- [Xiaomi LYWSD03MMC driver](https://github.com/lavrenovalexsandr-cmyk/esp32-component-xiaomi-lywsd03)
- [ESP32 Lovelace Cards](https://github.com/lavrenovalexsandr-cmyk/esp32-card)

Основная документация — README.md на русском языке; английская версия — README_EN.md.

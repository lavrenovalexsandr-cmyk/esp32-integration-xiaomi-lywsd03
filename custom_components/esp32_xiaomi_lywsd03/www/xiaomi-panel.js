class Esp32XiaomiSensorManager extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._gateways = [];
    this._selectedGateway = "";
    this._selectedMac = "";
    this._unsubscribe = null;
    this._loading = false;
    this._busy = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._ensureSubscription();
    this._loadState();
  }

  connectedCallback() {
    this._render();
    this._ensureSubscription();
    this._loadState();
  }

  disconnectedCallback() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
  }

  async _ensureSubscription() {
    if (!this._hass || this._unsubscribe || !this.isConnected) return;
    try {
      this._unsubscribe = await this._hass.connection.subscribeEvents(
        () => this._loadState(),
        "esp32_xiaomi_lywsd03_state_updated"
      );
    } catch (error) {
      this._showMessage(this._errorText(error), true);
    }
  }

  async _loadState() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    try {
      const result = await this._hass.callWS({
        type: "esp32_xiaomi_lywsd03/get_state"
      });
      this._gateways = Array.isArray(result.gateways) ? result.gateways : [];
      if (!this._gateways.some((item) => item.device_id === this._selectedGateway)) {
        this._selectedGateway = this._gateways[0]?.device_id || "";
      }
      this._renderData();
    } catch (error) {
      this._showMessage(this._errorText(error), true);
    } finally {
      this._loading = false;
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; padding:24px; color:var(--primary-text-color); }
        .content { max-width:760px; margin:0 auto; }
        h1 { font-size:24px; font-weight:500; margin:0 0 8px; }
        p { color:var(--secondary-text-color); line-height:1.5; }
        .card { background:var(--card-background-color); border-radius:12px; padding:20px; box-shadow:var(--ha-card-box-shadow, 0 2px 8px #0002); }
        label { display:block; font-size:14px; margin:16px 0 6px; }
        select, input { box-sizing:border-box; width:100%; min-height:44px; padding:8px 12px; border:1px solid var(--outline-color); border-radius:8px; background:var(--input-fill-color, var(--card-background-color)); color:var(--primary-text-color); font:inherit; }
        .status { margin-top:14px; color:var(--secondary-text-color); font-size:14px; }
        .tag { display:inline-block; border-radius:16px; padding:3px 10px; margin-left:8px; font-size:12px; background:var(--secondary-background-color); }
        .actions { display:flex; gap:12px; margin-top:18px; flex-wrap:wrap; }
        button { border:0; border-radius:8px; padding:10px 18px; min-height:40px; font:inherit; cursor:pointer; background:var(--primary-color); color:var(--text-primary-color, white); }
        button.secondary { background:var(--secondary-background-color); color:var(--primary-text-color); }
        button:disabled { opacity:.45; cursor:not-allowed; }
        .message { min-height:22px; margin-top:14px; color:var(--success-color); overflow-wrap:anywhere; }
        .message.error { color:var(--error-color); }
        .empty { padding:14px 0; color:var(--secondary-text-color); }
        @media (max-width:600px) { :host { padding:16px; } .card { padding:16px; } }
      </style>
      <div class="content">
        <h1>Xiaomi Sensor Manager</h1>
        <p>Управление BLE-датчиками Xiaomi LYWSD03MMC через ESP32-шлюзы.</p>
        <div class="card">
          <label for="gateway">ESP32-шлюз</label>
          <select id="gateway"></select>
          <div id="gateway-status" class="status"></div>

          <label for="sensor">Датчик</label>
          <select id="sensor"></select>
          <div id="sensor-status" class="status"></div>

          <div id="key-row">
            <label for="bind-key">Bind Key (32 hex-символа)</label>
            <input id="bind-key" type="password" autocomplete="off" spellcheck="false" maxlength="32" placeholder="0123456789ABCDEF0123456789ABCDEF">
          </div>
          <div class="actions">
            <button id="add">Добавить датчик</button>
            <button id="remove" class="secondary">Удалить датчик</button>
            <button id="refresh" class="secondary">Обновить</button>
          </div>
          <div id="message" class="message" role="status" aria-live="polite"></div>
        </div>
      </div>
    `;

    this.shadowRoot.getElementById("gateway").addEventListener("change", (event) => {
      this._selectedGateway = event.target.value;
      this._selectedMac = "";
      this._renderData();
    });
    this.shadowRoot.getElementById("sensor").addEventListener("change", (event) => {
      this._selectedMac = event.target.value;
      this._renderSelection();
    });
    this.shadowRoot.getElementById("add").addEventListener("click", () => this._addSensor());
    this.shadowRoot.getElementById("remove").addEventListener("click", () => this._removeSensor());
    this.shadowRoot.getElementById("refresh").addEventListener("click", () => this._loadState());
  }

  _selectedGatewayData() {
    return this._gateways.find((item) => item.device_id === this._selectedGateway) || null;
  }

  _sensorOptions(gateway) {
    if (!gateway) return [];
    const discovered = Array.isArray(gateway.discovered) ? gateway.discovered : [];
    const registry = Array.isArray(gateway.registry) ? gateway.registry : [];
    const saved = new Set(registry);
    const items = new Map();
    for (const item of discovered) items.set(item.mac, item);
    for (const mac of registry) if (!items.has(mac)) items.set(mac, { mac });
    return [...items.values()].sort((a, b) => a.mac.localeCompare(b.mac)).map((item) => ({
      mac: item.mac,
      saved: saved.has(item.mac),
      rssi: item.rssi
    }));
  }

  _renderData() {
    if (!this.shadowRoot.firstElementChild) this._render();
    const gatewaySelect = this.shadowRoot.getElementById("gateway");
    const sensorSelect = this.shadowRoot.getElementById("sensor");
    gatewaySelect.replaceChildren();
    for (const gateway of this._gateways) {
      gatewaySelect.add(new Option(`${gateway.name} (${gateway.device_id})`, gateway.device_id));
    }
    gatewaySelect.value = this._selectedGateway;
    const gateway = this._selectedGatewayData();
    const options = this._sensorOptions(gateway);
    if (!options.some((item) => item.mac === this._selectedMac)) {
      this._selectedMac = options[0]?.mac || "";
    }
    sensorSelect.replaceChildren();
    for (const item of options) {
      const status = item.saved ? "Save" : "New";
      const rssi = Number.isInteger(item.rssi) ? ` · RSSI ${item.rssi} dBm` : "";
      sensorSelect.add(new Option(`${item.mac} — ${status}${rssi}`, item.mac));
    }
    sensorSelect.value = this._selectedMac;
    this.shadowRoot.getElementById("gateway-status").textContent = gateway
      ? (gateway.available ? "Шлюз подключён" : "Шлюз недоступен") +
        (gateway.registry_received ? "" : " · ожидается retained registry")
      : "Нет обнаруженных ESP32-шлюзов";
    this._renderSelection();
  }

  _renderSelection() {
    const gateway = this._selectedGatewayData();
    const selected = this._sensorOptions(gateway).find((item) => item.mac === this._selectedMac);
    const saved = Boolean(selected?.saved);
    this.shadowRoot.getElementById("sensor-status").textContent = selected
      ? (saved ? "Статус: Save — датчик сохранён на шлюзе" : "Статус: New — датчик обнаружен, но не сохранён")
      : "Нет доступных датчиков. Убедитесь, что шлюз обнаруживает BLE-рекламу.";
    this.shadowRoot.getElementById("key-row").hidden = saved || !selected;
    this.shadowRoot.getElementById("add").hidden = saved || !selected;
    this.shadowRoot.getElementById("remove").hidden = !saved;
    this.shadowRoot.getElementById("gateway").disabled = this._gateways.length === 0;
    this.shadowRoot.getElementById("sensor").disabled = !selected;
    this.shadowRoot.getElementById("add").disabled = this._busy || !selected || !gateway?.available;
    this.shadowRoot.getElementById("remove").disabled = this._busy || !saved || !gateway?.available;
  }

  async _addSensor() {
    const gateway = this._selectedGatewayData();
    const bindKey = this.shadowRoot.getElementById("bind-key").value.trim();
    if (!gateway || !this._selectedMac) return;
    if (!/^[0-9a-fA-F]{32}$/.test(bindKey)) {
      this._showMessage("Bind Key должен содержать ровно 32 шестнадцатеричных символа.", true);
      return;
    }
    this._setBusy(true);
    try {
      await this._hass.callService("esp32_xiaomi_lywsd03", "add_sensor", {
        device_id: gateway.device_id,
        mac: this._selectedMac,
        bind_key: bindKey
      });
      this.shadowRoot.getElementById("bind-key").value = "";
      this._showMessage("Команда добавления подтверждена шлюзом.", false);
      await this._loadState();
    } catch (error) {
      this._showMessage(this._errorText(error), true);
    } finally {
      this._setBusy(false);
    }
  }

  async _removeSensor() {
    const gateway = this._selectedGatewayData();
    if (!gateway || !this._selectedMac) return;
    this._setBusy(true);
    try {
      await this._hass.callService("esp32_xiaomi_lywsd03", "remove_sensor", {
        device_id: gateway.device_id,
        mac: this._selectedMac
      });
      this._showMessage("Команда удаления подтверждена шлюзом. Если датчик продолжает рекламироваться, он снова появится со статусом New.", false);
      await this._loadState();
    } catch (error) {
      this._showMessage(this._errorText(error), true);
    } finally {
      this._setBusy(false);
    }
  }

  _setBusy(busy) {
    this._busy = busy;
    this._renderSelection();
    this.shadowRoot.getElementById("refresh").disabled = busy;
  }

  _showMessage(message, isError) {
    const target = this.shadowRoot.getElementById("message");
    if (!target) return;
    target.textContent = message || "";
    target.classList.toggle("error", Boolean(isError));
  }

  _errorText(error) {
    return error?.message || String(error);
  }
}

if (!customElements.get("esp32-xiaomi-sensor-manager")) {
  customElements.define("esp32-xiaomi-sensor-manager", Esp32XiaomiSensorManager);
}

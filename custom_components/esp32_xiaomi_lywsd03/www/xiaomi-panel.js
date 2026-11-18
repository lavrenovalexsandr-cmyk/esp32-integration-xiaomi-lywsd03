class Esp32XiaomiSensorManager extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._gateways = [];
    this._selectedGateway = "";
    this._selectedMac = "";
    this._unsubscribe = null;
    this._statusTimer = null;
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
    if (this._statusTimer) clearInterval(this._statusTimer);
    this._statusTimer = setInterval(() => {
      if (this.isConnected) this._renderData();
    }, 15000);
  }

  disconnectedCallback() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
    if (this._statusTimer) {
      clearInterval(this._statusTimer);
      this._statusTimer = null;
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
        input { box-sizing:border-box; width:100%; min-height:44px; padding:8px 12px; border:1px solid var(--outline-color); border-radius:8px; background:var(--input-fill-color, var(--card-background-color)); color:var(--primary-text-color); font:inherit; }
        .picker { position:relative; width:100%; }
        .picker-trigger { display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%; min-height:48px; padding:8px 12px; border:1px solid var(--outline-color); border-radius:8px; background:var(--input-fill-color, var(--card-background-color)); color:var(--primary-text-color); text-align:left; font:inherit; }
        .picker-trigger:focus-visible, .picker-option:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
        .picker-trigger:disabled { opacity:.5; cursor:not-allowed; }
        .picker-current, .picker-option-main { display:flex; align-items:center; gap:10px; min-width:0; }
        .picker-name { overflow-wrap:anywhere; }
        .picker-chevron { color:var(--secondary-text-color); flex:none; }
        .picker-menu { position:absolute; z-index:10; top:calc(100% + 4px); left:0; right:0; max-height: min(320px, 50vh); overflow-y:auto; padding:5px; border:1px solid var(--outline-color); border-radius:10px; background:var(--card-background-color); box-shadow:var(--ha-card-box-shadow, 0 4px 14px #0003); }
        .picker-menu[hidden] { display:none; }
        .picker-option { display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%; padding:10px; border:0; border-radius:7px; background:transparent; color:var(--primary-text-color); text-align:left; font:inherit; cursor:pointer; }
        .picker-option:hover, .picker-option[aria-selected="true"] { background:var(--secondary-background-color); }
        .picker-option-label { min-width:0; overflow-wrap:anywhere; }
        .picker-empty { padding:12px; color:var(--secondary-text-color); font-size:14px; }
        .tag { display:inline-flex; align-items:center; border-radius:16px; padding:4px 11px; font-size:12px; font-weight:600; line-height:1.4; }
        .tag.online, .tag.saved { color:var(--success-color); background:color-mix(in srgb, var(--success-color) 14%, transparent); }
        .tag.offline { color:var(--error-color); background:color-mix(in srgb, var(--error-color) 14%, transparent); }
        .tag.new { color:var(--info-color, #039be5); background:color-mix(in srgb, var(--info-color, #039be5) 14%, transparent); }
        .tag.unknown { color:var(--secondary-text-color); background:var(--secondary-background-color); }
        .status-line { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
        .status-note { color:var(--secondary-text-color); font-size:13px; }
        .actions { display:flex; gap:12px; margin-top:18px; flex-wrap:wrap; }
        button { border:0; border-radius:8px; padding:10px 18px; min-height:40px; font:inherit; cursor:pointer; background:var(--primary-color); color:var(--text-primary-color, white); }
        button.secondary { background:var(--secondary-background-color); color:var(--primary-text-color); }
        button.danger { background:var(--error-color); color:var(--text-primary-color, white); }
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
          <div id="gateway-picker" class="picker"></div>
          <label for="sensor">Датчик</label>
          <div id="sensor-picker" class="picker"></div>
          <div id="key-row">
            <label for="bind-key">Bind Key (32 hex-символа)</label>
            <input id="bind-key" type="password" autocomplete="off" spellcheck="false" maxlength="32" placeholder="0123456789ABCDEF0123456789ABCDEF">
          </div>
          <div class="actions">
            <button id="add">Добавить датчик</button>
            <button id="remove" class="danger">Удалить датчик</button>
            <button id="refresh" class="secondary">Обновить</button>
          </div>
          <div id="message" class="message" role="status" aria-live="polite"></div>
        </div>
      </div>
    `;

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
    const lastSeen = gateway.sensor_last_seen && typeof gateway.sensor_last_seen === "object"
      ? gateway.sensor_last_seen : {};
    const items = new Map();
    for (const item of discovered) items.set(item.mac, item);
    for (const mac of registry) if (!items.has(mac)) items.set(mac, { mac });
    return [...items.values()].sort((a, b) => a.mac.localeCompare(b.mac)).map((item) => {
      const isSaved = saved.has(item.mac);
      let availability = null;
      if (isSaved) {
        const seen = Number(lastSeen[item.mac]);
        if (gateway.availability_received && !gateway.available) {
          availability = "offline";
        } else if (Number.isFinite(seen) && seen > 0) {
          availability = Date.now() / 1000 - seen < 300 ? "online" : "offline";
        } else {
          availability = "unknown";
        }
      }
      return {
        mac: item.mac,
        availability,
        saved: isSaved,
        rssi: item.rssi
      };
    });
  }

  _renderDropdown(containerId, items, selectedValue, onSelect, disabled) {
    const container = this.shadowRoot.getElementById(containerId);
    if (!container) return;
    container.replaceChildren();

    const selected = items.find((item) => item.value === selectedValue);
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "picker-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.disabled = Boolean(disabled);
    const current = document.createElement("span");
    current.className = "picker-current";
    const currentLabel = document.createElement("span");
    currentLabel.className = "picker-name";
    currentLabel.textContent = selected?.label || (items.length ? "Выберите..." : "Нет доступных вариантов");
    current.append(currentLabel);
    if (selected) this._appendPickerBadges(current, selected);
    const chevron = document.createElement("span");
    chevron.className = "picker-chevron";
    chevron.textContent = "▾";
    trigger.append(current, chevron);

    const menu = document.createElement("div");
    menu.className = "picker-menu";
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "picker-empty";
      empty.textContent = "Нет доступных вариантов";
      menu.append(empty);
    }
    for (const item of items) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "picker-option";
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(item.value === selectedValue));
      const label = document.createElement("span");
      label.className = "picker-option-label";
      label.textContent = item.label;
      const main = document.createElement("span");
      main.className = "picker-option-main";
      main.append(label);
      const badges = document.createElement("span");
      badges.className = "status-line";
      this._appendPickerBadges(badges, item);
      option.append(main, badges);
      option.addEventListener("click", () => {
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        onSelect(item.value);
      });
      menu.append(option);
    }

    trigger.addEventListener("click", () => {
      const opening = menu.hidden;
      this.shadowRoot.querySelectorAll(".picker-menu").forEach((other) => { other.hidden = true; });
      this.shadowRoot.querySelectorAll(".picker-trigger").forEach((other) => other.setAttribute("aria-expanded", "false"));
      menu.hidden = !opening;
      trigger.setAttribute("aria-expanded", String(opening));
    });
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
      } else if (event.key === "ArrowDown" && menu.hidden) {
        event.preventDefault();
        menu.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        menu.querySelector(".picker-option")?.focus();
      }
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        menu.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        trigger.focus();
      }
    });
    container.append(trigger, menu);
  }

  _appendPickerBadges(target, item) {
    if (item.availability) {
      const availability = document.createElement("span");
      availability.className = `tag ${item.availability}`;
      availability.textContent = item.availabilityText;
      target.append(availability);
    }
    if (item.registry) {
      const registry = document.createElement("span");
      registry.className = `tag ${item.registry}`;
      registry.textContent = item.registryText;
      target.append(registry);
    }
    if (item.detail) {
      const detail = document.createElement("span");
      detail.className = "status-note";
      detail.textContent = item.detail;
      target.append(detail);
    }
  }

  _renderData() {
    if (!this.shadowRoot.firstElementChild) this._render();
    const gateway = this._selectedGatewayData();
    const gatewayItems = this._gateways.map((item) => {
      const known = item.availability_received !== false;
      return {
        value: item.device_id,
        label: `${item.name} (${item.device_id})`,
        availability: known ? (item.available ? "online" : "offline") : "unknown",
        availabilityText: known ? (item.available ? "Online" : "Offline") : "Unknown"
      };
    });
    this._renderDropdown("gateway-picker", gatewayItems, this._selectedGateway, (value) => {
      this._selectedGateway = value;
      this._selectedMac = "";
      this._renderData();
    }, this._gateways.length === 0);

    const options = this._sensorOptions(gateway);
    if (!options.some((item) => item.mac === this._selectedMac)) {
      this._selectedMac = options[0]?.mac || "";
    }
    const sensorItems = options.map((item) => ({
      value: item.mac,
      label: item.mac,
      availability: item.availability,
      availabilityText: item.availability === "online" ? "Online"
        : item.availability === "offline" ? "Offline" : "Unknown",
      registry: item.saved ? "saved" : "new",
      registryText: item.saved ? "Save" : "New",
      detail: Number.isInteger(item.rssi) ? `RSSI ${item.rssi} dBm` : ""
    }));
    this._renderDropdown("sensor-picker", sensorItems, this._selectedMac, (value) => {
      this._selectedMac = value;
      this._renderSelection();
    }, options.length === 0);

    this._renderSelection();
  }

  _renderSelection() {
    const gateway = this._selectedGatewayData();
    const selected = this._sensorOptions(gateway).find((item) => item.mac === this._selectedMac);
    const saved = Boolean(selected?.saved);
    this.shadowRoot.getElementById("key-row").hidden = saved || !selected;
    this.shadowRoot.getElementById("add").hidden = saved || !selected;
    this.shadowRoot.getElementById("remove").hidden = !saved;
    const gatewayTrigger = this.shadowRoot.querySelector("#gateway-picker .picker-trigger");
    const sensorTrigger = this.shadowRoot.querySelector("#sensor-picker .picker-trigger");
    if (gatewayTrigger) gatewayTrigger.disabled = this._gateways.length === 0;
    if (sensorTrigger) sensorTrigger.disabled = !selected;
    this.shadowRoot.getElementById("add").disabled = this._busy || !selected || !gateway?.available || !gateway?.registry_received;
    this.shadowRoot.getElementById("remove").disabled = this._busy || !saved || !gateway?.available || !gateway?.registry_received;
  }

  async _addSensor() {
    const gateway = this._selectedGatewayData();
    const bindKey = this.shadowRoot.getElementById("bind-key").value.trim();
    if (!gateway || !this._selectedMac) return;
    if (!/^[0-9a-fA-F]{32}$/.test(bindKey)) {
      this._showMessage("Bind Key должен содержать ровно 32 шестнадцатеричных символа.", true);
      return;
    }
    this.shadowRoot.getElementById("bind-key").value = "";
    this._setBusy(true);
    try {
      await this._hass.callService("esp32_xiaomi_lywsd03", "add_sensor", {
        device_id: gateway.device_id,
        mac: this._selectedMac,
        bind_key: bindKey
      });
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

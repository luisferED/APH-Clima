(function () {
  var API_STATE_URL = "/api/state";
  var API_EVENTS_URL = "/api/events";
  var API_OUTPUT_URL = "/api/output";
  var API_WEATHER_URL = "/api/weather";
  var API_WEATHER_REFRESH_URL = "/api/weather/refresh";
  var remoteSyncEnabled = location.protocol.indexOf("http") === 0;
  var eventSource = null;
  var state = { outputMode: "", weatherCity: "santa-cruz", updatedAt: "" };
  var weatherCache = { ready: false, updatedAt: "", cities: [] };
  var activeWeatherFrameIndex = 0;
  var lastWeatherUrl = "";
  var weatherTransitionTimer = null;
  var pendingWeatherUrl = "";
  var selectedView = "current";

  function merge(base, incoming) {
    return Object.assign({}, base, incoming || {});
  }

  function outputUrl() {
    return remoteSyncEnabled ? window.location.origin + "/output.html" : "output.html";
  }

  function setupOutputLinks() {
    var url = outputUrl();
    var openLink = document.getElementById("openOutputLink");
    var textLink = document.getElementById("outputUrlText");
    if (openLink) {
      openLink.href = url;
      openLink.addEventListener("click", function (event) {
        event.preventDefault();
        var opened = window.open(url, "salida_aph");
        if (!opened) window.location.href = url;
      });
    }
    if (textLink) {
      textLink.href = url;
      textLink.textContent = url;
    }
  }

  function applyRemoteState(remoteState) {
    state = merge(state, remoteState);
    selectedView = state.weatherView || "current";
    document.querySelectorAll('[name="weatherView"]').forEach(function (input) { input.checked = input.value === selectedView; });
    if (document.querySelector(".operator-layout")) loadWeatherCache();
    render();
  }

  function pullStateFromServer() {
    if (!remoteSyncEnabled) return;
    fetch(API_STATE_URL + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(applyRemoteState)
      .catch(function () {});
  }

  function setupRemoteSync() {
    if (!remoteSyncEnabled) return;
    if ("EventSource" in window) {
      eventSource = new EventSource(API_EVENTS_URL);
      eventSource.onmessage = function (event) {
        try {
          applyRemoteState(JSON.parse(event.data));
        } catch (error) {
          pullStateFromServer();
        }
      };
      eventSource.onerror = pullStateFromServer;
    }
    pullStateFromServer();
    window.setInterval(function () { if (!eventSource || eventSource.readyState !== EventSource.OPEN) pullStateFromServer(); }, 5000);
  }

  function loadWeatherCache() {
    if (!remoteSyncEnabled) return;
    fetch(API_WEATHER_URL + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        weatherCache = payload || weatherCache;
        renderWeatherControl();
      })
      .catch(function () {
        var status = document.getElementById("weatherCacheStatus");
        if (status) status.textContent = "No se pudo leer la base local del tiempo.";
      });
  }

  function refreshWeatherCache() {
    var button = document.getElementById("refreshWeatherBtn");
    var status = document.getElementById("weatherCacheStatus");
    if (button) button.disabled = true;
    if (status) status.textContent = "Consultando MET Norway una sola vez para los 9 departamentos...";
    fetch(API_WEATHER_REFRESH_URL, { method: "POST", headers: { "X-APH-Request": "operator" }, cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        weatherCache = payload || weatherCache;
        renderWeatherControl();
        toast(payload.message || (payload.ok ? "Tiempo actualizado." : "Se conservaron los datos anteriores."));
      })
      .catch(function () {
        if (status) status.textContent = "Fallo la consulta. La base anterior permanece intacta.";
        toast("Sin conexion: se conserva el respaldo local.");
      })
      .finally(function () {
        if (button) button.disabled = false;
      });
  }

  function showWeatherOnAir(citySlug) {
    postOutput({ mode: "weather", weatherCity: citySlug, weatherView: selectedView }, "Datos al aire.");
  }

  function clearOutput() {
    postOutput({ mode: "" }, "Salida limpia.");
  }

  function postOutput(payload, successMessage) {
    if (!remoteSyncEnabled) return;
    fetch(API_OUTPUT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8", "X-APH-Request": "operator" },
      body: JSON.stringify(payload || {}),
      cache: "no-store"
    })
      .then(function (response) { return response.json(); })
      .then(function (payload) {
        if (payload.state) applyRemoteState(payload.state);
        toast(payload.message || successMessage);
      })
      .catch(function () {
        toast("No se pudo actualizar la salida.");
      });
  }

  function formatWeatherUpdate(value) {
    if (!value) return "Sin actualizacion local";
    try {
      return new Intl.DateTimeFormat("es-BO", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
    } catch (error) {
      return value;
    }
  }

  function cityLabel(slug) {
    var city = (weatherCache.cities || []).find(function (item) { return item.slug === slug; });
    return city ? city.name : slug;
  }

  function weatherCityButton(city) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "city-button";
    if (state.outputMode === "weather" && state.weatherCity === city.slug) {
      button.classList.add("is-active");
    }
    button.disabled = !city.ready || (selectedView === "extended" && !city.extendedReady);

    var name = document.createElement("strong");
    name.textContent = city.name;

    var detail = document.createElement("span");
    if (!city.ready) {
      detail.textContent = "Sin datos locales";
    } else {
      detail.textContent = Math.round(city.currentTemperature) + "° actual | Min " +
        Math.round(city.todayMin) + "° | Max " + Math.round(city.todayMax) + "° | Viento " +
        Math.round(city.todayWindSpeed) + " km/h";
    }

    button.appendChild(name);
    button.appendChild(detail);
    button.addEventListener("click", function () { showWeatherOnAir(city.slug); });
    return button;
  }

  function renderWeatherControl() {
    var list = document.getElementById("weatherCityButtons");
    var status = document.getElementById("weatherCacheStatus");
    if (!list || !status) return;
    list.innerHTML = "";
    (weatherCache.cities || []).forEach(function (city) {
      list.appendChild(weatherCityButton(city));
    });
    if (!weatherCache.cities || !weatherCache.cities.length) {
      status.textContent = "Todavia no hay datos locales.";
      return;
    }
    status.className = "weather-cache-status" + (weatherCache.ready ? " is-ready" : " is-warning");
    status.textContent = (weatherCache.ready ? "Base lista: " : "Base incompleta: ") +
      "ultima consulta " + formatWeatherUpdate(weatherCache.updatedAt) + ".";
  }

  function renderOutput() {
    var frames = Array.prototype.slice.call(document.querySelectorAll(".weather-frame"));
    var idle = document.getElementById("idleOutput");
    var stage = document.getElementById("outputStage");
    if (!frames.length || !idle || !stage) return;
    var isWeather = state.outputMode === "weather";
    stage.className = "output-stage" + (isWeather ? " is-live" : "");
    idle.classList.toggle("is-hidden", isWeather);
    frames.forEach(function (frame) {
      frame.classList.toggle("is-hidden", !isWeather);
    });
    if (!isWeather) {
      lastWeatherUrl = "";
      pendingWeatherUrl = "";
      frames.forEach(function (frame) { frame.onload = null; });
      return;
    }
    var url = "/weather/local?city=" + encodeURIComponent(state.weatherCity || "santa-cruz") +
      "&view=" + encodeURIComponent(new URLSearchParams(location.search).get("view") || state.weatherView || "current") +
      "&v=" + encodeURIComponent(state.updatedAt || "0");
    var absoluteUrl = new URL(url, window.location.href).href;
    if (lastWeatherUrl === absoluteUrl || pendingWeatherUrl === absoluteUrl) return;
    transitionWeatherFrame(frames, url, absoluteUrl);
  }

  function transitionWeatherFrame(frames, url, absoluteUrl) {
    pendingWeatherUrl = absoluteUrl;
    var currentFrame = frames[activeWeatherFrameIndex] || frames[0];
    var nextIndex = frames.length > 1 ? 1 - activeWeatherFrameIndex : activeWeatherFrameIndex;
    var nextFrame = frames[nextIndex] || currentFrame;
    var firstRender = !lastWeatherUrl || !currentFrame.src;
    window.clearTimeout(weatherTransitionTimer);

    function activateFrame() {
      if (pendingWeatherUrl !== absoluteUrl || state.outputMode !== "weather") return;
      pendingWeatherUrl = "";
      frames.forEach(function (frame, index) {
        frame.classList.remove("is-entering", "is-exiting", "is-active");
        if (index === nextIndex) {
          frame.classList.add("is-active", firstRender ? "is-initial" : "is-entering");
        } else if (!firstRender) {
          frame.classList.add("is-exiting");
        }
      });
      activeWeatherFrameIndex = nextIndex;
      lastWeatherUrl = absoluteUrl;
      weatherTransitionTimer = window.setTimeout(function () {
        frames.forEach(function (frame, index) {
          frame.classList.remove("is-entering", "is-exiting", "is-initial");
          if (index !== activeWeatherFrameIndex) frame.removeAttribute("src");
        });
      }, firstRender ? 320 : 840);
    }

    nextFrame.onload = function () {
      nextFrame.onload = null;
      activateFrame();
    };
    nextFrame.src = url;
  }

  function resizePreview() {
    var wrap = document.querySelector(".preview-frame");
    var frame = document.getElementById("outputPreview");
    if (!wrap || !frame) return;
    var scale = wrap.clientWidth / 1600;
    frame.style.transform = "scale(" + scale + ")";
  }

  function render() {
    renderWeatherControl();
    renderOutput();
    var pill = document.getElementById("activeCityPill");
    if (pill) {
      pill.textContent = state.outputMode === "weather" ? cityLabel(state.weatherCity) : "Libre";
      pill.classList.toggle("is-live", state.outputMode === "weather");
    }
  }

  function toast(message) {
    var node = document.getElementById("toast");
    if (!node) return;
    node.textContent = message || "";
    node.classList.add("is-visible");
    window.clearTimeout(node._timer);
    node._timer = window.setTimeout(function () {
      node.classList.remove("is-visible");
    }, 2400);
  }

  function wireControl() {
    if (!document.querySelector(".operator-layout")) return;
    setupOutputLinks();
    document.querySelectorAll('[name="weatherView"]').forEach(function (input) {
      input.addEventListener("change", function () {
        selectedView = input.value;
        renderWeatherControl();
        if (state.outputMode === "weather") showWeatherOnAir(state.weatherCity);
      });
    });
    var refresh = document.getElementById("refreshWeatherBtn");
    var clear = document.getElementById("clearOutputBtn");
    var preview = document.getElementById("outputPreview");
    if (refresh) refresh.addEventListener("click", refreshWeatherCache);
    if (clear) clear.addEventListener("click", clearOutput);
    if (preview) preview.addEventListener("load", resizePreview);
    window.addEventListener("resize", resizePreview);
    resizePreview();
  }

  wireControl();
  setupRemoteSync();
  loadWeatherCache();
  render();
})();

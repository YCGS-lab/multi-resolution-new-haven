// Where the website runs, and what the user has unlocked.
//
//   - env.json: "cloud" ("auto": the deployed website, i.e. any host but
//     localhost; or true / false) and the URLs of cloud services (e.g.
//     titiler-cmr and this repository's tiler, which read data next to it in AWS).
//     Datasets that need the cloud (product.requires.cloud) are disabled
//     elsewhere. `?cloud=1` / `?cloud=0` in the page URL overrides it, and
//     `?service.<name>=<url>` sets a service, for testing (e.g.
//     `?cloud=1&service.tiler=http://localhost:8100` with tiler/serve-local.sh).
//   - Credentials (API keys) the user enters in the Credentials dialog, kept
//     in this browser only: localStorage when "remember" is ticked, else
//     sessionStorage. Datasets that need one (product.requires.credential)
//     are locked until it is set.

export const env = { cloud: false, services: {} };

// #region load-env
export async function loadEnv(url = "env.json") {
  let cfg = {};
  try {
    const res = await fetch(url, { cache: "no-cache" });
    if (res.ok) cfg = await res.json();
  } catch {
    // no env.json: defaults
  }
  const local = /^(localhost|127\.|\[::1\]|0\.0\.0\.0)|\.local$/.test(location.hostname) || location.protocol === "file:";
  let cloud = cfg.cloud ?? "auto";
  if (cloud === "auto") cloud = !local;
  const query = new URLSearchParams(location.search);
  const q = query.get("cloud");
  if (q === "1" || q === "0") cloud = q === "1";
  env.cloud = !!cloud;
  env.services = { ...(cfg.services ?? {}) };
  for (const [k, v] of query) if (k.startsWith("service.") && /^https?:\/\//.test(v)) env.services[k.slice(8)] = v.replace(/\/$/, "");
  return env;
}
// #endregion load-env

/** Credentials the website can use, by name (as in product.requires.credential). */
export const CREDENTIALS = {
  planet: {
    label: "Planet API key",
    dataset: "Planet monthly basemaps",
    help: "From your Planet account settings. Sent only to Planet (tile and Basemaps API requests).",
    link: "https://www.planet.com/account/#/user-settings",
  },
  cds: {
    label: "Copernicus CDS API key",
    dataset: "ERA5-Land",
    help: "Your personal access token from the Climate Data Store profile page. Sent only to the CDS. Accept the ERA5-Land licence on the CDS website once.",
    link: "https://cds.climate.copernicus.eu/profile",
  },
};

// #region credentials-store
const STORE_KEY = "newhaven-credentials";
const listeners = new Set();

function readStore(storage) {
  try {
    return JSON.parse(storage.getItem(STORE_KEY) || "{}");
  } catch {
    return {};
  }
}

/** The credential's value, or "" if not set. */
export function credential(name) {
  return readStore(sessionStorage)[name] || readStore(localStorage)[name] || "";
}

/** Whether the credential is remembered across browser sessions. */
export function remembered(name) {
  return !!readStore(localStorage)[name];
}

/** Set (or with "" clear) a credential; `remember` keeps it in localStorage. */
export function setCredential(name, value, remember) {
  for (const storage of [localStorage, sessionStorage]) {
    const all = readStore(storage);
    delete all[name];
    if (value && (storage === localStorage) === !!remember) all[name] = value;
    storage.setItem(STORE_KEY, JSON.stringify(all));
  }
  listeners.forEach((fn) => fn(name));
}

/** Call `fn(name)` whenever a credential changes. */
export function onCredentialsChange(fn) {
  listeners.add(fn);
}
// #endregion credentials-store

// #region requirement
/**
 * Whether a product can be shown here: {ok: true}, or {ok: false, kind:
 * "credential" | "cloud", credential, message} with a short reason for
 * tooltips and notices.
 */
export function requirement(product) {
  const r = product?.requires;
  if (!r) return { ok: true };
  if (r.cloud && !env.cloud)
    return {
      ok: false,
      kind: "cloud",
      message: `Cloud only: ${r.reason || "read next to the data in AWS"}. Available on the deployed website, not when testing locally.`,
    };
  if (r.cloud && r.service && !env.services[r.service])
    return {
      ok: false,
      kind: "cloud",
      message: `Cloud only: ${r.reason || "read next to the data in AWS"}. This deployment has no "${r.service}" service (see env.json).`,
    };
  if (r.credential && !credential(r.credential)) {
    const c = CREDENTIALS[r.credential];
    return {
      ok: false,
      kind: "credential",
      credential: r.credential,
      message: `Requires a ${c?.label ?? r.credential}: add it under Credentials.`,
    };
  }
  return { ok: true };
}
// #endregion requirement

// --------------------------------------------------------------------------
// Credentials dialog
// --------------------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);

// #region credentials-dialog
/** Fill the <dialog id="credentials-dialog"> and wire the header button. */
export function initCredentialsDialog() {
  const dialog = document.getElementById("credentials-dialog");
  const button = document.getElementById("credentials-button");
  const form = dialog.querySelector("form");
  const render = () => {
    form.querySelector(".cred-fields").innerHTML = Object.entries(CREDENTIALS)
      .map(
        ([name, c]) => `
        <fieldset class="cred" data-name="${name}">
          <legend>${esc(c.label)} <span class="cred-for">for ${esc(c.dataset)}</span></legend>
          <div class="cred-row">
            <input type="password" name="${name}" autocomplete="off" spellcheck="false" value="${esc(credential(name))}"
              placeholder="Not set" aria-label="${esc(c.label)}" />
            <button type="button" class="btn subtle cred-show" title="Show / hide">Show</button>
            <button type="button" class="btn subtle cred-clear" title="Forget this key">Clear</button>
          </div>
          <label class="cred-remember"><input type="checkbox" name="${name}-remember" ${remembered(name) ? "checked" : ""} />
            Remember in this browser</label>
          <p class="cred-help">${esc(c.help)} <a href="${c.link}" target="_blank" rel="noopener">Get a key</a></p>
        </fieldset>`,
      )
      .join("");
    form.querySelectorAll(".cred").forEach((fs) => {
      const input = fs.querySelector("input[type=password], input[type=text]");
      fs.querySelector(".cred-show").addEventListener("click", () => (input.type = input.type === "password" ? "text" : "password"));
      fs.querySelector(".cred-clear").addEventListener("click", () => (input.value = ""));
    });
  };
  const update = () => {
    const n = Object.keys(CREDENTIALS).filter((k) => credential(k)).length;
    button.classList.toggle("has-keys", n > 0);
    button.title = n ? `${n} API key${n > 1 ? "s" : ""} set` : "Enter API keys for locked datasets";
  };
  button.addEventListener("click", () => openCredentials());
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    for (const name of Object.keys(CREDENTIALS)) {
      const value = form.elements[name].value.trim();
      const remember = form.elements[`${name}-remember`].checked;
      if (value !== credential(name) || remember !== remembered(name)) setCredential(name, value, remember);
    }
    dialog.close();
  });
  dialog.querySelector(".cred-cancel").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => button.focus());
  onCredentialsChange(update);
  update();
  openCredentials = (focus) => {
    render();
    dialog.showModal();
    (focus && form.elements[focus])?.focus();
  };
}
// #endregion credentials-dialog

/** Open the credentials dialog, focusing one credential's field. */
export let openCredentials = () => {};

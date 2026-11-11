# JBL Bar Toolkit for Home Assistant

Control a **JBL Bar 9.1 True Wireless Surround** from Home Assistant through the soundbar's local browser remote from [kisinga/jbl-bar-toolkit](https://github.com/kisinga/jbl-bar-toolkit). No cloud, no extra hardware: Home Assistant talks to the remote on your LAN. Only the Bar 9.1 is supported, like the toolkit's packaged remote: setup checks the model the remote reports (`GET /api/features`, `bar91`) and refuses another bar, whose controls differ. Remotes that predate that endpoint are accepted.

> **Renamed.** This repository was `naonak/jbl-bar-9.1-ha`, following the toolkit's own rename (`kisinga/jbl-bar-9.1` → `kisinga/jbl-bar-toolkit`). Existing installations keep working: the integration's domain (`jbl_bar_91`), devices and entities are unchanged. In HACS, replace the custom repository URL with `https://github.com/naonak/jbl-bar-toolkit-ha`.

Not affiliated with JBL or Harman. Experimental, like the remote it relies on.

## Requirements

- The **browser remote** from [kisinga/jbl-bar-toolkit](https://github.com/kisinga/jbl-bar-toolkit) installed on the bar (the toolkit USB with the web remote, or an owner build) and reachable at `http://<bar-ip>` or `http://<bar-ip>:8080`.
- Home Assistant **2025.1** or newer.
- Home Assistant's IP address inside the remote's trusted network (`allowed_cidr` in the toolkit's `config.txt`, or `tools/build_web.py --allowed-cidr`). Otherwise setup reports that the remote refused Home Assistant.

## Installation

**HACS:** HACS → ⋮ → *Custom repositories* → add this repository's URL with category *Integration*, then install **JBL Bar Toolkit (Bar 9.1)** and restart Home Assistant.

**Manual:** copy `custom_components/jbl_bar_91` into your Home Assistant `config/custom_components/` folder and restart.

Then: *Settings → Devices & services → Add integration → JBL Bar Toolkit (Bar 9.1)*, and enter the bar's IP address (`192.168.1.50`, `192.168.1.50:80` or `192.168.1.50:8080`).

## Entities

| Entity | What it does |
| --- | --- |
| Media player | Power, volume (0–32 shown as 0–100 %), mute, source (TV, HDMI, Bluetooth), play/pause/next/previous/stop when the current source supports them, now playing (title, artist, album, app) |
| Bass level | 1–5 |
| Center level | 1–6 like the web page: 1 = original, up to +12 dB at 6 (the option values stay `0`–`5`, so automations are unchanged). Only when the remote includes the center-level control |
| Bass offset | −3 to +3 dB in 0.5 dB steps on every native bass level, saved on the bar for startup (the toolkit's experimental bass offset); attributes `status`, `error` (for example `WAITING_FOR_FRONT_EQ`: paused while a Front EQ is applied). Only when the remote includes it |
| Atmos height | Low, Mid, High |
| Rear speakers | Low, Mid, High, Muted (rear speakers must be undocked) |
| Front EQ preset | The remote's presets: Original, Less bass, Clear dialogue, Softer treble, Warm, Bright, Vocal focus. Attributes `status`, `error` and, with a remote that keeps the EQ until Reset, `kept` |
| Front EQ status | Sensor, like the web page's badge: `active` (heard now), `waiting` (kept, applied when Standard audio plays; attribute `reason`), `off`, `reset_needed`; attribute `gains_db` |
| Front EQ 125 Hz … 8 kHz | −6 to 0 dB per band; each change applies the full curve |
| Night mode | Switch |
| Smart mode | Switch: on = Smart, off = Standard (the bar returns to Smart at power-on). Needs a remote with the advanced controls |
| Audio sync | Lip-sync delay, 0–250 ms in 10 ms steps, TV and HDMI inputs only (one request per change: about 10 s plus one second per 10 ms step). Needs a remote with the advanced controls |
| Bluetooth pairing | Button |
| Command running | Binary sensor: on while a command runs, sent from Home Assistant (`source: home_assistant`) or elsewhere (`source: remote`: the web page, another client, a calibration); `action` names it |
| Calibrate surround | Button: starts the next step of the wireless surround calibration (both rear speakers undocked; step 1 near your listening position, step 2 at their final places; about 35 s each). Needs a remote with the setup controls |
| Pair subwoofer | Button: opens subwoofer pairing on the bar for up to three minutes; then hold the button on the back of the subwoofer until it flashes white quickly. Needs a remote with the setup controls |
| Audio format | Sensor: what the bar last showed for the incoming stream, e.g. `DOLBY SURROUND DD+` (while on). Needs a remote with the setup controls |
| Calibration, Subwoofer | Diagnostic sensors: calibration progress (Idle, Measuring, Step 1 done…) and subwoofer pairing/connection messages |
| Mode after standby | Diagnostic sensor: Standard or Smart, the mode the bar returns to after the next wake. Only when the remote restores the mode chosen before standby (`smart_mode_memory`) |
| Standard mode | Button, only with older remotes (replaced by the Smart mode switch) |
| Sound mode, Bluetooth device, Bluetooth audio | Sensors |
| Rear speakers docked, Bluetooth connected | Binary sensors |
| CPU, Memory used, Temperature, Wi-Fi signal, Uptime | Diagnostics (the last two disabled by default) |

## Messages on the display

Two services show your own text on the bar's front display, on or in standby, without waking it. Both target the bar's media player. They need a toolkit remote with display messages (`bar91.display-message`, November 2026); an older remote is reported clearly.

- `jbl_bar_91.display_message`:
  - `message`: up to 31 characters once converted. The display shows capital letters without accents, so `Frigo fermé` shows as `FRIGO FERME`.
  - How long, one of:
    - `repeat`: 1–99 passes (default: one pass);
    - `duration`: up to 24 h; the last pass is shown to its end;
    - `forever`: until the message is cancelled or replaced.
  - `id`: a message with the same id replaces it. Messages with different ids take turns, pass by pass, each with its own repeat, duration or forever: `Hello` ×3 and `Goodbye` ×2 show Hello, Goodbye, Hello, Goodbye, Hello.
- `jbl_bar_91.display_cancel` stops the message with `id`, or every message (timers are not affected). A message sent without an `id`, by `display_message` or the notify entity, has the id `default`: there is one at a time, and `id: default` clears it.
- `clear_on_key: true` on `display_message` lets whoever reads the message clear it with any key on the JBL remote (toolkit remotes with the Messages panel). With `forever: true`, the message stays until it is seen.
- The buttons **Clear unnamed message** and **Clear all messages** do the same from a dashboard or an automation.
- **Dashboard template.** [`dashboards/messages-card.yaml`](dashboards/messages-card.yaml) lists the messages on the bar, one line each with a **Clear** button for that message only, leaves one (text, how long, clear with a key) and clears them all. It needs [`dashboards/messages-package.yaml`](dashboards/messages-package.yaml): see [Dashboard templates](#dashboard-templates).
- With a toolkit remote that lists them (the Messages panel), the **Messages** sensor gives how many messages are on the display or waiting, and the `messages` attribute each one: `id`, `name` (empty for the unnamed one), `text` as shown, `mode` (`passes`, `duration` or `forever`), `passes_left`, `ends_at` and `showing`.

The bar's own messages (volume, `HELLO` at wake-up…) come first: yours waits, then shows the interrupted pass again. A 1.5 s blank separates passes. Example, the fridge door:

```yaml
- alias: Fridge open
  triggers:
    - trigger: state
      entity_id: binary_sensor.fridge_door
      to: "on"
      for: "00:02:00"
  actions:
    - action: jbl_bar_91.display_message
      target:
        entity_id: media_player.jbl_bar_9_1
      data: {message: "Frigo ouvert", id: fridge, forever: true}
- alias: Fridge closed
  triggers:
    - trigger: state
      entity_id: binary_sensor.fridge_door
      to: "off"
  actions:
    - action: jbl_bar_91.display_message
      target:
        entity_id: media_player.jbl_bar_9_1
      data: {message: "Frigo fermé", id: fridge}
```

The second message replaces the first, so the endless one stops.

**As a notification target.** The bar also has a notify entity, *Display* (`notify.jbl_bar_9_1_display`, `notify.jbl_bar_9_1_ecran` with Home Assistant in French). `notify.send_message` shows the message in two passes. When a title is given, it goes in front of the message if both fit in 31 characters. The entity can be part of a notify group, next to your phone. For repeats, a duration or replacement by id, use `jbl_bar_91.display_message`.

```yaml
action: notify.send_message
target:
  entity_id: notify.jbl_bar_9_1_display
data:
  message: "Colis livré"
```

Details: [toolkit docs](https://github.com/kisinga/jbl-bar-toolkit/blob/main/docs/DISPLAY_MESSAGES.md).

## Timers

With a toolkit remote that has timers (`bar91.timer`, November 2026), the bar can be a kitchen timer, driven from Home Assistant.

- `jbl_bar_91.timer_start` starts a timer. It takes `duration` (1 s to 12 h, required) and, optionally:
  - `name` (e.g. `Pizza`);
  - `show_time_left`: on the bar, second by second when it is the only timer, `PIZZA 4'34` once a minute when several run;
  - `sound`: `off`, `unless_tv` (not while the bar plays TV, optical or HDMI) or `always`;
  - `sound_volume` (at least, 1–30, default 10);
  - `ring_for` (default 30 s).

  When the time is up, `TIME'S UP PIZZA` scrolls on the display, on or in standby, until any key on the JBL remote is pressed (10 minutes at most). With a sound, the bar plays a chime through its Chromecast for `ring_for`, then returns to its volume, source or standby.
- `jbl_bar_91.timer_cancel` stops a timer by `name`, by `id`, or `all: true`.
- `jbl_bar_91.timer_extend` adds time to a running timer, 1 minute by default (`duration`, up to 1 hour): by `name` or `id`, otherwise the next one to end. A ringing timer is not extended. It needs a toolkit remote with `bar91.timer.extend`.
- Entities:
  - **Timers**: the number of timers, with each one in the `timers` attribute (`id`, `name`, `ends_at`, `ringing`, `countdown`, `sound`, and `duration_s` from start to end, time added included);
  - **Next timer**: a timestamp, so dashboards show it as a countdown;
  - **Timer ringing**: on while one rings; handy to tell a phone too.

**Dashboard template.** [`dashboards/timers-card.yaml`](dashboards/timers-card.yaml) is a card with:
- the running timers, one line each with its end time and the time left, or *ringing*, and a **Cancel** button that stops that timer only, at once;
- 1/5/10/15-minute buttons;
- a custom timer (name, minutes, sound, time left);
- *+1 min* for the next timer, and *Stop all timers*, with a confirmation.

It needs [`dashboards/timers-package.yaml`](dashboards/timers-package.yaml): see [Dashboard templates](#dashboard-templates). The package adds `sensor.jbl_timer_1` to `sensor.jbl_timer_4`, the running timers in order (first to end first, a ringing one on top), and the script `script.jbl_timer_cancel_slot` that the Cancel buttons call; the card lists four timers, and says how many more run beyond them.

## Dashboard templates

Two ready-made cards, each with a *package*: a YAML file that adds the helpers (text fields, lists, switches) and scripts its card uses.

| Card | Package | Adds |
| --- | --- | --- |
| [`timers-card.yaml`](dashboards/timers-card.yaml) | [`timers-package.yaml`](dashboards/timers-package.yaml) | quick and custom timers, cancel one, +1 min, stop all |
| [`messages-card.yaml`](dashboards/messages-card.yaml) | [`messages-package.yaml`](dashboards/messages-package.yaml) | the messages on the bar, clear one, leave one, clear all |

Neither names an entity of the bar: they find it with `integration_entities('jbl_bar_91')`, so they work whatever Home Assistant's language and the bar's entity ids. With several bars, they use the first one.

**1. Turn on packages, once.** In `configuration.yaml`, add (or complete) the `homeassistant:` section:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Then create the folder `packages` next to `configuration.yaml` (`/config/packages`), with the File editor, Studio Code Server or Samba add-on.

**2. Add the packages.** Copy each package you want into that folder, under a name of your own, one file per package:

```
/config/
├── configuration.yaml
└── packages/
    ├── jbl_timers.yaml      ← contents of timers-package.yaml
    └── jbl_messages.yaml    ← contents of messages-package.yaml
```

Do not paste both into one file, and do not replace one with the other: each file is its own package.

**3. Restart Home Assistant** (Settings › System › ⋮ › Restart). Before that, Developer tools › YAML › *Check configuration* should report no error. Afterwards, Settings › Devices & services › Helpers lists the new helpers (`jbl_timer_…`, `jbl_message_…`).

**4. Add the cards.** On a dashboard: Edit › Add card › *Manual*, then paste the contents of the card file. To show both in one card, put the `cards` of both under a single `vertical-stack`.

If a card shows *Entity not found*, or *The timers package is missing*, its package is not loaded: check the file is in `/config/packages`, the configuration check, then restart again. If it shows *No Timers entity* or *No Messages entity*, the integration or the toolkit remote on the bar is older than the feature. When the bar's remote is updated while Home Assistant runs, the integration reloads by itself to add the new entities.

## Restart

The **Restart** button (in the device's configuration) restarts the soundbar, for when it stops responding. The sound stops; the bar is back in about a minute, and the integration reconnects by itself. It needs a toolkit remote with `bar91.system.reboot`. Home Assistant does not ask before pressing a button, so on a dashboard add a confirmation:

```yaml
type: button
entity: button.jbl_bar_9_1_restart
name: Restart the soundbar
tap_action:
  action: perform-action
  perform_action: button.press
  target:
    entity_id: button.jbl_bar_9_1_restart
  confirmation:
    text: Restart the soundbar? The sound stops for about a minute.
```

## How it behaves

- **Live updates.** While the bar is on, the integration listens to the remote's event stream, so changes from the physical remote or the web page appear immediately. The stream makes the remote sample the bar every second, so it is closed in standby; a light state request every 15 s then detects the wake.
- **Same rules as the web page.** One control at a time. Levels that the bar can only cycle (bass, center, Atmos, rear, volume) are stepped one press at a time with read-back before the next. Switches and mute only send a toggle when the read-back state differs.
- **One command after the other.** A command waits (up to 90 s) while another control runs on the bar, whoever sent it, and is sent once the bar is free; "Another control is running" is refused by the remote before it acts, so that one refusal is followed by a new attempt. In scripts each step already waits for the bar's confirmation; to wait for commands sent elsewhere, use `wait_template: "{{ is_state('binary_sensor.jbl_bar_9_1_command_running', 'off') }}"`.
- **Refusals are shown, never retried.** If the remote refuses a control (for example a playback command the source does not support, rear levels while the speakers are docked, or another control already running), Home Assistant shows the remote's message. A stale security token after a remote restart is refreshed and the request is sent once more, because the remote rejects such requests before acting.
- **Front EQ** follows the remote: cuts only, front left/right only. With a remote that keeps the EQ until Reset, the preset keeps showing your choice while the bar waits to apply it again after a source change, Smart Mode or a restart (`status: waiting`, bands unavailable meanwhile); select *Original* to reset it. You can also change the preset or bands while the EQ cannot apply (standby, Smart Mode, another input or audio route): the remote saves the new curve and applies it once Standard audio plays. Older remotes refuse it then, and reset the EQ when the bar restarts.
- **Bass offset and Front EQ** do not run together: the remote pauses the bass offset while a Front EQ is applied.

## Troubleshooting

- *The remote refused Home Assistant*: rebuild the remote with an `allowed_cidr` that includes Home Assistant's address, and use the bar's IP address rather than `jbl.local`.
- *Cannot reach the browser remote*: check `http://<bar-ip>` (or `:8080`) in a browser on the same network.
- Diagnostics (*Download diagnostics* on the device page) contain the last state with the security token and names removed.

## Development

```sh
pip install pytest-homeassistant-custom-component
pytest -q
```

Tests run Home Assistant against a fake remote that enforces the real API rules (JSON content type, CSRF token, `409` refusals, event stream).

## Français

Intégration Home Assistant pour la **JBL Bar 9.1**, via la télécommande web locale de [kisinga/jbl-bar-toolkit](https://github.com/kisinga/jbl-bar-toolkit) (dépôt anciennement `naonak/jbl-bar-9.1-ha` : mettez à jour l'URL du dépôt personnalisé dans HACS, les entités ne changent pas). Installez d'abord cette télécommande sur la barre, avec un `allowed_cidr` qui inclut l'adresse de Home Assistant. Ajoutez ensuite ce dépôt dans HACS (*Dépôts personnalisés*, catégorie *Intégration*), installez-le, redémarrez, puis ajoutez l'intégration en saisissant l'IP de la barre. Seule la Bar 9.1 est prise en charge : l'intégration vérifie le modèle annoncé par la télécommande et refuse une autre barre. L'interface est traduite en français.

**Messages sur l'écran.** Les services `jbl_bar_91.display_message` et `jbl_bar_91.display_cancel` affichent un texte sur l'écran de la barre, allumée ou en veille, sans la réveiller. Le message accepte 31 caractères ; il est converti en majuscules sans accent. On peut le répéter (`repeat`), l'afficher pendant une durée (`duration`) ou jusqu'à annulation (`forever`). Un message avec le même `id` remplace le précédent : « Frigo fermé » remplace ainsi « Frigo ouvert ». Des messages d'`id` différents s'affichent à tour de rôle, passage par passage, chacun avec ses propres répétitions, sa durée ou son « jusqu'à annulation ». Un message sans `id` (y compris ceux de l'entité de notification) a l'identifiant `default` : `display_cancel` avec `id: default` l'efface, et sans `id` tous les messages (pas les minuteurs). Avec `clear_on_key: true`, n'importe quelle touche de la télécommande JBL efface le message, signe qu'il a été vu. Les boutons **Effacer le message sans nom** et **Effacer tous les messages** font de même, et le capteur **Messages** liste ceux en cours, avec une télécommande récente.

**Minuteurs.** `jbl_bar_91.timer_start` lance un minuteur sur la barre (durée, nom, temps restant affiché, son à la fin, volume minimum, durée de sonnerie). `jbl_bar_91.timer_cancel` l'arrête par nom, par identifiant ou tous. `jbl_bar_91.timer_extend` ajoute du temps à un minuteur en cours (1 minute par défaut), par nom ou identifiant, sinon au prochain à se terminer. À la fin, `TIME'S UP` et le nom défilent jusqu'à l'appui sur une touche de la télécommande JBL. Les entités *Minuteurs*, *Prochain minuteur* (compte à rebours) et *Minuteur qui sonne* servent au suivi. Un modèle de tableau de bord est fourni dans `dashboards/` : il trouve lui-même les entités de la barre, quelle que soit la langue. Chaque minuteur en cours y a sa ligne avec un bouton **Annuler**, et chaque message de la carte des messages un bouton **Effacer**, sans confirmation, grâce aux capteurs `sensor.jbl_timer_1` à `_4` et `sensor.jbl_message_1` à `_4` des packages. Exemple ci-dessus. L'entité de notification *Écran* (`notify.jbl_bar_9_1_ecran`) sert de cible à `notify.send_message` : chaque notification passe deux fois, et le titre est placé devant le message s'il tient dans les 31 caractères. Elle peut entrer dans un groupe de notifications, avec votre téléphone par exemple.

**Modèles de tableau de bord.** Chaque carte (`dashboards/timers-card.yaml`, `dashboards/messages-card.yaml`) a besoin de son *package* (`timers-package.yaml`, `messages-package.yaml`) :
1. dans `configuration.yaml`, ajoutez une seule fois `packages: !include_dir_named packages` sous `homeassistant:`, puis créez le dossier `/config/packages` ;
2. copiez chaque package dans ce dossier, un fichier par package (par exemple `jbl_timers.yaml` et `jbl_messages.yaml`), sans les fusionner ni les remplacer l'un par l'autre ;
3. vérifiez la configuration (Outils de développement › YAML), puis redémarrez Home Assistant ;
4. dans un tableau de bord, Modifier › Ajouter une carte › Manuel, et collez la carte.

Quand la télécommande de la barre est mise à jour pendant que Home Assistant tourne (minuteurs, messages…), l'intégration se recharge d'elle-même pour ajouter les nouvelles entités.

« Entité non trouvée » sur une carte veut dire que son package n'est pas chargé. Des versions françaises de ces fichiers, avec des libellés français, se font en traduisant les `name:` et textes ; les identifiants ne changent pas.

**Redémarrer.** Le bouton **Redémarrer** (dans la configuration de l'appareil, `button.jbl_bar_9_1_redemarrer` en français) redémarre la barre quand elle ne répond plus ; le son s'arrête environ une minute. Home Assistant ne demande pas de confirmation pour un bouton : sur un tableau de bord, ajoutez `confirmation` comme dans l'exemple ci-dessus.

## License

MIT

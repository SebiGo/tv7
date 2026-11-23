# TV7 Player

**English · Deutsch · Français · Italiano**: each language has its own section below, in this order.

---

# English

Watch Init7 TV7 and the SRG Full HD channels on the TV connected to your Home Assistant device. You choose channels in the **TV7** page in the Home Assistant sidebar, with your TV remote, or from automations.

## What you need
- An Init7 internet connection (the channels are only available in the Init7 network).
- A device with Home Assistant OS and an HDMI output, connected to your TV, projector or AV receiver. Developed and tested on a Raspberry Pi 5.

## Installation
1. Settings > Apps > App store > menu (⋮) > Repositories: add `https://github.com/SebiGo/tv7`.
2. Install **TV7 Player**, switch on **Show in sidebar** and start the app.
3. Open **TV7** in the sidebar and pick a channel.

No picture or sound? Switch the TV or receiver to the HDMI input of the device. If that does not help, see "Problems" below.

## Using it

### In Home Assistant
- **Player:** your **favorites** (tap the star on a channel) at the top, then the running channel with previous/next, stop, volume, mute, audio language and subtitles. Below: search and the channel lists **SRG Full HD** and **TV7**. Subtitles are off at every channel start; switch them on here when you need them.
- **Settings:** all options as drop-downs and switches. Most changes apply at once; options marked "restart" show a button to restart the app.
- **Nerd mode** (button at the top): technical details for the curious and for bug reports, plus the technical settings. Your browser remembers the choice.

### With the TV remote
If your TV or projector passes its remote control keys on to connected devices (HDMI-CEC, usually on by default), you can use TV7 without a phone:
- **OK** opens the menu on the TV: ▲ ▼ choose, ◀ ▶ switch between **Channels**, **Audio**, **Subtitles** and **Settings**, **OK** selects, **Back** closes.
- Without the menu: **channel +/−** switches channels, **digits** choose a channel number, **Info** shows technical details on the picture, **Play** starts the last channel again.
- Every channel start shows a short banner with logo and name. When nothing is playing, the TV shows the TV7 logo.

Starting a channel switches TV and receiver to TV7. When you turn the TV off or switch to another source, TV7 stops after a short while and continues when you switch back (see `hdmi_disconnect`). Which keys arrive depends on the TV.

## Options
The defaults suit most setups.

| Option | Meaning |
|---|---|
| `hdmi_port` | Which HDMI output to use. `auto` finds it; on a Raspberry Pi, `HDMI-A-1` is the port next to the power connector. |
| `hdmi_disconnect` | What happens when the TV is off, unplugged or shows another source: `resume` (default) stops and continues the same channel when TV7 is shown again, `stop` only stops, `keep` keeps playing (for receivers that wrongly report the TV as off). |
| `cec` | Control with the TV remote (HDMI-CEC). `auto` (default) uses it unless Home Assistant's HDMI-CEC integration already does; `off` switches it off. |
| `video_mode` | Output resolution. `auto` (default) uses 1080p, which fits the channels; higher resolutions only add load, the TV scales just as well. |
| `video_refresh` | `auto` (default) matches the TV's refresh rate to the channel for smooth motion. |
| `deinterlace` | Smooth picture for channels broadcast interlaced (default on). |
| `hardware_decoding` | `auto` (default) uses the video decoder of the device where possible, which keeps it cool and quiet. `no` turns it off. |
| `video_output` | `auto` (default). Change only when asked to in a bug report. |
| `decode_speed` | `fast` saves a little processor load at a barely visible cost in picture quality. |
| `audio_output` | `auto` (default). If there is no sound, try `pulseaudio` or `alsa`. |
| `audio_device` | Leave empty. For special setups only. |
| `audio_language` | Preferred audio language. |
| `audio_channels` | `auto` passes surround sound on; `stereo` always sends stereo. |
| `start_volume` | Volume at the start, 0-130 (100 = unchanged). |
| `idle_stop` | Stop after 60 to 480 minutes without operation, so the device does not keep playing when nobody watches. Default `off`. |
| `debug` | More details in the app log, for bug reports. |

The configuration page also shows an **Audio** section. The app does not use it; leave it as it is.

## Control from Home Assistant
**As a media player:** the ready-made package [tv7_media_player.yaml](https://github.com/SebiGo/tv7/blob/main/docs/tv7_media_player.yaml) adds `media_player.tv7` to Home Assistant: channel list (favorites first) with logo, start, stop, channel up/down, volume and mute, for dashboards and automations. How to install it is written at the top of the file.

Scripts and automations of this Home Assistant control the player at `http://127.0.0.1:8765` (all calls are `GET`).

| Call | Effect |
|---|---|
| `/play?channel=SRF%201` | start a channel by name or number |
| `/stop` | stop |
| `/volume?v=50` or `?d=5` | set or change the volume |
| `/mute` | mute on/off |
| `/status` | what is playing |
| `/channels` | channel list |
| `/osd?on=1` / `?on=0` | technical details on the TV picture on/off |
| `/key?k=ok` | a remote control key (`ok`, `up`, `down`, `left`, `right`, `back`, `ch_up`, `ch_down`, `info`, `stop`, `0`–`9`) |

```yaml
rest_command:
  tv7_play:
    url: "http://127.0.0.1:8765/play?channel={{ channel | urlencode }}"
    timeout: 70
  tv7_stop:
    url: "http://127.0.0.1:8765/stop"

script:
  tv7_srf1:
    sequence:
      - action: rest_command.tv7_play
        data:
          channel: "SRF 1"
```

## Good to know
- The channel list comes live from Init7; new channels appear without an update.
- If the TV was off when the app started, the first channel takes a few seconds longer.

## Problems
- **No sound:** in **Settings > Environment**, check the audio device, then try `audio_output`.
- **No picture:** switch the TV to the right input; with two HDMI ports, try `hdmi_port`.
- **Bug report:** press **Copy support info** at the top of **Settings** and paste the text into a new issue at https://github.com/SebiGo/tv7/issues. Passwords, tokens and addresses are masked with `****`; read the text once before you post it.

## Changelog
The changes are listed in the Changelog tab of the app. Versions follow [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

## License
MIT, see [LICENSE.md](https://github.com/SebiGo/tv7/blob/main/LICENSE.md). The TV7 name and logo belong to Init7 (Schweiz) AG and are excluded.

---

# Deutsch

Init7 TV7 und die SRG-Full-HD-Sender auf dem Fernseher schauen, der an deinem Home-Assistant-Gerät hängt. Die Sender wählst du auf der Seite **TV7** in der Seitenleiste von Home Assistant, mit der Fernbedienung des Fernsehers oder aus Automationen.

## Was du brauchst
- Einen Init7-Internetanschluss (die Sender gibt es nur im Init7-Netz).
- Ein Gerät mit Home Assistant OS und HDMI-Ausgang, angeschlossen an Fernseher, Projektor oder AV-Receiver. Entwickelt und getestet auf einem Raspberry Pi 5.

## Installation
1. Einstellungen > Apps > App-Store > Menü (⋮) > Repositories: `https://github.com/SebiGo/tv7` hinzufügen.
2. **TV7 Player** installieren, **In der Seitenleiste anzeigen** einschalten und die App starten.
3. **TV7** in der Seitenleiste öffnen und einen Sender wählen.

Kein Bild oder kein Ton? Fernseher oder Receiver auf den HDMI-Eingang des Geräts stellen. Hilft das nicht, siehe unten "Probleme".

## Benutzung

### In Home Assistant
- **Player:** oben deine **Favoriten** (Stern am Sender antippen), darunter der laufende Sender mit vorherigem/nächstem Sender, Stopp, Lautstärke, Stumm, Tonsprache und Untertiteln. Weiter unten: Suche und die Senderlisten **SRG Full HD** und **TV7**. Untertitel sind bei jedem Senderstart aus; bei Bedarf hier einschalten.
- **Einstellungen:** alle Optionen als Auswahlmenüs und Schalter. Die meisten Änderungen wirken sofort; Optionen mit "Neustart" zeigen einen Knopf zum Neustarten der App.
- **Nerd-Modus** (Knopf oben): technische Angaben für Neugierige und für Fehlermeldungen, dazu die technischen Einstellungen. Der Browser merkt sich die Wahl.

### Mit der Fernbedienung des Fernsehers
Reicht dein Fernseher oder Projektor die Tasten seiner Fernbedienung an angeschlossene Geräte weiter (HDMI-CEC, meist schon eingeschaltet), geht TV7 auch ohne Handy:
- **OK** öffnet das Menü im Fernsehbild: ▲ ▼ wählen, ◀ ▶ zwischen **Sender**, **Ton**, **Untertitel** und **Einstellungen** wechseln, **OK** auswählen, **Zurück** schliessen.
- Ohne Menü: **Kanal +/−** schaltet um, **Ziffern** wählen eine Sendernummer, **Info** blendet technische Angaben ein, **Play** startet den letzten Sender wieder.
- Jeder Senderstart zeigt kurz ein Banner mit Logo und Name. Läuft nichts, zeigt der Fernseher das TV7-Logo.

Ein Senderstart schaltet Fernseher und Receiver auf TV7. Schaltest du den Fernseher aus oder auf eine andere Quelle, stoppt TV7 nach kurzer Zeit und läuft weiter, sobald du zurückschaltest (siehe `hdmi_disconnect`). Welche Tasten ankommen, hängt vom Fernseher ab.

## Optionen
Die Standardwerte passen für die meisten Aufbauten.

| Option | Bedeutung |
|---|---|
| `hdmi_port` | Welcher HDMI-Ausgang genutzt wird. `auto` findet ihn; beim Raspberry Pi ist `HDMI-A-1` der Anschluss neben der Stromversorgung. |
| `hdmi_disconnect` | Was passiert, wenn der Fernseher aus, abgesteckt oder auf einer anderen Quelle ist: `resume` (Standard) stoppt und setzt denselben Sender fort, sobald TV7 wieder gezeigt wird, `stop` stoppt nur, `keep` spielt weiter (für Receiver, die den Fernseher fälschlich als aus melden). |
| `cec` | Bedienung mit der Fernbedienung des Fernsehers (HDMI-CEC). `auto` (Standard) nutzt sie, ausser die HDMI-CEC-Integration von Home Assistant tut das schon; `off` schaltet sie aus. |
| `video_mode` | Ausgabeauflösung. `auto` (Standard) nimmt 1080p, das passt zu den Sendern; höhere Auflösungen belasten nur das Gerät, der Fernseher skaliert genauso gut. |
| `video_refresh` | `auto` (Standard) stellt die Bildwiederholrate des Fernsehers auf den Sender ein, für flüssige Bewegungen. |
| `deinterlace` | Ruhiges Bild bei Sendern im Zeilensprungverfahren (Standard an). |
| `hardware_decoding` | `auto` (Standard) nutzt wo möglich den Video-Decoder des Geräts, das hält es kühl und leise. `no` schaltet das aus. |
| `video_output` | `auto` (Standard). Nur ändern, wenn eine Fehlermeldung darum bittet. |
| `decode_speed` | `fast` spart etwas Prozessorlast bei kaum sichtbar geringerer Bildqualität. |
| `audio_output` | `auto` (Standard). Fehlt der Ton, `pulseaudio` oder `alsa` ausprobieren. |
| `audio_device` | Leer lassen. Nur für besondere Aufbauten. |
| `audio_language` | Bevorzugte Tonsprache. |
| `audio_channels` | `auto` gibt Surround-Ton weiter; `stereo` sendet immer Stereo. |
| `start_volume` | Lautstärke beim Start, 0-130 (100 = unverändert). |
| `idle_stop` | Nach 60 bis 480 Minuten ohne Bedienung stoppen, damit das Gerät nicht weiterspielt, wenn niemand schaut. Standard `off`. |
| `debug` | Mehr Angaben im Protokoll der App, für Fehlermeldungen. |

Auf der Konfigurationsseite erscheint ausserdem ein Abschnitt **Audio**. Die App nutzt ihn nicht; lass ihn unverändert.

## Steuerung aus Home Assistant
**Als Media Player:** das fertige Paket [tv7_media_player.yaml](https://github.com/SebiGo/tv7/blob/main/docs/tv7_media_player.yaml) fügt Home Assistant `media_player.tv7` hinzu: Senderliste (Favoriten zuerst) mit Logo, Start, Stopp, Sender auf/ab, Lautstärke und Ton aus, für Dashboards und Automationen. Wie man es installiert, steht oben in der Datei (auf Englisch).

Skripte und Automationen dieses Home Assistant steuern den Player unter `http://127.0.0.1:8765` (alle Aufrufe sind `GET`).

| Aufruf | Wirkung |
|---|---|
| `/play?channel=SRF%201` | Sender starten (Name oder Nummer) |
| `/stop` | Stopp |
| `/volume?v=50` oder `?d=5` | Lautstärke setzen oder ändern |
| `/mute` | Stumm ein/aus |
| `/status` | was gerade läuft |
| `/channels` | Senderliste |
| `/osd?on=1` / `?on=0` | technische Angaben im Fernsehbild ein/aus |
| `/key?k=ok` | eine Fernbedienungstaste (`ok`, `up`, `down`, `left`, `right`, `back`, `ch_up`, `ch_down`, `info`, `stop`, `0`–`9`) |

Ein Beispiel mit `rest_command` und `script` steht im englischen Abschnitt.

## Gut zu wissen
- Die Senderliste kommt live von Init7; neue Sender erscheinen ohne Update.
- War der Fernseher beim Start der App aus, dauert der erste Senderstart ein paar Sekunden länger.

## Probleme
- **Kein Ton:** unter **Einstellungen > Umgebung** das Audiogerät prüfen, dann `audio_output` ausprobieren.
- **Kein Bild:** den Fernseher auf den richtigen Eingang stellen; bei zwei HDMI-Anschlüssen `hdmi_port` ausprobieren.
- **Fehler melden:** oben in den **Einstellungen** auf **Support-Infos kopieren** drücken und den Text in ein neues Issue unter https://github.com/SebiGo/tv7/issues einfügen. Passwörter, Tokens und Adressen sind mit `****` maskiert; den Text vor dem Posten einmal durchlesen.

---

# Français

Regardez Init7 TV7 et les chaînes SRG Full HD sur le téléviseur relié à votre appareil Home Assistant. Vous choisissez les chaînes sur la page **TV7** de la barre latérale de Home Assistant, avec la télécommande du téléviseur ou depuis des automatisations.

## Prérequis
- Une connexion Internet Init7 (les chaînes ne sont disponibles que dans le réseau Init7).
- Un appareil sous Home Assistant OS avec sortie HDMI, relié au téléviseur, au projecteur ou au récepteur AV. Développé et testé sur un Raspberry Pi 5.

## Installation
1. Paramètres > Applications > Boutique d'applications > menu (⋮) > Dépôts : ajouter `https://github.com/SebiGo/tv7`.
2. Installer **TV7 Player**, activer **Afficher dans la barre latérale** et démarrer l'application.
3. Ouvrir **TV7** dans la barre latérale et choisir une chaîne.

Pas d'image ou pas de son ? Mettez le téléviseur ou le récepteur sur l'entrée HDMI de l'appareil. Si cela ne suffit pas, voir « Problèmes » ci-dessous.

## Utilisation

### Dans Home Assistant
- **Lecteur :** en haut vos **favoris** (touchez l'étoile d'une chaîne), puis la chaîne en cours avec chaîne précédente/suivante, arrêt, volume, muet, langue audio et sous-titres. Plus bas : la recherche et les listes **SRG Full HD** et **TV7**. Les sous-titres sont désactivés à chaque démarrage de chaîne ; activez-les ici si besoin.
- **Réglages :** toutes les options sous forme de menus et d'interrupteurs. La plupart des changements s'appliquent tout de suite ; les options marquées « redémarrage » affichent un bouton pour redémarrer l'application.
- **Mode nerd** (bouton en haut) : détails techniques pour les curieux et pour les rapports de bug, ainsi que les réglages techniques. Le navigateur retient le choix.

### Avec la télécommande du téléviseur
Si votre téléviseur ou projecteur transmet les touches de sa télécommande aux appareils connectés (HDMI-CEC, généralement activé), TV7 s'utilise aussi sans téléphone :
- **OK** ouvre le menu à l'écran : ▲ ▼ choisir, ◀ ▶ passer entre **Chaînes**, **Audio**, **Sous-titres** et **Réglages**, **OK** valider, **Retour** fermer.
- Sans menu : **chaîne +/−** change de chaîne, les **chiffres** choisissent un numéro de chaîne, **Info** affiche les détails techniques, **Play** relance la dernière chaîne.
- Chaque démarrage de chaîne affiche brièvement un bandeau avec logo et nom. Quand rien ne joue, le téléviseur affiche le logo TV7.

Le démarrage d'une chaîne bascule le téléviseur et le récepteur sur TV7. Si vous éteignez le téléviseur ou passez à une autre source, TV7 s'arrête peu après et reprend quand vous revenez (voir `hdmi_disconnect`). Les touches transmises dépendent du téléviseur.

## Options
Les valeurs par défaut conviennent à la plupart des installations.

| Option | Signification |
|---|---|
| `hdmi_port` | La sortie HDMI utilisée. `auto` la trouve ; sur un Raspberry Pi, `HDMI-A-1` est le port à côté de l'alimentation. |
| `hdmi_disconnect` | Ce qui se passe quand le téléviseur est éteint, débranché ou sur une autre source : `resume` (par défaut) arrête puis reprend la même chaîne quand TV7 est de nouveau affiché, `stop` arrête seulement, `keep` continue (pour les récepteurs qui signalent à tort le téléviseur comme éteint). |
| `cec` | Commande avec la télécommande du téléviseur (HDMI-CEC). `auto` (par défaut) l'utilise, sauf si l'intégration HDMI-CEC de Home Assistant le fait déjà ; `off` la désactive. |
| `video_mode` | Résolution de sortie. `auto` (par défaut) utilise 1080p, adapté aux chaînes ; une résolution plus élevée ne fait que charger l'appareil, le téléviseur agrandit tout aussi bien. |
| `video_refresh` | `auto` (par défaut) adapte la fréquence du téléviseur à la chaîne, pour des mouvements fluides. |
| `deinterlace` | Image stable pour les chaînes diffusées en entrelacé (activé par défaut). |
| `hardware_decoding` | `auto` (par défaut) utilise si possible le décodeur vidéo de l'appareil, qui reste ainsi frais et silencieux. `no` le désactive. |
| `video_output` | `auto` (par défaut). À changer seulement si un rapport de bug le demande. |
| `decode_speed` | `fast` économise un peu de charge processeur pour une perte de qualité à peine visible. |
| `audio_output` | `auto` (par défaut). S'il n'y a pas de son, essayez `pulseaudio` ou `alsa`. |
| `audio_device` | Laisser vide. Pour des installations particulières seulement. |
| `audio_language` | Langue audio préférée. |
| `audio_channels` | `auto` transmet le son surround ; `stereo` envoie toujours de la stéréo. |
| `start_volume` | Volume au démarrage, 0-130 (100 = inchangé). |
| `idle_stop` | Arrêter après 60 à 480 minutes sans utilisation, pour que l'appareil ne continue pas quand personne ne regarde. Par défaut `off`. |
| `debug` | Plus de détails dans le journal de l'application, pour les rapports de bug. |

La page de configuration affiche aussi une section **Audio**. L'application ne l'utilise pas ; laissez-la telle quelle.

## Commande depuis Home Assistant
**Comme lecteur multimédia :** le paquet prêt à l'emploi [tv7_media_player.yaml](https://github.com/SebiGo/tv7/blob/main/docs/tv7_media_player.yaml) ajoute `media_player.tv7` à Home Assistant : liste des chaînes (favoris en premier) avec logo, démarrage, arrêt, chaîne suivante/précédente, volume et sourdine, pour les tableaux de bord et les automatisations. L'installation est décrite en tête du fichier (en anglais).

Les scripts et automatisations de ce Home Assistant pilotent le lecteur à `http://127.0.0.1:8765` (tous les appels sont des `GET`).

| Appel | Effet |
|---|---|
| `/play?channel=SRF%201` | lancer une chaîne (nom ou numéro) |
| `/stop` | arrêt |
| `/volume?v=50` ou `?d=5` | régler ou modifier le volume |
| `/mute` | muet oui/non |
| `/status` | ce qui joue |
| `/channels` | liste des chaînes |
| `/osd?on=1` / `?on=0` | détails techniques à l'écran oui/non |
| `/key?k=ok` | une touche de télécommande (`ok`, `up`, `down`, `left`, `right`, `back`, `ch_up`, `ch_down`, `info`, `stop`, `0`–`9`) |

Un exemple avec `rest_command` et `script` figure dans la section anglaise.

## Bon à savoir
- La liste des chaînes vient en direct d'Init7 ; les nouvelles chaînes apparaissent sans mise à jour.
- Si le téléviseur était éteint au démarrage de l'application, la première chaîne met quelques secondes de plus à démarrer.

## Problèmes
- **Pas de son :** dans **Réglages > Environnement**, vérifiez le périphérique audio, puis essayez `audio_output`.
- **Pas d'image :** mettez le téléviseur sur la bonne entrée ; avec deux ports HDMI, essayez `hdmi_port`.
- **Signaler un bug :** appuyez sur **Copier les infos de support** en haut des **Réglages** et collez le texte dans une nouvelle issue sur https://github.com/SebiGo/tv7/issues. Mots de passe, jetons et adresses sont masqués par `****` ; relisez le texte avant de le publier.

---

# Italiano

Guarda Init7 TV7 e i canali SRG Full HD sul televisore collegato al tuo dispositivo Home Assistant. Scegli i canali nella pagina **TV7** della barra laterale di Home Assistant, con il telecomando del televisore o da automazioni.

## Cosa serve
- Una connessione Internet Init7 (i canali sono disponibili solo nella rete Init7).
- Un dispositivo con Home Assistant OS e uscita HDMI, collegato al televisore, al proiettore o al ricevitore AV. Sviluppato e testato su un Raspberry Pi 5.

## Installazione
1. Impostazioni > App > Store delle app > menu (⋮) > Repository: aggiungere `https://github.com/SebiGo/tv7`.
2. Installare **TV7 Player**, attivare **Mostra nella barra laterale** e avviare l'app.
3. Aprire **TV7** nella barra laterale e scegliere un canale.

Niente immagine o niente audio? Imposta il televisore o il ricevitore sull'ingresso HDMI del dispositivo. Se non basta, vedi «Problemi» più sotto.

## Uso

### In Home Assistant
- **Lettore:** in alto i tuoi **preferiti** (tocca la stella di un canale), poi il canale in corso con canale precedente/successivo, stop, volume, muto, lingua audio e sottotitoli. Più sotto: la ricerca e gli elenchi **SRG Full HD** e **TV7**. I sottotitoli sono spenti a ogni avvio di un canale; attivali qui se servono.
- **Impostazioni:** tutte le opzioni come menu e interruttori. La maggior parte delle modifiche vale subito; le opzioni contrassegnate «riavvio» mostrano un pulsante per riavviare l'app.
- **Modalità nerd** (pulsante in alto): dettagli tecnici per i curiosi e per le segnalazioni di errori, più le impostazioni tecniche. Il browser ricorda la scelta.

### Con il telecomando del televisore
Se il televisore o il proiettore inoltra i tasti del suo telecomando ai dispositivi collegati (HDMI-CEC, di solito già attivo), TV7 si usa anche senza telefono:
- **OK** apre il menu sullo schermo: ▲ ▼ scegliere, ◀ ▶ passare tra **Canali**, **Audio**, **Sottotitoli** e **Impostazioni**, **OK** selezionare, **Indietro** chiudere.
- Senza menu: **canale +/−** cambia canale, le **cifre** scelgono un numero di canale, **Info** mostra i dettagli tecnici, **Play** riavvia l'ultimo canale.
- Ogni avvio di un canale mostra brevemente un banner con logo e nome. Quando non c'è niente in riproduzione, il televisore mostra il logo TV7.

L'avvio di un canale commuta televisore e ricevitore su TV7. Se spegni il televisore o passi a un'altra sorgente, TV7 si ferma poco dopo e riprende quando torni (vedi `hdmi_disconnect`). Quali tasti arrivano dipende dal televisore.

## Opzioni
I valori predefiniti vanno bene per la maggior parte dei casi.

| Opzione | Significato |
|---|---|
| `hdmi_port` | Quale uscita HDMI usare. `auto` la trova; su un Raspberry Pi, `HDMI-A-1` è la porta accanto all'alimentazione. |
| `hdmi_disconnect` | Cosa succede quando il televisore è spento, scollegato o su un'altra sorgente: `resume` (predefinito) ferma e riprende lo stesso canale quando TV7 viene di nuovo mostrato, `stop` ferma soltanto, `keep` continua (per i ricevitori che segnalano per errore il televisore come spento). |
| `cec` | Comando con il telecomando del televisore (HDMI-CEC). `auto` (predefinito) lo usa, a meno che l'integrazione HDMI-CEC di Home Assistant lo faccia già; `off` lo disattiva. |
| `video_mode` | Risoluzione di uscita. `auto` (predefinito) usa 1080p, adatto ai canali; risoluzioni più alte caricano solo il dispositivo, il televisore ingrandisce altrettanto bene. |
| `video_refresh` | `auto` (predefinito) adatta la frequenza del televisore al canale, per movimenti fluidi. |
| `deinterlace` | Immagine stabile per i canali trasmessi in interlacciato (attivo per impostazione predefinita). |
| `hardware_decoding` | `auto` (predefinito) usa se possibile il decodificatore video del dispositivo, che resta così fresco e silenzioso. `no` lo disattiva. |
| `video_output` | `auto` (predefinito). Da cambiare solo se richiesto in una segnalazione di errore. |
| `decode_speed` | `fast` risparmia un po' di carico del processore con una perdita di qualità appena visibile. |
| `audio_output` | `auto` (predefinito). Se manca l'audio, prova `pulseaudio` o `alsa`. |
| `audio_device` | Lasciare vuoto. Solo per configurazioni particolari. |
| `audio_language` | Lingua audio preferita. |
| `audio_channels` | `auto` trasmette l'audio surround; `stereo` invia sempre stereo. |
| `start_volume` | Volume all'avvio, 0-130 (100 = invariato). |
| `idle_stop` | Fermare dopo 60-480 minuti senza utilizzo, così il dispositivo non continua quando nessuno guarda. Predefinito `off`. |
| `debug` | Più dettagli nel registro dell'app, per le segnalazioni di errori. |

Nella pagina di configurazione compare anche una sezione **Audio**. L'app non la usa; lasciala com'è.

## Controllo da Home Assistant
**Come lettore multimediale:** il pacchetto pronto [tv7_media_player.yaml](https://github.com/SebiGo/tv7/blob/main/docs/tv7_media_player.yaml) aggiunge `media_player.tv7` a Home Assistant: elenco dei canali (prima i preferiti) con logo, avvio, stop, canale su/giù, volume e muto, per dashboard e automazioni. Come installarlo è scritto all'inizio del file (in inglese).

Script e automazioni di questo Home Assistant controllano il lettore all'indirizzo `http://127.0.0.1:8765` (tutte le chiamate sono `GET`).

| Chiamata | Effetto |
|---|---|
| `/play?channel=SRF%201` | avvia un canale (nome o numero) |
| `/stop` | stop |
| `/volume?v=50` oppure `?d=5` | imposta o cambia il volume |
| `/mute` | muto sì/no |
| `/status` | cosa è in riproduzione |
| `/channels` | elenco dei canali |
| `/osd?on=1` / `?on=0` | dettagli tecnici sullo schermo sì/no |
| `/key?k=ok` | un tasto del telecomando (`ok`, `up`, `down`, `left`, `right`, `back`, `ch_up`, `ch_down`, `info`, `stop`, `0`–`9`) |

Un esempio con `rest_command` e `script` si trova nella sezione inglese.

## Da sapere
- L'elenco dei canali arriva in diretta da Init7; i nuovi canali compaiono senza aggiornamenti.
- Se il televisore era spento all'avvio dell'app, il primo canale impiega qualche secondo in più.

## Problemi
- **Niente audio:** in **Impostazioni > Ambiente** controlla il dispositivo audio, poi prova `audio_output`.
- **Niente immagine:** imposta il televisore sull'ingresso giusto; con due porte HDMI prova `hdmi_port`.
- **Segnalare un errore:** premi **Copia info di supporto** in alto nelle **Impostazioni** e incolla il testo in una nuova issue su https://github.com/SebiGo/tv7/issues. Password, token e indirizzi sono mascherati con `****`; rileggi il testo prima di pubblicarlo.

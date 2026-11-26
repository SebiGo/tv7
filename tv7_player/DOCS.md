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
- **Nerd mode** (button at the top): technical details for the curious and for bug reports, plus the technical settings and an overview of the device: HDMI ports, devices on HDMI-CEC, audio devices and the current options. Your browser remembers the choice.

### With the TV remote
If your TV or projector passes its remote control keys on to connected devices (HDMI-CEC, usually on by default), you can use TV7 without a phone:
- **OK** opens the menu on the TV: ▲ ▼ choose, ◀ ▶ switch between **Channels**, **Audio**, **Subtitles** and **Settings**, **OK** selects, **Back** closes.
- Without the menu: **channel +/−** switches channels, **digits** choose a channel number, **Info** shows technical details on the picture, **Play** starts the last channel again.
- Every channel start shows a short banner with logo and name. When nothing is playing, the TV shows the TV7 logo.

Starting a channel switches TV and receiver to TV7. When you turn the TV off or switch to another source, TV7 stops after a short while and continues the same channel when you switch back. Which keys arrive depends on the TV.

## Options
Vous n'avez rien à régler : l'application trouve elle-même le port HDMI, la sortie son et une bonne image. Les options servent quand vous voulez autre chose. Vous les trouvez dans **Réglages** sur la page TV7, dans le menu du téléviseur sous **Réglages** ou sur la page de configuration de l'application dans Home Assistant.

| Option | Ce qu'elle fait |
|---|---|
| `hdmi_port` | La sortie HDMI de l'appareil à laquelle le téléviseur est branché. `auto` (par défaut) la trouve. Sur un Raspberry Pi, `HDMI-A-1` est le port à côté de l'alimentation. |
| `cec` | Commande avec la télécommande du téléviseur (HDMI-CEC). `auto` (par défaut) l'utilise, sauf si l'intégration HDMI-CEC de Home Assistant le fait déjà ; l'option est alors grisée. `off` la désactive. |
| `video_mode` | Résolution de l'image. `auto` (par défaut) utilise 1080p, adapté aux chaînes. Une résolution plus élevée ne fait que charger l'appareil ; le téléviseur met l'image à l'échelle tout aussi bien. |
| `decode_speed` | `quality` (par défaut). `fast` économise un peu de processeur pour une perte de qualité à peine visible. |
| `audio_channels` | `auto` (par défaut) transmet le son surround au récepteur ; `stereo` envoie toujours de la stéréo. |
| `idle_stop` | Arrête la lecture après 60 à 480 minutes sans utilisation, pour que l'appareil ne continue pas quand personne ne regarde. `off` (par défaut) : jamais. |
| `debug` | Plus de détails dans le journal de l'application, pour les rapports de bug. |

Les options marquées « redémarrage » dans les réglages prennent effet après un redémarrage de l'application ; la page affiche un bouton pour cela.

### Ce que l'application fait d'elle-même
- **Image :** la fréquence de rafraîchissement du téléviseur suit la chaîne (mouvements fluides). Les chaînes diffusées en entrelacé sont désentrelacées. Si l'appareil a un décodeur vidéo, l'application l'utilise ; cela le garde frais et silencieux.
- **Son :** passe par HDMI vers le téléviseur ou le récepteur. La langue audio est celle que la chaîne diffuse en premier ; changez-la dans le lecteur ou dans le menu du téléviseur pendant la lecture. Au démarrage de l'application, le volume est à 100 %.
- **Téléviseur éteint ou autre source :** TV7 s'arrête peu après et reprend la même chaîne quand le téléviseur affiche de nouveau TV7.

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
- **Pas de son :** vérifiez que le téléviseur ou le récepteur est sur la bonne entrée HDMI et pas en sourdine. Activez ensuite le **mode nerd** et regardez les périphériques audio dans **Réglages** : un périphérique HDMI devrait être marqué actif. Si aucun ne l'est, redémarrez l'application ; s'il n'y a toujours pas de son, signalez le problème (voir ci-dessous).
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
- **Modalità nerd** (pulsante in alto): dettagli tecnici per i curiosi e per le segnalazioni di errori, più le impostazioni tecniche e una panoramica del dispositivo: porte HDMI, dispositivi su HDMI-CEC, dispositivi audio e opzioni attuali. Il browser ricorda la scelta.

### Con il telecomando del televisore
Se il televisore o il proiettore inoltra i tasti del suo telecomando ai dispositivi collegati (HDMI-CEC, di solito già attivo), TV7 si usa anche senza telefono:
- **OK** apre il menu sullo schermo: ▲ ▼ scegliere, ◀ ▶ passare tra **Canali**, **Audio**, **Sottotitoli** e **Impostazioni**, **OK** selezionare, **Indietro** chiudere.
- Senza menu: **canale +/−** cambia canale, le **cifre** scelgono un numero di canale, **Info** mostra i dettagli tecnici, **Play** riavvia l'ultimo canale.
- Ogni avvio di un canale mostra brevemente un banner con logo e nome. Quando non c'è niente in riproduzione, il televisore mostra il logo TV7.

L'avvio di un canale commuta televisore e ricevitore su TV7. Se spegni il televisore o passi a un'altra sorgente, TV7 si ferma poco dopo e riprende lo stesso canale quando torni. Quali tasti arrivano dipende dal televisore.

## Opzioni
Non devi impostare nulla: l'app trova da sola la porta HDMI, l'uscita audio e una buona immagine. Le opzioni servono quando vuoi qualcosa di diverso. Le trovi in **Impostazioni** nella pagina TV7, nel menu del televisore sotto **Impostazioni** o nella pagina di configurazione dell'app in Home Assistant.

| Opzione | Cosa fa |
|---|---|
| `hdmi_port` | L'uscita HDMI del dispositivo a cui è collegato il televisore. `auto` (predefinito) la trova. Sul Raspberry Pi, `HDMI-A-1` è la porta accanto all'alimentazione. |
| `cec` | Comando con il telecomando del televisore (HDMI-CEC). `auto` (predefinito) lo usa, a meno che l'integrazione HDMI-CEC di Home Assistant lo faccia già; allora l'opzione è grigia. `off` lo disattiva. |
| `video_mode` | Risoluzione dell'immagine. `auto` (predefinito) usa 1080p, adatto ai canali. Risoluzioni più alte caricano solo il dispositivo; il televisore scala l'immagine altrettanto bene. |
| `decode_speed` | `quality` (predefinito). `fast` risparmia un po' di processore con una perdita di qualità appena visibile. |
| `audio_channels` | `auto` (predefinito) passa l'audio surround al ricevitore; `stereo` invia sempre stereo. |
| `idle_stop` | Ferma la riproduzione dopo 60 a 480 minuti senza utilizzo, così il dispositivo non continua quando nessuno guarda. `off` (predefinito): mai. |
| `debug` | Più dettagli nel registro dell'app, per le segnalazioni di errori. |

Le opzioni contrassegnate con «riavvio» nelle impostazioni hanno effetto dopo un riavvio dell'app; la pagina mostra un pulsante per farlo.

### Cosa fa l'app da sola
- **Immagine:** la frequenza di aggiornamento del televisore segue il canale (movimenti fluidi). I canali trasmessi interlacciati vengono deinterlacciati. Se il dispositivo ha un decoder video, l'app lo usa; così resta fresco e silenzioso.
- **Audio:** va al televisore o al ricevitore tramite HDMI. La lingua audio è quella che il canale trasmette per prima; cambiala nel player o nel menu del televisore mentre un canale è in onda. All'avvio dell'app il volume è al 100 %.
- **Televisore spento o altra sorgente:** TV7 si ferma poco dopo e riprende lo stesso canale quando il televisore mostra di nuovo TV7.

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
- **Niente audio:** controlla che il televisore o il ricevitore sia sull'ingresso HDMI giusto e non in muto. Poi attiva la **modalità nerd** e guarda i dispositivi audio in **Impostazioni**: un dispositivo HDMI dovrebbe essere segnato come attivo. Se nessuno lo è, riavvia l'app; se l'audio manca ancora, segnala l'errore (vedi sotto).
- **Niente immagine:** imposta il televisore sull'ingresso giusto; con due porte HDMI prova `hdmi_port`.
- **Segnalare un errore:** premi **Copia info di supporto** in alto nelle **Impostazioni** e incolla il testo in una nuova issue su https://github.com/SebiGo/tv7/issues. Password, token e indirizzi sono mascherati con `****`; rileggi il testo prima di pubblicarlo.

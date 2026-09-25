# Opus Latency Analyzer — Windows V1 (prototype)

## Obtenir l'exécutable Windows sans installer Python
1. Créer un dépôt GitHub privé et y déposer **le contenu** de ce dossier, y compris `.github/workflows/windows.yml` (conserver l'arborescence).
2. Dans GitHub, ouvrir **Actions → Build Windows executable → Run workflow** (ou pousser sur `main`).
3. Après la compilation, ouvrir l'exécution terminée puis télécharger l'artifact **OpusLatencyAnalyzer-Windows-x64**.
4. Décompresser l'artifact : il contient `OpusLatencyAnalyzer.exe`, application graphique autonome (pas un installateur MSI). Windows peut afficher un avertissement SmartScreen car l'exécutable n'est pas signé.

## Montage et précautions
- Sortie gauche de la M-Track Duo → répartiteur compatible → entrée 1 LINE de la M-Track et entrée LINE de l'AuraGate.
- Sortie casque 3,5 mm AuraSTRX → adaptateur séparant L/R, un seul canal → entrée 2 LINE de la M-Track. Volume casque faible au démarrage.
- 48 V OFF, monitoring DIRECT désactivé / USB, 48 kHz, gains réglés sans écrêtage.
- MIC : utiliser un atténuateur et respecter le niveau d'entrée de l'émetteur; ne pas envoyer directement un niveau ligne sur une entrée micro.
- Dante/AES67 : cette V1 nécessite un **convertisseur externe analogique vers Dante/AES67** alimenté par la sortie M-Track, avec référence analogique commune sur entrée 1. Elle ne génère ni ne reçoit directement du Dante/AES67 et ne pilote pas Dante Virtual Soundcard.

## Utilisation
1. Choisir le périphérique audio duplex 2 entrées / 2 sorties, le mode et la chaîne.
2. Faire d'abord une boucle directe : envoyer le même signal vers les entrées 1 et 2, puis cliquer **Étalonner**.
3. Rebrancher le circuit Auracast; lancer une série de mesures; exporter CSV.

## Limites V1
Prototype non testé avec la M-Track Duo réelle et non compilé sur Windows dans cet environnement. Le logiciel mesure le décalage électrique entre les deux entrées, pas le délai radio isolé. La fonction d'étalonnage soustrait le décalage médian inter-voies. Les séries utilisent des acquisitions répétées, pas un flux continu 24 h. Une interface 2 entrées ne permet pas d'acquérir référence + 2 récepteurs simultanément. La V1 ne comporte pas de graphe de formes d'onde ni d'installateur signé.

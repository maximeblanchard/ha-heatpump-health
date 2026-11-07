# HeatPump-Health — Home Assistant

<img src="custom_components/heatpump_health/icon.png" width="96" height="96" alt="Logo HeatPump-Health">

Intégration personnalisée Home Assistant qui calcule des indicateurs d'usure d'une pompe à
chaleur (ou de tout appareil à cycles marche/arrêt), son efficacité énergétique quotidienne
en **kWh / DJU** (standard base 18 °C et **DJU réel** compensé par la température intérieure
moyenne) ainsi qu'une estimation de rendement thermodynamique à partir d'un simple capteur
de puissance en Watts.

## Indicateurs fournis

### Usure et cycles (toujours créés)

| Entité | Description |
|---|---|
| `sensor.<nom>_nombre_de_cycles_total` | Nombre total de cycles depuis l'installation |
| `sensor.<nom>_usure` | Usure en % (cycles / cycles max) |
| `sensor.<nom>_temps_de_fonctionnement_total` | Temps de fonctionnement cumulé (h) |
| `sensor.<nom>_temps_de_fonctionnement_7_jours` | Temps de fonctionnement sur 7 jours glissants (h) |
| `sensor.<nom>_cycles_aujourdhui` | Nombre de cycles depuis minuit (reset quotidien) |
| `sensor.<nom>_cycles_7_jours` | Nombre de cycles sur les 7 derniers jours |
| `sensor.<nom>_duree_moyenne_dun_cycle_7_jours` | Durée moyenne d'un cycle sur 7 jours (min) |
| `sensor.<nom>_duree_moyenne_dun_cycle_depuis_le_debut` | Durée moyenne des cycles mesurés depuis l'installation (min) |
| `sensor.<nom>_taux_dusure_quotidien` | Cycles ajoutés par jour en moyenne |
| `sensor.<nom>_usure_quotidienne` | % d'usure ajouté par jour en moyenne |
| `sensor.<nom>_duree_de_vie_restante_jours` / `_annees` | Estimation extrapolée à partir du taux d'usure quotidien |
| `sensor.<nom>_indice_dusure_7_jours` | `faible` / `moyen` / `eleve`, basé sur les cycles/jour de la semaine |
| `binary_sensor.<nom>_en_fonctionnement` | État marche/arrêt en direct |
| `button.<nom>_reinitialiser_les_compteurs_dusure` | Remise à zéro (catégorie Configuration, ex : remplacement du compresseur) |

### Suivi énergétique par DJU standard (base 18 °C — créé si capteur T° extérieure configuré)

| Entité | Description |
|---|---|
| `sensor.<nom>_dju_aujourdhui` | Degrés-Jours Unifiés (base 18 °C, norme Météo-France / COSTIC) accumulés depuis minuit |
| `sensor.<nom>_efficacite_dju_aujourdhui` | Consommation en temps réel rapportée à la rigueur météo du jour (`kWh/DJU`) |
| `sensor.<nom>_efficacite_dju_veille` | Bilan `kWh/DJU` consolidé de la veille (J-1) |
| `sensor.<nom>_efficacite_dju_7_jours` | Efficacité glissante sur les 7 derniers jours complets ($\sum \text{kWh} / \sum \text{DJU}$) |

### Suivi énergétique par DJU réel (compensé par la T° intérieure — créé si capteurs T° intérieure + extérieure configurés)

Si vous sélectionnez un ou plusieurs capteurs de température intérieure (salon, chambres, etc.),
l'intégration calcule leur moyenne en direct ($\overline{T_{\text{int}}}$) et intègre des **DJU réels**
basés sur l'écart thermique réel $\max(0, \overline{T_{\text{int}}} - T_{\text{ext}})$ : chauffer plus
fort à l'intérieur augmente naturellement les DJU réels, ce qui permet de juger l'efficacité de
la PAC indépendamment des changements de consigne.

| Entité | Description |
|---|---|
| `sensor.<nom>_temperature_interieure_moyenne` | Moyenne en temps réel des capteurs de température intérieure sélectionnés (°C) |
| `sensor.<nom>_dju_reel_aujourdhui` | Degrés-Jours réels ($\max(0, \overline{T_{\text{int}}} - T_{\text{ext}})$) accumulés depuis minuit |
| `sensor.<nom>_efficacite_dju_reel_aujourdhui` | Efficacité temps réel compensée par la T° intérieure (`kWh/DJU`) |
| `sensor.<nom>_efficacite_dju_reel_veille` | Bilan `kWh/DJU réel` consolidé de la veille (J-1) |
| `sensor.<nom>_efficacite_dju_reel_7_jours` | Efficacité glissante sur les 7 derniers jours ($\sum \text{kWh} / \sum \text{DJU}_{\text{réel}}$) |

L'énergie électrique consommée (`kWh`) est calculée automatiquement par intégration temporelle
(somme de Riemann à gauche) du capteur de puissance en Watts déjà configuré — aucun compteur
d'énergie supplémentaire n'est nécessaire. Si une entité `climate` est renseignée et passe en
mode climatisation, l'énergie de refroidissement est automatiquement exclue du bilan DJU chauffage.

### Rendement théorique (optionnel — entités créées uniquement selon les champs renseignés)

| Entité | Condition de création | Description |
|---|---|---|
| `sensor.<nom>_temperature_exterieure` | Capteur T° extérieure | Miroir du capteur de température extérieure configuré |
| `sensor.<nom>_humidite_exterieure` | Capteur humidité ext. | Miroir du capteur d'humidité extérieure configuré |
| `sensor.<nom>_mode_de_fonctionnement` | Entité `climate` | `chauffage` / `climatisation` / `arret` / `inconnu` |
| `sensor.<nom>_cop_instantane` | `climate` + T° ext + COP nominal | COP théorique en temps réel (mode chauffage uniquement) |
| `sensor.<nom>_eer_instantane` | `climate` + T° ext + EER nominal | EER théorique en temps réel (mode climatisation uniquement) |
| `sensor.<nom>_puissance_restituee` | COP ou EER configuré | Puissance thermique restituée estimée (kW) = puissance absorbée × COP/EER |

**Modèle utilisé** : COP de Carnot théorique (limite thermodynamique), mis à l'échelle par
un facteur d'efficacité calibré une fois pour toutes sur le COP/EER **nominal** déclaré par
le fabricant, aux points de référence EN 14511 **air/air** (7 °C ext / 20 °C int en chauffage,
35 °C ext / 27 °C int en froid). En chauffage, une correction de givrage basée sur le point de
rosée (formule de Magnus-Tetens) dégrade le COP entre −7 °C et +7 °C uniquement lorsque l'air
est simultanément froid et humide (condensation/givre sur la batterie extérieure sous 0 °C).
Voir `custom_components/heatpump_health/performance.py` pour le détail et les hypothèses.

⚠️ **C'est une estimation physique (calibrée pour une PAC air/air), pas une mesure.** Sur une
PAC **air/eau** fonctionnant en loi d'eau (plancher chauffant ou radiateurs à 30–55 °C), la
température au condenseur varie avec la température extérieure et s'écarte de la température
ambiante intérieure : l'estimation du COP y est donc plus approximative. Précision indicative
uniquement (±10-20 % environ) — utile pour repérer des tendances et anomalies (ex : dérive du
ratio `kWh/DJU` d'une saison à l'autre ou chute anormale de performance), pas comme valeur
métrologique certifiée.

## Installation

### Via HACS (dépôt personnalisé)

[![Ouvrir dans Home Assistant et ajouter ce dépôt dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=maximeblanchard&repository=ha-heatpump-health&category=integration)

Le bouton ouvre directement votre instance Home Assistant sur la boîte de dialogue HACS.

Sans le bouton, manuellement :
1. HACS → menu ⋮ → "Dépôts personnalisés"
2. Ajouter l'URL de ce dépôt GitHub, catégorie "Intégration"
3. Installer "HeatPump-Health", redémarrer Home Assistant

### Manuelle
1. Copier le dossier `custom_components/heatpump_health` dans `config/custom_components/`
2. Redémarrer Home Assistant

## Configuration

Paramètres → Appareils et services → Ajouter une intégration → "HeatPump-Health"

### Étape 1 : Détection des cycles et usure
- **Capteur de puissance** : votre capteur en Watts
- **Seuil de détection marche (W)** : au-dessus = PAC en marche
- **Délai avant confirmation d'arrêt (s)** : ignore les creux de dégivrage/modulation sans gonfler la durée réelle du cycle
- **Nombre de cycles max** : durée de vie théorique du compresseur (30 000 / 50 000...)
- **Seuils cycles/jour faible/élevé** : bornes de l'indice d'usure 7 jours
- **Date de mise en service / cycles déjà effectués** : optionnel, pour reprendre un comptage existant

### Étape 2 (optionnelle) : DJU & Rendement
Après l'étape ci-dessus, un second écran propose de renseigner (tout est optionnel,
laissez vide ce que vous n'utilisez pas) :
- **Capteur de température extérieure** : active les capteurs de suivi `DJU` (base 18 °C) et `kWh/DJU`
- **Capteurs de température intérieure (liste multiple)** : calcule la température intérieure moyenne des pièces sélectionnées, active le suivi `kWh/DJU réel` et alimente le calcul du COP/EER
- **Entité climate** : pour connaître le mode chaud/froid (et la température intérieure si aucun capteur intérieur n'est sélectionné)
- **Capteur d'humidité extérieure** : pour affiner la pénalité de givrage sur le COP
- **COP nominal**, **EER nominal**, **kW chaud**, **kW froid** : valeurs de la fiche technique
  constructeur (ex. Panasonic Multi Z : COP 4,25 / EER 3,91 / 8,5 kW chaud / 6,8 kW froid)

Tous les seuils, capteurs intérieurs/météo/climate et valeurs constructeur sont modifiables à tout
moment via le bouton **"Configurer"** de l'intégration (sans perdre les compteurs déjà accumulés).

## Notes

- Sur une PAC inverter, le seuil doit être choisi juste au-dessus de la consommation de
  veille électronique (le compresseur module en continu et ne s'arrête pas franchement).
- Vérifiez `binary_sensor.<nom>_en_fonctionnement` pendant quelques jours avant de faire
  confiance aux statistiques, pour vous assurer qu'il ne "flappe" pas.
- Pour les bilans `kWh/DJU (veille)` et `kWh/DJU réel (veille)`, une journée n'est consolidée
  à minuit que si l'intégration a suivi au moins 18 h sur les 24 h écoulées (évite de fausser
  la veille le soir même de l'installation ou après une longue coupure).
- Les données (compteurs cumulés, historique 7 jours des cycles et des DJU) sont stockées dans
  `.storage/heatpump_health_<entry_id>` et survivent aux redémarrages de Home Assistant.

## Licence

MIT

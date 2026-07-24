# HeatPump-Health — Home Assistant

<img src="custom_components/heatpump_health/icon.png" width="96" height="96" alt="Logo HeatPump-Health">

Intégration personnalisée Home Assistant qui calcule des indicateurs d'usure d'une pompe à
chaleur (ou de tout appareil à cycles marche/arrêt) à partir d'un simple capteur de
puissance en Watts.

## Indicateurs fournis

| Entité | Description |
|---|---|
| `sensor.<nom>_nombre_de_cycles_total` | Nombre total de cycles depuis l'installation |
| `sensor.<nom>_usure` | Usure en % (cycles / cycles max) |
| `sensor.<nom>_temps_de_fonctionnement_total` | Temps de fonctionnement cumulé (h) |
| `sensor.<nom>_temps_de_fonctionnement_7_jours` | Temps de fonctionnement sur 7 jours (h) |
| `sensor.<nom>_cycles_aujourdhui` | Nombre de cycles depuis minuit (reset quotidien) |
| `sensor.<nom>_cycles_7_jours` | Nombre de cycles sur les 7 derniers jours |
| `sensor.<nom>_duree_moyenne_dun_cycle_7_jours` | Durée moyenne d'un cycle (7 jours glissants) |
| `sensor.<nom>_duree_moyenne_dun_cycle_depuis_le_debut` | Durée moyenne d'un cycle (depuis le début) |
| `sensor.<nom>_taux_dusure_quotidien` | Cycles ajoutés par jour en moyenne depuis l'installation |
| `sensor.<nom>_usure_quotidienne` | % d'usure ajouté par jour en moyenne |
| `sensor.<nom>_duree_de_vie_restante_jours` / `_annees` | Estimation extrapolée à partir du taux d'usure quotidien |
| `sensor.<nom>_indice_dusure_7_jours` | `faible` / `moyen` / `eleve`, basé sur les cycles/jour de la semaine |
| `binary_sensor.<nom>_en_fonctionnement` | État marche/arrêt en direct |
| `button.<nom>_reinitialiser_les_compteurs_dusure` | Remise à zéro (ex : remplacement du compresseur) |

### Rendement théorique (optionnel)

| Entité | Description |
|---|---|
| `sensor.<nom>_temperature_exterieure` | Miroir du capteur de température extérieure configuré |
| `sensor.<nom>_humidite_exterieure` | Miroir du capteur d'humidité extérieure configuré |
| `sensor.<nom>_mode_de_fonctionnement` | `chauffage` / `climatisation` / `arret` / `inconnu` (déduit de l'entité climate) |
| `sensor.<nom>_cop_instantane` | COP théorique en temps réel (mode chauffage uniquement) |
| `sensor.<nom>_eer_instantane` | EER théorique en temps réel (mode climatisation uniquement) |
| `sensor.<nom>_puissance_restituee` | Puissance thermique restituée estimée (kW) = puissance absorbée × COP/EER |

**Modèle utilisé** : COP de Carnot théorique (limite thermodynamique), mis à l'échelle par
un facteur d'efficacité calibré une fois pour toutes sur le COP/EER **nominal** déclaré par
le fabricant, aux points de référence EN 14511 (7°C ext/20°C int en chauffage, 35°C ext/27°C
int en froid). Une correction de dégivrage (formule météo publique de Stull, 2011) dégrade le
COP chauffage dans la zone -5°C/+8°C où le givrage de l'unité extérieure est fréquent. Voir
`custom_components/heatpump_health/performance.py` pour le détail et les hypothèses.

⚠️ **C'est une estimation physique, pas une mesure.** Précision indicative uniquement
(±10-20% environ) — utile pour repérer des tendances et anomalies (ex : chute de COP
anormale hors zone de givrage = signe possible de manque de fluide frigorigène), pas comme
valeur métrologique certifiée.

## Installation

### Via HACS (dépôt personnalisé)

[![Ouvrir dans Home Assistant et ajouter ce dépôt dans HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=maximeblanchard&repository=ha-heatpump-health&category=integration)

Le bouton ouvre directement votre instance Home Assistant sur la boîte de dialogue HACS


Sans le bouton, manuellement :
1. HACS → menu ⋮ → "Dépôts personnalisés"
2. Ajouter l'URL de ce dépôt GitHub, catégorie "Intégration"
3. Installer "HeatPump-Health", redémarrer Home Assistant

### Manuelle
1. Copier le dossier `custom_components/heatpump_health` dans `config/custom_components/`
2. Redémarrer Home Assistant

## Configuration

Paramètres → Appareils et services → Ajouter une intégration → "HeatPump-Health"

- **Capteur de puissance** : votre capteur en Watts
- **Seuil de détection marche (W)** : au-dessus = PAC en marche
- **Délai avant confirmation d'arrêt (s)** : ignore les creux de dégivrage/modulation
- **Nombre de cycles max** : durée de vie théorique du compresseur (30000 / 50000...)
- **Seuils cycles/jour faible/élevé** : bornes de l'indice d'usure 7 jours
- **Date de mise en service / cycles déjà effectués** : optionnel, pour reprendre un
  comptage existant

Les seuils sont modifiables ensuite via le bouton "Configurer" de l'intégration
(sans perdre les compteurs déjà accumulés).

### Étape 2 (optionnelle) : Rendement

Après l'étape ci-dessus, un second écran propose de renseigner (tout est optionnel,
laissez vide pour ignorer cette fonctionnalité) :

- **Entité climate** : pour connaître le mode chaud/froid et la consigne
- **Capteur de température extérieure** / **capteur d'humidité extérieure**
- **COP nominal**, **EER nominal**, **SCOP**, **SEER**, **kW chaud**, **kW froid** : valeurs
  de la fiche technique constructeur (ex. Panasonic Multi Z : COP 4,25 / EER 3,91 / SCOP 4,60
  / SEER 8,20 / 8,5 kW chaud / 6,8 kW froid)

Ces valeurs sont aussi modifiables plus tard via "Configurer" (l'entité climate et les
capteurs météo, une fois choisis à l'installation, ne sont pas modifiables sans recréer
l'intégration pour l'instant).

## Notes

- Sur une PAC inverter, le seuil doit être choisi juste au-dessus de la consommation de
  veille électronique (le compresseur module en continu et ne s'arrête pas franchement).
- Vérifiez `binary_sensor.<nom>_en_fonctionnement` pendant quelques jours avant de faire
  confiance aux statistiques, pour vous assurer qu'il ne "flappe" pas.
- Les données (compteurs cumulés, historique 7 jours) sont stockées dans
  `.storage/heatpump_health_<entry_id>` et survivent aux redémarrages de Home Assistant.

## Licence

MIT

## Logo

`custom_components/heatpump_health/heatpump_health_icon.svg` (source vectoriel) + exports
`icon.png`/`icon@2x.png` (256/512px) et `logo.png`/`logo@2x.png`. Pour que l'icône apparaisse
dans HACS et sur la page d'intégration Home Assistant (pas seulement dans ce dépôt), il faut
soumettre ces 4 PNG séparément au dépôt [home-assistant/brands](https://github.com/home-assistant/brands)
sous `custom_integrations/heatpump_health/{icon.png,icon@2x.png,logo.png,logo@2x.png}` — une
pull request y est revue par l'équipe Home Assistant avant d'être fusionnée.

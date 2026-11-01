# 🏭 Industrial What-If Simulator

**Système d'aide à la décision industrielle** : teste virtuellement une décision de production (ajout de capacité, amélioration de process) avant de l'appliquer réellement — avec optimisation mathématique, quantification du risque, et analyse économique.

🔗 **Démo en ligne :** [industrial-what-if-simulator.streamlit.app](https://industrial-what-if-simulator.streamlit.app)
📂 **Code source :** ce dépôt

---

## 🎯 Le problème industriel

Un ingénieur de production doit régulièrement arbitrer entre plusieurs décisions possibles pour améliorer une ligne de production : ajouter une machine, réduire le temps d'une opération, réorganiser un planning... Ces décisions sont coûteuses et difficiles à annuler une fois prises.

**Ce projet répond à une question simple : *"Que se passerait-il si je faisais ce changement — avant de le faire réellement ?"***

L'outil modélise un atelier de production (commandes, machines, opérations, gammes) comme un problème d'ordonnancement flexible (**Flexible Job Shop Scheduling Problem**), l'optimise mathématiquement, puis permet de comparer la situation actuelle à un scénario modifié — avec une recommandation chiffrée et argumentée.

---

## 🏗️ Architecture

```
Données (CSV) → Génération des tâches → Optimisation (MILP) → KPI industriels
                                                                      ↓
Décision finale ← Analyse économique ← Monte Carlo ← Comparaison de scénarios
```

**Stack technique :**
- **Modélisation & optimisation** : [PuLP](https://coin-or.github.io/pulp/) (solveur CBC) — programmation linéaire en nombres entiers (MILP)
- **Interface** : [Streamlit](https://streamlit.io)
- **Visualisation** : Plotly (diagrammes de Gantt)
- **Données** : Pandas / NumPy
- **Tests** : Pytest

---

## ⚙️ Méthode d'optimisation

Le problème est modélisé comme un **Flexible Job Shop Scheduling Problem (FJSP)** :
- Chaque commande suit une gamme d'opérations séquentielles (contraintes de précédence)
- Chaque opération peut être réalisée sur plusieurs machines compatibles (flexibilité)
- Chaque machine ne peut traiter qu'une tâche à la fois (contraintes de non-chevauchement, formulées en *big-M*)
- **Objectif** : minimiser le Makespan (durée totale de production)

Le modèle est résolu à l'optimum exact (`gapRel = 0.0`) via le solveur CBC, avec une limite de temps de sécurité.

> **Note méthodologique** : une version pondérée de l'objectif (Makespan + retard) a été testée puis abandonnée après diagnostic d'une instabilité numérique liée à la formulation big-M sur des instances de grande taille. L'objectif actuel (Makespan pur) est fiable à 100%, validé par les tests automatisés ci-dessous.

---

## 🔬 Scénarios "what-if"

Deux types de décisions industrielles peuvent être testées :
1. **Modifier la durée d'une opération** (amélioration de process, formation...)
2. **Ajouter une machine compatible à une opération** (flexibilisation de la capacité)

Chaque scénario est comparé automatiquement à la situation actuelle sur : Makespan, retard total, taux de respect des délais, commandes en retard, et goulot de production — avec un diagramme de Gantt comparatif.

**Exemple validé** : ajouter une machine compatible à une opération goulot améliore le Makespan de 8 à 18% et le retard total de 12 à 40% selon le jeu de données, avec un statut de décision "SCÉNARIO FAVORABLE" généré automatiquement.

---

## 🎲 Analyse Monte Carlo

Les durées industrielles réelles ne sont jamais parfaitement fixes. Cette section relance l'optimisation plusieurs fois (jusqu'à 30 simulations) avec des durées légèrement aléatoires (±5 à 30%), pour donner une **fourchette de risque** plutôt qu'un chiffre déterministe unique.

**Exemple observé** : sur une instance à forte charge (goulots > 90% d'utilisation), un Makespan déterministe de 47h peut en réalité varier entre 55h et 140h selon les aléas — une information cruciale qu'un chiffre unique ne révèle pas.

---

## 💰 Analyse économique

Chaque scénario peut être associé à un coût d'investissement estimé. L'outil calcule automatiquement :
- Le gain financier estimé (valeur du temps de production gagné + coût de retard évité)
- Le retour sur investissement (ROI)
- Une recommandation "investissement rentable" ou non

**Exemple** : ajout d'une machine (investissement 40 000 DH) → gain net estimé de ~31 700 DH, ROI de +179%.

> ⚠️ Les paramètres économiques par défaut sont **illustratifs**, réglables librement dans l'interface, et non calibrés sur des données industrielles réelles. L'objectif est de démontrer la méthodologie de décision économique, pas de fournir un chiffrage validé pour un cas industriel précis.

---

## 📊 Résultats & validation

Le moteur d'optimisation a été validé selon 3 approches complémentaires :

**1. Tests logiques automatisés (11/11 passants)**
- Réduire la durée d'une opération ne dégrade jamais le Makespan optimal
- Ajouter une machine compatible ne dégrade jamais le Makespan optimal
- Aucun chevauchement de tâches sur une même machine
- Contraintes de gamme toujours respectées
- Cohérence des KPI et de la logique de décision

→ `pytest tests/ -v`

**2. Benchmark académique**
Validé sur l'instance **mk01** (Brandimarte, référence classique du FJSP) : Makespan obtenu de **47h**, contre un optimum théorique connu de **40h** dans la littérature — écart de 17,5% expliqué et documenté (voir Limites).

**3. Vérifications manuelles ciblées**
Plusieurs anomalies (instabilité numérique du solveur sur objectif pondéré, à grande échelle) ont été diagnostiquées méthodiquement par élimination des causes possibles (tolérance de gap, poids de l'objectif, taille d'instance) plutôt que contournées.

---

## ⚠️ Limites connues

Ce projet assume honnêtement ses limites actuelles :

| Limite | Détail |
|---|---|
| **Durée fixe par opération** | Le modèle utilise une durée moyenne par opération, alors que le vrai FJSP autorise une durée différente selon la machine choisie. Explique l'écart de 17,5% avec l'optimum académique. |
| **Scalabilité** | Le modèle MILP exact montre des signes d'instabilité numérique au-delà de ~50 tâches (formulation big-M). Une vraie usine à grande échelle nécessiterait des heuristiques. |
| **Données synthétiques** | Pas d'accès à des données industrielles réelles ; validation croisée avec un benchmark académique reconnu à la place. |
| **Paramètres économiques illustratifs** | Non calibrés sur un cas industriel réel (voir section Analyse économique). |
| **Pas de contraintes de calendrier** | Pas de gestion des shifts, maintenance planifiée, ou temps de changement de série (setup/changeover) — piste d'évolution identifiée. |

---

## 🛠️ Technologies utilisées

Python 3.13 · Streamlit · PuLP (CBC) · Pandas · NumPy · Plotly · Pytest · Git/GitHub · Streamlit Community Cloud

---

## 🚀 Installation locale

```bash
git clone https://github.com/Bruja160/industrial-decision-simulator.git
cd industrial-decision-simulator
python -m venv .venv
.venv\Scripts\Activate.ps1      # Windows
pip install -r requirements.txt
streamlit run app.py
```

Lancer les tests :
```bash
pytest tests/ -v
```

---

## 📁 Structure du projet

```
├── app.py                          # Interface Streamlit
├── src/
│   ├── optimizer/optimizer.py      # Moteur d'optimisation (MILP)
│   └── analysis/
│       ├── scenario_analysis.py    # Comparaison de scénarios
│       └── scenario_generator.py
├── tests/
│   ├── test_optimizer.py           # Tests du moteur (11 tests)
│   └── test_data.py                # Tests d'intégrité des données
├── data/                           # Jeux de données (synthétique + benchmark)
├── convert_benchmark.py            # Conversion instance Brandimarte → CSV
└── requirements.txt
```

---

## 🔭 Perspectives d'évolution

- Durées dépendantes de la machine assignée (vrai FJSP)
- Contraintes de calendrier (shifts, maintenance, changement de série)
- Score de décision multicritère pondéré
- Probabilités de respect de délai issues de Monte Carlo
- Données industrielles réelles calibrées

---

*Projet personnel développé dans une démarche d'ingénierie rigoureuse : modélisation, validation scientifique, diagnostic méthodique d'anomalies, et documentation honnête des limites.*

import sys
from pathlib import Path
import random

import pandas as pd
import numpy as np
import streamlit as st


# ============================================================
# CONFIGURATION DU PROJET
# ============================================================

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# IMPORTS DU PROJET
# ============================================================

from src.optimizer.optimizer import (
    create_tasks,
    optimize_schedule,
    calculate_kpis,
)

from src.analysis.scenario_analysis import compare_scenarios


# ============================================================
# CONFIGURATION STREAMLIT
# ============================================================

st.set_page_config(
    page_title="Industrial Decision Simulator",
    page_icon="🏭",
    layout="wide",
)


# ============================================================
# UTILITAIRE : RETROUVER LE TAUX D'UTILISATION DU GOULOT
# ============================================================
# kpis["bottleneck"] est une chaîne déjà formatée, ex: "M3 - Usinage_2".
# On retrouve le taux d'utilisation en cherchant dans kpis["machines"].

def get_bottleneck_utilization(kpis):
    bottleneck_id = kpis["bottleneck"].split(" - ")[0].strip()

    machine_row = kpis["machines"][
        kpis["machines"]["machine_id"] == bottleneck_id
    ]

    if not machine_row.empty:
        return float(machine_row["utilization_percent"].iloc[0])

    return None


# ============================================================
# UTILITAIRE : PHRASE DE DÉCISION EN LANGAGE HUMAIN
# ============================================================

def describe_change(value, unit="%"):
    """Transforme un gain signé en verbe + valeur absolue lisible."""
    if value > 0.05:
        return f"diminue de {value:.1f} {unit}"
    elif value < -0.05:
        return f"augmente de {abs(value):.1f} {unit}"
    else:
        return f"reste quasiment inchangé"


def generate_decision_sentence(comparison, scenario_label):

    makespan_txt = describe_change(comparison["makespan_gain"])
    delay_txt = describe_change(comparison["delay_gain"])
    on_time_txt = describe_change(comparison["on_time_change"], unit="points")

    recommendation = comparison["recommendation"]

    if recommendation == "SCÉNARIO FAVORABLE":
        verdict = "Ce scénario est **recommandé**."
    elif recommendation == "SCÉNARIO À ÉTUDIER":
        verdict = "Ce scénario **mérite d'être approfondi** avant décision, les gains sont partiels."
    else:
        verdict = "Ce scénario **n'est pas recommandé** en l'état."

    sentence = (
        f"**{scenario_label}**. Avec ce changement, le Makespan {makespan_txt}, "
        f"le retard total {delay_txt}, et le taux de respect des délais {on_time_txt}. "
        f"{verdict}"
    )

    return sentence


# ============================================================
# TITRE
# ============================================================

st.title("🏭 Industrial Decision Simulator")

st.write(
    "Système digital d'aide à la décision pour "
    "l'amélioration des performances industrielles."
)


# ============================================================
# CHARGEMENT DES DONNÉES
# ============================================================

@st.cache_data
def load_project_data():

    orders = pd.read_csv(ROOT / "data" / "orders.csv")
    machines = pd.read_csv(ROOT / "data" / "machines.csv")
    operations = pd.read_csv(ROOT / "data" / "operations.csv")

    return orders, machines, operations


orders, machines, operations = load_project_data()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("⚙️ Paramètres du scénario")

st.sidebar.write(
    "Modifiez un paramètre industriel puis "
    "comparez le scénario avec la situation actuelle."
)


# ============================================================
# DONNÉES DU SYSTÈME
# ============================================================

st.header("📊 Données du système industriel")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Commandes", len(orders))

with col2:
    st.metric("Machines", len(machines))

with col3:
    st.metric("Opérations", len(operations))

with col4:
    st.metric("Produits", operations["product_id"].nunique())


with st.expander("Voir les commandes"):
    st.dataframe(orders, use_container_width=True)

with st.expander("Voir les machines"):
    st.dataframe(machines, use_container_width=True)

with st.expander("Voir les opérations"):
    st.dataframe(operations, use_container_width=True)


# ============================================================
# 1️⃣ OPTIMISATION SITUATION ACTUELLE
# ============================================================

st.header("1️⃣ Situation actuelle")


if st.button("🚀 Optimiser la situation actuelle", type="primary"):

    with st.spinner("Optimisation de la situation actuelle..."):
        baseline_tasks = create_tasks(orders, operations)
        baseline_schedule = optimize_schedule(baseline_tasks)

    if baseline_schedule is None:
        st.error("Aucune solution trouvée pour la situation actuelle.")
        st.stop()

    baseline_kpis = calculate_kpis(baseline_schedule, orders, machines)

    st.session_state["baseline_schedule"] = baseline_schedule
    st.session_state["baseline_kpis"] = baseline_kpis

    st.success("Optimisation de la situation actuelle terminée.")


if "baseline_kpis" in st.session_state:

    baseline_kpis = st.session_state["baseline_kpis"]

    st.subheader("📈 KPI de la situation actuelle")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Makespan", f"{baseline_kpis['makespan']:.2f} h")

    with col2:
        st.metric("Retard total", f"{baseline_kpis['total_delay']:.2f} h")

    with col3:
        st.metric(
            "Commandes en retard",
            f"{baseline_kpis['late_orders']} / {baseline_kpis['total_orders']}"
        )

    with col4:
        st.metric("Respect des délais", f"{baseline_kpis['on_time_rate']:.2f} %")

    st.write(f"**Goulot actuel :** {baseline_kpis['bottleneck']}")


# ============================================================
# 2️⃣ CRÉATION DU SCÉNARIO
# ============================================================

st.header("2️⃣ Création du scénario")

st.write("Choisissez le type de décision industrielle à tester.")

scenario_type = st.radio(
    "Type de scénario",
    [
        "Modifier la durée d'une opération",
        "Ajouter une machine compatible à une opération",
    ],
    horizontal=True,
)

operation_options = operations["operation_id"].tolist()

selected_operation = st.selectbox("Opération concernée", operation_options)

selected_row = operations[
    operations["operation_id"] == selected_operation
].iloc[0]

machine_to_add = None
scenario_duration = None
current_duration = None

if scenario_type == "Modifier la durée d'une opération":

    current_duration = float(selected_row["duration"])

    scenario_duration = st.number_input(
        "Nouvelle durée de l'opération (heures)",
        min_value=0.001,
        value=current_duration,
        step=0.001,
        format="%.3f"
    )

    variation = (scenario_duration - current_duration) / current_duration * 100

    if variation < 0:
        st.info(f"Amélioration simulée : {variation:.2f} %")
    elif variation > 0:
        st.warning(f"Dégradation simulée : +{variation:.2f} %")
    else:
        st.info("Aucune modification de durée.")

else:

    current_machines = [
        m.strip() for m in str(selected_row["compatible_machines"]).split("|")
    ]

    st.write(f"Machines actuellement compatibles : **{', '.join(current_machines)}**")

    available_machines = [
        m for m in machines["machine_id"].tolist() if m not in current_machines
    ]

    if available_machines:
        machine_to_add = st.selectbox(
            "Machine à ajouter comme option pour cette opération",
            available_machines
        )
        st.info(
            f"Cette opération pourra désormais aussi être réalisée sur "
            f"**{machine_to_add}**, en plus de {', '.join(current_machines)}."
        )
    else:
        st.warning("Toutes les machines existantes sont déjà compatibles avec cette opération.")


if st.button("🔬 Simuler le scénario"):

    if "baseline_kpis" not in st.session_state:
        st.warning("Vous devez d'abord optimiser la situation actuelle.")
        st.stop()

    if scenario_type == "Ajouter une machine compatible à une opération" and machine_to_add is None:
        st.warning("Aucune machine disponible à ajouter pour cette opération.")
        st.stop()

    scenario_operations = operations.copy()

    if scenario_type == "Modifier la durée d'une opération":
        scenario_operations.loc[
            scenario_operations["operation_id"] == selected_operation, "duration"
        ] = scenario_duration

        scenario_label = (
            f"Durée de {selected_operation} modifiée : "
            f"{current_duration:.3f} h → {scenario_duration:.3f} h"
        )
    else:
        current_value = str(selected_row["compatible_machines"])
        new_value = f"{current_value}|{machine_to_add}"

        scenario_operations.loc[
            scenario_operations["operation_id"] == selected_operation,
            "compatible_machines"
        ] = new_value

        scenario_label = f"{machine_to_add} ajoutée comme machine compatible pour {selected_operation}"

    st.caption(f"**Scénario testé :** {scenario_label}")

    scenario_tasks = create_tasks(orders, scenario_operations)

    with st.spinner("Optimisation du scénario..."):
        scenario_schedule = optimize_schedule(scenario_tasks)

    if scenario_schedule is None:
        st.error("Aucune solution trouvée pour ce scénario.")
        st.stop()

    scenario_kpis = calculate_kpis(scenario_schedule, orders, machines)

    baseline_kpis = st.session_state["baseline_kpis"]
    comparison = compare_scenarios(baseline_kpis, scenario_kpis)

    st.session_state["scenario_schedule"] = scenario_schedule
    st.session_state["scenario_kpis"] = scenario_kpis
    st.session_state["comparison"] = comparison
    st.session_state["scenario_label"] = scenario_label


# ============================================================
# 3️⃣ RESULTATS DU SCENARIO
# ============================================================

if "scenario_kpis" in st.session_state:

    scenario_kpis = st.session_state["scenario_kpis"]
    comparison = st.session_state["comparison"]
    baseline_kpis = st.session_state["baseline_kpis"]

    st.header("3️⃣ Résultats de la simulation")

    st.subheader("📊 Comparaison des performances")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Makespan", f"{scenario_kpis['makespan']:.2f} h",
            delta=f"{comparison['makespan_gain']:.2f} %"
        )

    with col2:
        st.metric(
            "Retard total", f"{scenario_kpis['total_delay']:.2f} h",
            delta=f"{comparison['delay_gain']:.2f} %"
        )

    with col3:
        st.metric(
            "Respect des délais", f"{scenario_kpis['on_time_rate']:.2f} %",
            delta=f"{comparison['on_time_change']:.2f} points"
        )

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Commandes en retard - actuel", baseline_kpis["late_orders"])

    with col2:
        st.metric("Commandes en retard - scénario", scenario_kpis["late_orders"])

    st.subheader("🔴 Analyse du goulot")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**Situation actuelle**")
        st.write(baseline_kpis["bottleneck"])
        baseline_utilization = get_bottleneck_utilization(baseline_kpis)
        if baseline_utilization is not None:
            st.write(f"Utilisation : {baseline_utilization:.2f} %")

    with col2:
        st.write("**Scénario**")
        st.write(scenario_kpis["bottleneck"])
        scenario_utilization = get_bottleneck_utilization(scenario_kpis)
        if scenario_utilization is not None:
            st.write(f"Utilisation : {scenario_utilization:.2f} %")

    st.subheader("📋 Tableau comparatif")

    comparison_table = comparison["comparison"].copy()
    st.dataframe(comparison_table, use_container_width=True)

    with st.expander("Voir le planning optimisé du scénario"):
        scenario_schedule = st.session_state["scenario_schedule"]
        st.dataframe(
            scenario_schedule.sort_values(["machine", "start"]),
            use_container_width=True
        )


# ============================================================
# 4️⃣ ANALYSE DE L'INCERTITUDE (MONTE CARLO)
# ============================================================

st.divider()
st.header("4️⃣ Analyse de l'incertitude (Monte Carlo)")

st.write(
    "En réalité, les durées ne sont jamais parfaitement fixes "
    "(variabilité opérateur, aléas machine...). Cette section relance "
    "l'optimisation de la situation actuelle plusieurs fois avec des "
    "durées légèrement aléatoires, pour obtenir une **fourchette** de "
    "Makespan plutôt qu'un chiffre unique."
)

col1, col2 = st.columns(2)

with col1:
    n_simulations = st.slider("Nombre de simulations", min_value=5, max_value=30, value=15)

with col2:
    variation_pct = st.slider("Variation des durées (%)", min_value=5, max_value=30, value=15)

st.caption(
    f"⏱️ Chaque simulation est limitée à 30 secondes de calcul pour rester "
    f"gérable ({n_simulations} simulations : jusqu'à "
    f"{n_simulations * 30 // 60} min dans le pire des cas)."
)

if st.button("🎲 Lancer l'analyse Monte Carlo"):

    makespans = []
    progress_bar = st.progress(0.0)
    status_text = st.empty()

    for i in range(n_simulations):
        status_text.text(f"Simulation {i + 1} / {n_simulations}...")

        randomized_operations = operations.copy()
        factors = [
            random.uniform(1 - variation_pct / 100, 1 + variation_pct / 100)
            for _ in range(len(randomized_operations))
        ]
        randomized_operations["duration"] = (
            randomized_operations["duration"].values * np.array(factors)
        )

        tasks_mc = create_tasks(orders, randomized_operations)
        schedule_mc = optimize_schedule(tasks_mc, time_limit=30)

        if schedule_mc is not None:
            makespans.append(float(schedule_mc["end"].max()))

        progress_bar.progress((i + 1) / n_simulations)

    status_text.empty()
    progress_bar.empty()

    if len(makespans) == 0:
        st.error("Aucune simulation n'a abouti à une solution exploitable.")
    else:
        makespans_array = np.array(makespans)

        st.session_state["mc_results"] = {
            "makespans": makespans_array,
            "n_simulations": n_simulations,
            "n_valid": len(makespans),
            "variation_pct": variation_pct,
        }

        st.success(f"{len(makespans)} / {n_simulations} simulations exploitables.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Makespan minimum", f"{makespans_array.min():.2f} h")
        c2.metric("Makespan moyen", f"{makespans_array.mean():.2f} h")
        c3.metric("Makespan maximum", f"{makespans_array.max():.2f} h")
        c4.metric("Écart-type", f"{makespans_array.std():.2f} h")

        st.bar_chart(pd.DataFrame({"Makespan (h)": makespans_array}))

        st.caption(
            f"Avec ±{variation_pct}% de variabilité sur les durées, le "
            f"Makespan réel a de bonnes chances de se situer entre "
            f"{makespans_array.min():.1f}h et {makespans_array.max():.1f}h, "
            f"plutôt que d'être exactement la valeur déterministe calculée "
            f"en section 1."
        )


# ============================================================
# 5️⃣ DÉCISION FINALE
# ============================================================

if "scenario_kpis" in st.session_state:

    st.divider()
    st.header("5️⃣ Décision finale")

    comparison = st.session_state["comparison"]
    scenario_label = st.session_state["scenario_label"]
    recommendation = comparison["recommendation"]

    if recommendation == "SCÉNARIO FAVORABLE":
        st.success(f"✅ {recommendation}")
    elif recommendation == "SCÉNARIO À ÉTUDIER":
        st.warning(f"⚠️ {recommendation}")
    else:
        st.error(f"❌ {recommendation}")

    st.markdown(generate_decision_sentence(comparison, scenario_label))

    if "mc_results" in st.session_state:
        mc = st.session_state["mc_results"]
        st.caption(
            f"🎲 Pour rappel, l'analyse Monte Carlo ({mc['n_valid']} simulations, "
            f"±{mc['variation_pct']}% de variabilité) montre que le Makespan réel "
            f"de la situation actuelle peut varier entre "
            f"{mc['makespans'].min():.1f}h et {mc['makespans'].max():.1f}h — "
            f"à garder en tête pour relativiser la précision du chiffre déterministe "
            f"ci-dessus."
        )
    else:
        st.caption(
            "💡 Lance l'analyse Monte Carlo (section 4️⃣) pour connaître la "
            "fourchette de risque associée à ce résultat."
        )

else:
    st.divider()
    st.header("5️⃣ Décision finale")
    st.info(
        "Optimise la situation actuelle puis simule un scénario "
        "(sections 1️⃣ et 2️⃣) pour obtenir une décision finale."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Industrial Decision Simulator — "
    "Système digital d'aide à la décision industrielle"
)
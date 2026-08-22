import sys
from pathlib import Path

import pandas as pd
import streamlit as st


# ============================================================
# CONFIGURATION DU PROJET
# ============================================================

ROOT = Path(__file__).resolve().parent

# Permet à Python de trouver le dossier src
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
# Dans cette version d'optimizer.py, kpis["bottleneck"] est une
# chaîne déjà formatée, ex: "M3 - Usinage_2". Le taux d'utilisation
# n'est donc plus directement dedans : on va le rechercher dans le
# tableau détaillé kpis["machines"] à partir de l'identifiant machine.

def get_bottleneck_utilization(kpis):
    bottleneck_id = kpis["bottleneck"].split(" - ")[0].strip()

    machine_row = kpis["machines"][
        kpis["machines"]["machine_id"] == bottleneck_id
    ]

    if not machine_row.empty:
        return float(machine_row["utilization_percent"].iloc[0])

    return None


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

    orders = pd.read_csv(
        ROOT / "data" / "orders.csv"
    )

    machines = pd.read_csv(
        ROOT / "data" / "machines.csv"
    )

    operations = pd.read_csv(
        ROOT / "data" / "operations.csv"
    )

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
    st.metric(
        "Commandes",
        len(orders)
    )

with col2:
    st.metric(
        "Machines",
        len(machines)
    )

with col3:
    st.metric(
        "Opérations",
        len(operations)
    )

with col4:
    st.metric(
        "Produits",
        operations["product_id"].nunique()
    )


# ============================================================
# AFFICHAGE DES DONNÉES
# ============================================================

with st.expander("Voir les commandes"):

    st.dataframe(
        orders,
        use_container_width=True
    )


with st.expander("Voir les machines"):

    st.dataframe(
        machines,
        use_container_width=True
    )


with st.expander("Voir les opérations"):

    st.dataframe(
        operations,
        use_container_width=True
    )


# ============================================================
# OPTIMISATION SITUATION ACTUELLE
# ============================================================

st.header("1️⃣ Situation actuelle")


if st.button(
    "🚀 Optimiser la situation actuelle",
    type="primary"
):

    with st.spinner(
        "Optimisation de la situation actuelle..."
    ):

        baseline_tasks = create_tasks(
            orders,
            operations
        )

        baseline_schedule = optimize_schedule(
            baseline_tasks
        )

    if baseline_schedule is None:

        st.error(
            "Aucune solution trouvée pour la situation actuelle."
        )

        st.stop()

    baseline_kpis = calculate_kpis(
        baseline_schedule,
        orders,
        machines
    )

    # Sauvegarde dans session
    st.session_state["baseline_schedule"] = (
        baseline_schedule
    )

    st.session_state["baseline_kpis"] = (
        baseline_kpis
    )

    st.success(
        "Optimisation de la situation actuelle terminée."
    )


# ============================================================
# AFFICHAGE KPI BASELINE
# ============================================================

if "baseline_kpis" in st.session_state:

    baseline_kpis = st.session_state[
        "baseline_kpis"
    ]

    st.subheader(
        "📈 KPI de la situation actuelle"
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Makespan",
            f"{baseline_kpis['makespan']:.2f} h"
        )

    with col2:

        st.metric(
            "Retard total",
            f"{baseline_kpis['total_delay']:.2f} h"
        )

    with col3:

        st.metric(
            "Commandes en retard",
            f"{baseline_kpis['late_orders']} / "
            f"{baseline_kpis['total_orders']}"
        )

    with col4:

        st.metric(
            "Respect des délais",
            f"{baseline_kpis['on_time_rate']:.2f} %"
        )

    # bottleneck est déjà une chaîne formatée (ex: "M3 - Usinage_2")
    st.write(
        f"**Goulot actuel :** {baseline_kpis['bottleneck']}"
    )


# ============================================================
# CRÉATION DU SCÉNARIO
# ============================================================

st.header("2️⃣ Création du scénario")


st.write(
    "Choisissez le type de décision industrielle à tester."
)


scenario_type = st.radio(
    "Type de scénario",
    [
        "Modifier la durée d'une opération",
        "Ajouter une machine compatible à une opération",
    ],
    horizontal=True,
)


operation_options = operations[
    "operation_id"
].tolist()


selected_operation = st.selectbox(
    "Opération concernée",
    operation_options
)


selected_row = operations[
    operations["operation_id"] == selected_operation
].iloc[0]


machine_to_add = None
scenario_duration = None
current_duration = None


if scenario_type == "Modifier la durée d'une opération":

    current_duration = float(
        selected_row["duration"]
    )

    scenario_duration = st.number_input(
        "Nouvelle durée de l'opération (heures)",
        min_value=0.001,
        value=current_duration,
        step=0.001,
        format="%.3f"
    )

    # --------------------------------------------------------
    # CALCUL DE L'IMPACT
    # --------------------------------------------------------

    variation = (
        (scenario_duration - current_duration)
        / current_duration
        * 100
    )

    if variation < 0:

        st.info(
            f"Amélioration simulée : "
            f"{variation:.2f} %"
        )

    elif variation > 0:

        st.warning(
            f"Dégradation simulée : "
            f"+{variation:.2f} %"
        )

    else:

        st.info(
            "Aucune modification de durée."
        )

else:

    current_machines = [
        m.strip()
        for m in str(selected_row["compatible_machines"]).split("|")
    ]

    st.write(
        f"Machines actuellement compatibles : "
        f"**{', '.join(current_machines)}**"
    )

    available_machines = [
        m for m in machines["machine_id"].tolist()
        if m not in current_machines
    ]

    if available_machines:

        machine_to_add = st.selectbox(
            "Machine à ajouter comme option pour cette opération",
            available_machines
        )

        st.info(
            f"Cette opération pourra désormais aussi être réalisée "
            f"sur **{machine_to_add}**, en plus de "
            f"{', '.join(current_machines)}."
        )

    else:

        st.warning(
            "Toutes les machines existantes sont déjà "
            "compatibles avec cette opération."
        )


# ============================================================
# LANCEMENT DU SCÉNARIO
# ============================================================

if st.button(
    "🔬 Simuler le scénario"
):

    if "baseline_kpis" not in st.session_state:

        st.warning(
            "Vous devez d'abord optimiser "
            "la situation actuelle."
        )

        st.stop()

    if (
        scenario_type == "Ajouter une machine compatible à une opération"
        and machine_to_add is None
    ):

        st.warning(
            "Aucune machine disponible à ajouter pour cette opération."
        )

        st.stop()


    # --------------------------------------------------------
    # COPIE DES OPERATIONS
    # --------------------------------------------------------

    scenario_operations = operations.copy()


    # --------------------------------------------------------
    # MODIFICATION DE L'OPERATION (selon le type de scénario)
    # --------------------------------------------------------

    if scenario_type == "Modifier la durée d'une opération":

        scenario_operations.loc[
            scenario_operations["operation_id"]
            == selected_operation,
            "duration"
        ] = scenario_duration

        scenario_label = (
            f"Durée de {selected_operation} modifiée : "
            f"{current_duration:.3f} h → {scenario_duration:.3f} h"
        )

    else:

        current_value = str(
            selected_row["compatible_machines"]
        )

        new_value = f"{current_value}|{machine_to_add}"

        scenario_operations.loc[
            scenario_operations["operation_id"]
            == selected_operation,
            "compatible_machines"
        ] = new_value

        scenario_label = (
            f"{machine_to_add} ajoutée comme machine compatible "
            f"pour {selected_operation}"
        )

    st.caption(f"**Scénario testé :** {scenario_label}")

    with st.expander("🔍 Debug : opération modifiée"):
        st.write("Ligne correspondante dans scenario_operations :")
        st.dataframe(
            scenario_operations[
                scenario_operations["operation_id"] == selected_operation
            ]
        )

    # --------------------------------------------------------
    # CREATION DES TACHES DU SCENARIO
    # --------------------------------------------------------

    scenario_tasks = create_tasks(
        orders,
        scenario_operations
    )

    with st.expander("🔍 Debug : tâches générées pour cette opération"):
        st.write("Toutes les tâches liées à cette opération, avec leur durée finale :")
        st.dataframe(
            scenario_tasks[
                scenario_tasks["operation_id"] == selected_operation
            ]
        )


    # --------------------------------------------------------
    # OPTIMISATION
    # --------------------------------------------------------

    with st.spinner(
        "Optimisation du scénario..."
    ):

        scenario_schedule = optimize_schedule(
            scenario_tasks
        )


    if scenario_schedule is None:

        st.error(
            "Aucune solution trouvée pour ce scénario."
        )

        st.stop()


    # --------------------------------------------------------
    # KPI SCENARIO
    # --------------------------------------------------------

    scenario_kpis = calculate_kpis(
        scenario_schedule,
        orders,
        machines
    )


    # --------------------------------------------------------
    # COMPARAISON
    # --------------------------------------------------------

    baseline_kpis = st.session_state[
        "baseline_kpis"
    ]


    comparison = compare_scenarios(
        baseline_kpis,
        scenario_kpis
    )


    # --------------------------------------------------------
    # SAUVEGARDE
    # --------------------------------------------------------

    st.session_state[
        "scenario_schedule"
    ] = scenario_schedule

    st.session_state[
        "scenario_kpis"
    ] = scenario_kpis

    st.session_state[
        "comparison"
    ] = comparison

    st.session_state[
        "scenario_operation"
    ] = selected_operation

    st.session_state[
        "scenario_label"
    ] = scenario_label


# ============================================================
# RESULTATS DU SCENARIO
# ============================================================

if "scenario_kpis" in st.session_state:

    scenario_kpis = st.session_state[
        "scenario_kpis"
    ]

    comparison = st.session_state[
        "comparison"
    ]


    st.header(
        "3️⃣ Résultats de la simulation"
    )


    # --------------------------------------------------------
    # KPI
    # --------------------------------------------------------

    st.subheader(
        "📊 Comparaison des performances"
    )


    baseline_kpis = st.session_state[
        "baseline_kpis"
    ]


    col1, col2, col3 = st.columns(3)


    with col1:

        st.metric(
            "Makespan",
            f"{scenario_kpis['makespan']:.2f} h",
            delta=(
                f"{comparison['makespan_gain']:.2f} %"
            )
        )


    with col2:

        st.metric(
            "Retard total",
            f"{scenario_kpis['total_delay']:.2f} h",
            delta=(
                f"{comparison['delay_gain']:.2f} %"
            )
        )


    with col3:

        st.metric(
            "Respect des délais",
            f"{scenario_kpis['on_time_rate']:.2f} %",
            delta=(
                f"{comparison['on_time_change']:.2f} points"
            )
        )


    # --------------------------------------------------------
    # COMMANDES EN RETARD
    # --------------------------------------------------------

    col1, col2 = st.columns(2)


    with col1:

        st.metric(
            "Commandes en retard - actuel",
            baseline_kpis["late_orders"]
        )


    with col2:

        st.metric(
            "Commandes en retard - scénario",
            scenario_kpis["late_orders"]
        )


    # --------------------------------------------------------
    # GOULOTS
    # --------------------------------------------------------

    st.subheader(
        "🔴 Analyse du goulot"
    )


    col1, col2 = st.columns(2)


    with col1:

        st.write(
            "**Situation actuelle**"
        )

        st.write(
            baseline_kpis["bottleneck"]
        )

        baseline_utilization = get_bottleneck_utilization(
            baseline_kpis
        )

        if baseline_utilization is not None:

            st.write(
                f"Utilisation : "
                f"{baseline_utilization:.2f} %"
            )


    with col2:

        st.write(
            "**Scénario**"
        )

        st.write(
            scenario_kpis["bottleneck"]
        )

        scenario_utilization = get_bottleneck_utilization(
            scenario_kpis
        )

        if scenario_utilization is not None:

            st.write(
                f"Utilisation : "
                f"{scenario_utilization:.2f} %"
            )


    # --------------------------------------------------------
    # DECISION
    # --------------------------------------------------------

    st.subheader(
        "🎯 Décision"
    )


    recommendation = comparison[
        "recommendation"
    ]


    if recommendation == "SCÉNARIO FAVORABLE":

        st.success(
            f"✅ {recommendation}"
        )


    elif recommendation == "SCÉNARIO À ÉTUDIER":

        st.warning(
            f"⚠️ {recommendation}"
        )


    else:

        st.error(
            f"❌ {recommendation}"
        )


    # --------------------------------------------------------
    # DETAILS COMPARAISON
    # --------------------------------------------------------

    st.subheader(
        "📋 Tableau comparatif"
    )


    comparison_table = comparison[
        "comparison"
    ].copy()


    st.dataframe(
        comparison_table,
        use_container_width=True
    )


    # --------------------------------------------------------
    # PLANNING SCENARIO
    # --------------------------------------------------------

    with st.expander(
        "Voir le planning optimisé du scénario"
    ):

        scenario_schedule = st.session_state[
            "scenario_schedule"
        ]

        st.dataframe(
            scenario_schedule.sort_values(
                ["machine", "start"]
            ),
            use_container_width=True
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Industrial Decision Simulator — "
    "Système digital d'aide à la décision industrielle"
)